# AgentMarketBench V1 Final-Holdout Evidence

## Failed attempt #1 and permanent retirement

The original final partition `2_000_000_000 .. 2_000_009_999` was opened
exactly once, from source commit
`93073144db6128d7e23558545e5d544e350ad292`. It is now permanently retired.
No further original-final seed is to be intentionally generated, and the
original final holdout must not be resumed or rerun.

Exactly 3,000 cases persisted as six semantic and six timing shards, each
containing 500 cases, covering exactly
`2_000_000_000 .. 2_000_002_999`:

```text
semantic/part-00000.jsonl.gz .. semantic/part-00005.jsonl.gz
timing/part-00000.jsonl.gz   .. timing/part-00005.jsonl.gz
```

Execution aborted during the seventh 500-case block before `part-00006`
publication, with:

```text
ValueError("method welfare exceeds full-information oracle welfare")
```

The cause was a benchmark metric feasibility-domain mismatch: a public
method's partial latent-valid realization could have positive raw welfare
while falling below the buyer's minimum acceptable quantity. Such an outcome
is outside the full-information oracle's feasible set.

The partial failed-attempt evidence is preserved at
`benchmarks/agentmarketbench_v1/final_holdout_v1/`. It contains exactly the
12 shards above. No completed `manifest.json`, `summary.json`, `report.md`, or
`run_metadata.json` exists. These files must remain byte-for-byte unchanged:
no additions, renames, rewrites, deletions, intentional permission changes,
or staging of the partial evidence. No final benchmark conclusion or winner
may be inferred from partial data.

Slice 24E-R1 retires `run_agent_market_bench_final_holdout_v1` so it fails
deterministically before writer construction, output-directory creation,
generator invocation, or seed iteration. The API and CLI report the stable
retirement reason:

```text
original AgentMarketBench final holdout partition is retired after failed attempt 1; a reviewed replacement holdout is required
```

The CLI exits nonzero for this reason. There is no resume, retry, cleanup,
alternate-output, or replacement-seed path.

## Corrected metric semantics and version boundary

Failed attempt #1 used the accepted source commit above and the pre-repair
raw-welfare oracle-comparison semantics. Repaired source uses the exported
semantic revision:

```python
AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION: Final[str] = (
    "agent-market-bench-metric-semantics-v1.1"
)
```

Raw latent realization remains unchanged: realized quantity, realized buyer
value, realized true cost, raw realized welfare, latent capacity excess, and
latent hard-violation units. Raw welfare remains buyer value minus true cost.
The repaired benchmark welfare is zero when latent-valid realized quantity
is below `minimum_acceptable_quantity`, and raw realized welfare otherwise.
It supplies `WELFARE`, `ALLOCATIVE_EFFICIENCY`, `REGRET`, the oracle
nonnegative invariant, and the method-to-oracle upper-bound invariant.
Raw surplus, completion, and latent diagnostics remain raw. This is a
benchmark-comparability convention, not a claim that partial delivered units
have no intrinsic value, not physical fulfillment evidence, and not a refund
or settlement rule. See [the metric definitions](AGENTMARKETBENCH_RUNNER_V1.md).

`AGENT_MARKET_BENCH_METRICS_V1_VERSION` remains exactly
`"agent-market-bench-metrics-v1"`, identifying the existing V1 measurement
observation/schema family. Slice 24E-R1 changes no model literals or schemas,
adds no semantic-revision field to existing V1 models, and leaves the
`AgentMarketBenchCaseRunV1` and final-evidence schemas unchanged. This is not
claimed to be byte-compatible metric behavior. The evaluated source commit
and future replacement-evidence semantic revision distinguish pre-repair and
repaired evidence. Slice 24E-R2 must explicitly carry
`agent-market-bench-metric-semantics-v1.1` in its replacement manifest and
metadata.

## Frozen pre-implementation diagnostics and regressions

The diagnostic-only quarantine is `500_000_000 .. 500_020_999`. It is
permanently excluded from every future replacement holdout selection.

The pre-implementation reproducer at seed `500_002_459` is a
`FAKE_INVENTORY` case. `RANDOM_QUALIFYING_SELLER` contracts for the requested
five units; the minimum acceptable quantity is three. Its raw realized
quantity is two, raw realized welfare is 4,224 paise, and latent capacity
excess is three units. The full-information oracle is `INFEASIBLE` with raw
welfare zero. Under the repaired semantics, the method's benchmark `WELFARE`
and `REGRET` are `0/1`, efficiency is N/A with `ORACLE_WELFARE_ZERO`, and
completion remains `2/5`. Raw welfare remains 4,224 and capacity excess
remains three. This reproducer is required normal pytest regression evidence.

The frozen development diagnostic evaluated exactly 1,008 cases and 8,064
ordinary method evaluations. The proposed rule changed exactly these four
method observations, all to zero benchmark welfare:

| Seed | Method | Raw welfare (paise) | Realized quantity | Minimum quantity |
|:---|:---|---:|---:|---:|
| `100000549` | `RANDOM_QUALIFYING_SELLER` | 4792 | 4 | 6 |
| `100000549` | `CHEAPEST_QUALIFYING` | 4792 | 4 | 6 |
| `100000803` | `STATIC_WEIGHTED_SCORE` | 9911 | 5 | 8 |
| `100000803` | `SEQUENTIAL_NEGOTIATION` | 7886 | 5 | 8 |

There were four benchmark welfare changes, zero raw oracle-bound violations,
zero raw violations unexplained by below-minimum realization, and zero
minimum-qualified oracle-bound violations.

The frozen quarantine diagnostic evaluated exactly 1,000 `FAKE_INVENTORY` /
`SLA_OVERPROMISE` cases and 8,000 ordinary method evaluations. It found 345
benchmark welfare changes and 35 raw oracle-bound violations. All 35 were
explained by below-minimum realization; zero were unexplained. There were
zero minimum-qualified oracle-bound violations.

These are frozen pre-implementation diagnostic facts and regression evidence,
not proof that the rule holds universally. Post-implementation diagnostics
must reproduce the same counts and the same four development changes; any
unexpected count, additional development change, or minimum-qualified
oracle-bound violation requires stopping and reporting. A genuine
minimum-qualified method welfare above the oracle must still raise the
original invariant exception; it must not be clamped.

No diagnostic or test may generate a case from a seed `>= 2_000_000_000`.
The existing invalid-input regression may pass `2_147_483_648` solely to
assert rejection before generation; this disclosed exception does not pass
an original-final seed or generate a case.
Reading the already-persisted shard bytes for preservation checks does not
generate a case. Slice 24E-R1 does not choose, generate, inspect, or execute
any replacement holdout and does not run the historical Week-2 benchmark.
A future reviewed replacement must be previously unopened and exclude the
entire quarantine range; replacement seeds are not selected here.

## Historical 24E-A protocol

The remaining sections describe the original frozen protocol as historical
context. Slice 24E-A froze the schema, transport, execution harness, neutral
report renderer, manifest, and verifier before the single failed attempt.
They do not authorize another execution or describe a completed artifact.

## Evaluated source commit

`evaluated_source_commit` is the exact lowercase 40-hex Git commit whose
generator, methods, oracle, metrics, statistics, and evidence harness are being
evaluated. The original CLI preflight required repository `HEAD` to equal that
commit, an entirely clean working tree, and absence of the frozen output path.
It did not require a branch name or change Git history. Retirement now prevents
generation regardless of those former preconditions.

## One-case-at-a-time execution

The original runner processed the frozen seed tuple in order. For each seed
it generated one case, called the frozen 24D single-case runner once using its
real default `time.perf_counter_ns` clock, compacted that CaseRun, updated
exact streaming sufficient statistics and aggregate counters, and released
the CaseRun before continuing. It never materialized a tuple of all 10,000
CaseRuns.

Progress callbacks receive only `(processed_count, total_count)`. They do not
receive outcomes, metrics, classifications, paired differences, timings, or
report fragments.

## Semantic and timing separation

Each case produces two compact records:

- The semantic record contains the case identity, normalized scenario and
  assessment tuples, a shared-admission digest, all nine normalized method
  records, complete method-result digests, quantities, payments, statuses,
  latent diagnostics, and the ten frozen non-latency observations. It contains
  no observational timing.
- The timing record contains only the seed, case digest, all nine methods in
  baseline enum order, and their nonnegative elapsed nanoseconds. It contains
  no economic metric, scenario classification, or result digest.

Semantic reproducibility is defined by the uncompressed canonical semantic
transport and its semantic raw-evidence root. Timing is observational and
environment-sensitive even though its JSON transport and timing root are
canonical.

The result digest covers the complete frozen
`AgentMarketBenchMethodResultV1`: method, market, status, complete admission,
quantities, payment, winner count, and all decision lines. The shared-admission
digest covers the complete frozen `AgentMarketBenchAdmissionV1`. Compaction
requires identical admission evidence across all nine method results.

## Canonical JSON and sharding

Every JSON model record uses `model_dump(mode="json")` followed by:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

The result is UTF-8 with exactly one trailing newline. Records remain in frozen
seed-tuple order; no outcome or scenario sorting is performed after generation.

The exact final output path is:

```text
benchmarks/agentmarketbench_v1/final_holdout_v1/
```

The original protocol required the following complete output, which the
failed attempt did not produce:

```text
semantic/part-00000.jsonl.gz ... semantic/part-00019.jsonl.gz
timing/part-00000.jsonl.gz     ... timing/part-00019.jsonl.gz
summary.json
report.md
run_metadata.json
manifest.json
```

Each semantic and timing shard contains exactly 500 canonical JSONL records.
Shard 0 covers holdout positions 0 through 499 and shard 19 covers positions
9500 through 9999. Python standard-library gzip uses compression level 9,
`mtime=0`, and no payload timestamp or filesystem name. Shards are atomically
published from temporary sibling files.

Every shard records compressed and uncompressed SHA-256 values. The three roots
have distinct frozen meanings:

- `semantic_root_sha256` is compression-independent. It is derived from the
  uncompressed canonical semantic-shard hashes plus deterministic shard
  identity metadata: relative path, line count, first seed, and last seed. It
  is the primary deterministic economic-evidence fingerprint.
- `timing_root_sha256` is likewise compression-independent and derived from the
  uncompressed canonical timing-shard hashes plus the same deterministic shard
  identity metadata. It still naturally changes when observational
  `elapsed_ns` contents change.
- `evidence_root_sha256` is the exact stored-transport root over all 43
  non-manifest evidence files. It includes stored-file hashes, optional
  uncompressed hashes, byte counts, and line counts, so it commits to gzip
  representation and singleton evidence bytes and may be transport- or
  environment-sensitive.

All root inputs are sorted by relative path. `manifest.json` is excluded from
`evidence_root_sha256` to prevent a self-hash cycle. The SHA-256 of the exact
canonical `manifest.json` bytes is a separate manifest transport fingerprint.

## Exact streaming summaries

The streaming accumulator produces the exact frozen 24D
`AgentMarketBenchRunSummaryV1`: all 99 method/metric summaries and all 88
comparator-minus-CLEAR paired summaries. N/A values are excluded and never
imputed as zero. Method sums and counts use exact `Fraction` arithmetic.
Paired sufficient statistics retain exact `n`, `sum(x)`, and `sum(x^2)`.

For `n >= 2`, the inherited 24D descriptive interval is:

```text
mean = sum(x) / n
sample_variance = (sum(x^2) - sum(x)^2 / n) / (n - 1)
standard_error = sqrt(sample_variance / n)
half_width = Decimal("1.95996398454005423552") * standard_error
lower = mean - half_width
upper = mean + half_width
```

All arithmetic before `Decimal` is exact. Decimal evaluation uses precision 80
with `ROUND_HALF_EVEN`; bounds serialize with exactly 12 fractional digits.
Development tests require the first-42 streaming result to equal the frozen
24D tuple-based summary exactly, including N/A pairing and CI serialization.

The final aggregate summary also records exact method-status coverage, standard
case count, all 21 scenario counts, and observed scenario assessment counts.
It does not contain rankings, recommendations, p-values, significance labels,
or an automatic winner.

## Neutral report

The report renderer is frozen before final outcomes are known. It prints all
method status counts, all 99 method metric summaries, all 88 paired summaries,
scenario coverage, scenario assessment counts, version and root identifiers,
and interpretation limits. Difference orientation remains comparator minus
CLEAR even for metrics where lower values are preferable. The renderer does
not interpret a method as best, dominant, or statistically significant.

The interpretation boundary states that results describe only the generated
synthetic distribution; make no general V2 truthfulness or strategy-proofness,
Sybil prevention, collusion prevention, physical-inventory truth, or physical-
fulfillment claim; treat payment correctness as benchmark rule correctness
rather than settlement; keep duplicate financial side effects N/A in this
economic runner; leave runtime provider scenarios out of scope; leave AI-text
scenarios out of scope because AI is not exercised; treat latency as
environment-sensitive; treat normal-approximation intervals as descriptive;
and make no p-value, significance, ranking, or live Razorpay claim.

The historical Week-2 benchmark remains a separate artifact and is not run by
this harness.

## Manifest-last completion and verification

`manifest.json` is written last. Its valid presence marks a completed run. It
records the evaluated commit, frozen component versions, exact seed-sequence
digest, 500-case shard size, 20 semantic and 20 timing shards, three singleton
evidence files, all compressed/uncompressed hashes, and all three roots.

Before publishing the manifest, the verifier checks every declared file and
rejects unexpected files; validates compressed bytes, gzip transport,
uncompressed bytes, record counts, canonical JSON, strict models, shard seed
metadata, global seed order, semantic/timing pairing, unique case digests,
exact final count and seed tuple, seed-sequence digest, roots, reconstructed
streaming summary and aggregates, neutral report bytes, run metadata, and all
frozen version fields. It executes no generator, method, oracle, provider, or
payment code.

These checks establish internal transport integrity relative to the supplied
or loaded manifest, canonical encoding, evidence pairing, aggregate and report
reconstruction, and the frozen version, seed, and file contracts. The verifier
is not a signature scheme. External evidence authenticity comes from freezing
and committing the evidence artifacts and recording the manifest SHA-256 and
the Git commit that contains those artifacts.

Run metadata is observational. It records canonical UTC start/completion
timestamps, Python/platform and dependency versions, and the literal clock
name. It contains no hostname, username, absolute path, address, or device
identifier.

## Retirement replaces the original execution instructions

The original 24E-B execution instructions are withdrawn. Attempt #1 stopped
on its invariant failure and its partial directory is preserved. Slice
24E-R1 is the scoped metric repair and permanent retirement; it does not
authorize a second execution of the original partition. A reviewed,
previously unopened replacement and a protocol explicitly binding the
semantic revision are required before further final evaluation.

[Slice 24E-R2 replacement protocol](AGENTMARKETBENCH_REPLACEMENT_FINAL_HOLDOUT_V1.md)
freezes a distinct replacement protocol and output path,
`benchmarks/agentmarketbench_v1/replacement_final_holdout_v1/`. Its seeds are
selected deterministically from the remotely verified R1 repair commit
`a4fc224ba9b10b518753d05237ab7d56d737943b`. R2 does not generate, execute, or
inspect any replacement case; execution remains prohibited until the R2
commit is externally reviewed, pushed, and remotely verified. The historical
original final partition and runner remain permanently retired.
