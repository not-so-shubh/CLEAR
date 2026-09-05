# AgentMarketBench V1 Final-Holdout Evidence

Slice 24E-A freezes the final evidence schema, transport, execution harness,
neutral report renderer, manifest, and verifier before any final-holdout case
is opened. The final cases remain ungenerated, unexecuted, and uninspected in
24E-A. After this slice passes external review, its commit must be remotely
verified before the separate 24E-B execution begins.

The frozen final partition contains exactly 10,000 seeds in tuple order from
`2_000_000_000` through `2_000_009_999`. The final runner accepts no caller-
supplied seed collection. It checks the imported frozen tuple against the
complete expected range before generating a case.

## Evaluated source commit

`evaluated_source_commit` is the exact lowercase 40-hex Git commit whose
generator, methods, oracle, metrics, statistics, and evidence harness are being
evaluated. The CLI requires repository `HEAD` to equal that commit and requires
an entirely clean working tree before any final case can be generated. It does
not require a branch name and never changes Git history.

## One-case-at-a-time execution

The runner processes the frozen seed tuple in order. For each seed it generates
one case, calls the frozen 24D single-case runner once using its real default
`time.perf_counter_ns` clock, compacts that CaseRun, updates exact streaming
sufficient statistics and aggregate counters, and releases the CaseRun before
continuing. It never materializes a tuple of all 10,000 CaseRuns.

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

It contains:

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

## CLI preflight and future 24E-B command

The CLI resolves the repository root with `git rev-parse --show-toplevel` and,
before any final generation, requires an exact lowercase expected commit, exact
`HEAD` equality, an empty `git status --porcelain`, and absence of the frozen
output path.

**DO NOT RUN THIS COMMAND UNTIL 24E-A HAS PASSED EXTERNAL REVIEW AND THE
24E-A COMMIT HAS BEEN REMOTELY VERIFIED.**

```bash
python -m clear_market.agentmarketbench.final_holdout \
  --expected-source-commit <24E-A-COMMIT-SHA>
```

After the final holdout is opened in 24E-B, source, evidence schemas, economic
methods, metrics, and statistical rules must not be modified or tuned.

## Final-run failure policy

Once the 24E-B final command has generated the first final-holdout case, any
exception means STOP. Preserve the partial output directory exactly as left;
do not delete it, retry automatically, or modify source, schemas, metrics, or
statistics. Return to the external reviewer before any decision about a second
execution. This is an operational evidence rule, not an automatic recovery or
resume feature.
