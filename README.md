# CLEAR

**Proof-Carrying Market Infrastructure for Autonomous AI Commerce**

> AI proposes. Deterministic rules decide. Proof carries the decision. Money waits for verified
> authority.

**[Open the public judge product](https://clear-production-8197.up.railway.app)**

AI is useful for understanding a fuzzy commercial request. It should not get to decide who wins or
where money goes. CLEAR separates those jobs.

A buyer can describe what they want in natural language. AI proposes a candidate policy, then
deterministic code validates it against trusted context and freezes `BuyerPolicyV2`. Merchants add
their own catalog, inventory, and economic inputs, optionally ask AI for a proposal, and explicitly
submit signed offers. When the market is explicitly closed, CLEAR allocates it, creates an
`AllocationCertificateV2`, and independently replays the decision. Only a verified certificate
lets the Money Governor issue an `ExecutionPlanV1`.

Raw AI never authorizes money. Raw allocation never authorizes money. The browser presents server
results but does not construct policy authority, awarded quantities, certificate verdicts,
Governor decisions, or execution plans.

> **NO VALID CERTIFICATE = NO MONEY ACTION**

CLEAR is market infrastructure, not a shopping assistant, reverse-auction dashboard, agent wallet,
Razorpay wrapper, or generic audit log. Its proofs are replayable certificates, not blockchain
records, zero-knowledge proofs, or formal verification.

## Try CLEAR

### Public judge product

The public product has exactly three workspaces: **BUYER → MERCHANT → CLEARING**. Evidence is not a
fourth workspace.

The reviewed deployment supports this judge flow:

1. Enter buyer intent and ask the externally configured OpenAI-compatible provider for an advisory
   candidate.
2. Inspect the candidate and deterministically freeze it as `BuyerPolicyV2`.
3. Open an already-eligible merchant. To use a new merchant, create it before starting the buyer
   draft so it can be included in the eligible merchant set.
4. Ask AI for an advisory merchant proposal, then explicitly submit it so the server
   deterministically constructs, signs, and authenticates the offer.
5. Close the `OPEN` market and inspect the deterministic multiwinner allocation and
   `AllocationCertificateV2`.
6. Run the independent verifier, alter a certificate copy, and observe
   `POLICY_COMMITMENT_MISMATCH`, `CERTIFICATE_NOT_VERIFIED`, and no money action.
7. Return to the valid certificate, authorize it through the Money Governor, and inspect
   `ExecutionPlanV1`.
8. Explicitly create a Razorpay Test Mode order.
9. Open Razorpay Standard Checkout in Test Mode. The browser callback remains advisory; the
   server accepts authenticated webhook input and deterministically replays payment state.
10. Observe `PAYMENT_CAPTURED` only after authenticated webhook evidence and server replay confirm
    the state.

An earlier reviewed order-only observation returned `CREATED` for the first Razorpay Test Mode order
request and `EXISTING` for an identical provider-backed retrieval. That earlier observation used
**₹2,250 / 225000 paise INR**.

The reviewed public Test Mode run then demonstrated a payment progressing to `PAYMENT_CAPTURED`
only after an authenticated Razorpay webhook was accepted and deterministic server replay confirmed
the payment state. Its historical evidence identity was provider order `order_TawQXx7CYUnomd`,
provider payment `pay_TawQsZwHzumnsu`, execution `17096ec0-d355-43ab-9fe1-fbc6fdb4f6ca`, and
**₹3,750.00 / 375000 paise INR**. The replay UI showed webhook disposition `—`; this run is not a
claim that later sessions will reproduce the same provider observation automatically.

AI and Razorpay actions occur only when the user requests them. Provider configuration and secrets
stay on the server. The deployment is one application process and one ephemeral SQLite-backed demo
session shared by its visitors. It is judge infrastructure, not a production-grade multi-tenant
service, and a restart creates fresh seeded state.

The reviewed public run is **HISTORICAL LIVE EVIDENCE ONLY** for Test Mode checkout, authenticated
webhook ingress, and deterministic captured-payment replay. It does not demonstrate settlement,
supplier transfer or payout, Route transfer execution, refunds or reversals, physical fulfillment,
disputes, real-money movement, or exactly-once external delivery.

### Local deterministic rehearsal

```sh
.venv/bin/python -m ui.judge_demo
```

Open `http://127.0.0.1:8765/#clearing`. This launcher creates an isolated temporary session and a
fresh product database. It starts with an `OPEN` market, exactly two authenticated submitted offers,
and no winner. Allocation happens only after explicit close.

The local rehearsal removes AI and Razorpay configuration from its own process before starting the
server. It makes no provider call and cannot be used to demonstrate live AI or live Razorpay. It is
a deterministic fallback for reviewing allocation, the certificate, tamper rejection, the
Governor, and `ExecutionPlanV1`.

## How authority moves through CLEAR

```text
buyer natural language
    -> advisory AI candidate
    -> strict parse + trusted-context freeze
    -> BuyerPolicyV2

merchant catalog + inventory + economic policy
    -> optional advisory AI candidate
    -> deterministic MerchantOfferV2 construction
    -> signed/authenticated offers

explicit market close
    -> deterministic multiwinner allocation
    -> AllocationCertificateV2
    -> independent replay verifier
    -> Money Governor
    -> ExecutionPlanV1

explicit Razorpay Test Mode action
    -> validated provider facts / authenticated webhooks
    -> deterministic payment-state replay
    -> captured-payment gate
    -> transfer or recovery path
```

The production path is one buyer and multiple eligible sellers. Server-side production code owns
every authoritative transition. AI remains advisory, and payment adapters accept only a
Governor-approved plan.

## What is implemented

| Area | Implementation and boundary |
| --- | --- |
| Buyer intent | An OpenAI-compatible provider can propose a candidate. Strict parsing and trusted-context freezing create `BuyerPolicyV2`. |
| Merchant workflow | The server creates merchant identity and trusted supply inputs. AI may propose values; deterministic construction, signing, authentication, and explicit submission create the offer evidence. Private signing keys never enter the browser. |
| Allocation | Deterministic OR-Tools CP-SAT implements `heterogeneous-pay-as-bid-v2` and `quantity-cost-soft-objective-v2` using integer paise. |
| Certificate and verifier | `AllocationCertificateV2` carries the decision evidence. A structurally independent oracle replays admission and allocation rather than trusting the stored result. |
| Money Governor | A verified certificate plus explicit financial authorization reserves an execution in SQLite and produces immutable `ExecutionPlanV1`. |
| Razorpay Test Mode | Governor-gated order, webhook, payment-state, Route mapping, transfer, reconciliation, and recovery code is implemented. Reviewed public Test Mode evidence covers order creation and authenticated captured-payment replay; transfer/recovery/settlement execution is not demonstrated by that run. |
| AgentMarketBench | The replacement final evaluation covers 10,000 cases. It is evidence for its frozen corpus, not production telemetry. |

In the reviewed public judge run, an externally supplied OpenAI-compatible provider produced an
advisory merchant proposal. The offer gained authority only after explicit deterministic
construction, signing, authentication, and submission.

The repository also contains an advisory certificate-explanation task. CLEAR's
certificate-explanation task was exercised through an externally supplied OpenAI-compatible
provider after independent certificate verification. AI did not verify the certificate or change
authority. “OpenAI-compatible” describes the wire protocol and does not identify the external
provider as an official OpenAI service.

## Mechanism

The current mechanism is `heterogeneous-pay-as-bid-v2` with objective
`quantity-cost-soft-objective-v2`. It supports heterogeneous or substitutable SKUs, typed hard
constraints and soft preferences, merchant-specific capacity and minimum-price policy, partial
fulfillment, split awards, multiple winners, and bounded integer INR paise.

The objective is lexicographic:

1. maximize fulfilled quantity;
2. minimize total pay-as-bid payment;
3. maximize soft-preference score; and
4. choose the deterministic canonical allocation among remaining ties.

CLEAR does not claim Vickrey semantics, general truthfulness, strategy-proofness, collusion
resistance, or Sybil resistance.

## What the certificate proves

`AllocationCertificateV2` binds the buyer policy, trusted market and merchant evidence,
authenticated offers and admission outcomes, mechanism identity, and allocation. Canonical
serialization and digests make it stable to exchange and inspect.

The independent verifier reparses the certificate, rechecks source commitments and signatures,
replays admission, computes the expected allocation with an independent reference oracle, and
compares every authoritative result field. The reference oracle does not import the production
CP-SAT allocator.

A valid certificate establishes internal consistency with the supplied evidence and trust roots.
It cannot establish physical inventory truth, shipment, settlement, or transcript completeness.

## Money and provider boundary

The Money Governor requires successful certificate verification plus explicit market, buyer,
merchant-recipient, budget, and execution authorizations. It reserves the execution and returns an
immutable plan. An AI response, merchant proposal, or stored allocation is insufficient.

The Razorpay integration is Test Mode only. Provider responses and authenticated webhook inputs are
validated and recorded before deterministic payment-state replay. Transfer work additionally
requires recorded captured-payment evidence. A provider order or transfer object is not proof of
customer payment, settlement, or fulfillment. The reviewed public Test Mode evidence reached
`PAYMENT_CAPTURED` through authenticated webhook input and deterministic replay; that historical
observation is not settlement, payout, fulfillment, or real-money evidence.

## Evidence labels

CLEAR uses five evidence classes:

1. **REAL LOCAL PRODUCTION LOGIC** — the production implementation ran locally.
2. **DETERMINISTIC FIXTURE** — inputs came from fixed, reproducible demo data.
3. **FAKE/CONTROLLED EXTERNAL TRANSPORT** — production boundary code ran against a controlled fake.
4. **HISTORICAL LIVE EVIDENCE ONLY** — a reviewed run reached a real external provider; it is
   evidence for that observed run, not every later session.
5. **NOT DEMONSTRATED** — the run provides no evidence for the capability.

One flow can combine several classes. Code existence is not live evidence, and
`NOT INVOKED BY BOOTSTRAP` is an operational state rather than a sixth class.

## AgentMarketBench

The judge-facing comparison is the
[AgentMarketBench replacement final evaluation](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md).
It evaluated source commit `6eadd5b6eb737649ec35747a73d90b69c403e24f` on 10,000 final cases. Its
manifest SHA-256 is `27c8cc724634caec4a587a52e5687b76fefb47500b8261244cf3762bb7099c3a`,
and its evidence-root SHA-256 is
`9b9d3fd24d0efe0fed26cdaf63fc5ff6ff4b843ad8061d70c09232c021500c51`.

On that frozen corpus, CLEAR has higher welfare and completion than
`RANDOM_QUALIFYING_SELLER`, `CHEAPEST_QUALIFYING`, `STATIC_WEIGHTED_SCORE`,
`BILATERAL_NEGOTIATION`, and `SEQUENTIAL_NEGOTIATION`. The corresponding descriptive paired 95%
intervals exclude zero.

`FIRST_PRICE_REVERSE_AUCTION` is near-identical in aggregate. The report does not show that CLEAR
beat first price and does not establish statistical or formal equivalence. The full-information
oracle is a latent upper bound, not a deployable method.

CLEAR reaches first-price-auction-level aggregate economic outcomes on this frozen benchmark while
its broader architecture adds authenticated offers, deterministic multiwinner allocation,
replay-verifiable allocation certificates, and the Money Governor boundary.

Measured limitations remain visible: 47 successful manipulation cases out of 1,310 applicable
observations, and a mean latent hard-violating allocated-unit count per case of 1/125 (`0.008`). The
benchmark is not a universal ranking of market mechanisms or AI models.

The replacement holdout is permanently closed and must not be rerun. The linked results document
contains the exact metrics, intervals, provenance, and interpretation limits.

## Install and verify

CLEAR requires Python `>=3.12,<3.13`.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pip check
```

Run the normal holdout-safe checks:

```sh
.venv/bin/python -m ruff check . \
  --exclude benchmarks/agentmarketbench_v1/final_holdout_v1
.venv/bin/python -m ruff format --check . \
  --exclude benchmarks/agentmarketbench_v1/final_holdout_v1
.venv/bin/python -m mypy src
.venv/bin/python -m mypy \
  ui/demo_bootstrap.py ui/judge_demo.py ui/public_demo.py
.venv/bin/python -m pytest -q \
  --ignore=benchmarks/agentmarketbench_v1/final_holdout_v1
PYTHONHASHSEED=1 .venv/bin/python -m pytest -q \
  --ignore=benchmarks/agentmarketbench_v1/final_holdout_v1
```

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for evidence identity and interpretation boundaries.

## Repository map

- `src/clear_market/ai`: typed AI tasks, strict parsing, and the OpenAI-compatible adapter.
- `src/clear_market/commerce`: buyer policy, merchant sources, offers, and authentication.
- `src/clear_market/mechanism/v2`: production CP-SAT allocation.
- `src/clear_market/oracle/v2`: structurally independent reference allocation.
- `src/clear_market/certificate/v2` and `verification/v2`: proof construction and replay.
- `src/clear_market/execution` and `persistence`: Governor, plans, and SQLite ledger.
- `src/clear_market/payments` and `orchestration`: Razorpay Test Mode boundaries and recovery.
- `src/clear_market/agentmarketbench`: deterministic evaluation and evidence-integrity tooling.
- `ui`: the Buyer, Merchant, and Clearing product plus local/public launchers.
- `tests`: unit, property, differential, adversarial, integration, and evidence tests.

## Limits

- CLEAR is a one-buyer, many-seller market, not an N-buyer exchange or general combinatorial
  auction.
- Signatures prove attribution and integrity, not the physical truth of catalog or inventory
  claims.
- Transcript completeness requires an external trusted receipt or observation system.
- Physical fulfillment, shipping, disputes, refunds, reversals, and settlement processing are not
  implemented.
- The reviewed public Test Mode run includes authenticated webhook and deterministic replay evidence
  reaching `PAYMENT_CAPTURED`, but does not include supplier transfer/payout, Route transfer
  execution, settlement, refunds, reversals, fulfillment, disputes, or real-money movement.
- Ledger reservations, request fingerprints, provider references, and reconciliation reduce
  duplicate effects; they do not provide exactly-once external delivery.
- CLEAR does not claim collusion resistance, Sybil resistance, formal verification, zero-knowledge
  proof, blockchain consensus, or a universal mechanism/model ranking.

## Documentation

- [Current architecture](docs/ARCHITECTURE.md)
- [V2 mechanism contract](docs/MECHANISM_V2_CONTRACT.md)
- [AgentMarketBench replacement final results](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md)
- [AgentMarketBench replacement final-holdout record](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_HOLDOUT_V1.md)
- [Reproducibility and evidence integrity](REPRODUCIBILITY.md)
