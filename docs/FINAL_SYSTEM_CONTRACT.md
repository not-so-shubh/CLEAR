# CLEAR Final-System Architecture Contract

> "AI interprets fuzzy commercial intent; deterministic systems decide which economic agreement
> wins and where the money goes."

This document is the normative architecture contract for post-Week-2 CLEAR development.

**CORE KERNEL: IMPLEMENTED**

**FULL FINAL SYSTEM: NOT YET IMPLEMENTED**

The implemented Week-2 v1 kernel is the foundation described below. Every final-system capability
described as required or future remains unimplemented merely by the existence of this contract.
Implementation must proceed through later reviewed slices. In particular, this document does not
claim that AI interpretation, heterogeneous allocation, durable financial execution, Razorpay
integration, or settlement is present.

## Status and authority

CLEAR is intended to become proof-carrying market infrastructure for autonomous AI commerce. This
contract freezes authority, trust boundaries, dependency direction, required evidence, and the
completion criteria for that final system. It does not freeze source code, schemas, algorithms, or
provider behavior that later slices must decide from evidence.

The Week-2 v1 kernel is implemented and remains governed by its existing versioned contracts.
Future capabilities in this document are requirements for later reviewed slices, not descriptions
of current behavior. A later implementation must demonstrate conformance with tests and evidence;
names or packages alone do not establish conformance.

Where this contract says must or must not, it establishes a normative boundary. Where it says
should, it records a preferred design subject to evidence in the responsible slice. An actual defect
in this contract or in v1 requires explicit review rather than an implicit reinterpretation.

## End-to-end trust chain

The required final trust chain is:

~~~text
Buyer natural-language intent
    ↓
AI structured candidate
    ↓ deterministic validation and freeze
BuyerPolicyV2
    ↓
Merchant catalogs and merchant reasoning
    ↓ deterministic merchant authorization and signing
Authenticated MerchantOfferV2 values
    ↓
Deterministic constrained allocator
    ↓
AllocationCertificateV2
    ↓ independent replay and verification
Independent verifier
    ↓
Money Governor
    ↓
Immutable approved ExecutionPlan
    ↓
Persistent financial ledger
    ↓
Razorpay Test Mode adapter
    ↓ verified provider events
Reconciliation, recovery, and settlement
~~~

AI is upstream advisory computation. It does not directly invoke a financial provider, and Razorpay
does not consume model output. The only authorized path to an external financial side effect is:

~~~text
verified certificate
    → Money Governor
    → approved ExecutionPlan
    → payment adapter
~~~

No shortcut around this path is conformant, including direct use of an AI candidate, an unverified
allocation, or a stored provider payload.

## Frozen Week-2 v1 boundary

New final-system semantics must be versioned rather than silently changing the meaning of v1
evidence. The following existing protocol boundaries are protected:

- MarketSpec v1;
- BuyerPolicy v1;
- MerchantIdentity v1;
- MerchantBid v1;
- canonical JSON v1;
- Ed25519 bid signature v1;
- reverse_second_price_v1;
- Allocation v1;
- AllocationCertificate v1;
- verifier v1; and
- the frozen 10,000-market report and manifest.

These protections preserve semantic and evidentiary meaning; they do not claim source files can
never change. An actual defect may justify a separately reviewed fix or migration. New heterogeneous,
multi-winner, provenance, certificate, or execution semantics must use explicit new versions and
must not alter how old evidence is interpreted.

The frozen report and manifest remain historical evidence for the exact v1 source revision recorded
in that evidence. Later features, tests, or benchmark results neither strengthen nor rewrite the
historical result.

## Final-system package boundaries

The following names reserve future ownership. They are architectural boundaries only and are not
created by this contract:

- clear_market.commerce — heterogeneous market schemas, provenance, catalogs, inventory snapshots,
  and merchant offers;
- clear_market.ai — the model-provider boundary, buyer-intent interpretation, semantic candidate
  generation, merchant reasoning, and certificate-grounded explanation;
- clear_market.mechanism.v2 — production deterministic heterogeneous allocation only;
- clear_market.oracle.v2 — an independent reference or validation implementation;
- clear_market.certificate.v2 — v2 proof evidence, canonical serialization, digest, and parsing;
- clear_market.verification.v2 — independent v2 replay and semantic verification;
- clear_market.execution — the Money Governor, immutable ExecutionPlan, execution identity, and
  deterministic authorization;
- clear_market.persistence — durable financial and event state plus idempotency records;
- clear_market.payments.razorpay — the Razorpay-specific API and webhook adapter; and
- clear_market.agentmarketbench — the final comparative benchmark and adversarial/economic
  evaluation.

No package in this list exists merely because its boundary is reserved.

### Dependency direction

- AI may depend on commerce schemas.
- AI must not depend on provider credentials, Razorpay adapter internals, or mutable provider state.
- The deterministic allocator must not import model clients, Razorpay, persistence clients, or
  network clients.
- The independent v2 oracle must not import production winner/allocation search, the production
  objective or model builder, or the production solver wrapper.
- The certificate layer may bind deterministic evidence but must not perform provider side effects.
- The Money Governor may call independent certificate verification, deterministic execution
  validation, and persistence interfaces needed for duplicate-execution checks.
- The payment adapter may accept only an approved ExecutionPlan or a provider-event processing
  command, never arbitrary AI output or arbitrary Allocation values.
- Persistence must not become a hidden input to deterministic market allocation.

## Heterogeneous commerce boundary

Final market v2 must support:

- one buyer;
- multiple merchants;
- non-identical products and SKU offers;
- typed product and specification attributes;
- hard buyer constraints;
- soft buyer preferences;
- explicit provenance on decision-relevant attributes;
- merchant capacity;
- partial fulfillment;
- split allocation;
- multiple winners where the mechanism permits;
- deterministic tie resolution;
- bounded integer INR paise; and
- a frozen allocation-relevant buyer policy before executable offers are accepted.

This boundary does not claim an N-buyers-by-N-sellers market. It does not choose an arbitrary score,
objective, optimization formulation, or payment rule. Those choices are deferred to Slice 18A.
OR-Tools is not selected or added by this contract.

Hard constraints and soft preferences must be distinct typed concepts. Allocation-relevant policy
and offer data must be frozen and bindable before allocation. Explanatory text, model confidence,
and presentation metadata must not silently affect a deterministic result.

## Provenance contract

Decision-relevant facts must carry one of these provenance labels with the following meanings:

- **VERIFIED** — evidence validated by CLEAR against an explicitly trusted authoritative or
  cryptographic source under a documented verification rule. VERIFIED is not a statement of
  universal physical-world truth.
- **ATTESTED** — a claim signed or otherwise attributable to an accountable external actor or
  source, without CLEAR independently proving the underlying real-world fact.
- **CLAIMED** — an attributable assertion supplied by a participant without independent
  verification.
- **DERIVED** — a deterministic transformation of explicitly referenced source facts under a
  versioned derivation rule.
- **PREDICTED** — a statistical or model-generated estimate or inference.

These labels are not one simplistic total trust ranking. Each hard constraint must declare an
explicit allowed provenance set or provenance rule. PREDICTED evidence must not satisfy a hard
constraint by default.

DERIVED evidence must bind both its source evidence and its deterministic derivation rule/version.
AI-generated information must not silently become VERIFIED. Any provenance transition must be
explicit, attributable, and governed by a documented rule.

## AI trust boundary

AI may:

- interpret natural-language buyer intent;
- propose structured MarketSpec or BuyerPolicy candidates;
- perform semantic SKU and product matching;
- assist merchant SKU and offer reasoning;
- produce human-readable explanations grounded in verified certificate evidence; and
- generate adversarial-agent behavior for evaluation.

AI is not authoritative for:

- constraint validity;
- provenance elevation;
- eligibility;
- allocation winner or winners;
- payment amount;
- financial authorization;
- transfer-mapping authorization;
- webhook validity;
- payment-state transitions; or
- refund or reversal authority.

An AI-generated candidate becomes executable only after deterministic typed validation and policy
freeze. Malformed, incomplete, or untrusted model output must fail closed before entering
deterministic economic logic.

Explanations must cite certificate-bound evidence and must not acquire authority over the result
they explain. Model-provider failures must not weaken validation or permit an economic or financial
fallback with broader authority.

## Merchant and catalog boundary

Future merchant infrastructure must represent commercial state beyond a public key:

- merchant identity;
- catalog;
- SKU and product attributes;
- inventory and capacity snapshots;
- inventory-source evidence and provenance;
- cost basis or an economic floor where appropriate;
- margin policy;
- merchant offer-generation policy; and
- financial or provider account mapping kept outside signed commercial facts where appropriate.

Merchant AI may propose an offer. A deterministic merchant policy must enforce stock/capacity
constraints, the configured economic floor, schema validity, and signing authority. AI must not
sign as a merchant without explicit deterministic merchant authorization.

Signed commercial claims establish attribution and binding under the signature protocol. They do
not prove physical inventory, future fulfillment, product condition, or other physical-world facts.
Provider account mappings require separate authorization and must not be inferred from catalog text.

## Deterministic market-v2 boundary

Inputs must be typed and frozen before allocation. Every decision-relevant input must be bindable in
certificate evidence. Allocation must be:

- deterministic;
- independent of input ordering where order is semantically irrelevant;
- independent of wall-clock reads;
- independent of model output after policy and offer freeze; and
- safe for bounded integer money.

The result must contain enough evidence to reconstruct qualifying offers, winning allocation lines,
quantities, payment obligations, the objective/mechanism version, and deterministic tie resolution.
Exact optimization, objective, and payment design are deferred to Slice 18A.

If a solver is later introduced:

- every solver version or configuration that can affect results must be explicit;
- deterministic solver configuration must be defined;
- production and oracle must not share a production model builder or solver wrapper and call that
  independence; and
- an independent validation strategy must exist before acceptance of the mechanism.

### Independent oracle strategy

For bounded tests and benchmark cases, CLEAR should prefer a structurally independent reference
implementation such as enumeration, independent dynamic programming, or another architecturally
separate formulation when practical.

For larger optimization cases, Slice 18A must define independent feasibility and optimality
validation. Invoking the same production solver formulation twice is not an independent oracle.
This contract does not choose the final oracle strategy.

## AllocationCertificate v2 boundary

AllocationCertificateV2 is a distinct protocol version. It must bind sufficient evidence to replay
or independently validate the v2 decision, including at least:

- BuyerPolicyV2;
- the policy commitment;
- authenticated merchant offers;
- offer admission and rejection evidence;
- decision-relevant provenance;
- the mechanism and objective version;
- deterministic allocation lines;
- quantities;
- payment obligations;
- certificate identity and version; and
- canonicalization and version metadata.

If solver configuration can affect the deterministic result, its decision-relevant version and
configuration must also be bound.

The verifier must not trust stored eligibility labels, stored allocation lines, or stored payment
totals. It must replay, recompute, or independently validate them. Verification must fail closed
when required evidence is missing, inconsistent, unsupported, or noncanonical.

AllocationCertificate v1 must not be mutated to carry v2 fields. V2 parsing, serialization, digest,
and semantic verification require their own explicit versions and compatibility rules.

## Money Governor

The Money Governor is the mandatory deterministic financial-authorization boundary.

**NO VALID CERTIFICATE = NO MONEY ACTION**

The governor must fail closed unless it establishes at minimum:

1. AllocationCertificateV2 verification succeeds.
2. The certificate and mechanism versions are supported for execution.
3. The market is in an executable state.
4. Buyer financial authorization and sufficient budget exist.
5. Payment obligations exactly equal the verified allocation.
6. Every paid merchant is execution-eligible.
7. Every allocation line maps deterministically to an authorized financial recipient.
8. No duplicate execution exists for the certificate, market, or execution identity.
9. Execution totals remain within approved money ceilings.
10. The generated ExecutionPlan is internally consistent.

The governor outputs an immutable, versioned ExecutionPlan. Pure authorization logic does not call
Razorpay directly; provider execution consumes an approved plan afterward.

### ExecutionPlan boundary

An immutable future ExecutionPlan must bind:

- execution_id;
- verified certificate identity and digest;
- market identity;
- buyer authorization reference;
- exact order amount;
- exact merchant transfer mapping;
- currency;
- idempotency identity; and
- execution-plan version.

The plan must not contain model prose as authority, unverified seller payment routing, or
recomputed economic discretion inside the provider adapter.

## Persistent financial state

Financial execution requires durable state. The in-memory AdmissionState is not a payment ledger.
Persistence must record at least:

- execution identity;
- certificate digest;
- market execution state;
- provider order ID;
- provider payment ID;
- provider transfer IDs;
- webhook and event IDs;
- processed-event status;
- idempotency records; and
- recovery and reconciliation status.

Financial transitions must be transactional where multiple local mutations represent one logical
transition. Allocation must remain independent of mutable persistence state; persistence records
authorization and execution facts rather than changing the economic answer.

The persistence implementation and library are deferred to Slice 20A. This contract does not select
SQLAlchemy, a database engine, or a table design.

## Payment state machine

The conceptual normal path is:

~~~text
ALLOCATION_CREATED
    → GOVERNOR_APPROVED
    → ORDER_CREATED
    → PAYMENT_AUTHORIZED
    → PAYMENT_CAPTURED
    → TRANSFER_PENDING
    → TRANSFER_PROCESSED
    → FULFILLMENT_PENDING
    → SETTLED
~~~

Explicit failure and recovery state families are required for:

- order creation failure;
- payment failure;
- transfer failure;
- reconciliation required;
- refund pending and refunded;
- reversal pending and reversed; and
- cancellation where semantically valid.

Slice 22B owns the exact transition table. The governing principles are:

- transitions are deterministic;
- provider events do not directly mutate arbitrary state;
- duplicate events are idempotent;
- out-of-order events are explicitly handled;
- impossible transitions fail closed; and
- provider reconciliation may repair locally uncertain state without inventing financial facts.

## Razorpay boundary

The final buildathon integration target is Razorpay Test Mode. Where the provider capability is
available to the test account, the adapter must support actual rather than mocked-only integration
for:

- Orders;
- payment signature verification;
- Route and Linked Accounts;
- allocation-to-transfer mapping;
- split transfers when supported or required;
- webhook HMAC or signature verification;
- webhook event-ID deduplication;
- provider idempotency where supported;
- timeout and error classification;
- reconciliation;
- refunds; and
- transfer reversals or seller-specific recovery where supported.

This contract does not claim every API is available in every Razorpay test account. If a required
capability is unavailable, the adapter must surface that fact explicitly. It must not silently
replace required provider integration with a mock and declare the integration complete. Mock and
fake providers are allowed for tests only.

Provider secrets belong behind an environment or configuration boundary. They must never enter
source, AllocationCertificate evidence, logs, or model input/output.

The adapter must not expose a convenience path equivalent to AI output →
razorpay.order.create(), or unverified Allocation → provider side effect. It accepts only an
approved ExecutionPlan or a validated provider-event processing command.

## Failure and recovery invariants

The final system must explicitly handle:

- duplicate webhooks;
- out-of-order webhooks;
- provider or API timeouts;
- payment failures;
- transfer failures;
- retries;
- reconciliation;
- partial seller-transfer failures;
- refunds; and
- reversals where applicable.

Safety invariants are:

- retry must not duplicate money movement;
- uncertainty must not be interpreted as success;
- provider IDs and event IDs must be persisted;
- reconciliation must compare provider facts with local expected state; and
- every recovery action must remain attributable to the original verified certificate and
  ExecutionPlan.

Physical fulfillment remains a separate trust domain unless independently verified. Recovery must
not infer fulfillment or provider success from an absent, delayed, or malformed event.

## AgentMarketBench boundary

The existing deterministic-market-generator-v1, differential-benchmark-runner-v1, and 10,000
frozen markets are Week-2 kernel evidence. They are not the final AgentMarketBench.

AgentMarketBench requires separately versioned generator, runner, seeds, report, manifest, and
frozen evidence. The old frozen seed range must not be reused for tuning.

The final benchmark domain must separate **LATENT GROUND TRUTH** from **REPORTED / AGENT-GENERATED
OFFERS** so that economic metrics remain meaningful.

Eventual baselines must include:

- random qualifying seller;
- cheapest qualifying;
- static weighted score;
- bilateral negotiation;
- sequential negotiation;
- first-price reverse auction;
- reverse Vickrey only where its assumptions apply;
- CLEAR; and
- a full-information or reference oracle.

Eventual paired metrics must include:

- allocative efficiency;
- regret;
- buyer surplus;
- merchant surplus;
- welfare;
- completion;
- hard-constraint violations;
- manipulation success;
- payment correctness;
- duplicate financial side effects; and
- latency.

The benchmark contract must define deterministic development seeds, distinct frozen holdout seeds,
no tuning on the frozen holdout, paired comparisons, and 95% confidence intervals. At least 10,000
frozen final markets are required before final claims. A 100,000-market run is optional and depends
on measured practicality. This contract invents no benchmark result.

### Adversarial classification

Final evaluation must classify every relevant scenario as one of:

- PREVENTED;
- DETECTED;
- MITIGATED;
- MEASURED; or
- OUT_OF_SCOPE.

Coverage must eventually include:

- market/protocol: altered offer, late offer, replay, and forged merchant;
- AI: prompt injection, malicious catalog text, and schema-manipulation attempts;
- economic: strategic shading, seller dropout, fake inventory, SLA overpromise, Sybil sensitivity,
  and collusion sensitivity where measured; and
- payments: duplicate event, event reordering, timeout, payment failure, transfer failure, retry,
  reconciliation, and recovery.

No Sybil- or collusion-prevention claim is permitted unless later evidence specifically supports it.

## Security and secret boundaries

- Private merchant signing keys must never enter certificates or logs.
- Provider secrets must never enter deterministic market models.
- Razorpay secrets must remain behind provider configuration.
- The raw webhook body must be available for signature verification before the parsed payload is
  trusted.
- Signed bids prove attribution and binding, not physical-world truth.
- Certificate verification proves protocol and economic consistency under implemented rules, not
  fulfillment or universal correctness.
- AI and model output is untrusted input.

Secret-bearing configuration must be excluded from certificates, canonical market evidence,
benchmark records, model prompts, and normal logs. Redaction must not be relied upon as the only
boundary against secret ingestion.

## Decisions intentionally deferred

The following decisions are intentionally deferred:

- exact heterogeneous objective;
- exact multi-winner payment mechanism;
- exact split-allocation formulation;
- OR-Tools or alternative solver choice;
- independent large-instance optimality-validation strategy;
- exact MarketSpecV2 field schema;
- exact MerchantOfferV2 field schema;
- exact model provider;
- exact semantic matching implementation;
- exact persistence library;
- exact Razorpay SDK versus direct HTTP choice;
- exact payment-state transition table;
- provider capability availability in the user's Razorpay test account;
- AgentMarketBench parameter distributions; and
- final benchmark results.

These decisions belong in dedicated reviewed slices with source, provider-API, economic, and
experimental evidence. Guessing them in an architecture document would over-freeze later design
before the required facts exist.

## Full-system completion gate

The final differentiator is:

~~~text
generic heterogeneous market state
    → independently authenticated commercial offers
    → deterministic constrained allocation
    → independently replayable AllocationCertificateV2
    → Money Governor
    → approved ExecutionPlan
    → Razorpay Test Mode execution
    → verified provider events
    → settlement and recovery invariants
~~~

Full CLEAR is not complete until an executable path demonstrates:

~~~text
AI buyer
    → merchant interaction
    → deterministic financial decision
    → verified certificate
    → gated Razorpay transaction
    → auditable explanation and result
    → graceful failure and recovery
~~~

An AI demonstration without deterministic and payment gates does not satisfy this completion gate.
Razorpay calls without a verified certificate and Money Governor do not satisfy it. The Week-2
kernel alone does not satisfy it.

The gate is evidence-based: each boundary must be exercised through reviewed implementation,
failure tests, and provider-facing evidence appropriate to its authority. Architectural prose,
package names, or a mocked-only happy path do not satisfy the gate.
