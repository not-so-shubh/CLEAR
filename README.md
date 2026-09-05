# CLEAR

**Proof-Carrying Market Infrastructure for Autonomous AI Commerce**

> AI proposes. Deterministic rules decide. Proof carries the decision. Money waits for verified
> authority.

AI is good at understanding a fuzzy request. It is much less suitable for deciding who wins or who
gets paid. CLEAR separates those jobs.

A buyer can describe what they want in natural language. AI can propose a candidate, but
deterministic code parses it against trusted context and freezes the actual rules as
`BuyerPolicyV2`. Merchants submit signed offers. CLEAR allocates the market, creates an
`AllocationCertificateV2`, replays the decision with an independent verifier, and only then lets
the Money Governor issue an `ExecutionPlanV1`.

Raw AI never authorizes money. Neither does a raw allocation. The browser only presents server
results; it never constructs authority, awarded quantities, verifier or Governor decisions, or an
execution plan. Production code on the server remains authoritative.

CLEAR is market infrastructure, not a shopping assistant, procurement/reverse-auction dashboard,
agent wallet, Razorpay wrapper, or generic audit log. Its proofs are replayable certificates, not
blockchain records, zero-knowledge proofs, or formal verification.

## The invariant

> **NO VALID CERTIFICATE = NO MONEY ACTION**

An AI response, merchant proposal, stored allocation, or payment-provider request is not enough.
CLEAR checks the certificate again before the Governor can issue the immutable plan used by
payment adapters.

## What happens in CLEAR

1. AI helps interpret the buyer's request. A strict parser combines that candidate with trusted
   context and freezes `BuyerPolicyV2`.
2. Each merchant starts from its own trusted catalog, inventory, and pricing policy. Merchant AI
   may suggest an offer, but deterministic rules build `MerchantOfferV2`; the submitted offer is
   signed and authenticated.
3. The market stays open until an explicit close. Only then does the deterministic multiwinner
   allocator decide quantities, winners, and integer-paise payments.
4. CLEAR records that result in `AllocationCertificateV2`. A separate verifier replays admission
   and allocation instead of trusting the stored answer.
5. The Money Governor accepts only a verified certificate plus explicit financial authorization.
   If those checks succeed, it reserves the execution and issues `ExecutionPlanV1` for downstream
   payment adapters.

## Judge demo: one command

```sh
.venv/bin/python -m ui.judge_demo
```

The launcher creates an isolated temporary session and bootstraps a fresh product database. The
sibling financial-ledger path is inside that session but remains absent at startup. The ledger is
created only if the later authority path needs it.

Before creating the local server, the launcher points its own process at the product database and
removes AI-provider settings and Razorpay Test Mode credentials from its environment. That same
process serves the UI. AI and Razorpay are disabled for this rehearsal, and neither is called
automatically.

Open `http://127.0.0.1:8765/#clearing`. The UI has exactly **BUYER → MERCHANT → CLEARING**;
Evidence is not a fourth workspace. The market starts `OPEN` with two authenticated merchant offers
and no winner. Closing the market is what triggers allocation.

The review flow is straightforward:

1. Open Clearing and close the market.
2. Inspect the allocation and `AllocationCertificateV2`.
3. Tamper with the certificate copy.
4. Watch the independent verifier reject it and the Money Governor refuse authority.
5. Return to the valid certificate and authorize it.
6. Inspect the resulting `ExecutionPlanV1`.

This launcher is always provider-disabled. It does not demonstrate live AI or live Razorpay, and it
cannot be used to enable either one. Razorpay is **NOT DEMONSTRATED** in this judge run.

## Authority path

```text
AI / ADVISORY
  buyer natural language
      -> buyer-intent candidate

DETERMINISTIC / AUTHORITATIVE
  strict parse + validation + trusted-context freeze
      -> BuyerPolicyV2
      -> trusted merchant catalog + inventory snapshot + economic policy

AI / ADVISORY
  optional per-merchant offer candidate

DETERMINISTIC / AUTHORITATIVE
  merchant-specific validation + deterministic MerchantOfferV2 construction
      -> signed/authenticated offers
      -> deterministic multiwinner allocation
      -> AllocationCertificateV2
      -> independent replay verifier
      -> Money Governor
      -> ExecutionPlanV1

RAZORPAY TEST MODE PROVIDER BOUNDARY
  order operation
      -> validated provider facts + authenticated webhooks
      -> deterministic payment-state replay
      -> captured-payment gate
      -> transfer / recovery
```

The production path is **one buyer × N autonomous sellers**, not an N-buyer exchange. The diagram
shows the full implemented authority path. The provider-disabled judge demo exercises only the
local steps described above.

## Evidence taxonomy

CLEAR uses exactly five evidence classes:

1. **REAL LOCAL PRODUCTION LOGIC** — the actual production implementation ran locally.
2. **DETERMINISTIC FIXTURE** — the inputs came from fixed, reproducible demo data.
3. **FAKE/CONTROLLED EXTERNAL TRANSPORT** — the production provider boundary ran against a
   controlled fake instead of a live service.
4. **HISTORICAL LIVE EVIDENCE ONLY** — a reviewed earlier run reached a real external provider. It
   says nothing about whether the current demo reached that provider.
5. **NOT DEMONSTRATED** — the run being discussed provides no evidence for the capability.

A deterministic demo can contain several of these classes at once. The allocator, certificate
builder, independent verifier, and Money Governor are **REAL LOCAL PRODUCTION LOGIC** when the demo
actually runs them. The same applies to the financial ledger and provider adapter when those parts
of the path are used. Seeded buyer and merchant inputs are **DETERMINISTIC FIXTURE**. A controlled
fake provider is **FAKE/CONTROLLED EXTERNAL TRANSPORT**.

For judge startup, live AI is `NOT INVOKED BY BOOTSTRAP`; that is an operational state, not a sixth
evidence class. The run supplies no live-AI evidence, and live Razorpay is **NOT DEMONSTRATED**.

## What is implemented

| Area | Current status | Authority boundary |
| --- | --- | --- |
| Buyer-intent interpretation | Implemented and tested. One reviewed historical run exercised the live buyer-intent path through an externally supplied OpenAI-compatible provider. | AI supplies a candidate. Strict parsing and trusted-context freezing produce `BuyerPolicyV2`. |
| Merchant-offer proposal | Implemented and tested. CLEAR's merchant-proposal task was exercised through an externally supplied OpenAI-compatible provider. The reviewed run returned a schema-valid `NO_OFFER` and passed the strict advisory production boundary. That run did not demonstrate signing, authentication, admission, allocation, winner selection, or payment authorization. | Each candidate is checked against that merchant's catalog, inventory, and economic policy before deterministic offer construction. |
| Certificate explanation | Implemented and tested. CLEAR's certificate-explanation task was exercised through an externally supplied OpenAI-compatible provider after independent certificate verification. The returned citation references passed CLEAR's validation checks. AI did not verify the certificate; the run did not provide natural-language entailment proof or formal proof, and it did not change authority. | Explanation is advisory and is only produced for independently verified certificate evidence. |
| OpenAI-compatible adapter | Implemented as synchronous Chat Completions over HTTPS with externally supplied provider name, base URL, key, and model identifier. | It is a transport adapter, not an economic decision-maker. |
| Development live profile | Implemented and tested with fakes. Real cross-model profiling was attempted, but the runs aborted on provider unavailability before a comparison completed; no result or ranking is claimed. | Fixed buyer cases, deterministic merchant fixtures, a four-call-per-model budget, and sanitized reporting. |
| V2 market and merchant authentication | Implemented and tested. | Canonical commitments and Ed25519 signatures bind merchant offers to trusted identities and frozen sources. |
| V2 production allocation | Implemented and tested with deterministic OR-Tools CP-SAT. | Pure authoritative mechanism code decides allocation and payment fields from admitted offers. |
| V2 certificate and independent verifier | Implemented and tested. | The verifier replays evidence and recomputes allocation with an independent reference oracle. |
| Money Governor and SQLite financial ledger | Implemented and tested. | A verified certificate plus explicit financial authorization is required to reserve an execution and issue an immutable plan. |
| Razorpay Test Mode boundary | Order, authenticated webhook, Route mapping, transfer, replay, reconciliation, recovery, and orchestration code is implemented and tested with controlled transports. External provider use is classified **HISTORICAL LIVE EVIDENCE ONLY** and is bounded below. | Only a governor-approved plan may drive provider operations; authenticated observations return to deterministic state replay. |
| AgentMarketBench frozen evaluation report | The committed report covers 10,000 frozen scenarios and is integrity-tested. | It is evaluation evidence for the defined distribution, not production telemetry or universal model/mechanism proof. |

“OpenAI-compatible” describes the wire protocol. The one historical live buyer-intent exercise was
through an externally supplied compatible provider; this repository does not identify it as an
official OpenAI endpoint and publishes no endpoint, credential, or reseller information.

## V2 market mechanism

The current production mechanism is `heterogeneous-pay-as-bid-v2` with objective
`quantity-cost-soft-objective-v2`:

- one buyer and multiple eligible merchants;
- heterogeneous or substitutable catalog SKUs;
- typed hard constraints and soft preferences with provenance requirements;
- merchant-specific inventory capacity and minimum-price policy;
- partial fulfillment and split awards across multiple winners;
- integer INR paise arithmetic; and
- deterministic allocation and tie-breaking.

The CP-SAT objective is hierarchical: maximize fulfilled quantity, minimize total payment,
maximize soft-preference score, then choose the lexicographically deterministic allocation. It is
pay-as-bid. CLEAR does **not** claim Vickrey semantics, general truthfulness, strategy-proofness,
collusion resistance, or Sybil resistance for this mechanism.

The older homogeneous single-winner v1 reverse-second-price protocol remains versioned and tested
for historical compatibility. It is not the primary architecture described here.

## Proof-carrying decisions

`AllocationCertificateV2` carries the buyer policy, trusted market and merchant evidence,
authenticated offers and admission outcomes, versioned mechanism/objective identity, and the
resulting allocation. Canonical serialization and digests make the artifact stable to exchange and
inspect.

The independent verifier does not simply accept the stored allocation or admission labels. It
revalidates the relevant inputs, replays admission, invokes a structurally independent V2 oracle,
and compares the frozen result semantics. The reference oracle does not import the production
CP-SAT allocator.

A valid certificate shows that the decision is internally consistent with the protocol and supplied
trust roots. It cannot show that a merchant's catalog or inventory claim is physically true, that
every timely offer appears in the transcript, or that goods were shipped or settled. The complete
scope boundary is listed below.

## Financial authorization and Razorpay boundary

The Money Governor accepts only independently verified certificate evidence plus explicit market,
buyer, merchant-recipient, budget, and execution authorizations. It reserves the execution in the
SQLite financial ledger and returns an immutable `ExecutionPlanV1`. Raw AI output and a raw
`AllocationV2` cannot authorize an order or transfer.

The Razorpay Test Mode integration includes:

- order creation under a governor-approved plan;
- webhook signature authentication and immutable event recording;
- deterministic Route mapping to authorized linked accounts;
- captured-payment evidence checks before transfer work;
- transfer creation or reconciliation against recorded provider facts;
- deterministic payment-state replay; and
- order recovery plus normal and graceful orchestration paths.

These paths have automated tests with controlled transports. Separately, and classified
**HISTORICAL LIVE EVIDENCE ONLY**, CLEAR’s Governor-gated Razorpay order path was exercised against
real Razorpay Test Mode: order creation succeeded and a second identical call resolved the existing
provider order through provider-backed retrieval.

That earlier run showed Test Mode order creation and retrieval, nothing more. It did not show a
customer payment, payment capture, webhook delivery, transfer creation, settlement, fulfillment,
real money, refunds or reversals, exactly-once delivery, or full-system execution.

## AgentMarketBench: what the frozen report says

The frozen report is `benchmarks/frozen_evaluation_report_v1.json` (SHA-256
`d63d4217486daf9ca1cc4840bbcd091b5589507cfa376a232eb61fc08ed7e2fe`) and covers 10,000 frozen
scenarios. On that exact corpus:

- CLEAR has higher welfare and completion than `RANDOM_QUALIFYING_SELLER`,
  `CHEAPEST_QUALIFYING`, `STATIC_WEIGHTED_SCORE`, `BILATERAL_NEGOTIATION`, and
  `SEQUENTIAL_NEGOTIATION`; the corresponding descriptive paired 95% intervals exclude zero.
- `FIRST_PRICE_REVERSE_AUCTION` is near-identical in aggregate. Its paired intervals against CLEAR
  include zero for welfare, regret, and allocation efficiency. The report does not show that CLEAR
  beat first price, and it does not prove statistical or formal equivalence.
- The full-information oracle is a latent, non-deployable upper bound. CLEAR is materially below
  it, so the result is not a near-optimality claim.
- CLEAR and `FIRST_PRICE_REVERSE_AUCTION` both record 47 successful manipulation cases out of
  1,310 applicable observations and a mean hard-constraint-violation rate of 1/125 (`0.008`).
  These are measured limitations, not security guarantees.

CLEAR reaches first-price-auction-level aggregate economic outcomes on this frozen benchmark while
its broader architecture adds authenticated offers, deterministic multiwinner allocation,
replay-verifiable allocation certificates, and the Money Governor boundary.

The benchmark covers its declared market path only. It did not run AI, certificate explanation,
payments, Razorpay, recovery, or physical fulfillment end to end, and its latency numbers depend on
the environment. See the
[replacement final results](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md) for exact metrics,
intervals, provenance, and limitations.

Verify the committed report bytes without regenerating any benchmark data:

```sh
shasum -a 256 benchmarks/frozen_evaluation_report_v1.json
```

## Quick start

CLEAR is distributed as `clear-market`, imported as `clear_market`, and requires Python
`>=3.12,<3.13`.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pip check
```

Run the normal verification suite:

```sh
.venv/bin/python -m ruff check . \
  --exclude benchmarks/agentmarketbench_v1/final_holdout_v1
.venv/bin/python -m ruff format --check . \
  --exclude benchmarks/agentmarketbench_v1/final_holdout_v1
.venv/bin/python -m mypy src
.venv/bin/python -m pytest -q \
  --ignore=benchmarks/agentmarketbench_v1/final_holdout_v1
```

## Useful verification commands

Inspect the certificate verifier:

```sh
.venv/bin/clear verify --help
```

`clear verify` accepts canonical v1 certificates directly. V2 verification additionally requires
trusted merchant identity mappings supplied with repeatable `--trusted-identity` arguments; use
the command help for the exact `merchant_id=public_key_hex` syntax. The command emits one compact
machine-readable JSON object and fails closed on parse, configuration, or semantic errors.

Verify the stored replacement-final evidence without regenerating the holdout:

```sh
.venv/bin/python -m pytest -q tests/agentmarketbench/test_replacement_final_evidence.py
```

### Optional paid AI profile

The development-only profile is manually runnable:

```sh
.venv/bin/python -m clear_market.ai.live_profile
```

It refuses to run unless the explicit paid-request acknowledgement and all required
`CLEAR_AI_BASE_URL`, `CLEAR_AI_API_KEY`, `CLEAR_AI_PROVIDER_NAME`, and `CLEAR_AI_MODELS`
configuration are present. It accepts at most four ordered model identifiers and performs exactly
four paid calls per model that reaches every phase: two sequential buyer calls and two concurrent
merchant calls, for an absolute maximum of 16. There are no retries or warmups. Do not treat its
tiny fixed corpus or end-to-end timings as a universal model ranking.

## Repository map

- `src/clear_market/ai`: typed AI tasks, strict candidate parsing, the OpenAI-compatible adapter,
  and the guarded live profile.
- `src/clear_market/commerce`: V2 buyer policy, catalogs, inventory, constraints, merchant
  economics, offer construction, and signed-offer authentication.
- `src/clear_market/mechanism/v2`: deterministic production CP-SAT allocation.
- `src/clear_market/oracle/v2`: structurally independent reference allocation.
- `src/clear_market/certificate/v2`: V2 certificate schemas, canonical bytes, digests, and parsing.
- `src/clear_market/verification/v2`: independent evidence replay and certificate verification.
- `src/clear_market/execution`: Money Governor, financial authorization, and immutable execution
  plans.
- `src/clear_market/persistence`: SQLite ledger for executions, provider references, facts, and
  authenticated events.
- `src/clear_market/payments`: Razorpay Test Mode orders, authenticated webhooks, state replay,
  Route mapping, transfers, and recovery.
- `src/clear_market/orchestration`: normal and graceful Razorpay execution coordination.
- `src/clear_market/agentmarketbench`: deterministic scenario, method, metric, statistics, and
  frozen-evidence tooling.
- `tests`: unit, property, differential, adversarial, integration-boundary, and evidence-integrity
  tests.

## Limits

- CLEAR is a one-buyer, many-seller market. It is not an N-buyer exchange, continuous market, or
  general combinatorial auction.
- A signature shows who made a catalog or inventory claim. It does not make that claim physically
  true.
- Transcript completeness needs an external trusted receipt or observation system. CLEAR does not
  guarantee that every real, timely offer appears in the supplied transcript.
- Physical fulfillment, shipping, and disputes are outside the implemented system. Refund,
  reversal, and settlement processing are not implemented.
- There is no live evidence of payment capture, transfers, settlement, refunds, reversals, or real
  money. The historical Razorpay evidence covers only the Test Mode order path, and transfer
  creation would not by itself prove settlement.
- Ledger reservations, fingerprints, provider references, and reconciliation reduce duplicate
  effects. CLEAR does not claim exactly-once delivery across an external network.
- The mechanism does not claim collusion or Sybil resistance.
- The certificates are not formal verification, zero-knowledge proofs, or blockchain consensus.
- The benchmark is not a universal ranking of AI models or market mechanisms.

## Documentation and evidence

- [Current architecture](docs/ARCHITECTURE.md)
- [Final system contract](docs/FINAL_SYSTEM_CONTRACT.md)
- [V2 mechanism contract](docs/MECHANISM_V2_CONTRACT.md)
- [AgentMarketBench replacement final results](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md)
- [Reproducibility and evidence integrity](REPRODUCIBILITY.md)

Historical v1 contracts and evidence remain in the repository as explicitly versioned artifacts;
they should not be read as the current top-level system description.
