# Week-2 Contract

This document is the normative architectural contract for Week 2. The requirements are frozen for
Week 2 but are **to be implemented in later slices** unless explicitly identified as Slice 0
foundation work.

## Project, track, and thesis

**Project:** CLEAR — Proof-Carrying Market Infrastructure for Autonomous AI Commerce

**Track:** Razorpay Track 01 — AI Growth & Agentic Commerce

**Thesis:** "AI interprets fuzzy commercial intent; deterministic systems decide which economic
agreement wins and where the money goes."

## Frozen Week-2 market scope

- Exactly one buyer participates in each market.
- Examples use exactly 5 sellers.
- Mechanisms should eventually support a configurable 2–20 sellers.
- The good is standardized and homogeneous.
- Allocation is single-winner only.
- The winning seller must fulfill the full requested quantity.
- Split fulfillment is not supported.
- Heterogeneous scoring is not supported.
- LLMs do not participate in financial decisions.

## Domain bounds to be implemented in later slices

Slice 0 does not implement these constants. The frozen bounds are:

- `MIN_SELLERS = 2`
- `MAX_SELLERS = 20`
- `MAX_QUANTITY = 1_000_000`
- `MAX_MONEY_PAISE = 1_000_000_000_000`
- Currency is INR only.
- Money is represented as integer paise only.

## Identities

The future identifiers `market_id`, `buyer_id`, `merchant_id`, `bid_id`, `certificate_id`, and
`event_id` use canonical UUID strings.

Week-2 generated domain identities use UUIDv4 unless a later architect-approved deterministic
derived identifier is explicitly required. Mutable display names never establish identity.

## Time and deadlines

- Timestamps are timezone-aware and UTC only.
- Naive datetimes are invalid.
- Deterministic logic receives `now` explicitly when needed.
- Pure/domain logic must not call `datetime.now()` or `datetime.utcnow()`.
- Bid deadline semantics are inclusive: `submitted_at <= bid_deadline` is timely, while
  `submitted_at > bid_deadline` is late.

Explicit time inputs prevent wall-clock and timezone differences from changing deterministic
results.

## Tie-break

For equal eligible unit bids, canonical `merchant_id` ascending is the frozen tie-break.
Submission time must not be used for tie-breaking.

## Week-2 bid policy

- There is one bid per (`market_id`, `merchant_id`).
- Bid revisions and replacements are not supported.
- `bid_id` is the replay identifier for Week 2.
- No separate nonce field is required in Week 2 unless a later concrete threat justifies it.
- Duplicate or replayed bids fail closed.
- Rejected bids can never participate in allocation.

## Buyer policy freeze

Buyer constraints and mechanism settings are frozen before seller bids are evaluated.

`BuyerPolicy` will eventually contain or embed enough information to freeze:

- `MarketSpec`;
- requested quantity;
- buyer budget;
- buyer reserve unit price;
- eligible merchant identities;
- bid deadline;
- mechanism version;
- tie-break rule; and
- other allocation-relevant buyer constraints.

`buyer_policy_commitment` will later be SHA-256 over the canonical serialized `BuyerPolicy`. Any
allocation-relevant mutation changes the commitment. Merchant bids will later bind the relevant
`buyer_policy_commitment` so a bid cannot silently migrate to a changed policy.

## Canonicalization contract to be implemented later

CLEAR Week 2 uses a restricted deterministic JSON representation with these requirements:

- Encoding is UTF-8.
- Object keys are sorted.
- JSON separators are exactly `","` and `":"`, with no insignificant whitespace.
- `ensure_ascii = false`.
- Floats are forbidden.
- UUIDs are lowercase canonical hyphenated strings.
- Enums are explicit string values.
- Datetimes are converted to UTC and encoded exactly as `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- Naive datetimes are rejected.
- `None` serializes explicitly as JSON `null` when a schema permits `None`.
- Cryptographically protected fields are never silently omitted.
- Arrays preserve defined semantic order.
- Set-like fields are normalized before serialization.
- Every cryptographically relevant payload contains an explicit `canonicalization_version`.

This contract does not claim RFC 8785/JCS compliance.

## Cryptography to be implemented later

- Signatures use Ed25519.
- Digests and commitments use SHA-256.
- `MerchantIdentity` binds `merchant_id` to an Ed25519 public key.
- Private keys are never committed or logged.
- Deterministic test keys are permitted only in test fixtures.
- Signatures cover all allocation-relevant bid fields.
- Signature verification never decides the economic winner or payment.

Cryptographic verification establishes authenticity and binding; it remains separate from the
economic mechanism.

## Frozen Week-2 economic mechanism

The future mechanism is a narrow standardized single-contract reverse second-price procurement
mechanism with a buyer reserve.

Its assumptions are:

- There is one standardized contract.
- Requested quantity `Q` is fixed.
- There is exactly one winner.
- The winning seller fulfills all of `Q`.
- Each seller has one private per-unit cost.
- Seller utility is quasilinear: payment minus cost.
- The buyer reserve is frozen before bids.
- Seller eligibility is frozen before bids.
- No claim covers collusion.
- No claim covers Sybils.
- There are no externalities.
- There are no side payments.
- There is no repeated-game guarantee.
- There is no false-fulfillment guarantee.

Future allocation semantics are:

1. Bids first pass structural, identity, market, policy-commitment, signature, deadline, duplicate,
   and replay checks.
2. Allocation eligibility additionally requires
   `quantity_available >= requested_quantity` and
   `unit_price_paise <= reserve_unit_price_paise`.
3. The lowest eligible unit bid wins.
4. Equal lowest bids use canonical `merchant_id` ascending.
5. The winner's per-unit payment is the second-lowest eligible unit bid if one exists; otherwise,
   it is `reserve_unit_price_paise`.
6. Total payment is `payment_per_unit_paise * requested_quantity`.
7. `BuyerPolicy` must ensure
   `reserve_unit_price_paise * requested_quantity <= max_total_payment_paise`.
8. No eligible bid produces an explicit infeasible market.
9. Rejected or ineligible bids never affect the winner or payment.

The only permitted future economic claim is: under the explicitly documented standardized,
single-winner, single-dimensional private-cost assumptions, the implemented reverse second-price
mechanism has the standard truthful-bidding incentive property.

The following broad claims are forbidden:

- "CLEAR is strategy-proof."
- "CLEAR prevents collusion."
- "CLEAR guarantees seller honesty."
- "CLEAR guarantees fulfillment."
- "CLEAR is optimal for arbitrary procurement."
- "CLEAR is Sybil-proof."

## Week-2 persistence

- No database is required.
- Bid and replay state may initially be in-memory and single-process.
- Persistence must not leak into pure allocation or oracle logic.

## Deferred beyond Week 2

The following are explicitly out of scope:

- UI, dashboard, or frontend;
- N buyers × N sellers;
- heterogeneous goods;
- split allocation;
- LLM negotiation;
- semantic catalog matching;
- collusion detection;
- commit/reveal;
- blockchain;
- ZK proofs;
- complex procurement workflows;
- production deployment;
- Kubernetes;
- full Razorpay Route integration;
- live onboarding;
- settlement orchestration;
- recommendation systems;
- LangChain;
- LangGraph;
- CrewAI;
- MCP;
- vector databases;
- microservices;
- FastAPI;
- SQLAlchemy; and
- OR-Tools until mechanism complexity requires it.

## Week-2 evidence standard

Week 2 proves:

- deterministic correctness;
- financial and allocation invariant enforcement;
- signature and policy binding;
- independent production/oracle agreement;
- certificate replay correctness; and
- benchmark reproducibility.

Week 2 does not by itself prove:

- superior business value;
- superior market welfare compared with real procurement systems;
- production readiness; or
- broad mechanism-design guarantees.
