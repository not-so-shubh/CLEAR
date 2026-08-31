# CLEAR — Proof-Carrying Market Infrastructure for Autonomous AI Commerce

> AI interprets fuzzy commercial intent; deterministic systems decide which economic agreement
> wins and where the money goes.

Status: **Week-2 correctness core under construction**

See [Architecture](docs/ARCHITECTURE.md) and the normative
[Week-2 contract](docs/WEEK2_CONTRACT.md).

Requires Python `>=3.12,<3.13`.

## Local development

```sh
python -m pip install -e ".[dev]"
```

## Quality gates

```sh
pytest -q
ruff check .
ruff format --check .
mypy src
```
