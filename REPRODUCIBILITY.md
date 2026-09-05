# CLEAR Reproducibility

## Environment

CLEAR requires Python `>=3.12,<3.13`. Create an isolated environment and install the declared
development dependencies:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Normal verification

Run these commands from the repository root. Each repository-wide command explicitly excludes the
protected original holdout path.

```sh
.venv/bin/python -m pip check
.venv/bin/python -m ruff check . \
  --exclude benchmarks/agentmarketbench_v1/final_holdout_v1
.venv/bin/python -m ruff format --check . \
  --exclude benchmarks/agentmarketbench_v1/final_holdout_v1
.venv/bin/python -m mypy src
.venv/bin/python -m mypy \
  ui/demo_bootstrap.py ui/judge_demo.py ui/public_demo.py
.venv/bin/python -m pytest -q \
  --ignore=benchmarks/agentmarketbench_v1/final_holdout_v1
PYTHONHASHSEED=1 .venv/bin/python -m pytest -q \
  --ignore=benchmarks/agentmarketbench_v1/final_holdout_v1
```

These tests validate committed evidence and application behavior. They do not regenerate or run a
final holdout.

## Historical deterministic differential evaluation

- Evaluated source commit: `67f1f6f772e52d9207a6555e403a9edb53e7bf63`
- Evidence freeze commit: `97e1113520f08b645885e3e6aa46d72eab5caaab`
- Frozen report: `benchmarks/frozen_evaluation_report_v1.json`
- Evidence manifest: `benchmarks/frozen_evaluation_manifest_v1.json`
- Report SHA-256: `d63d4217486daf9ca1cc4840bbcd091b5589507cfa376a232eb61fc08ed7e2fe`
- Generator: `deterministic-market-generator-v1`
- Runner: `differential-benchmark-runner-v1`
- Seller count: 5
- Frozen market count: 10,000
- Seed-sequence SHA-256: `75e00e23b222fe03242ac7d115909c0a12abc50ba10844337ec9d0ea4dd507f2`
- Reproducibility fingerprint: `89cb65d3accaba76d90a1c6091503480ab6c3edeabf8e863613e86c9d2703867`

This is the earlier `deterministic-market-generator-v1` differential evaluation. It is not the
AgentMarketBench comparator report. Its 10,000 frozen seeds recorded:

- 24,990 admission attempts;
- 6,271 feasible and 3,729 infeasible markets;
- zero admission rejections, differential mismatches, budget violations, allocation-quantity
  violations, winner-evidence violations, hard failures, or failed markets.

For the exact deterministic generator distribution over 10,000 frozen seeds with five sellers, the
production allocator agreed with the independent oracle on every frozen differential field. The
runner observed none of its defined hard invariant failures.

Verify the committed report bytes without regenerating benchmark data:

```sh
.venv/bin/python - <<'PY'
from hashlib import sha256
from pathlib import Path

report = Path("benchmarks/frozen_evaluation_report_v1.json")
print(f"{sha256(report.read_bytes()).hexdigest()}  {report}")
PY
```

Expected output:

```text
d63d4217486daf9ca1cc4840bbcd091b5589507cfa376a232eb61fc08ed7e2fe  benchmarks/frozen_evaluation_report_v1.json
```

## Final AgentMarketBench replacement evaluation

The final judge-facing comparator evidence is
`docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md`:

- Evaluated source commit: `6eadd5b6eb737649ec35747a73d90b69c403e24f`
- Final cases: 10,000
- Manifest SHA-256: `27c8cc724634caec4a587a52e5687b76fefb47500b8261244cf3762bb7099c3a`
- Evidence root SHA-256: `9b9d3fd24d0efe0fed26cdaf63fc5ff6ff4b843ad8061d70c09232c021500c51`

This replacement evaluation is permanently closed. **DO NOT RERUN IT.** The committed results
document reports the stored comparison metrics and provenance; it is not an instruction to open or
regenerate either final holdout.

## Interpretation limits

Each artifact applies only to its recorded source revision, data-generation protocol, and frozen
cases. Neither proves correctness outside its distribution, collusion resistance, Sybil resistance,
fulfillment correctness, or broader strategy-proofness. The full-information oracle is a latent
upper bound, not a deployable method. Later code, tests, and documentation do not retroactively
change either frozen result.

The [replacement final results](docs/AGENTMARKETBENCH_REPLACEMENT_FINAL_RESULTS_V1.md) contain the
benchmark comparison, paired descriptive intervals, manipulation observations, and other measured
limitations.
