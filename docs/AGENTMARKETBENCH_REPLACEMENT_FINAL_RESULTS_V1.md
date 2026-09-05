# AgentMarketBench V1 Replacement Final Results

## Status

The reviewed replacement final holdout completed exactly once on 10,000
previously unopened synthetic cases. It evaluated source commit
`6eadd5b6eb737649ec35747a73d90b69c403e24f` using metric semantic revision
`agent-market-bench-metric-semantics-v1.1`. The stored bundle passed the frozen
stored-evidence verifier. The replacement holdout is permanently closed:
**DO NOT RERUN THE REPLACEMENT HOLDOUT.**

All numbers below are read from the verified stored `summary.json`, `report.md`,
`run_metadata.json`, and `manifest.json`. No case or result was regenerated.

## Evidence identity

- Evaluated source commit (the R2 source commit):
  `6eadd5b6eb737649ec35747a73d90b69c403e24f`
- Selection anchor commit: `a4fc224ba9b10b518753d05237ab7d56d737943b`
- Selection SHA-256: `babe2f63fe83fa6a67a63d0fc02c16a2a4cfcfc2fe04e4aa94a0e0af29b655f3`
- Seed-sequence SHA-256: `9f255e0668f40a0b61a0ec79b5c25fac5682b5e374ee19cf854615c68187c422`
- Manifest SHA-256: `27c8cc724634cae4a587a52e5687b76fefb47500b8261244cf3762bb7099c3a`
- Semantic root SHA-256: `168eb51dc9c2324db3e9b571bc6c2cefa4211e53ed3b56f4bf5d594713018ebb`
- Timing root SHA-256: `6e727815537b889ca84587ac143c931d2170ea93ce0ee2c95af7da454afeab1f`
- Evidence root SHA-256: `9b9d3fd24d0efe0fed26cdaf63fc5ff6ff4b843ad8061d70c09232c021500c51`
- Stored output: `benchmarks/agentmarketbench_v1/replacement_final_holdout_v1/`
- Inventory: 44 regular files, including 43 non-manifest evidence entries
- Replacement range: `1_641_790_000 .. 1_641_799_999` inclusive
- Started: `2026-09-05T09:59:33.484810Z`
- Completed: `2026-09-05T10:29:43.490096Z`
- Environment: Python 3.12.14, Darwin arm64, Pydantic 2.13.5,
  OR-Tools 9.15.6755, cryptography 49.0.0, clock
  `time.perf_counter_ns`

R3 is publication and evidence preservation only. It is not a new evaluated
source commit; the evaluated source remains the R2 commit above.

## Method summary

The table reports rounded means from the stored exact summaries. Welfare and
regret are **paise per case**. Feasible rate is the FEASIBLE count divided by
10,000. Allocative-efficiency means use the 7,775 cases with nonzero oracle
welfare; the other 2,225 cases are N/A, rather than zero-imputed. Completion
and hard-constraint-violation means use all 10,000 cases. Manipulation success
uses its 1,310 applicable observations. Latency is an observational mean in
nanoseconds and is environment-sensitive. Canonical values are exact rational
values in `summary.json`.

| Method | Feasible rate | Allocative efficiency | Welfare (paise) | Regret (paise) | Completion | Hard-constraint violations | Manipulation success | Latency (ns) |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| `RANDOM_QUALIFYING_SELLER` | 0.342700 | 0.309784 | 2799.33 | 7121.38 | 0.284039 | 0.006200 | 0.025191 | 4,322,405.16 |
| `CHEAPEST_QUALIFYING` | 0.342700 | 0.311612 | 2813.05 | 7107.66 | 0.286074 | 0.006200 | 0.025954 | 4,316,618.14 |
| `STATIC_WEIGHTED_SCORE` | 0.414700 | 0.409315 | 3998.06 | 5922.65 | 0.377676 | 0.007400 | 0.029008 | 4,340,507.26 |
| `BILATERAL_NEGOTIATION` | 0.203600 | 0.185671 | 1576.68 | 8344.02 | 0.167924 | 0.004100 | 0.012214 | 4,329,750.51 |
| `SEQUENTIAL_NEGOTIATION` | 0.405200 | 0.398523 | 3888.26 | 6032.45 | 0.366719 | 0.006900 | 0.026718 | 4,318,405.52 |
| `FIRST_PRICE_REVERSE_AUCTION` | 0.466400 | 0.464800 | 4576.99 | 5343.72 | 0.427517 | 0.008000 | 0.035878 | 4,344,364.49 |
| `REVERSE_VICKREY` | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 4,298,974.27 |
| `CLEAR` | 0.466400 | 0.464784 | 4576.75 | 5343.95 | 0.427517 | 0.008000 | 0.035878 | 5,535,731.93 |
| `FULL_INFORMATION_ORACLE` | 0.777500 | 1.000000 | 9920.71 | 0.00 | 0.753197 | 0.000000 | 0.000000 | 9,891,354.89 |

`REVERSE_VICKREY` had status count `NOT_APPLICABLE = 10000`, so its economic
columns remain N/A. Its displayed latency is still an observational timing
summary.

## CLEAR versus ordinary comparators

Independent checks of the stored paired summaries show that CLEAR had higher
mean welfare and completion than `RANDOM_QUALIFYING_SELLER`,
`CHEAPEST_QUALIFYING`, `STATIC_WEIGHTED_SCORE`, `BILATERAL_NEGOTIATION`, and
`SEQUENTIAL_NEGOTIATION` on this frozen 10,000-case synthetic holdout. For each
of those five comparators, the stored descriptive paired 95% intervals for
welfare and completion are wholly below zero in comparator-minus-CLEAR
orientation, so they exclude zero. These are descriptive intervals, not
p-values or formal hypothesis tests, and they do not establish universal
superiority.

## CLEAR versus first-price reverse auction

`CLEAR` and `FIRST_PRICE_REVERSE_AUCTION` each have 4,664 FEASIBLE and 5,336
INFEASIBLE cases. Their aggregate completion is equal at
`59253889/138600000`, their aggregate hard-constraint-violation mean is equal
at `1/125`, and their measured manipulation-success rate is equal at `47/1310`
over 1,310 applicable observations. Economic outcomes are near-identical in
this benchmark. The stored comparator-minus-CLEAR mean welfare difference is
`+239/1000` paise per case (approximately `+0.239`), and the mean regret
difference is `-239/1000` paise per case (approximately `-0.239`).

The exact stored descriptive paired 95% intervals are:

| Metric | Mean difference (comparator minus CLEAR) | 95% lower | 95% upper |
|:---|---:|---:|---:|
| Welfare (paise) | `+0.239` | `-0.318463779827` | `0.796463779827` |
| Regret (paise) | `-0.239` | `-0.796463779827` | `0.318463779827` |
| Allocative efficiency | `0.000016320821` | `-0.000019045379` | `0.000051687021` |

All three intervals include zero. This is **not** a statistical-equivalence
claim, **not** a dominance claim, and not evidence that CLEAR economically
beats first-price reverse auction. The precise framing is: CLEAR produced
near-identical aggregate economic outcomes to the strongest applicable
first-price reverse-auction baseline in this benchmark.

## Oracle interpretation

`FULL_INFORMATION_ORACLE` is a latent-information upper-bound reference. It is
not an implementable market-protocol competitor. CLEAR is not described as
near-optimal or oracle-equivalent, and the oracle is not evidence of production
performance.

## Robustness and manipulation

CLEAR measured manipulation success in `47 / 1310` applicable observations and
had a hard-constraint-violation mean of `1 / 125`. Those aggregate values match
`FIRST_PRICE_REVERSE_AUCTION` in this benchmark. Protocol rejection/admission
scenarios may be prevented by shared admission. Sybil, collusion,
fake-inventory, SLA-overpromise, dropout, and strategic-shading scenarios are
measured sensitivities, not proven prevented attacks. This evidence does not
claim collusion-proofness, Sybil-proofness, fraud-proofness, strategy-proofness,
truthful V2, or incentive compatibility.

## What the benchmark supports

CLEAR's benchmark value is not an assertion that it economically dominates
every baseline. The supported statement is that CLEAR reaches first-price
auction-level aggregate economic outcomes on this frozen benchmark while the
broader architecture adds authenticated offers, deterministic multiwinner
allocation, replay-verifiable allocation certificates, and a money-governor
boundary. This holdout evaluates the benchmarked mechanism behavior; it does
not imply that every broader production subsystem was exercised by this run.

## Limitations

- This is a synthetic benchmark in a one-buyer x N-sellers scope; it makes no
  N-buyer exchange claim.
- V2 is not claimed strategy-proof, truthful, or incentive-compatible.
- No collusion, Sybil, or fraud proof claim is made.
- Reverse Vickrey is N/A across this final holdout.
- Timing is observational and environment-sensitive.
- The full-information oracle is a latent reference, not an implementable
  protocol.
- The evidence is not proof of physical fulfillment.
- It makes no refunds, reversals, or settlement claim; transfer creation is
  not settlement.
- It makes no exactly-once network-delivery claim.
- The benchmark does not establish transcript completeness for omitted
  real-world submissions.
- It does not prove that signed inventory equals real inventory.
- It makes no formal-verification, ZK, or blockchain claim.
- Duplicate financial side effects are N/A here; that must not be converted
  into a zero-duplicate production claim.
- Razorpay live or test claims are outside this benchmark unless separately
  demonstrated.

## Incident provenance

The original final attempt opened exactly once at source commit
`93073144db6128d7e23558545e5d544e350ad292` and persisted exactly 3,000 cases.
It failed because of the benchmark welfare-semantics infrastructure defect
described in the historical holdout record. The entire original final
partition is permanently retired; those 3,000 cases are excluded from every
replacement aggregate. R1 repaired minimum-qualified benchmark-welfare
semantics. The replacement partition was selected before it was opened, and
R2 froze the execution and evidence protocol before replacement generation.
After remote R2 verification, the replacement execution occurred exactly once.
No original-partition result is combined with these replacement final results.

## Verification

The following is a read-only verification example. It calls only the stored
replacement-evidence verifier and does not run a holdout, generate a case, or
execute a method:

```python
from pathlib import Path

from clear_market.agentmarketbench.replacement_final_evidence import (
    verify_agent_market_bench_replacement_final_evidence_v1,
)

manifest = verify_agent_market_bench_replacement_final_evidence_v1(
    Path("benchmarks/agentmarketbench_v1/replacement_final_holdout_v1")
)
print(manifest.evidence_root_sha256)
```

**DO NOT RERUN THE REPLACEMENT HOLDOUT.**
