# Replay conventions (Phase 16)

A replay of a Meta portfolio run must reproduce the original run
exactly. This document defines what "replay" means, what identity a
replay carries, and what has been proven.

## Determinism chain

1. **Data**: frames are fixed inputs; each context's dataset digest
   (`dataset_sha256`, sha256 of the OHLC block) is in the manifest.
2. **Grid**: the rebalance grid is a pure function of the index
   (`rebalance_grid`); its sha256 (`rebalance_schedule_hash`) is in
   the manifest.
3. **Decisions**: `decide_weights(t)` is a pure function of the
   as-of snapshot (stats, regimes, drift — all strictly pre-`t`) plus
   the layer's runtime state. Two fresh layers decide identically
   (pinned).
4. **Execution**: the canonical `PortfolioEngine` is deterministic
   (prior-gate pins); fills, costs, netting and caps are seed-free.

## Restart equivalence (proven)

`test_restart_at_rebalance_reproduces_suffix` proves: a `MetaLayer`
restarted from the runtime state after decision *k* — final weights +
zero reasons + activation (`MetaState`) — reproduces the remaining
decision suffix bit-for-bit. A crashed process can therefore resume
from its last decision without changing the run.

Run identity includes the **sorted book-id order** (it arbitrates
shared-account budget consumption when caps bind — see the audit
register): a rename that reorders books is a NEW run.

## Manifest (every replay carries)

`git_commit`, `engine_version`, `cost_version`, `meta_version`,
`contract_version`, `regime_version`, `drift_version`,
`certification_protocol`, `config_hash`, `random_seed`,
`rebalance_schedule_hash`, per-instrument `dataset_sha256` + explicit
spec echo + conversion, and the `ineligible` journal. Produced by
`MetaPortfolioEngine.manifest()`; pinned by
`test_manifest_echoes_specs_datasets_versions`.

## What must match on a replay

- trades: row-for-row (symbol, strategy, entry/exit time, lots, pnl)
- equity curve: bit-exact
- weight journals: bit-exact (including regime/drift provenance)

## How to verify

Run the same engine twice on the same contexts/config and compare the
`PolicyRun` frames (the metamorphic suite does exactly this for the
transformations; a plain re-run is the identity case).
