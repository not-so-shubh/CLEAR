# AgentMarketBench Runner V1

Slice 24D is the measurement layer for AgentMarketBench V1. Slice 24E-R1
repairs its oracle-relative welfare comparability semantics. It runs the nine
frozen methods from Slice 24C, evaluates their decisions against the complete
latent case truth, records scenario classifications, and produces exact
paired summaries. It does not choose a winner, tune a method, execute a
provider, or create the final holdout report.

## Versions and boundary

The evidence models use these versions:

```text
agent-market-bench-runner-v1
agent-market-bench-metrics-v1
agent-market-bench-statistics-v1
agent-market-bench-rational-v1
agent-market-bench-metric-observation-v1
agent-market-bench-scenario-assessment-v1
agent-market-bench-method-evaluation-v1
agent-market-bench-case-run-v1
agent-market-bench-metric-summary-v1
agent-market-bench-paired-summary-v1
agent-market-bench-run-summary-v1
agent-market-bench-run-v1
```

The existing `agent-market-bench-metrics-v1` identifier remains the V1
measurement observation/schema family in this slice. All existing model
literals and schemas, including `AgentMarketBenchCaseRunV1`, remain unchanged.
The corrected semantic interpretation is identified separately by:

```python
AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION: Final[str] = (
    "agent-market-bench-metric-semantics-v1.1"
)
```

This exported constant is not an added field in any existing V1 model. Failed
final attempt #1 used source commit
`93073144db6128d7e23558545e5d544e350ad292` and the pre-repair raw-welfare
oracle-comparison semantics. Repaired source uses
`agent-market-bench-metric-semantics-v1.1`; this is not claimed to be
byte-compatible metric behavior. The source commit and the future replacement
final-evidence protocol's explicit semantic revision distinguish the two.
Slice 24E-R2 must carry that revision in its manifest and metadata.

Ordinary public economic methods remain latent-free and receive only the
`AgentMarketBenchMarketInputV1`. `FULL_INFORMATION_ORACLE` is the sole
case-aware economic method and reads latent truth during its call. After method
execution, the metrics layer may read latent truth to evaluate decisions. No
certificate, financial ledger, Money Governor, payment provider, Razorpay,
persistence, execution,
AI, or historical benchmark subsystem is called here.

The full-information oracle is a benchmark reference comparator, not an
executable mechanism or payment recommendation. There is no live Razorpay
claim, fulfillment proof, physical-inventory truth claim, duplicate-money-
side-effect claim, or general V2 truthfulness/strategy-proofness claim. Slice
24D makes no Sybil or collusion prevention claim and makes no prompt-injection
robustness claim because AI is not exercised.

## Raw latent realization

For each result line, the metrics layer resolves the exact latent line by
`(merchant_id, sku_id)`. Allocated quantity is capped at true availability for
realized economics. Excess contractual units are retained separately as
`latent_capacity_excess_units`; they are not relabelled as hard violations.

Hard constraints are evaluated against typed latent values. Latent values have
no reported provenance, so the reported provenance allowlist is ignored while
the attribute key, exact value type, and EQ/NE or integer comparison semantics
remain required. A line failing any latent hard rule realizes zero quantity and
adds its contractual allocated units once to `latent_hard_violation_units`.

Across realized units:

```text
realized_buyer_value = sum(quantity * true_unit_buyer_value)
realized_true_cost   = sum(quantity * true_unit_cost)
raw_realized_welfare = realized_buyer_value - realized_true_cost
buyer_surplus        = realized_buyer_value - full contractual total payment
merchant_surplus     = full contractual total payment - realized_true_cost
```

`realize_agent_market_bench_method_v1` retains this raw diagnostic truth:
realized quantity, realized buyer value, realized true cost,
`realized_welfare_paise`, capacity excess, and latent hard-violation units.
Raw welfare is never clamped or erased when realization falls below the
buyer's minimum. Full contractual payment remains in both surplus formulas,
including payment on impossible excess units.

## Minimum-qualified benchmark welfare

Oracle-relative benchmark welfare uses exactly this rule for both the method
and the full-information oracle:

```text
benchmark_welfare = 0 if realized_quantity < minimum_acceptable_quantity
                   else raw_realized_welfare
```

The full-information oracle only accepts allocations satisfying
`minimum_acceptable_quantity`. Oracle-relative welfare comparisons therefore
must use the same minimum-quantity feasibility domain. Latent-hard failing
lines already contribute no realized quantity, value, cost, or welfare. If
the surviving latent-valid allocation reaches the minimum, its raw welfare
remains comparable to the oracle. The rule does not additionally gate on
requested quantity, full completion, scenario, method, capacity excess, or
hard-violation count.

Minimum-qualified welfare determines `WELFARE`, `ALLOCATIVE_EFFICIENCY`,
`REGRET`, and the oracle nonnegative and method upper-bound invariants. Raw
realization still determines `COMPLETION`, `BUYER_SURPLUS`,
`MERCHANT_SURPLUS`, capacity diagnostics, and hard-constraint diagnostics.

When realized quantity reaches the minimum, buyer surplus plus merchant
surplus equals benchmark `WELFARE`. Below the minimum, their sum remains raw
realized social surplus while benchmark `WELFARE` is zero. This is a
benchmark-comparability convention. It is not a claim that partial delivered
units have no intrinsic value. It is not physical fulfillment evidence and
does not imply refunds, returns, acceptance, or settlement behavior.

## Metrics

All values are exact reduced rationals; no floating-point arithmetic is used.

| Metric | Unit | Definition |
|:---|:---|:---|
| `ALLOCATIVE_EFFICIENCY` | `RATIO` | Method minimum-qualified welfare divided by full-information oracle minimum-qualified welfare. N/A with `ORACLE_WELFARE_ZERO` when the latter is zero. |
| `REGRET` | `PAISE` | Oracle minimum-qualified welfare minus method minimum-qualified welfare; negative values are an invariant error. |
| `BUYER_SURPLUS` | `PAISE` | Realized buyer value minus the result's contractual total payment. |
| `MERCHANT_SURPLUS` | `PAISE` | Result's contractual total payment minus realized true cost. This is aggregate selected-seller surplus, not principal-level anti-Sybil economics. |
| `WELFARE` | `PAISE` | Zero below the minimum acceptable realized quantity; otherwise raw realized buyer value minus raw realized true cost. |
| `COMPLETION` | `RATIO` | Realized quantity divided by requested quantity. |
| `HARD_CONSTRAINT_VIOLATIONS` | `COUNT` | Contractual allocated units on lines failing latent hard rules. |
| `MANIPULATION_SUCCESS` | `BINARY` | Scenario-specific rule described below. |
| `PAYMENT_CORRECTNESS` | `BINARY` | Benchmark payment-rule correctness, not provider settlement correctness. |
| `DUPLICATE_FINANCIAL_SIDE_EFFECTS` | `COUNT` | Always N/A with `NO_FINANCIAL_EXECUTION_IN_24D`; Slice 24D executes no financial runtime. |
| `LATENCY` | `NANOSECONDS` | Observed elapsed nanoseconds around exactly one public 24C method call. |

For a method-not-applicable result, every economic/payment/manipulation metric
except latency is N/A with `METHOD_NOT_APPLICABLE`; duplicate side effects
keeps its stronger runtime N/A reason. Latency remains measured because the
call occurred. For feasible or infeasible results, economic metrics are
measured. The oracle has efficiency `1/1` whenever its minimum-qualified
welfare is positive. Minimum-qualified oracle welfare must be nonnegative.
A method exceeding the minimum-qualified oracle welfare still raises exactly
`ValueError("method welfare exceeds full-information oracle welfare")`;
the repair does not clamp welfare or weaken the oracle. Metric order, units,
N/A precedence and reasons, manipulation, payment correctness, duplicate-side-
effect N/A, and latency semantics are unchanged.

Payment correctness independently checks authenticated reported asks for
ordinary methods, including CLEAR and first-price, independently checks the
narrow reverse-Vickrey second price, and checks latent true-cost reference
payments for the full-information oracle. An infeasible zero-payment result is
correct by definition. This does not observe settlement or provider behavior.

Manipulation is deliberately narrow. With no scenario it is N/A with
`SCENARIO_NOT_DEFINED`. AI-text scenarios are N/A because no AI is exercised.
Economic shading, dropout, Sybil, and collusion scenarios are also N/A for
this causal metric; they are classified as measured economic sensitivity in
the scenario audit. Fake inventory is one only when a method allocates beyond
the latent quantity on the inflated target. SLA overpromise is one only when
the reported SLA satisfies a relevant hard rule while latent SLA fails and
the method allocates that line. Protocol scenarios use shared admission:
altered and forged offers expect authentication failure, late offers expect
`LATE_OFFER`, and replays expect `DUPLICATE_OFFER_ID`; a present expected
rejection gives zero, otherwise one. Runtime markers are always N/A with
`NO_FINANCIAL_EXECUTION_IN_24D` because no provider/webhook/transfer evidence
is fabricated.

## Scenario classifications

The audit emits one assessment for each declared scenario:

| Scenarios | Classification | Evidence basis |
|:---|:---|:---|
| `ALTERED_OFFER`, `LATE_OFFER`, `REPLAYED_OFFER`, `FORGED_MERCHANT` | `PREVENTED` when the expected shared-admission rejection exists, otherwise `MEASURED` | `SHARED_ADMISSION` |
| `PROMPT_INJECTION`, `MALICIOUS_CATALOG_TEXT`, `SCHEMA_MANIPULATION` | `OUT_OF_SCOPE` | `AI_NOT_EXERCISED` |
| `STRATEGIC_SHADING`, `SELLER_DROPOUT`, `FAKE_INVENTORY`, `SLA_OVERPROMISE`, `SYBIL_SENSITIVITY`, `COLLUSION_SENSITIVITY` | `MEASURED` | `ECONOMIC_SENSITIVITY` |
| `DUPLICATE_EVENT`, `EVENT_REORDERING`, `PROVIDER_TIMEOUT`, `PAYMENT_FAILURE`, `TRANSFER_FAILURE`, `RETRY`, `RECONCILIATION`, `RECOVERY` | `OUT_OF_SCOPE` | `FINANCIAL_RUNTIME_NOT_EXERCISED` |

The runtime marker exists in the generated case, but Slice 24D does not
fabricate provider, webhook, payment, or transfer evidence. `OUT_OF_SCOPE`
means the AgentMarketBench economic runner did not execute that trust domain;
it does not mean CLEAR lacks separate reviewed payment tests, and it does not
prove runtime safety.

## Timing and reproducibility

Method execution order is deterministic but is not baseline enum order. For a
case digest and method, rank the ASCII SHA-256 input
`agent-market-bench-runner-v1|method-order|case_digest={digest}|method={value}`
and sort by `(digest_hex, method.value)`. The runner retains this actual order
while normalizing evaluations to baseline enum order.

The timed region is exactly one public 24C method call. Case generation,
statistics, and serialization are outside the clock. Economic outputs and all
non-latency metrics are deterministic for a fixed case and implementation;
latency is observational and environment-sensitive. Exact case-run equality
therefore requires an injected deterministic clock. Real runs only promise
nonnegative integer nanoseconds.

## Exact summaries and confidence intervals

Method summaries cover all 9 methods by all 11 metrics. N/A observations are
counted separately and never imputed as zero. Paired summaries cover each of
the eight non-CLEAR comparators and each metric. Every pair is oriented exactly
as:

```text
comparator value - CLEAR value
```

Only cases where both observations are measured contribute. The mean is exact
rational arithmetic. For `n >= 2`, the descriptive paired normal-approximation
95% interval uses:

```text
sample_variance = sum((x_i - mean)^2) / (n - 1)
standard_error  = sqrt(sample_variance / n)
half_width      = 1.95996398454005423552 * standard_error
lower           = mean - half_width
upper           = mean + half_width
```

Python `Decimal` is used only for square root and bounds, with precision `80`
and `ROUND_HALF_EVEN`. Bounds serialize as exactly 12 fractional decimal
places. For `n=0`, mean and intervals are absent; for `n=1`, the exact mean is
present and intervals are absent. No p-values, significance labels, rankings,
winner fields, or superiority claims are emitted.

## Holdout boundary

Development data may be used for implementation and tests. Slice 24D does not
import seed partitions and does not generate, inspect, execute, or summarize
the final holdout. The original final partition
`2_000_000_000 .. 2_000_009_999` was opened exactly once and is permanently
retired after failed attempt #1. Its partial evidence is preserved; the
original API and CLI cannot execute it again. See
[the final-holdout incident record](AGENTMARKETBENCH_FINAL_HOLDOUT_V1.md).

The diagnostic-only quarantine `500_000_000 .. 500_020_999` is permanently
excluded from future replacement holdout selection. Slice 24E-R1 uses frozen
development cases and diagnostic regressions only; no generated case may use
a seed `>= 2_000_000_000`. The existing invalid-input test may pass
`2_147_483_648` solely to verify rejection before any case generation; no
original-final seed is passed. It does not choose, generate, inspect, or execute
any replacement holdout. A reviewed replacement must be previously unopened,
and Slice 24E-R2 must explicitly bind the corrected semantic revision in its
replacement evidence manifest and metadata.
