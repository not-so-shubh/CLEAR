# CLEAR Reproducibility

## Environment

CLEAR requires Python `>=3.12,<3.13`. Install the project and its declared development dependencies with:

```sh
python -m pip install -e ".[dev]"
```

## Normal verification

From the repository root, run:

```sh
python -m pip install -e ".[dev]"
python -m pip check
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q
PYTHONHASHSEED=1 python -m pytest -q
```

The ordinary test suite validates the frozen report snapshot but does not execute the frozen 10,000-market benchmark.

## Frozen evaluation evidence

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

Observed:

- 24,990 admission attempts
- 0 admission rejections
- 6,271 feasible markets
- 3,729 infeasible markets
- 0 differential mismatches
- 0 budget violations
- 0 allocation-quantity violations
- 0 winner-evidence violations
- 0 hard failures
- 0 failed markets

The frozen evaluation demonstrates that, for the exact deterministic-market-generator-v1 distribution over the 10,000 frozen seeds with five sellers, the production allocator agreed with the independent oracle on all frozen differential fields and the runner observed zero defined hard invariant failures.

Verify the report bytes using only the Python standard library:

```sh
python - <<'PY'
import hashlib
from pathlib import Path

path = Path("benchmarks/frozen_evaluation_report_v1.json")
expected = "d63d4217486daf9ca1cc4840bbcd091b5589507cfa376a232eb61fc08ed7e2fe"
actual = hashlib.sha256(path.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit(f"SHA-256 mismatch: expected {expected}, got {actual}")
print(actual)
PY
```

## Optional historical evaluation replay

This optional procedure reproduces the frozen run from the exact evaluated source revision. It was not executed while creating this guide. From the current repository root, create an isolated detached worktree:

```sh
git worktree add --detach ../CLEAR-frozen-eval 67f1f6f772e52d9207a6555e403a9edb53e7bf63
cd ../CLEAR-frozen-eval
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python - <<'PY'
import json
from pathlib import Path

from clear_market.benchmark import (
    FROZEN_EVALUATION_SEEDS,
    run_differential_benchmark,
)

report = run_differential_benchmark(
    FROZEN_EVALUATION_SEEDS,
    seller_count=5,
)
serialized = (
    json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n"
)
Path("/tmp/clear_frozen_evaluation_replay.json").write_text(serialized, encoding="utf-8")
print(serialized, end="")
PY
.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path

path = Path("/tmp/clear_frozen_evaluation_replay.json")
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
```

The expected replay SHA-256 is `d63d4217486daf9ca1cc4840bbcd091b5589507cfa376a232eb61fc08ed7e2fe`. Matching it demonstrates byte-for-byte reproduction of the frozen report transport under the committed runner/generator contract.

After reviewing the output, remove the isolated worktree:

```sh
cd -
git worktree remove ../CLEAR-frozen-eval
```

## Interpretation limits

This does not prove correctness outside the tested generator distribution, and it does not establish collusion resistance, Sybil resistance, fulfillment correctness, or broader strategy-proofness.

The evaluation concerns the exact evaluated source commit recorded above. Later test, CI, and documentation commits do not retroactively change the frozen evaluation result. The normal CI suite verifies the evidence artifact but does not rerun the frozen benchmark.
