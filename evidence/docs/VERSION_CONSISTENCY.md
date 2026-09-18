# VERSION CONSISTENCY — Meta Layer contract & implementation versions

Single authoritative statement of every version carrier in the repository,
resolved by the Phase-1 audit of the Meta-production-integration mission.
Rule: **one authoritative Meta contract version; every producer/consumer
references it or explicitly declares compatibility.**

## Authoritative versions

| Authority | Value | Carrier |
|---|---|---|
| **Meta contract** | **1.1.1** | `docs/META_LAYER_CONTRACT.md` header; `docs/DECISIONS.md` ML-9 |
| Meta implementation | 1.0.0 | `META_LAYER_VERSION` in `python/mql5bot/meta_layer.py` |
| Decision journal | 1.0.0 | `DECISION_VERSION` in `meta_layer.py` |
| Allocation file schema | "1" | `ALLOCATION_SCHEMA_VERSION` in `meta_layer.py` (file `body.schema_version`) |
| Engine / cost model | `ENGINE_VERSION` / `COST_MODEL_VERSION` | `meta_layer.py` module constants |
| Regime labeller | as-of labeller v1 (`meta_replay.regime_labels`) | research only |

Contract ≠ implementation version on purpose: the contract changed twice
(1.0.0 → 1.1.0 → 1.1.1, DECISIONS ML-1..ML-9); the implementation
(`META_LAYER_VERSION = 1.0.0`) tracks its own code lifecycle and is pinned
by its own tests. Changing the contract does not change the implementation
version unless implementation code changes.

## Carrier registry (Phase-1 sweep results)

| Location | Says | Status |
|---|---|---|
| `docs/META_LAYER_CONTRACT.md` header | 1.1.1 | **AUTHORITATIVE** |
| `docs/DECISIONS.md` ML-9 | 1.1.0 → 1.1.1 | authoritative changelog |
| `python/mql5bot/meta_layer.py` `_versions()` | `contract_version: CONTRACT_VERSION (1.1.1)` | **FIXED this phase** (was hard-coded "1.1.0" — journals emitted a stale contract version while implementing 1.1.1 semantics since `0a722f1`) |
| `python/mql5bot/meta_layer.py` module docstring | v1.1.1 | **FIXED this phase** (was 1.1.0) |
| `mql5/Include/Mql5Bot/Allocation.mqh` header | contract 1.1.1 | **FIXED this phase** (was 1.1.0; consumer implements the ML-9 reduce-only seam, which is 1.1.1 semantics) |
| `mql5/Experts/Mql5Bot/Mql5Bot.mq5` (allocation init comment) | contract 1.1.1 | **FIXED this phase** (was 1.1.0; the seam comment at the sizing site already said 1.1.1 — internal contradiction resolved) |
| `python/mql5bot/meta_replay.py` docstring | v1.1.1 | consistent |
| `tests/test_mql5_sources.py`, `tests/test_meta_layer_unit.py` docstrings | v1.1.1 | **FIXED this phase** (comments only) |
| Historical changelog mentions of 1.1.0 in DECISIONS.md / contract changelog / SEMANTICS_REVIEW | 1.1.0 as *history* | correct as-is (changelog, not a live reference) |

## Compatibility trace (not a string update)

1. **What 1.1.0 → 1.1.1 changed:** §5.2 clarification only (DECISIONS
   ML-9) — the Meta Layer owns allocation budgets; daily-loss and
   drawdown-kill-switch remain Risk-Engine authorities. No wire format
   change, no weight-arithmetic change, no new field.
2. **Python producer:** implements the clarified authority split
   (exposure clamp reduces weights/size only; never touches risk state)
   — verified by `tests/test_meta_risk_invariants.py` structural pins.
   Its only inconsistency was the *declared* contract version in
   `_versions()`; corrected to 1.1.1. Effect on artifacts: decision
   journals and `versions()` blocks from now on record
   `contract_version: 1.1.1`. Readers never *gate* on `contract_version`
   (they gate on `decision_version` and `body.schema_version` — verified
   by reading `read_allocation_file` / decision load paths), so the fix
   is journal-compatible; old journals remain readable.
3. **MQL5 consumer (`Allocation.mqh`):** parses `body.schema_version`
   ("1") and `digest` — it does not branch on a contract version field
   at all, so the header comment correction is documentation-only. The
   consumer's behavior (reduce-only scale, floor-and-drop, stale → base
   gate) is the 1.1.1 semantics per the EA seam in `Mql5Bot.mq5`.
4. **Allocation file schema** is independent of the contract version
   (`schema_version: "1"` unchanged) — no consumer break.

## Enforcement

`tests/test_docs_consistency.py` fails the build when: the contract
header version, the Python `CONTRACT_VERSION`, the `Allocation.mqh`
header version, or the `Mql5Bot.mq5` references disagree; when the
implementation exists while the contract claims "CONTRACT ONLY"; or when
the contract lacks the lifecycle status line.
