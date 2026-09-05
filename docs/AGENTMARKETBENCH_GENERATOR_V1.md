# AgentMarketBench Generator V1

This document freezes the Slice 24B case generator. It describes how benchmark
cases are constructed; it does not describe a benchmark runner, baselines,
metrics, an allocator, an oracle, or final benchmark results.

## Version and seed domain

The generator version is `agent-market-bench-generator-v1`. Seeds are exact
Python `int` values in the inclusive range `0..2,147,483,647`. `bool` is not an
accepted seed type.

The development partition is exactly:

```text
tuple(range(100_000_000, 100_001_008))
```

It contains 1,008 seeds, from 100,000,000 through 100,001,007. The final
holdout partition is exactly:

```text
tuple(range(2_000_000_000, 2_000_010_000))
```

It contains 10,000 seeds, from 2,000,000,000 through 2,000,009,999. The
partitions are disjoint from each other and from the historical Week-2 ranges
`0..31` and `1,000,000..1,009,999`. Final-holdout values are frozen metadata in
Slice 24B. Development seeds may be used for implementation, debugging, and
tuning. Final-holdout seeds, cases, and results must not be inspected or used
for tuning before the frozen final evaluation. No final-holdout case is
generated or reported in this slice; this is a workflow boundary, not a claim
that the holdout is secret or technically inaccessible.

## Deterministic construction

Every semantic draw is domain-separated. For a seed and domain label, the
generator computes:

```text
SHA-256("agent-market-bench-generator-v1|seed={seed}|{domain}")
```

The first eight digest bytes are interpreted as a big-endian unsigned integer.
Bounded integer values use modulo over the requested inclusive range, and
booleans use the low-order bit. Adding a new domain draw does not shift a
mutable random stream. The generator does not use `random`, `secrets`,
`os.urandom`, process-global RNG state, `hash()`, UUID-v4 wall-clock/random
helpers, or wall-clock time.

Visible UUIDs are derived from the same version/seed/domain material, use the
first 16 digest bytes, and have RFC 4122 variant and version-4 bits set. They
are canonical lowercase UUID strings and do not embed a readable seed. This
derivation covers case, market, buyer, merchant, economic-principal, catalog,
product, SKU, inventory snapshot, evidence, offer, economic-policy, and rule
identifiers.

Each merchant's synthetic Ed25519 private key is derived from a separate
SHA-256 domain (`merchant-key`, with `forged-merchant-key` for the forged
signature fixture). Private keys exist only during fixture construction. Only
the public key is placed in the case; no private key enters case data, market
input, canonical bytes, logs, or evidence projections.

Protocol timestamps are fixed aware UTC values:

```text
catalog generated_at        2030-01-01T09:00:00Z
inventory captured_at       2030-01-01T10:00:00Z
normal receipt window       starts 2030-01-01T11:00:00Z
offer deadline              2030-01-01T12:00:00Z
late receipt                2030-01-01T12:00:01Z
```

Normal receipts are ranked by a domain-separated draw, then assigned increasing
seconds in that ranking. Reported submission indexes are contiguous and their
tuple order is benchmark-semantic.

## Base market distribution

Each case is one buyer with 3..7 heterogeneous merchants and 1..3 SKUs per
merchant. The buyer requests 4..12 units, permits 1..min(4, merchant count,
requested quantity) winners, and draws a unit budget of 1,800..3,600 paise.
`max_total_payment` is exactly requested quantity times that unit budget.
Minimum acceptable quantity is selected from integer ceilings of one-half,
three-quarters, or all requested quantity.

For every SKU, monetary fields below are integer INR paise; quantity, quality
score, SLA days, and eco certification use their stated non-monetary types or
units:

```text
true unit cost             500..2,400
buyer-value uplift         800..2,200
true unit buyer value      true cost + uplift
true available quantity   1..8
minimum merchant margin    100..300
ordinary extra ask markup  0..300
quality_score              1..10
sla_days                   1..7
eco_certified              deterministic boolean
```

An ordinary ask is true cost plus minimum margin plus ordinary extra markup.
Each SKU has exactly the typed catalog attributes `quality_score` (INTEGER),
`sla_days` (INTEGER), and `eco_certified` (BOOLEAN). Attribute provenance is
drawn from the production provenance labels, while latent attributes retain
the same values without provenance. Every SKU receives deterministic evidence
references.

The policy always has `quality_score >= threshold`, with threshold 5..8 and
accepted provenance exactly `VERIFIED`, `ATTESTED`, `CLAIMED`, and `DERIVED`.
An independent bit may add `sla_days <= threshold`, with threshold 3..6 and
the same accepted provenance. The policy always prefers `eco_certified ==
True`; another independent bit may add a `quality_score >= 8` preference. Rule
IDs are deterministic UUIDv4 values. Policies use the production mechanism and
objective versions `heterogeneous-pay-as-bid-v2` and
`quantity-cost-soft-objective-v2`.

Offers are built and signed through the production merchant builder with real
buyer-policy, catalog, and inventory commitments. Merchant economic policies
are generator-private and never part of the case.

Buyer prose records the quantity, paise ceiling, and visible policy rules only.
It does not contain the seed, case ID, scenario token, economic principals, or
latent economics. `AgentMarketBenchMarketInputV1` is the evaluated-method
projection: latent lines, buyer prose, case metadata, scenario labels, and
economic principals are outside that input. This is the authoritative
information firewall: latent truth is for a later full-information oracle and
metrics only; evaluated methods receive observed/reported state only. The
generator never conditions on an allocation, oracle, baseline, payment, or AI
result.

## Scenario assignment

For every even seed, `adversarial_scenarios == ()`. For every odd seed, exactly
one scenario is selected using the frozen enum order:

```python
scenarios[(seed // 2) % len(scenarios)]
```

Thus every 42 consecutive seeds beginning at an even seed contains 21 standard
cases and one case for each of the 21 scenarios. The development partition has
24 such complete cycles: 504 standard cases and 24 cases of each scenario.
These synthetic frequencies are test design, not a claim about real-world
attack prevalence or realism.

## Case-embedded scenarios

The following 13 scenarios change typed case evidence while preserving the
protocol's explicit structural boundary:

* `ALTERED_OFFER`: build and sign normally, then increase one target offer
  line's unit price by one paise without resigning. It is structurally valid
  but fails cryptographic verification.
* `LATE_OFFER`: retain a valid signed offer and set one receipt to one second
  after the policy deadline.
* `REPLAYED_OFFER`: append a byte-identical valid signed offer with the next
  contiguous submission index before the deadline.
* `FORGED_MERCHANT`: sign a legitimate target offer with the separate forged
  key while leaving the trusted observed public key unchanged. Verification
  fails attribution/signature checks.
* `PROMPT_INJECTION`: replace one product description with deterministic
  hostile instruction text. The enum token is not placed in the text.
* `MALICIOUS_CATALOG_TEXT`: replace one product description with deceptive
  provenance/authority prose while keeping typed state and signatures valid.
* `SCHEMA_MANIPULATION`: place deterministic JSON-/schema-shaped hostile text
  in one description. This is text-based coverage, not malformed-wire-input
  coverage.
* `STRATEGIC_SHADING`: set one target merchant's prices to true cost plus
  1,500 paise and sign normally.
* `SELLER_DROPOUT`: keep the target eligible, observed, and latent, but omit
  its reported offer.
* `FAKE_INVENTORY`: report target inventory as true quantity plus three and
  offer the inflated quantity. Public source verification succeeds; latent
  truth retains the lower quantity.
* `SLA_OVERPROMISE`: report target SLA as one day while latent truth retains
  seven days, with normal source-bound signing.
* `SYBIL_SENSITIVITY`: give at least two distinct merchant IDs the same
  economic principal while retaining distinct catalogs, inventory, offers,
  and signing keys.
* `COLLUSION_SENSITIVITY`: set at least two distinct-principal merchants'
  prices to the shared 3,500-paise anchor and sign normally. This measures a
  sensitivity fixture and is not a claim to model every collusion strategy.

## Runtime-marker-only scenarios

`DUPLICATE_EVENT`, `EVENT_REORDERING`, `PROVIDER_TIMEOUT`, `PAYMENT_FAILURE`,
`TRANSFER_FAILURE`, `RETRY`, `RECONCILIATION`, and `RECOVERY` are labels only in
Slice 24B. Their cases otherwise contain ordinary economic state. No webhook,
payment, transfer, provider-event, or new case fields are fabricated, and no
payment/provider code is called. Their runtime fault semantics must be supplied
by a later reviewed runner or audit layer. A marker is not evidence that a
scenario was executed, prevented, detected, mitigated, or measured.

## Scope and evidence status

The generator creates validated cases only. It does not implement baselines,
allocation benchmarking, the full-information oracle, metrics, confidence
intervals, reports, manifests, final holdout execution, provider fault
injection, Razorpay execution, or AI calls. No benchmark-performance claim is
made by Slice 24B.
