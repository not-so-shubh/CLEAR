# CLEAR Architecture

## Slice 0 status

This document reserves CLEAR's Week-2 architectural boundaries. Slice 0 establishes only the
package, tooling, and documentation foundation. It introduces no financial or market-domain code
and no persistence.

## Pure domain logic and stateful infrastructure

The Week-2 architecture separates pure domain logic from stateful infrastructure so economic
results can be reproduced and checked without hidden process state.

Pure domain logic will contain:

- immutable/value-oriented domain schemas;
- money arithmetic;
- canonical representation;
- hashing and signature verification;
- production allocation and payment computation;
- oracle/reference computation; and
- certificate replay and verification.

Stateful infrastructure will contain:

- market lifecycle;
- bid repository and admission state;
- replay registry; and
- a later event ledger.

No persistence is introduced in Slice 0. Persistence added in a later slice must remain outside
pure allocation and oracle logic so stored state cannot silently alter an economic computation.

## Reserved future package boundaries

These boundaries are frozen for Week 2 but are **to be implemented in later slices**. Slice 0 does
not create these packages.

- `clear_market.domain`: typed immutable/value-oriented domain schemas and primitive validation.
- `clear_market.canonical`: pure deterministic canonical representation and hashing inputs.
- `clear_market.crypto`: cryptographic primitives only; no market decisions.
- `clear_market.lifecycle`: stateful admission, deadline, duplicate, and replay behavior.
- `clear_market.mechanism`: pure production allocation and payment computation.
- `clear_market.oracle`: independent reference implementation; it must not share winner-selection
  or allocation logic with `clear_market.mechanism`.
- `clear_market.certificate`: certificate construction and independent replay verification.
- `clear_market.benchmark`: deterministic generators, baselines, and evaluation harness.

The boundaries keep cryptographic validity, economic decisions, and state transitions separately
auditable. They also prevent persistence or admission state from becoming an implicit input to
pure computations.

## Production/oracle independence

The production allocator and oracle may share only:

- schemas;
- immutable primitive/value types; and
- unavoidable primitive validation.

They must not share:

- winner selection;
- bid ranking;
- allocation search; or
- mechanism payment-selection logic.

The oracle is an independent check rather than a second entry point into production logic. Any
production/oracle disagreement where their semantics should match is a CI failure.

## Deterministic allocation boundary

Once `MarketSpec` and `BuyerPolicy` are frozen, allocation must never depend on:

- LLM output;
- input list order;
- unordered collection iteration;
- local timezone;
- hidden randomness;
- environment-specific ordering; or
- current-time reads inside pure logic.

These exclusions make identical frozen inputs yield identical, replayable economic results across
processes and environments.
