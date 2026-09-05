# CLEAR

**Proof-Carrying Market Infrastructure for Autonomous AI Commerce**

> AI interprets fuzzy commercial intent; deterministic systems decide which economic agreement
> wins and where the money goes.

CLEAR is an executable trust boundary for commerce among autonomous agents. A buyer can express
what it wants in natural language, independent seller agents can construct offers from their own
catalogs and policies, and a deterministic core can select an agreement, emit replayable evidence,
and authorize a payment plan. The language model is useful at the ambiguity boundary; it is never
the authority for constraints, winners, prices, or money movement.

## The invariant

> **NO VALID CERTIFICATE = NO MONEY ACTION**

An AI response, merchant proposal, stored allocation, or payment-provider request is insufficient
on its own. Before any provider-side money action, CLEAR independently verifies the allocation
certificate and passes it through the Money Governor, which produces the immutable execution plan
that downstream adapters are allowed to use.

## How CLEAR works

```text
AI / UNTRUSTED ADVISORY
  buyer natural language
      -> buyer-intent candidate

DETERMINISTIC / AUTHORITATIVE
  strict parse + validation + trusted-context freeze
      -> BuyerPolicyV2
      -> merchant catalog + inventory snapshot + economic policy

AI / UNTRUSTED ADVISORY
  per-merchant offer proposal

DETERMINISTIC / AUTHORITATIVE
  merchant-specific validation + offer construction
      -> authenticated SignedMerchantOfferV2 values
      -> heterogeneous multiwinner allocation
      -> AllocationCertificateV2
      -> independent replay verifier
      -> Money Governor
      -> immutable approved ExecutionPlanV1

EXTERNAL PROVIDER BOUNDARY
  Razorpay Test Mode order operation

DETERMINISTIC / AUTHORITATIVE
  validated provider facts + authenticated webhooks + deterministic payment-state replay
      -> captured-payment gate
      -> transfer / recovery decision

EXTERNAL PROVIDER BOUNDARY
  Razorpay Route transfer creation or reconciliation when authorized
```

The production path is **one buyer × N autonomous sellers**. It is not an N-buyer exchange, and
the diagram does not imply that every subsystem has been exercised against a live external
service.

## What is implemented

| Area | Current status | Authority boundary |
| --- | --- | --- |
| Buyer-intent interpretation | Implemented and tested. The live buyer-intent path was exercised once successfully through an externally supplied OpenAI-compatible provider. | AI output is an untrusted candidate; strict parsing and trusted-context freezing produce `BuyerPolicyV2`. |
| Merchant-offer proposal | Implemented and tested with fake providers; no live merchant-proposal run is claimed. | Each candidate is checked against that merchant's catalog, inventory, and economic policy before deterministic offer construction. |
| Certificate explanation | Implemented and tested with fake providers; no live explanation run is claimed. | Explanation is advisory and is only produced for independently verified certificate evidence. |
| OpenAI-compatible adapter | Implemented as synchronous Chat Completions over HTTPS with externally supplied provider name, base URL, key, and model identifier. | It is a transport adapter, not an economic decision-maker. |
| Development live profile | Implemented and tested with fakes. Real cross-model profiling was attempted, but the runs aborted on provider unavailability before a comparison completed; no result or ranking is claimed. | Fixed buyer cases, deterministic merchant fixtures, a four-call-per-model budget, and sanitized reporting. |
| V2 market and merchant authentication | Implemented and tested. | Canonical commitments and Ed25519 signatures bind merchant offers to trusted identities and frozen sources. |
| V2 production allocation | Implemented and tested with deterministic OR-Tools CP-SAT. | Pure authoritative mechanism code decides allocation and payment fields from admitted offers. |
| V2 certificate and independent verifier | Implemented and tested. | The verifier replays evidence and recomputes allocation with an independent reference oracle. |
| Money Governor and SQLite financial ledger | Implemented and tested. | A verified certificate plus explicit financial authorization is required to reserve an execution and issue an immutable plan. |
| Razorpay Test Mode boundary | Order, authenticated webhook, Route mapping, transfer, replay, reconciliation, recovery, and orchestration code is implemented and tested with controlled transports. One reviewed historical external Razorpay Test Mode order-provider exercise succeeded: order creation persisted a provider reference, and a second identical call resolved the existing provider order through provider-backed retrieval. Live payment capture, transfer, settlement, and real-money paths remain unexercised. | Only a governor-approved plan may drive provider operations; authenticated observations return to deterministic state replay. |
| AgentMarketBench replacement final holdout | Stored 10,000-scenario evidence is committed and integrity-tested. | It is evaluation evidence for the defined distribution, not production telemetry or universal model/mechanism proof. |

“OpenAI-compatible” describes the wire protocol. The one historical live buyer-intent exercise was
through an externally supplied compatible provider; this repository does not identify it as an
official OpenAI endpoint and publishes no endpoint, credential, or reseller information.

## Why this architecture is different

Many agent-commerce demos let an LLM negotiate, choose, and call a payment API in one opaque
loop. CLEAR splits those responsibilities:

- AI proposes typed candidates at fuzzy-language boundaries.
- Deterministic code validates every candidate against frozen, merchant-specific sources.
- Sellers authenticate their offers before allocation.
- The production allocator emits evidence rather than only an answer.
- A structurally independent verifier recomputes the relevant semantics.
- The Money Governor converts verified evidence and explicit authorizations into the only approved
  provider-side plan.
- Webhook inputs are authenticated; provider observations are validated and recorded before
  deterministic replay, rather than trusted merely because an API call returned.

This creates an auditable chain from intent to economic decision to payment authorization without
pretending that signatures prove physical inventory or that a certificate proves fulfillment.

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

A valid certificate proves internal consistency under the implemented protocol and supplied trust
roots. It does not prove:

- that catalog or inventory claims are physically true (a signature establishes attribution, not
  real-world truth);
- that awarded goods were shipped or fulfilled;
- that a supplied transcript includes every real timely offer without an external trusted receipt
  system;
- formal verification, a zero-knowledge proof, or a blockchain record; or
- legal validity or settlement finality.

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

These paths have automated tests with controlled transports. Separately, one reviewed historical
external Razorpay Test Mode order-provider exercise succeeded: order creation persisted a provider
reference, and a second identical call resolved the existing order through provider-backed retrieval.
This evidence is limited to the order path and is not repository-level cryptographic proof of the
historical run. It does not demonstrate payment capture, customer payment, Route transfer creation,
settlement, refunds, reversals, disputes, physical fulfillment, or real-money movement. Transfer
creation is not settlement. Refunds, reversals, settlement processing, and physical fulfillment are
not implemented. Ledger reservations, fingerprints, provider references, and reconciliation reduce
duplicate effects, but CLEAR does not claim exactly-once delivery across an external network.

## AgentMarketBench: what the stored evidence says

The committed replacement final holdout contains 10,000 deterministic scenarios. It was not
regenerated for this documentation update. On that exact corpus:

- CLEAR has higher welfare and completion than `RANDOM_QUALIFYING_SELLER`,
  `CHEAPEST_QUALIFYING`, `STATIC_WEIGHTED_SCORE`, `BILATERAL_NEGOTIATION`, and
  `SEQUENTIAL_NEGOTIATION`; the corresponding descriptive paired 95% intervals exclude zero.
- CLEAR and `FIRST_PRICE_REVERSE_AUCTION` have near-identical aggregates. The
  first-price-minus-CLEAR intervals include zero for welfare, regret, and allocation efficiency,
  so the evidence does not establish that CLEAR beats or is equivalent to first price.
- The full-information oracle is a latent upper bound. CLEAR is materially below it, so the result
  is not a near-optimality claim.
- CLEAR and `FIRST_PRICE_REVERSE_AUCTION` both record 47 successful manipulation cases out of
  1,310 applicable observations and a mean hard-constraint-violation rate of 1/125 (`0.008`).
  These are measured limitations, not security guarantees.

On this frozen benchmark, CLEAR reaches first-price-auction-level aggregate economic outcomes
while its broader runtime architecture adds authenticated offers, deterministic multiwinner
allocation, replay-verifiable certificates, and the Money Governor boundary. That is an
architecture comparison, not a claim of economic dominance or statistical equivalence.

Latency numbers are environment-sensitive. The benchmark covers its declared market/evaluation
path; it is not evidence that AI, certificate explanation, payments, Razorpay, recovery, or
physical fulfillment ran end to end. See the
[replacement final results](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md) for exact metrics,
intervals, provenance, and limitations.

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
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
.venv/bin/python -m pytest -q
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

## Scope and non-goals

CLEAR currently does not provide:

- an N-buyer exchange, continuous market, or general combinatorial auction;
- proof that participant-signed claims are true in the physical world;
- transcript completeness without an external trusted receipt/observation system;
- fulfillment, shipping, disputes, refunds, reversals, or settlement processing;
- live payment-capture, transfer, settlement, refund/reversal, or real-money evidence; demonstrated
  external Razorpay evidence is limited to the Test Mode order path;
- exactly-once external delivery;
- collusion or Sybil resistance;
- formal verification, zero-knowledge proofs, or blockchain consensus; or
- a universal AI model or market-mechanism ranking.

## Documentation and evidence

- [Current architecture](docs/ARCHITECTURE.md)
- [Final system contract](docs/FINAL_SYSTEM_CONTRACT.md)
- [V2 mechanism contract](docs/MECHANISM_V2_CONTRACT.md)
- [AgentMarketBench replacement final results](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md)
- [Reproducibility and evidence integrity](REPRODUCIBILITY.md)

Historical v1 contracts and evidence remain in the repository as explicitly versioned artifacts;
they should not be read as the current top-level system description.
