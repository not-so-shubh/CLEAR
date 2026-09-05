# AgentMarketBench Methods V1

This document freezes the economic comparators for AgentMarketBench V1.  The
method version is `agent-market-bench-methods-v1`.  Results are benchmark
evidence only: they are not certificates, payment instructions, settlement
authority, or fulfillment proof.

The companion evidence schemas are versioned as follows:

```text
agent-market-bench-methods-v1
agent-market-bench-admission-v1
agent-market-bench-admission-rejection-v1
agent-market-bench-decision-line-v1
agent-market-bench-method-result-v1
```

## Information firewall

Ordinary methods receive only `AgentMarketBenchMarketInputV1`: the buyer policy,
observed merchant source state, and reported signed offers.  They do not receive
case IDs, seeds, buyer text, latent lines, economic principals, adversarial
labels, true costs, true values, true inventory, or merchant-private policy.
Only `FULL_INFORMATION_ORACLE` receives a complete case and may read latent
truth.  A signed reported state proves authentication and source consistency; it
does not prove physical inventory, SLA performance, seller honesty, or fulfillment.

## Admission

Every comparator uses the shared admission layer.  Reports must have contiguous
submission indexes in tuple order.  Each report is processed in that order:

1. A receipt strictly later than the buyer deadline is `LATE_OFFER` (the exact
   deadline is accepted).
2. A merchant absent from observed source state is `UNKNOWN_MERCHANT`.
3. The production canonical signed-offer verifier checks the public signing
   identity, buyer-policy/catalog/inventory commitments, and SKU/source binding;
   any failure is `AUTHENTICATION_FAILED`.
4. A successfully authenticated repeated offer ID is `DUPLICATE_OFFER_ID`.
5. A successfully authenticated second offer from an admitted merchant is
   `DUPLICATE_MERCHANT`.

Only authenticated, on-time, nonduplicate reports enter economic methods.
Dropout is an absent report, not a fabricated rejection.  Admission does not
establish latent truth or authorize money.

## Baselines

All ordinary baselines enforce request quantity, minimum acceptable quantity,
reported capacities, total-payment ceiling, hard constraints, nonnegative
integer-money arithmetic, and the maximum number of winning merchants.  Except
for reverse Vickrey, selected lines are paid at their authenticated reported
unit ask.  Economic lines are canonicalized by `(merchant_id, sku_id, offer_id)`.
Hard and soft matching uses typed values and the line's allowed reported
provenance: missing attributes, disallowed provenance, and type mismatches do
not match.

### RANDOM_QUALIFYING_SELLER

For each merchant, greedily sort qualified lines by lower ask, greater soft-match
count, then canonical line key.  Keep single-merchant candidates that meet the
minimum quantity.  Rank them by the lexicographically smallest pair of SHA-256
hex digest and merchant ID, where the digest input is:

`agent-market-bench-methods-v1|RANDOM_QUALIFYING_SELLER|market_id={market_id}|merchant_id={merchant_id}`

The selected candidate is the only winner.  No mutable RNG or seed is used.

### CHEAPEST_QUALIFYING

Use the same single-merchant candidates.  Select by exact average payment using
`Fraction`, then greater quantity, lower total payment, and merchant ID.

### STATIC_WEIGHTED_SCORE

Hard-filter lines, then score each line with integer components in `0..1000`.
The unit-budget reference is
`max(1, max_total_payment.amount_paise // requested_quantity)`.

```text
price = max(0, 1000 - min(1000, unit_price_paise * 1000 // unit_budget_reference))
quality = clamp(quality_score * 100, 0, 1000)       # exact integer, else 0
sla = clamp((8 - sla_days) * 1000 // 7, 0, 1000)    # exact integer, else 0
eco = 1000 if exact typed True else 0
weighted = 40 * price + 30 * quality + 20 * sla + 10 * eco
```

Rank by higher weighted score, lower ask, greater soft-match count, then the
canonical line key, and greedily respect capacity, budget, request, and winner
cap.  These are synthetic frozen comparator weights, not an empirically tuned
optimum.

### BILATERAL_NEGOTIATION

This is a reproducible quote-selection proxy, not a simulation or evaluation of
LLM bargaining.  Engage only the first receipt-order admitted merchant with a
hard-qualified line.  Apply that merchant's single-seller greedy ordering and
use signed asks as final prices.  Do not move to another merchant.

### SEQUENTIAL_NEGOTIATION

This is also a deterministic quote-selection proxy, not a bargaining-quality
claim.  Process admitted merchants in receipt order, process each merchant's
qualified lines by lower ask, greater soft-match count, and canonical key, and
accept signed asks until request, budget, or winner cap is reached.  Merchants
receiving zero quantity do not consume a winner slot, and merchants are not
revisited.

### FIRST_PRICE_REVERSE_AUCTION

Ignore soft preferences after hard qualification.  Enumerate every merchant
subset of exact size `min(max_winners, qualifying merchant count)`; allowing zero
allocation within a subset covers candidates with fewer actual winners.  Inside
each subset, allocate cheapest reported units first, ties by canonical line key,
under capacity, request, and budget.  Choose exactly by greater fulfilled
quantity, lower pay-as-bid payment, then lexicographically greater allocation
quantity vector in canonical line order.  This is exact for its frozen cost-only
objective, not a greedy winner-cap artifact.

### REVERSE_VICKREY

This comparator is `NOT_APPLICABLE` except for a narrow homogeneous, single-unit
case: request and minimum are one, winner cap is one, at least two merchants each
contribute exactly one qualified line, each has capacity, and all decision-
relevant typed attributes are identical.  The lowest ask wins with canonical-key
tie breaking and is paid the second-lowest ask when that price fits the budget.
This does not claim V2 strategy-proofness, truthfulness, or general incentive
compatibility.  Generated multi-unit populations normally make it not applicable.

### CLEAR

CLEAR runs the same admission layer and then calls production
`allocate_market_v2` on exactly the admitted signed offers.  Its result is
translated without changing IDs, quantities, unit/line payments, total payment,
or winner count.  No certificate verifier, Money Governor, payment provider,
persistence layer, or Razorpay integration is involved.

### FULL_INFORMATION_ORACLE

The full-information oracle is a separate case-aware reference comparator, not
an executable mechanism or payment recommendation.  It first applies public
admission, so dropout, late, replay, altered, and forged participation are
excluded exactly as public methods exclude them.  Fake inventory and SLA
overpromise remain admitted when their reported state authenticates, but the
oracle uses latent true quantity and attributes.  Strategic shading and
collusion remain admitted, while the oracle uses latent cost and buyer value.

For admitted merchants, hard and soft rules compare typed latent values while
ignoring reported provenance allowlists; this does not promote latent values to
production `VERIFIED` provenance.  The oracle uses true unit cost as a bounded
benchmark reference payment, not a production transfer recommendation.

An independent bounded dynamic program searches exact integer allocations under
true capacities, request/minimum quantity, winner cap, and the buyer budget.  It
optimizes lexicographically:

1. maximize true welfare, `sum(quantity * (true_unit_buyer_value - true_unit_cost))`;
2. maximize fulfilled quantity;
3. maximize latent soft-preference unit score;
4. minimize true-cost reference payment;
5. lexicographically maximize the complete canonical latent allocation vector.

Oracle decision lines have no source offer ID.  The implementation does not use
OR-Tools, the production allocator, or `clear_market.oracle.v2`.

## Scope and reserved evaluation

Slice 24C has no runtime/provider semantics, aggregate metrics, rankings,
confidence intervals, superiority claims, or holdout inspection.  No Sybil or
collusion prevention claim is made.  Development data may be used for
implementation and tests.  The final holdout remains reserved for Slice 24E.
