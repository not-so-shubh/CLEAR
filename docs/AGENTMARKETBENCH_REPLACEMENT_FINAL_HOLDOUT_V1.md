# AgentMarketBench V1 Replacement Final-Holdout Protocol

## Pre-holdout freeze and execution gate

Slice 24E-R2 does not generate, execute, or inspect any replacement case.
It freezes the selection commitment, evidence models, writer, verifier,
preflight, runner, and CLI after the R1 repair and before opening even one
replacement case. The only permitted operations over replacement seeds in
R2 are constructing or inspecting the integer tuple, range and disjointness
checks, and seed-sequence hashing. No replacement scenario, catalog,
inventory, allocation, oracle output, metric, case digest, or result may be
generated, inspected, estimated, or compared during this slice.

**DO NOT RUN the replacement holdout until the R2 source commit is externally
reviewed, pushed, and remotely verified.** The command below is a template
for a future authorized execution. The R1 selection anchor is already
committed, pushed, externally reviewed, and remotely verified; it is not the
future R2 evaluated source commit.

## Incident lineage and permanent partition boundaries

The [historical original final holdout](AGENTMARKETBENCH_FINAL_HOLDOUT_V1.md)
was opened once from source commit
`93073144db6128d7e23558545e5d544e350ad292`. Attempt #1 persisted exactly
3,000 cases covering `2_000_000_000 .. 2_000_002_999`, as six semantic and
six timing shards of 500 cases each. It then stopped on the invariant
`ValueError("method welfare exceeds full-information oracle welfare")`
before a seventh shard was published. No completed summary, report, run
metadata, or manifest was produced.

R1 repaired a benchmark metric feasibility-domain mismatch at commit
`a4fc224ba9b10b518753d05237ab7d56d737943b`. Minimum-qualified benchmark
welfare is zero when latent-valid realized quantity is below the buyer's
minimum acceptable quantity, and raw realized welfare otherwise. Raw
realization diagnostics remain raw. R2 does not alter that repair, the
generator, methods, oracle, statistics, or historical evidence schemas.

| Partition | Inclusive range | Permanent status |
|:---|:---|:---|
| Frozen development | `100_000_000 .. 100_001_007` | Allowed for test fixtures |
| Diagnostic quarantine | `500_000_000 .. 500_020_999` | Excluded from every final or replacement holdout; only already-authorized diagnostic regression work is allowed |
| Retired original final | `2_000_000_000 .. 2_000_009_999` | Permanently retired in its entirety; never generate another seed from this partition |
| Replacement final | `1_641_790_000 .. 1_641_799_999` | Frozen here and unopened throughout R2 |

The original `run_agent_market_bench_final_holdout_v1` remains permanently
retired. Its source and the historical `final_evidence.py` remain unchanged.
The original partial directory,
`benchmarks/agentmarketbench_v1/final_holdout_v1/`, must remain byte-for-byte
unchanged. Do not add, rename, rewrite, delete, or stage its evidence files.
Its 3,000 cases are excluded from every replacement final aggregate. No
conclusion may combine partial attempt #1 with replacement results.

## Deterministic selection commitment

The selection was made after R1 was remotely frozen and before any case from
the replacement partition was generated or inspected. The selection version
is `agent-market-bench-replacement-holdout-selection-v1`, and its anchor is
`a4fc224ba9b10b518753d05237ab7d56d737943b`.

The exact selection preimage is the following ASCII text, **with no trailing
newline**:

```text
CLEAR|AgentMarketBench|replacement-holdout-v1|a4fc224ba9b10b518753d05237ab7d56d737943b
```

Its SHA-256 is:

```text
babe2f63fe83fa6a67a63d0fc02c16a2a4cfcfc2fe04e4aa94a0e0af29b655f3
```

The safe block space has `base = 1_400_000_000`, `block_size = 10_000`, and
`block_count = 40_000`. It covers `1_400_000_000 .. 1_799_999_999`. This
interval was chosen only because it is below `MAX_AGENT_MARKET_BENCH_SEED`,
far from development and the permanent quarantine, and disjoint from the
retired original final partition. No benchmark outcomes informed selection.

```python
block_index = int(selection_sha256, 16) % 40_000  # Entire 256-bit digest.
# block_index == 24_179
start = 1_400_000_000 + 24_179 * 10_000
# start == 1_641_790_000
seeds = tuple(range(1_641_790_000, 1_641_800_000))
```

The replacement tuple is exactly 10,000 consecutive integers in ascending
order, starting at `1_641_790_000` and ending at `1_641_799_999` inclusive.
It has zero intersection with the development tuple, the entire quarantine,
and the entire retired original final tuple.

The frozen V1 seed-sequence rule concatenates `ASCII(seed) + "\n"` for every
seed in tuple order, including a newline after the last seed. Its SHA-256 is:

```text
9f255e0668f40a0b61a0ec79b5c25fac5682b5e374ee19cf854615c68187c422
```

The exported constants in `seeds.py` are:

- `AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION`
- `AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1`
- `AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1`
- `AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1`
- `AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1`
- `AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1`

The historical development and original-final constants retain their exact
names and tuple values. Selection and seed-sequence tests independently
recompute the literals above without invoking the case generator.

## Evidence versions and strict model bindings

The existing observation/schema family remains
`agent-market-bench-metrics-v1`. The corrected metric semantic revision is
exactly `agent-market-bench-metric-semantics-v1.1`. These identifiers have
different roles; the replacement summary, run metadata, and manifest each
explicitly bind the corrected semantic revision.

| Replacement version constant | Exact value |
|:---|:---|
| `AGENT_MARKET_BENCH_REPLACEMENT_FINAL_EVIDENCE_V1_VERSION` | `agent-market-bench-replacement-final-evidence-v1` |
| `AGENT_MARKET_BENCH_REPLACEMENT_FINAL_SUMMARY_V1_VERSION` | `agent-market-bench-replacement-final-summary-v1` |
| `AGENT_MARKET_BENCH_REPLACEMENT_FINAL_MANIFEST_V1_VERSION` | `agent-market-bench-replacement-final-manifest-v1` |
| `AGENT_MARKET_BENCH_REPLACEMENT_FINAL_RUN_METADATA_V1_VERSION` | `agent-market-bench-replacement-final-run-metadata-v1` |

The three appended replacement models are
`AgentMarketBenchReplacementFinalSummaryV1`,
`AgentMarketBenchReplacementFinalRunMetadataV1`, and
`AgentMarketBenchReplacementFinalManifestV1`. They use `schema_version = "1"`,
their replacement-specific version fields, strict frozen validation,
forbidden extra fields, and fresh validation of supplied model instances.
Historical final model definitions and behavior remain unchanged.

The model version fields are respectively
`agent_market_bench_replacement_final_summary_version`,
`agent_market_bench_replacement_final_run_metadata_version`, and
`agent_market_bench_replacement_final_manifest_version`. The manifest's
`evidence_version` is `agent-market-bench-replacement-final-evidence-v1`.

The replacement reuses `AgentMarketBenchFinalSemanticRecordV1`,
`AgentMarketBenchFinalTimingRecordV1`, and
`AgentMarketBenchFinalEvidenceFileV1`; it introduces no renamed semantic or
timing record schema.

| Binding | Summary | Report | Run metadata | Manifest |
|:---|:---:|:---:|:---:|:---:|
| Evaluated source commit | Yes | Yes | Yes | Yes |
| Metric semantic revision v1.1 | Yes | Yes | Yes | Yes |
| Selection version, anchor commit, SHA-256 | Yes | Yes | Yes | Yes |
| Replacement seed-sequence SHA-256 | Yes | Yes | No field | Yes |
| Final case count | Yes | Yes | No field | Yes |
| Semantic and timing roots | No field | Yes | No field | Yes |
| Stored-transport evidence root | No field | No field | No field | Yes |

Every evaluated source commit is an exact lowercase 40-hex Git commit. All
three replacement models bind the selection version, exact R1 anchor, and
selection digest above. The verifier requires matching evaluated source
commits and bindings throughout the completed evidence. Their shared binding
fields are `evaluated_source_commit`, `metric_semantics_version`,
`selection_version`, `selection_anchor_commit`, and `selection_sha256`.

The summary additionally contains `case_count`, `standard_case_count`,
`method_status_counts`, `scenario_counts`, `scenario_assessment_counts`, and
`run_summary`. It preserves the historical strict count and coverage
validation and requires `run_summary.case_count == case_count`. It contains
no winner, rank, p-value, or significance field.

Run metadata contains `started_at_utc`, `completed_at_utc`, `python_version`,
`platform_system`, `platform_machine`, `pydantic_version`, `ortools_version`,
`cryptography_version`, and `clock_name = "time.perf_counter_ns"`, using
equivalent historical timestamp and text validation. It records no hostname,
username, absolute repository path, IP or network identifier, device serial,
or environment variable.

The manifest also binds these unchanged component versions:

| Field | Exact value |
|:---|:---|
| `generator_version` | `agent-market-bench-generator-v1` |
| `runner_version` | `agent-market-bench-runner-v1` |
| `metrics_version` | `agent-market-bench-metrics-v1` |
| `statistics_version` | `agent-market-bench-statistics-v1` |
| `semantic_record_version` | `agent-market-bench-final-semantic-record-v1` |
| `timing_record_version` | `agent-market-bench-final-timing-record-v1` |

A completed manifest requires `case_count = 10_000`, the exact replacement
first and last seeds and sequence digest, `shard_size = 500`,
`semantic_shard_count = 20`, `timing_shard_count = 20`, all three roots, and
the exact 43 non-manifest evidence entries described below.

## Fixed output, canonical records, and publication order

The real replacement output path is exactly:

```text
benchmarks/agentmarketbench_v1/replacement_final_holdout_v1/
```

It must not already exist. The runner resolves the repository root internally
and exposes no output-directory option. It must never reuse the preserved
original partial directory.

`AgentMarketBenchReplacementFinalEvidenceWriterV1` receives an output
directory and evaluated source commit, with no caller-supplied final seed
tuple. Its production seed source and seed digest are the frozen replacement
constants. It requires exact tuple order, processes one CaseRun at a time,
and publishes paired shards of exactly 500 cases:

```text
semantic/part-00000.jsonl.gz ... semantic/part-00019.jsonl.gz
timing/part-00000.jsonl.gz   ... timing/part-00019.jsonl.gz
summary.json
report.md
run_metadata.json
manifest.json
```

The singleton summary, report, and run metadata follow the shards.
`manifest.json` is published last, after stored-evidence verification.
A completed directory contains exactly 44 files: 20 semantic shards,
20 timing shards, three singleton evidence files, and the manifest. Each
completed shard contains exactly 500 JSONL records. A partial directory
cannot serve as completed evidence.

Each record uses the public frozen canonical JSON primitive: obtain
`model_dump(mode="json")`, then encode the following as UTF-8 with exactly
one trailing newline:

```python
json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

Records remain in frozen seed order. Semantic records contain economic and
scenario evidence without observational timing; timing records contain the
matching seed, case digest, and per-method elapsed nanoseconds. Compaction
and the semantic/timing record schemas retain their historical meanings.

Gzip uses the Python standard library, `compresslevel=9`, `mtime=0`, and
`filename=""`. File publication is atomic through temporary sibling files,
with equivalent historical flush/fsync and replacement behavior. The
replacement module uses public frozen canonicalization, seed hashing, root
hashing, compaction, and streaming-accumulator primitives. Any necessary
atomic-write, gzip, and load helpers are private to the replacement module;
it does not import historical private helpers or classes.

## Frozen content and transport root definitions

All root payloads are ASCII and sort file entries by `relative_path`.
For semantic shards only, and separately for timing shards only, concatenate
the following for each entry and SHA-256 the entire payload:

```text
relative_path + "\0" + uncompressed_sha256 + "\0"
+ decimal(line_count) + "\0" + decimal(first_seed) + "\0"
+ decimal(last_seed) + "\n"
```

These are `semantic_root_sha256` and `timing_root_sha256`. They are independent
of compressed gzip representation. Semantic content is deterministic; timing
content remains observational and environment-sensitive.

For `evidence_root_sha256`, concatenate the following for every one of the
43 non-manifest evidence entries and SHA-256 the entire payload:

```text
relative_path + "\0" + sha256 + "\0"
+ (uncompressed_sha256 or "") + "\0"
+ decimal(byte_count) + "\0" + decimal(line_count) + "\n"
```

Here `sha256` and `byte_count` describe exact stored bytes. This root binds
compressed transport identity and singleton file bytes. These are the
unchanged public historical V1 root definitions. `manifest.json` is excluded
from the evidence root to avoid a self-hash cycle. SHA-256 of its exact
canonical bytes is a separate manifest transport fingerprint.

## Exact summaries and deterministic neutral report

The existing `AgentMarketBenchFinalStreamingAccumulatorV1` builds the exact
historical counts and `AgentMarketBenchRunSummaryV1`; those values are wrapped
in `AgentMarketBenchReplacementFinalSummaryV1` with the explicit source,
semantic, and selection bindings. Statistics and scenario counting are
unchanged. N/A observations remain excluded, with no zero imputation.
Method summaries use exact `Fraction` arithmetic; paired summaries retain
exact `n`, `sum(x)`, and `sum(x^2)`. Difference orientation is always
comparator minus CLEAR.

The inherited descriptive normal-approximation 95% interval, for `n >= 2`,
uses sample variance `(sum(x^2) - sum(x)^2 / n) / (n - 1)`, standard error
`sqrt(sample_variance / n)`, and multiplier `1.95996398454005423552`.
Decimal evaluation retains precision 80, `ROUND_HALF_EVEN`, and exactly
12 fractional digits for bounds. There are no p-values, significance labels,
rankings, or automatic winner.

`render_agent_market_bench_replacement_final_report_v1(...)` is deterministic
and begins with `# AgentMarketBench V1 Replacement Final Holdout`. It shows
the evaluated source commit; generator, runner, metrics schema-family,
metric semantic revision, and statistics versions; selection version,
anchor, and SHA-256; replacement seed-sequence SHA-256; semantic and timing
roots; and final case count. Its neutral tables retain method status counts,
all 99 method metric summaries, all 88 paired comparator-minus-CLEAR
summaries, scenario coverage, and scenario assessment counts. It does not
recommend CLEAR. Its interpretation limits are frozen below.

## Preserved failed-attempt forensic whitelist

The following exact 12 files must exist relative to
`benchmarks/agentmarketbench_v1/final_holdout_v1/`. Hashes are SHA-256 of
the stored compressed bytes. No other file may exist under this directory.

| Relative path | SHA-256 | Bytes |
|:---|:---|---:|
| `semantic/part-00000.jsonl.gz` | `469721352e81bcf09e5a3aab9b6fccf64b12157c432272735262b8214a51002c` | 513713 |
| `semantic/part-00001.jsonl.gz` | `504193f372eba4afd5ff3edceb7809d354d92a909619ff6d4e13de6b2611d938` | 514291 |
| `semantic/part-00002.jsonl.gz` | `a2a1c6de06c42211f477e1a9ec4daec4120b5fd03239aedf7d9ac5e0c67f0540` | 508694 |
| `semantic/part-00003.jsonl.gz` | `1339a3d8d5df8566a4cd05316436221828e58d07bbb6057724d9001efb8ffd04` | 512863 |
| `semantic/part-00004.jsonl.gz` | `76f5a336d888211c949523f69d6a0cb1d622c6c28774d9df54693e9bf2d9c92c` | 506889 |
| `semantic/part-00005.jsonl.gz` | `b408f738feaf584d04432c4f63bdf58140e98f44f5374d311be8ffd7734d062f` | 513877 |
| `timing/part-00000.jsonl.gz` | `cc9642aa0b91834fd286123f973261b15ff6643e7c734bc50f62925049ab184f` | 47582 |
| `timing/part-00001.jsonl.gz` | `eabcd03f7dd2bef2af51c162710ebf8fe07b3e5c862a9ab6e9b9b3a49dcfd0bc` | 47687 |
| `timing/part-00002.jsonl.gz` | `1f949487a7a2bce4f97caad49944357568bd308c60a989448b80539ed4cd6e86` | 47669 |
| `timing/part-00003.jsonl.gz` | `909e53548b68a952c69c723f7802532368aa6415b3a444cfecf252ca35439453` | 47646 |
| `timing/part-00004.jsonl.gz` | `d6d1a111188344087be5abbdbf058c1255d32e199933b1dc8bc86bbafc4a53a5` | 47619 |
| `timing/part-00005.jsonl.gz` | `913a24de24ba04aa9f203e22a1415d44959122b1605816464cc3198b68d73205` | 47723 |

Preflight independently checks both size and hash for all 12 files and
rejects a missing file, changed hash, changed byte count, or any extra file.
R2 records path, hash, and byte count before edits and recomputes them after
the test matrix. BEFORE must equal AFTER exactly; any difference requires
STOP. Preservation checks never rewrite the files or generate their cases.

## Git and selection preflight

The production API is:

```python
run_agent_market_bench_replacement_final_holdout_v1(
    *,
    expected_source_commit: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> AgentMarketBenchReplacementFinalManifestV1
```

There is no caller seed argument and no output-directory argument. Before
output-directory creation, writer construction, seed iteration, or case
generation, preflight requires all of the following:

1. `expected_source_commit` is an exact lowercase 40-hex commit.
2. The internally resolved current repository root is a Git repository root.
3. `git rev-parse HEAD` equals `expected_source_commit`.
4. Selection anchor `a4fc224ba9b10b518753d05237ab7d56d737943b` is an ancestor
   of HEAD.
5. The tracked working tree and index are clean, using an equivalent of
   `git status --porcelain --untracked-files=no` with empty output.
6. Recursive untracked enumeration equivalent to
   `git ls-files --others --exclude-standard -z` yields exactly the 12
   repository-relative paths formed by prepending
   `benchmarks/agentmarketbench_v1/final_holdout_v1/` to the whitelist.
   No unrelated untracked file, patch, editor temporary file, or other
   benchmark artifact is allowed. Plain global `git status --porcelain`
   need not be empty because the preserved 12 shards are intentionally
   untracked.
7. Independent size and SHA-256 checks match the forensic whitelist exactly,
   with no extra file under the failed-attempt directory.
8. `benchmarks/agentmarketbench_v1/replacement_final_holdout_v1/` does not
   exist.
9. The frozen replacement tuple equals
   `tuple(range(1_641_790_000, 1_641_800_000))` exactly.
10. The seed-sequence digest equals
    `9f255e0668f40a0b61a0ec79b5c25fac5682b5e374ee19cf854615c68187c422`.
11. The selection preimage, full SHA-256, block index, and derived start
    recompute exactly from the frozen constants above.

A failed preflight creates no output directory and invokes no writer or
generator. Only after every check passes may the writer create the output
path and the runner generate the first replacement case. External review,
push, and remote verification are required before execution; local Git
preflight does not establish those external facts.

## Future execution command and fixed orchestration

**DO NOT RUN this template during R2.** Use the exact externally reviewed,
pushed, and remotely verified R2 commit as `<R2-COMMIT-SHA>` in a future
authorized execution:

```sh
python -m clear_market.agentmarketbench.replacement_final_holdout \
  --expected-source-commit <R2-COMMIT-SHA>
```

There is no CLI output-directory option. After successful preflight, the
runner visits every frozen replacement seed in tuple order, generates exactly
one case, calls the frozen `run_agent_market_bench_case_v1` once using the
real default `time.perf_counter_ns` timing path, adds exactly one CaseRun to
the replacement writer, and releases it before continuing. It never
materializes all 10,000 CaseRuns. It provides no alternate seeds, skipped
seeds, resume, retry, parallel generation, or wall-clock-timeout accepted
result.

The progress callback receives only `(processed_count, 10_000)`. The CLI
emits observational progress after every completed 500-case shard. On
success it prints these concise labels, with the computed values:

```text
case_count=10000
output_dir=benchmarks/agentmarketbench_v1/replacement_final_holdout_v1
semantic_root_sha256=<semantic root>
timing_root_sha256=<timing root>
evidence_root_sha256=<stored-transport root>
manifest_sha256=<SHA-256 of canonical manifest bytes>
```

It prints no winner, interpretation, ranking, or p-value. A failed preflight
exits nonzero.

## Failure policy: stop and preserve

**Once the first replacement case has been generated, ANY exception means
STOP.** Preserve the partial replacement directory exactly as left. Do not
delete it, clean it up, auto-retry, resume, skip a failing seed, change source,
change schema, change metrics, change statistics, or choose another
replacement partition. Return to the external reviewer before any second
execution decision. No resume or retry code is part of this protocol.

During R2, accidentally generating a replacement seed, changing any
failed-attempt byte, obtaining a different selection derivation, failing a
required invariant, or changing an unauthorized file likewise requires STOP
and reporting instead of improvising. The original final holdout and
historical Week-2 benchmark must not be run.

## Stored-evidence verification

The public verifier API is:

```python
verify_agent_market_bench_replacement_final_evidence_v1(
    output_dir: Path,
    *,
    expected_manifest: AgentMarketBenchReplacementFinalManifestV1 | None = None,
) -> AgentMarketBenchReplacementFinalManifestV1
```

After a future completed execution, verify stored evidence from the
repository root as follows:

```python
from pathlib import Path

from clear_market.agentmarketbench.replacement_final_evidence import (
    verify_agent_market_bench_replacement_final_evidence_v1,
)

manifest = verify_agent_market_bench_replacement_final_evidence_v1(
    Path("benchmarks/agentmarketbench_v1/replacement_final_holdout_v1")
)
```

An externally retained expected replacement manifest can be supplied via
`expected_manifest=`. Verification reads stored evidence only: it generates
no cases, runs no methods or oracle, and calls no payment code, AI, or
network service. R2 uses development or handcrafted fixtures for verifier
tests; it does not verify or inspect real replacement cases.

Verification requires the exact completed 44-file inventory and rejects:

- Missing or extra files, wrong shard paths, and reordered or gapped shard
  indexes.
- Seed gaps, duplicates, reordering, wrong first or last seed, any sequence
  differing from the frozen replacement tuple, or a wrong sequence digest.
- Wrong selection version, anchor, or digest; wrong semantic revision; or
  inconsistent evaluated source commits across manifest, summary, and
  metadata.
- Wrong compressed or uncompressed hashes, sizes or record counts, corrupted
  gzip, noncanonical JSONL, invalid strict models, or wrong content and
  evidence roots.
- Semantic/timing seed or case-digest mismatches.
- A summary differing from exact streaming reconstruction, report bytes
  differing from the deterministic renderer, or mismatched run metadata.

The verifier reconstructs all summary counts and run statistics using the
existing streaming accumulator over compact semantic/timing records, with
zero benchmark execution. These checks establish stored transport integrity,
canonical encoding, pairing, aggregation, and frozen version/selection/file
contracts. They are not a signature scheme; external provenance also depends
on the reviewed source and separately retained manifest fingerprint and
artifact record.

## Interpretation limits

The deterministic report must state all of the following:

- Results describe the generated synthetic distribution only.
- Results are replacement evidence only. The original failed 3,000-case
  partial attempt is excluded from the final aggregate, and no conclusion
  may combine partial attempt #1 with replacement results.
- Metric semantic revision v1.1 uses minimum-qualified benchmark welfare
  while raw realization diagnostics remain raw.
- There is no general V2 strategy-proofness or truthfulness claim.
- There is no Sybil-proof or collusion-proof claim.
- There is no physical inventory truth claim or physical fulfillment proof.
- Benchmark payment correctness does not establish settlement correctness.
- Runtime financial scenarios remain out of scope in this economic runner;
  duplicate financial side effects remain N/A.
- AI-text scenarios remain out of scope because AI is not exercised.
- Latency is observational and environment-sensitive.
- Normal-approximation 95% confidence intervals are descriptive only.
- There are no p-values or statistical-significance claims.
- There is no automatic benchmark winner or ranking, or recommendation of
  CLEAR.
- There is no live Razorpay claim.

## R2 validation boundary

Tests may use frozen development CaseRuns, handcrafted models, temporary
files, and monkeypatched functions. A private generic fixture writer may
support development fixtures; the production writer remains bound to the
replacement tuple. Successful orchestration tests substitute a small
development-seed fixture and prove generated seeds are below
`2_000_000_000` and outside the replacement tuple. Failed preflight tests
prove zero generator calls and no output creation. No test may generate an
original-final or replacement case.

The required matrix covers the four focused seed/model/evidence/runner test
files, all AgentMarketBench tests under default, `PYTHONHASHSEED=1`, and
`PYTHONHASHSEED=777`, the full pytest suite, Ruff checks and format checks,
`mypy src`, `pip check`, and `git diff --check`. It also reruns the four
frozen generator goldens, the R1 quarantine reproducer test, and the exact
four disclosed development-change regressions. These use only previously
authorized seeds. The forensic 12-file listing must match before and after
the completed matrix.

R2 changes only its authorized ten-file source, test, and documentation
footprint. It stages, commits, and pushes nothing, and creates no real
replacement output directory. Historical final evidence and runner code,
metric/generator/oracle/statistics code, historical final model definitions,
and the original-final seed tuple remain unchanged.
