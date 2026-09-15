# Development / Contributor Guide

## Repository layout

| Path | Contents |
|---|---|
| `mql5/Experts/Mql5Bot/` | the Expert Advisor |
| `mql5/Include/Mql5Bot/` | MQL5 modules (Config, Session, SignalEngine, RiskManager, TradeManager, PositionGuard, SlGuard, MagicMap, RetryQueue, Allocation, Kill Switch, Logger, Telemetry) |
| `mql5/Scripts/`, `mql5/Presets/` | data-export script, strategy presets |
| `python/mql5bot/` | quant toolkit + AEGIS (factory, discovery, dsl, indicator_universe, api, meta layer, certification, owner_gate) |
| `factory/`, `schemas/` | gates config, strategy JSON schema |
| `examples/strategies/` | example specs (incl. intentionally invalid/unsupported cases) |
| `tools/` | certification & owner tooling (compile.ps1, certify_strategy.py, run_mt5_backtest.*, build_gold*_standard.py, verify_owner_mt5_gate.py, owner_evidence_bind.py, broker_symbol_parity.py) |
| `scripts/install_mql5.py` | EA deployment into the MT5 data folder |
| `tests/` | pytest suite (contract pins live in `test_docs_contract.py`) |
| `artifacts/` | FROZEN evidence: `gold/`, `gold_2/`, `owner_mt5_gate/` |
| `docs/` | canonical docs + human guides + audit records |
| `migrations/`, `alembic.ini` | factory DB migrations |
| `.github/workflows/ci.yml` | CI (Python matrix, ruff, migrations smoke, tests) |

## Canonical vs historical files

- **Canonical (change deliberately, with doc updates):** `SPEC.md`,
  `SYSTEM_INVARIANTS.md`, `STATE_MODEL.md`, `DECISIONS.md`,
  `CERTIFICATION.md`, `MT5_ROUNDTRIP.md`, `KILL_SWITCH.md`,
  `SAFETY_GOVERNANCE.md`, `META_LAYER_CONTRACT.md`, `WFA_CONTRACT.md`.
- **Frozen evidence (never edit):** `artifacts/gold/`,
  `artifacts/gold_2/`, `artifacts/owner_mt5_gate/` templates'
  PENDING_OWNER values, committed audit conclusions.
- **Historical records (attribution, not instructions):** PHASE3 and
  audit documents superseded by later gates.

## Coding standards

- Python ≥3.10 idioms; `from __future__ import annotations` where
  needed; type hints on public functions.
- Lint: `ruff check python tests tools` must stay clean (CI enforces
  `python tests`).
- Tests answer a known defect, contract boundary, safety invariant,
  reconciliation requirement, stale-artifact attack or certification-
  state attack — count ≠ quality; do not add tests for appearance.
- Every command documented in guides must map to a real entry point;
  verify before documenting.

## Quality gates (run before every commit)

```bash
.venv/bin/python -m pytest           # full suite — must be all green
.venv/bin/ruff check python tests    # lint
.venv/bin/python -m pytest tests/test_docs_contract.py -q   # doc pins
```

MQL5 compile requirements (owner environment only): the strict script
`tools/compile.ps1 -Strict` with 0 errors / 0 warnings; there is no
sandbox substitute.

## Changing things — impact rules

| Change | Requirement |
|---|---|
| adding a strategy | research surface: spec + tests; MQL5 surface: a new engine changes the five-engine contract — requires SPEC + CERTIFICATION scope update + owner validation (BLOCKED_OWNER_ENVIRONMENT until then) |
| changing an indicator | causality/completed-bar property tests; gold-impact statement; deterministic replay must stay byte-equal |
| changing Risk / Meta / Kill Switch | SYSTEM_INVARIANTS review; invariant tests first; never weaken to make a test pass |
| changing schemas | examples + factory gates + schema tests together |
| changing certification logic | the fail-closed property is sacred: negative evidence may never become positive; add the attack test with the change |
| changing docs | doc-contract pins (`tests/test_docs_contract.py`) must stay green |
| touching `artifacts/gold*` | STOP — regeneration is never a fix; a gold diff means investigate |

When `DECISIONS.md` must change: any semantic contract change, any new
evidence rule, any warmup/tie/rounding ruling. When `SPEC.md` must
change: any behavior visible across the Python/MQL5 boundary.

## How to avoid weakening safety

1. Never edit a failing test to make it pass — fix the defect or
   record the finding.
2. Never loosen a fail-closed verifier branch "temporarily".
3. Never convert a BLOCKED state into a PASS by wording.
4. Never add tolerance epsilons to parity comparisons.
5. **Documentation must never become more optimistic than the
   implementation and the evidence.**
