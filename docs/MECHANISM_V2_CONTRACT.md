# CLEAR Mechanism V2 Contract

**NORMATIVE FOR `heterogeneous-pay-as-bid-v2` AND
`quantity-cost-soft-objective-v2`.**

This document freezes the solver-independent economic semantics, result contract, trust boundary,
and future implementation obligations for those two versions. Slice 18A defines no allocator,
constraint evaluator, solver integration, oracle, certificate, or financial execution path.

## 1. Scope

The mechanism is one buyer × N eligible merchants, where the eligible population is between
`MIN_SELLERS` and `MAX_SELLERS`. It supports heterogeneous substitutable SKU offers, integer units,
partial and split fulfillment, multiple winning merchants, multiple allocated SKU lines from one
merchant, hard constraints, soft preferences, explicit provenance, bounded integer INR paise, and
deterministic tie resolution.

It does not support N buyers, combinatorial package bids, complements, XOR bundles, fractional
quantities, merchant-side payment routing, proof of fulfillment, or future inventory reservations.
The mechanism output is not permission to move money.

The mechanism version is exactly `heterogeneous-pay-as-bid-v2`. The objective version is exactly
`quantity-cost-soft-objective-v2`. No alias, normalization, or compatibility guess is permitted.

## 2. Trust boundary

The future production API is conceptually:

```text
allocate_market_v2(
    *,
    buyer_policy: BuyerPolicyV2,
    signed_offers: tuple[SignedMerchantOfferV2, ...],
) -> AllocationV2
```

This function is not implemented in Slice 18A. A `SignedMerchantOfferV2` Python value is intended to
carry authenticated evidence, but its mere presence does not prove that its signature or source
state was verified. The mechanism is not a cryptographic verifier.

The authorized trust path is:

```text
canonical signed-offer bytes
    → Slice 16C authentication and source verification
    → signed-offer value
    → Slice 18B deterministic allocation
    → Slice 19A certificate
    → Slice 19B independent verification, including offer authentication
    → Money Governor
```

An invalid signature never becomes financial authority merely because an allocator was called.
There is at most one admitted signed offer per merchant. Offer IDs and merchant IDs are unique
across the input tuple. One offer may contain multiple SKU lines, and multiple lines for one merchant
may receive positive quantities. `max_winners` counts distinct merchants with positive allocation.

## 3. Input validation

Slice 18B must apply this exact failure precedence:

1. require the exact `BuyerPolicyV2` type;
2. defensively perform fresh `BuyerPolicyV2` validation;
3. require mechanism version `heterogeneous-pay-as-bid-v2`;
4. require objective version `quantity-cost-soft-objective-v2`;
5. require `signed_offers` to be an exact tuple;
6. require every tuple element to be an exact `SignedMerchantOfferV2`;
7. defensively fresh-validate every `SignedMerchantOfferV2` before any semantic field access used
   for ordering or checks; any failure is `INVALID_SIGNED_OFFER`;
8. normalize the successfully validated offers ascending by `(merchant_id, offer_id)`;
9. in a full-category pass, reject any duplicate `offer_id`;
10. in a full-category pass, reject any duplicate `merchant_id`;
11. in a full-category pass, reject any merchant that is not eligible;
12. in a full-category pass, reject any offer whose `market_id` mismatches the policy;
13. in a full-category pass, reject any buyer-policy commitment mismatch.

The stable error categories, in that order where applicable, are
`INVALID_BUYER_POLICY`, `INVALID_SIGNED_OFFER`, `UNSUPPORTED_MECHANISM_VERSION`,
`UNSUPPORTED_OBJECTIVE_VERSION`, `DUPLICATE_OFFER_ID`, `DUPLICATE_MERCHANT_OFFER`,
`MERCHANT_NOT_ELIGIBLE`, `MARKET_ID_MISMATCH`, `BUYER_POLICY_COMMITMENT_MISMATCH`, and
`SOLVER_FAILURE`. No cryptographic signature check occurs in this sequence. An empty exact offer
tuple is valid input and produces economic infeasibility, not an input error.

Fresh validation before canonical semantic ordering means allocator hardening never dereferences
malformed `model_construct()` state merely to determine validation order. Because every failed
fresh signed-offer validation maps to `INVALID_SIGNED_OFFER`, validating exact-type instances before
canonical semantic ordering does not weaken the public failure taxonomy. Each later category is a
complete pass over the normalized validated offers, so input tuple ordering cannot choose which
failure category wins.

For every admitted signed offer, the mechanism consumes its nested `MerchantOfferV2.lines`. The
canonical offer-line key is exactly `(merchant_id, sku_id, offer_id)`, ordered lexicographically
ascending. Offer order and line order are economically irrelevant.

## 4. Hard constraints

For each buyer `HardConstraint` and each offer line:

1. find the line attribute whose `attribute_key` exactly equals the constraint key;
2. if it is absent, the constraint is not satisfied;
3. require the attribute provenance to be a member of `allowed_provenance`;
4. require the attribute and operand `value_type` values to be exactly equal, including for `EQ`
   and `NE`;
5. apply the declared operator to the exact scalar values.

The operator semantics are exact equality for `EQ`, exact inequality for `NE`, and integer `<`,
`<=`, `>`, or `>=` for `LT`, `LTE`, `GT`, and `GTE`. There is no coercion, string-to-number parsing,
Unicode normalization, case folding, fuzzy matching, or AI interpretation. In particular, a type
mismatch does not accidentally satisfy `NE`.

A line is hard-qualifying only if every hard constraint is satisfied. With zero hard constraints,
every structurally admitted line is hard-qualifying. Nonqualifying lines have allocation quantity
zero.

## 5. Soft preferences

Soft preferences use the same exact attribute lookup, provenance membership, type equality, and
operator semantics. A missing attribute, disallowed provenance, or type mismatch does not satisfy a
preference. A soft preference never makes a line infeasible.

For hard-qualifying line `l`, `soft_match_count(l)` is the number of buyer soft preferences it
satisfies. Every soft preference has equal unit weight. There is no hidden weighting, model
confidence, ranking, or conversion into paise. The allocation score is:

```text
soft_preference_unit_score =
    Σ_l allocated_quantity_l × soft_match_count(l)
```

Only positively allocated units contribute. The maximum is `MAX_QUANTITY ×
MAX_SOFT_PREFERENCES`.

Cost precedes soft preferences because the current buyer policy supplies no monetary utility weight for a soft preference.

The policy supplies no weight, utility, willingness-to-pay, or monetary tradeoff from which CLEAR
could derive an exchange rate. A future weighted-utility mechanism requires a new policy and
objective version.

## 6. Feasible allocation

For every canonical hard-qualifying line `l`, the future allocator has an integer quantity `x_l`
such that:

```text
0 <= x_l <= line.max_offer_quantity
```

For nonqualifying lines, `x_l = 0`. Fractional allocation is forbidden. Total quantity must not
exceed `buyer_policy.market_spec.requested_quantity`. A feasible result must meet or exceed
`minimum_acceptable_quantity`; a smaller positive quantity is not feasible.

A winning merchant has positive total quantity over its lines. The number of distinct winning
merchants must not exceed `max_winners`. Multiple positive SKU lines from one merchant count as one
winner, and no one-SKU-per-merchant restriction exists.

An allocation is feasible exactly when every positive line is hard-qualifying, every line quantity
is a bounded nonnegative integer, requested and minimum quantity limits hold, the distinct-winner
limit holds, total pay-as-bid payment is within budget, and exact money arithmetic remains within
protocol bounds.

`AllocationLineV2` is a frozen, strict, extra-forbidden, always-revalidated schema with exactly:

```text
schema_version = "2"
allocation_line_version = "allocation-line-v2"
offer_id
merchant_id
sku_id
allocated_quantity
unit_payment
line_payment
```

It binds a positive quantity and requires `line_payment` to equal checked multiplication of
`unit_payment` by that quantity. It carries no attributes, provenance, qualification flags, source
IDs, or provider routing.

`AllocationV2` is likewise frozen, strict, extra-forbidden, and always revalidated. It has exactly
the schema and allocation versions, fixed mechanism and objective versions, market ID, existing
buyer-policy commitment version and lowercase SHA-256, status, fulfilled quantity, total payment,
soft-preference-unit score, winner count, and allocation-line tuple. The score is a strict integer
between zero and `MAX_QUANTITY × MAX_SOFT_PREFERENCES`; winner count is a strict integer between zero
and `MAX_SELLERS`; the tuple has at most `MAX_SELLERS × MAX_OFFER_LINES` entries.

`AllocationV2` normalizes lines by `(merchant_id, sku_id, offer_id)`, rejects duplicate `(offer_id,
sku_id)` and `(merchant_id, sku_id)` pairs, and requires its quantity, payment, and distinct-winner
aggregates to match its lines. Aggregate payment must remain within `MAX_MONEY_PAISE`.

Every merchant represented in allocation lines maps to exactly one `offer_id`, and every `offer_id`
represented in allocation lines maps to exactly one `merchant_id`. Multiple SKU lines under that
same merchant/offer pair are allowed. This binding follows from the transcript rule that admits at
most one offer per merchant.

For status `FEASIBLE`, lines are nonempty, fulfilled quantity is positive, and winner count is
positive. The result model alone does not re-evaluate the policy's minimum quantity, budget, or
winner cap; Slice 18B enforces those cross-object rules and Slice 19B independently replays them.

## 7. Pay-as-bid payment

The payment rule is pay-as-bid. For each allocated line:

```text
unit_payment = offer_line.unit_price
line_payment_paise = allocated_quantity × unit_payment.amount_paise
```

Total payment is the exact sum of line payments and must not exceed
`buyer_policy.max_total_payment.amount_paise`. All arithmetic is bounded integer INR paise, with no
float, Decimal, or rounding.

There is no second-price extension, VCG, generalized second price, critical-value payment,
reserve-derived payment, or payment smoothing.

## 8. Lexicographic objective

Among feasible allocations, optimize through separate phases:

1. maximize fulfilled quantity;
2. subject to the optimal quantity, minimize total payment in paise;
3. subject to the first two optima, maximize `soft_preference_unit_score`;
4. subject to all previous optima, apply the canonical allocation-vector tie rule.

There is no weighted scalarization, multiplication by arbitrary giant constants, or solver-tolerance
semantics. Quantity is optimized first. Cost is second because a soft preference currently has no
buyer-supplied monetary utility weight.

## 9. Canonical tie resolution

Let hard-qualifying lines `l_1, ..., l_n` be in ascending canonical order by `(merchant_id, sku_id,
offer_id)`. Define `X = (x_l1, ..., x_ln)`. Among allocations tied on quantity, payment, and soft
score, choose the lexicographically maximum `X`.

Operationally, first maximize `x_l1` and fix it, then maximize `x_l2` and fix it, continuing until
every quantity is fixed. This explicit sequential rule produces one answer independent of input
ordering or incidental solver choices. It is a deterministic tie rule, not a fairness claim.

## 10. Infeasibility

`AllocationStatusV2` has only `FEASIBLE` and `INFEASIBLE`. Partial fulfillment meeting the minimum
is `FEASIBLE`; there is no `PARTIAL` status. If no economic allocation meets all constraints, return
`INFEASIBLE` with exactly:

```text
fulfilled_quantity = 0
total_payment = Money(amount_paise=0)
soft_preference_unit_score = 0
winner_count = 0
lines = ()
```

The result still binds market ID, buyer-policy commitment, mechanism version, and objective version.
It carries no trusted textual reason; a verifier must recompute infeasibility.

Solver uncertainty, `UNKNOWN`, `MODEL_INVALID`, or abnormal termination is `SOLVER_FAILURE`, never
economic infeasibility.

## 11. CP-SAT production strategy

Slice 18B will use OR-Tools CP-SAT, but Slice 18A adds no dependency or solver code. The mathematical
contract above remains solver-independent. For each hard-qualifying line, the effective upper bound
is:

```text
if unit_price.amount_paise > 0:
    min(raw_capacity, requested_quantity,
        max_total_payment.amount_paise // unit_price.amount_paise)
else:
    min(raw_capacity, requested_quantity)
```

This reduction preserves the feasible set while reducing search and bounding expression domains.
For merchant quantity `q_m`, binary winner indicator `y_m`, and a valid upper bound `U_m`, enforce
iff-positive behavior with `q_m <= U_m * y_m` and `q_m >= y_m`, then require `Σ y_m <= max_winners`.

Objective phases are separate. Every phase must return `OPTIMAL`; a merely `FEASIBLE` result is not
accepted. Canonical Phase 4 must explicitly fix each quantity rather than accept an arbitrary equal
optimum. Configure one search worker, a fixed random seed, no wall-clock-derived decision, no
externally varying incumbent, and no time-limited economic answer. Failure to prove the required
result raises `MechanismV2Error(SOLVER_FAILURE)`.

## 12. Independent oracle

Slice 18C's independent oracle must not import the production allocator, CP-SAT model builder,
objective builder, solver wrapper, or OR-Tools. For bounded cases it should use exhaustive
enumeration, structurally independent dynamic programming, or another directly specified exact
reference algorithm.

The oracle independently implements hard qualification, provenance checks, pay-as-bid payment,
feasibility, objective ordering, and canonical tie comparison. Sharing Pydantic schema classes is
allowed; sharing winner, payment, or search implementation is forbidden.

## 13. Security / incentive limitations

CLEAR does not claim that heterogeneous-pay-as-bid-v2 is truthful, strategy-proof, incentive compatible, collusion resistant, or Sybil resistant.

The Week-2 reverse-second-price truthful-bidding claim remains limited to its frozen standardized,
single-dimensional assumptions and does not transfer to V2. Deterministic canonical tie resolution
is not a fairness guarantee.

`AllocationV2` is deterministic mechanism output. It is not proof of signature validity, an
`AllocationCertificateV2`, financial authorization, an `ExecutionPlan`, or permission to call
Razorpay. A stored allocation is never sufficient for money movement. It binds the existing
`sha256-buyer-policy-v2-clear-json-v1` policy commitment, introduces no canonicalization or hash
algorithm, and has no allocation digest in Slice 18A.

Explanation AI remains deferred until an independently verified `AllocationCertificateV2` exists.
