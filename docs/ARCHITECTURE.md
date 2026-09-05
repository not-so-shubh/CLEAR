# CLEAR Current Architecture

This document describes the implemented architecture at the current repository head. The
[final system contract](FINAL_SYSTEM_CONTRACT.md) defines the broader trust and safety contract;
the [V2 mechanism contract](MECHANISM_V2_CONTRACT.md) is the normative economic specification.
Older Week-2 and v1 documents remain historical, versioned contracts rather than the current
system narrative.

## 1. Authority model

CLEAR separates interpretation from authority:

> AI interprets fuzzy commercial intent; deterministic systems decide which economic agreement
> wins and where the money goes.

Its primary execution invariant is:

> **NO VALID CERTIFICATE = NO MONEY ACTION**

The end-to-end authority chain is:

```text
AI / UNTRUSTED ADVISORY
  buyer natural language
      -> buyer-intent candidate

DETERMINISTIC / AUTHORITATIVE
  strict candidate parse and validation
      -> freeze trusted market context
      -> BuyerPolicyV2
      -> catalogs + inventory snapshots + merchant economic policies

AI / UNTRUSTED ADVISORY
  merchant-specific proposal candidates

DETERMINISTIC / AUTHORITATIVE
  validate proposal against the same merchant's trusted sources
      -> build MerchantOfferV2
      -> authenticate SignedMerchantOfferV2
      -> admit evidence
      -> allocate with heterogeneous-pay-as-bid-v2
      -> AllocationCertificateV2
      -> independently replay and verify
      -> Money Governor
      -> immutable ExecutionPlanV1

EXTERNAL / SIDE EFFECT
  Razorpay Test Mode order boundary

DETERMINISTIC / AUTHORITATIVE
  validate provider observations / authenticate webhook inputs
      -> append immutable facts/events
      -> replay payment state
      -> captured-payment gate
      -> transfer or recovery decision

EXTERNAL / SIDE EFFECT
  Razorpay Route transfer creation or reconciliation when authorized
```

This is a one-buyer × N-seller system. Each seller can be represented by an autonomous agent, but
the system is not an N-buyer exchange.

## 2. Trust zones

| Zone | Trusted for | Explicitly not trusted for |
| --- | --- | --- |
| AI tasks | Producing candidate structures from fuzzy language or explaining verified evidence | Constraints, source facts, offer validity, admission, winner selection, payment, or provider authorization |
| Buyer/merchant source objects | Frozen typed inputs supplied under the relevant application trust model | Facts not represented by those objects |
| Participant signatures | Attribution and integrity of canonical merchant-offer bytes under configured public-key trust roots | Physical inventory, catalog truth, delivery, solvency, or completeness of the market transcript |
| Deterministic kernel | Parsing, validation, commitments, admission, allocation, canonicalization, and authorization semantics | External facts that were never authenticated or supplied |
| Independent verifier | Replaying supplied certificate evidence and recomputing the expected V2 allocation | Proving that no omitted real-world event or timely offer existed |
| Money Governor and ledger | Enforcing explicit authorizations, budgets, recipient bindings, execution uniqueness, and immutable provider observations | Exactly-once delivery by an external provider |
| Razorpay boundary | Returning externally observed Test Mode order, payment, and transfer data | Settlement finality, fulfillment, or correctness absent authenticated recording and replay |
| Physical world | Nothing is inferred automatically | Inventory truth, shipment, receipt, disputes, and legal performance |

## 3. Dependency direction

The architectural dependency flow is intentionally one-way around the authoritative decision:

```text
commerce schemas / canonical primitives / crypto
                    |
                    v
       AI candidate parsing and freeze
                    |
                    v
 signed merchant offers + deterministic admission
             |                       |
             v                       v
 production mechanism/v2        independent oracle/v2
             |                       |
             +---- certificate ------+
                         |
                         v
                verification/v2
                         |
                         v
              execution Money Governor
                         |
                         v
                immutable ledger
                         |
                         v
      payments + orchestration + recovery
```

Important structural rules:

- `mechanism/v2` owns production allocation and uses OR-Tools CP-SAT.
- `oracle/v2` independently enumerates/recomputes reference semantics and does not import the
  production allocator.
- `verification/v2` trusts neither the stored admission results nor stored allocation merely
  because they appear in a certificate.
- Payment adapters depend on a governor-approved plan; they do not accept raw AI output or a raw
  allocation as financial authority.
- Persistence records decisions and provider observations. It is not an implicit input to pure
  allocation semantics.

## 4. AI interpretation boundary

The `clear_market.ai` package exposes three typed tasks and one development harness.

### 4.1 Buyer intent

`interpret_buyer_intent_v1` sends natural-language intent through an `AIProvider`, strictly parses
the returned candidate, and freezes it with trusted identifiers, eligible merchants, deadline,
mechanism version, and objective version. The result is a `BuyerPolicyV2`; the model cannot replace
the trusted context.

The implementation and fake-provider tests cover parsing and semantic mismatches. The concrete
live path was exercised once successfully for buyer intent using an externally supplied compatible
provider. No official OpenAI endpoint claim is made.

### 4.2 Merchant proposal

`propose_merchant_offer_candidate_v1` receives merchant-specific trusted source projections:
catalog, inventory snapshot, and economic policy. Its output is still only a candidate.
`build_merchant_offer_v2` then checks known SKUs, inventory capacity, quantities, buyer policy,
minimum prices, source commitments, and related invariants before producing `MerchantOfferV2`.
Signing and verification create `SignedMerchantOfferV2` evidence bound to a configured merchant
identity.

This path is implemented and tested with controlled fake providers. No live merchant-proposal
exercise is claimed.

### 4.3 Certificate explanation

`explain_verified_allocation_certificate_v1` is an advisory presentation layer over certificate
evidence that has already passed independent verification. Its parsed output cannot mutate the
certificate, allocation, execution authorization, or provider plan. It is implemented and tested
with fakes; no live run is claimed.

### 4.4 Provider adapter and live profile

`OpenAICompatibleProvider` implements a synchronous OpenAI-compatible Chat Completions transport
over HTTPS. Provider name, base URL, credential, and model identifiers are supplied externally. It
performs one operation per request and has no retry path.

`clear_market.ai.live_profile` is a guarded development-only tool. It compares at most four model
identifiers on two fixed buyer cases and two deterministic merchant fixtures. Each fully reached
model uses two sequential buyer calls plus two merchant calls in a two-worker executor: exactly
four paid calls, with an absolute run maximum of 16. It reports sanitized correctness and observed
end-to-end timings. The harness is implemented and fake-tested; no real comparison result is
committed or claimed.

## 5. V2 commerce inputs and authenticated offers

The commerce layer uses immutable, versioned models for:

- `MarketSpecV2` and `BuyerPolicyV2`;
- typed `HardConstraint` and `SoftPreference` values;
- catalog products, SKUs, typed attributes, and provenance labels;
- inventory snapshots and per-SKU capacity;
- merchant economic rules and minimum acceptable unit prices; and
- candidate, built, and signed merchant offers.

The buyer policy and each merchant's catalog and inventory snapshot have canonical commitment
functions. Merchant offer construction embeds the relevant source commitments. Ed25519 signatures
cover canonical offer bytes, and verification binds the declared merchant to a trusted public key.

This gives deterministic attribution and tamper evidence. It does not establish that the signed
catalog or inventory corresponds to physical reality.

## 6. Production allocation

The V2 mechanism identity is `heterogeneous-pay-as-bid-v2`; its objective identity is
`quantity-cost-soft-objective-v2`.

The production allocator uses deterministic OR-Tools CP-SAT. Solver configuration fixes one search
worker and a deterministic seed, and the implementation requires optimal completion for each
lexicographic phase. Given identical validated frozen inputs, allocation does not depend on input
order, local time, hash iteration order, or AI output.

The authoritative objective is hierarchical:

1. maximize total fulfilled quantity subject to policy, hard constraints, provenance, inventory,
   offer, and winner-count limits;
2. minimize total pay-as-bid payment;
3. maximize the aggregate soft-preference score; and
4. select a deterministic lexicographic allocation among remaining ties.

The mechanism supports partial fulfillment, split awards, multiple winners, heterogeneous or
substitutable SKUs, merchant capacity, and integer paise arithmetic. It is not Vickrey and carries
no general incentive-compatibility claim.

## 7. Certificate construction and verification

`AllocationCertificateV2` is a canonical, digestible evidence object. It binds the policy and
market context, authenticated offer/admission evidence, mechanism and objective versions, and the
recorded allocation result.

Verification is semantic rather than cosmetic:

1. canonical certificate parsing applies bounded, duplicate-key-safe structural checks;
2. trusted merchant identity mappings are supplied out of band;
3. policy, source commitments, signatures, and admission decisions are revalidated;
4. the independent V2 oracle recomputes the expected allocation from admissible evidence; and
5. every relevant recorded allocation field is compared with that recomputation.

Production allocation and the reference oracle share schemas and unavoidable primitives, not the
production winner-selection implementation. This separation makes an allocator/oracle mismatch
observable instead of letting the verifier call the same code under a second name.

### Proof strength and limits

A verified certificate demonstrates internal consistency of the supplied versioned evidence under
configured trust roots. It is not:

- proof that a signed inventory or catalog claim is physically true;
- proof of shipment, delivery, service performance, or buyer satisfaction;
- proof that the transcript contains every real timely offer without an external trusted receipt
  service;
- formal verification or a proof that implementation bugs are impossible;
- a zero-knowledge proof or blockchain consensus artifact;
- a legal settlement instrument; or
- proof of payment settlement.

## 8. Money Governor and execution plan

`authorize_execution_v1` is the financial authority boundary. It first requires successful
`AllocationCertificateV2` verification and then validates explicit market execution, buyer
financial, and merchant recipient authorizations. It checks certificate identity, buyer/market
binding, budgets, transfer totals, recipient bindings, and execution state before reserving the
execution in the SQLite ledger.

The successful output is immutable `ExecutionPlanV1`, containing the approved order amount and
recipient transfer lines. This plan—not an AI response, `MerchantOfferV2`, or raw `AllocationV2`—is
the input authorized to cross the provider boundary.

The ledger enforces duplicate execution, certificate, market, and provider-reference checks and
uses canonical request fingerprints. These controls support idempotency and auditability; they do
not turn an external network into exactly-once delivery.

## 9. Razorpay Test Mode adapter boundary

The current payment boundary is intentionally limited to Razorpay Test Mode code paths.

### 9.1 Order path

`create_razorpay_test_order_v1` obtains the governor-approved plan, constructs the exact provider
order intent, records its fingerprint, and performs or reconciles the provider operation. Provider
identifiers and returned facts are validated before durable recording.

### 9.2 Webhook and state replay

`authenticate_and_record_razorpay_webhook_v1` authenticates the raw webhook body before recording a
normalized immutable event. `derive_razorpay_payment_state_v1` is a read-only deterministic fold
over authenticated ledger observations. It derives order-created, payment-failed-observed,
payment-authorized, or payment-captured state; it does not query the network or infer unrecorded
facts.

### 9.3 Route mapping and transfers

`build_razorpay_route_mapping_v1` maps approved execution transfer lines to explicit active linked
account bindings. Transfer work requires a governor-approved plan, a reconciled order, and recorded
captured-payment evidence. `create_or_reconcile_razorpay_test_transfers_v1` either creates the
planned transfers or reconciles uncertain prior attempts against provider facts, then records the
validated observations.

Transfer creation means the provider accepted or exposed a transfer object. It does not mean the
transfer settled, became irreversible, or resulted in physical fulfillment.

### 9.4 Recovery and orchestration

Order recovery can resolve uncertain create attempts by provider reference rather than blindly
issuing another POST. Normal orchestration coordinates governor authorization, order, payment
state, Route mapping, and transfers. The graceful path converts recognized uncertainty into an
explicit recovery disposition instead of treating ambiguity as success.

The provider code and controlled-transport tests cover these behaviors. The repository contains
no demonstrated live Razorpay Test Mode execution and no live transaction evidence. Refunds,
reversals, settlement processing, disputes, and fulfillment are not implemented.

## 10. Failure and recovery semantics

External calls can fail before a request, after the provider accepts it, or after the response is
lost. CLEAR therefore distinguishes safe failure from uncertain outcome:

- validation or authorization failures occur before provider work;
- immutable fingerprints and provider references prevent incompatible reuse;
- authenticated webhooks and fetched provider facts are recorded as evidence;
- deterministic replay derives state only from those recorded observations;
- uncertain order/transfer attempts enter recovery or reconciliation rather than being reported as
  successful; and
- an uncertain write is not retried as an unqualified duplicate write.

This is fail-closed authorization plus explicit reconciliation. It is not a claim of distributed
transactions or exactly-once external effects.

## 11. Benchmark and evidence boundary

AgentMarketBench is separate from runtime authority. The replacement final holdout stores 10,000
deterministic scenarios, method outputs, descriptive paired intervals, manifests, and integrity
metadata. Normal tests validate committed evidence; they do not regenerate the holdout.

The stored result supports these narrow statements:

- CLEAR exceeds five ordinary baselines (`RANDOM_QUALIFYING_SELLER`,
  `CHEAPEST_QUALIFYING`, `STATIC_WEIGHTED_SCORE`, `BILATERAL_NEGOTIATION`, and
  `SEQUENTIAL_NEGOTIATION`) on welfare and completion for the fixed corpus, with descriptive
  paired 95% intervals excluding zero.
- CLEAR and `FIRST_PRICE_REVERSE_AUCTION` have near-identical aggregate outcomes; intervals
  including zero for welfare, regret, and allocation efficiency do not establish superiority or
  equivalence.
- The full-information oracle remains materially above CLEAR and is a latent upper bound, not a
  production competitor.
- Measured hard-constraint violations and manipulation successes remain limitations.

Benchmark latency is environment-sensitive, and the holdout does not exercise the AI provider,
certificate explanation, Money Governor, Razorpay adapter, recovery orchestration, settlement, or
physical fulfillment. Exact results and caveats are in the
[replacement final results](AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md).

## 12. Package ownership

| Package | Responsibility |
| --- | --- |
| `clear_market.ai` | AI provider abstraction, candidate parsers, buyer/merchant/explanation tasks, guarded live profile |
| `clear_market.commerce` | V2 market policy, catalogs, inventory, constraints, merchant economics, offers, signatures |
| `clear_market.mechanism.v2` | Authoritative production CP-SAT allocation |
| `clear_market.oracle.v2` | Structurally independent reference allocation |
| `clear_market.certificate.v2` | Certificate models, canonical serialization, digests, parsing |
| `clear_market.verification.v2` | Trusted-identity-aware certificate replay and verification |
| `clear_market.execution` | Money Governor, financial authorization, execution plan |
| `clear_market.persistence` | SQLite executions, provider references, facts, and authenticated-event ledger |
| `clear_market.payments.razorpay` | Test Mode order, webhook, and Route mapping adapters |
| `clear_market.payments.state` | Deterministic replay of authenticated payment observations |
| `clear_market.payments.transfers` | Transfer creation and reconciliation |
| `clear_market.payments.recovery` | Order recovery from uncertain provider outcomes |
| `clear_market.orchestration` | Normal and graceful execution coordination |
| `clear_market.agentmarketbench` | Evaluation generators, methods, metrics, statistics, and evidence integrity |

The repository also retains v1 domain, lifecycle, mechanism, certificate, verification, and
benchmark packages. They support the historical homogeneous reverse-second-price contract and are
not silently substituted for V2 behavior.

## 13. Known limitations and unimplemented areas

- one buyer × N sellers only; no N-buyer exchange;
- no trusted physical inventory or fulfillment oracle;
- no external receipt system proving transcript completeness;
- no refunds, reversals, settlement processor, disputes, or shipment workflow;
- no live Razorpay Test Mode demonstration or live-money evidence;
- no exactly-once guarantee across provider/network boundaries;
- no collusion or Sybil resistance guarantee;
- no formal verification, zero-knowledge proof, or blockchain layer; and
- no universal AI-model or market-mechanism ranking.

For the exact normative boundaries, read the [final system contract](FINAL_SYSTEM_CONTRACT.md), the
[V2 mechanism contract](MECHANISM_V2_CONTRACT.md), and the
[reproducibility guide](../REPRODUCIBILITY.md).
