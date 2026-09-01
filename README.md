# CLEAR

AI interprets fuzzy commercial intent; deterministic systems decide which economic agreement wins and where the money goes.

CLEAR is a proof-carrying decision layer for autonomous commerce and procurement-style markets. The current Week-2 implementation focuses on authenticated seller bids, deterministic allocation, independently replayable evidence, and machine-verifiable `AllocationCertificate` objects. It does not implement an AI intent layer.

## What is implemented

- Strict, immutable `MarketSpec`, `BuyerPolicy`, `MerchantIdentity`, and `MerchantBid` models.
- A SHA-256 buyer-policy commitment frozen before merchant bids are signed.
- Restricted deterministic JSON for policy, bid, and certificate bytes.
- Ed25519 merchant signatures over canonical bid bytes.
- Stateless market, policy, merchant, signature, and timestamp admission checks.
- Stateful replayed-`bid_id` and duplicate-merchant protection.
- Deterministic `reverse_second_price_v1` production allocation.
- A structurally independent allocation oracle.
- `AllocationCertificate` construction from policy, transcript, and production allocation evidence.
- Canonical certificate bytes and an exact SHA-256 certificate digest.
- A strict, duplicate-key-safe certificate parser bounded to 1 MiB.
- An independent semantic certificate verifier.
- The `clear verify` machine-readable verification CLI.
- A deterministic benchmark generator and production-versus-oracle runner.
- Hypothesis property suites and deterministic adversarial suites.
- GitHub Actions checks for dependencies, linting, formatting, typing, tests, hash-seed reproducibility, and frozen-evidence integrity.

## Week-2 market contract

The implemented market is deliberately narrow:

- one buyer and 2–20 registered sellers;
- one homogeneous, standardized good and a fixed requested quantity;
- one winner, responsible for the full requested quantity;
- one bid per merchant, with `bid_id` used as the replay identifier;
- integer INR paise only;
- a buyer reserve and eligible-seller set frozen in `BuyerPolicy` before bids; and
- no bid revisions.

Allocation follows these exact rules:

1. Only admitted bids are considered.
2. A bid is economically eligible exactly when `quantity_available >= requested_quantity` and `unit_price_paise <= reserve_unit_price`.
3. The lowest eligible unit bid wins.
4. Equal unit bids tie-break by canonical `merchant_id` ascending.
5. Payment per unit is the second element of eligible bids ordered by `(unit_price_paise, merchant_id)`.
6. With only one eligible seller, payment per unit is the buyer reserve.
7. Total payment is payment per unit multiplied by requested quantity using checked integer arithmetic.
8. No eligible seller produces `INFEASIBLE`.
9. Rejected or economically ineligible bids cannot affect allocation.

“Second” means the second ordered bid, not the second distinct price. For bids A=100, B=100, and C=110, if A's `merchant_id` sorts before B's, A wins and payment is 100.

Under the documented single-dimensional standardized-good assumptions, the reverse second-price mechanism has the standard truthful-bidding incentive property. This narrow statement does not make CLEAR generally strategy-proof, collusion-proof, Sybil-proof, truthful for arbitrary multi-attribute markets, or proof of fulfillment.

## Proof-carrying architecture

```text
BuyerPolicy
    │ SHA-256 commitment
    ▼
Signed Merchant Bids
    │ stateless + stateful admission
    ▼
Ordered Admission Transcript
    │
    ▼
Production Allocator
    │
    ▼
AllocationCertificate ── canonical bytes / SHA-256 digest
    │
    ▼
Independent Verifier
    ├─ recomputes the buyer-policy commitment
    ├─ replays every admission decision
    └─ recomputes allocation with the independent oracle
```

The certificate builder uses the production allocator. The verifier uses the independent oracle, which does not import the production winner-selection implementation. AI or LLM output does not decide constraints, admission, winner, payment, or tie-breaks.

## AllocationCertificate

An `AllocationCertificate` binds sufficient evidence for deterministic independent replay:

- the buyer policy and its commitment;
- ordered admission decisions;
- signed merchant bids and receipt contexts;
- accepted or rejected admission evidence;
- mechanism, canonicalization, commitment, signature, and certificate versions;
- the resulting allocation; and
- certificate identity and schema metadata.

The verifier does not trust stored rejection labels: it replays admission and compares every declared decision. It does not trust the stored allocation: it independently recomputes the expected allocation with the oracle and compares every frozen result field. Verification fails closed on policy-commitment, transcript-replay, or allocation mismatch.

A successfully verified certificate demonstrates internal policy, signed-bid, admission-transcript, and allocation consistency under the implemented protocol. It is not a zero-knowledge proof, blockchain record, legal settlement instrument, or cryptographic proof of physical fulfillment.

## Quick start

CLEAR is distributed as `clear-market`, imported as `clear_market`, and requires Python `>=3.12,<3.13`.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pip check
```

Inspect the installed command:

```sh
.venv/bin/clear --help
.venv/bin/clear verify --help
```

## Verify a certificate

The CLI accepts one file containing the exact canonical bytes of an `AllocationCertificate`:

```sh
.venv/bin/clear verify path/to/certificate.json
```

It writes one compact six-field JSON object to standard output. Exit codes are stable:

- `0`: canonical parsing and semantic verification succeeded;
- `1`: parsing succeeded but semantic verification failed;
- `2`: command or argument usage error;
- `3`: canonical certificate parsing failed; and
- `4`: the file could not be read.

Parse failures do not run semantic verification or produce a certificate digest. See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for evidence integrity and optional historical replay instructions.

## Testing and reproducibility

Run the normal repository verification from the project root:

```sh
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q
PYTHONHASHSEED=1 python -m pytest -q
```

Normal tests validate the frozen benchmark evidence but do not execute the frozen 10,000-market evaluation. CI performs equivalent quality checks and independently checks the frozen report SHA-256. Full reproduction instructions are in [REPRODUCIBILITY.md](REPRODUCIBILITY.md).

## Frozen evaluation evidence

The committed evidence records the frozen aggregate evaluation result.

| Field | Frozen value |
| ----- | ------------ |
| Evaluated source commit | `67f1f6f772e52d9207a6555e403a9edb53e7bf63` |
| Evidence freeze commit | `97e1113520f08b645885e3e6aa46d72eab5caaab` |
| Generator | `deterministic-market-generator-v1` |
| Runner | `differential-benchmark-runner-v1` |
| Seller count | 5 |
| Markets | 10,000 |
| Admission attempts / rejections | 24,990 / 0 |
| Feasible / infeasible markets | 6,271 / 3,729 |
| Differential mismatches | 0 |
| Budget violations | 0 |
| Allocation-quantity violations | 0 |
| Winner-evidence violations | 0 |
| Hard failures / failed markets | 0 / 0 |
| Report SHA-256 | `d63d4217486daf9ca1cc4840bbcd091b5589507cfa376a232eb61fc08ed7e2fe` |
| Seed-sequence SHA-256 | `75e00e23b222fe03242ac7d115909c0a12abc50ba10844337ec9d0ea4dd507f2` |
| Reproducibility fingerprint | `89cb65d3accaba76d90a1c6091503480ab6c3edeabf8e863613e86c9d2703867` |

Evidence files: [frozen report](benchmarks/frozen_evaluation_report_v1.json), [evidence manifest](benchmarks/frozen_evaluation_manifest_v1.json), and [reproduction guide](REPRODUCIBILITY.md).

The frozen evaluation demonstrates that, for the exact deterministic-market-generator-v1 distribution over the 10,000 frozen seeds with five sellers, the production allocator agreed with the independent oracle on all frozen differential fields and the runner observed zero defined hard invariant failures.

This does not prove correctness outside the tested generator distribution, and it does not establish collusion resistance, Sybil resistance, fulfillment correctness, or broader strategy-proofness.

## Scope and non-goals

The current repository does not implement:

- N buyers × N sellers, heterogeneous products, split awards, or multi-attribute scoring;
- LLM negotiation, semantic catalogs, or vector search;
- collusion detection or Sybil resistance;
- physical fulfillment verification;
- blockchain or zero-knowledge proofs;
- commit/reveal bidding;
- production deployment, persistence, or databases;
- Razorpay Route or live account onboarding;
- live money movement; or
- webhook, refund, reversal, settlement, or reconciliation integration.

Razorpay payment integration is a later integration boundary, not implemented behavior in this repository.

## Repository layout

- `src/clear_market/domain`: immutable market, identity, bid, money, and primitive models.
- `src/clear_market/crypto`: policy commitments and Ed25519 bid signatures.
- `src/clear_market/canonical`: restricted deterministic JSON projections.
- `src/clear_market/lifecycle`: stateless and stateful bid admission.
- `src/clear_market/mechanism`: production reverse second-price allocation.
- `src/clear_market/oracle`: independent reference allocation.
- `src/clear_market/certificate`: certificate model, builder, canonical bytes, digest, and parser.
- `src/clear_market/verification`: independent certificate verification.
- `src/clear_market/benchmark`: deterministic generator and differential runner.
- `src/clear_market/cli.py`: `clear verify` command.
- `tests/`: unit, differential, property, adversarial, CLI, and evidence snapshot tests.
- `benchmarks/`: immutable frozen evaluation report and provenance manifest.
- [REPRODUCIBILITY.md](REPRODUCIBILITY.md): normal verification and optional historical replay.
