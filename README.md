# mql5bot — AEGIS

**A full-stack algorithmic trading system for MetaTrader 5: an MQL5
Expert Advisor, a deterministic Python research/certification toolkit,
and an evidence-bound certification gate.**

[![CI](https://github.com/raminhdev/mql5bot/actions/workflows/ci.yml/badge.svg)](https://github.com/raminhdev/mql5bot/actions/workflows/ci.yml)

One codebase, two layers that stay in lockstep:

| Layer | Language | Location | Purpose |
|-------|----------|----------|---------|
| **Expert Advisor** | MQL5 | `mql5/` | Executes trades in MetaTrader 5 (owner environment) |
| **Quant toolkit + certification** | Python | `python/mql5bot/` | Research, backtesting, gold-standard parity, owner-evidence verification |

> **Read this first if you are new:** [docs/INSTALLATION.md](docs/INSTALLATION.md)
> (setup), [docs/USER_GUIDE.md](docs/USER_GUIDE.md) (how the system
> works), [docs/MT5_SETUP_AND_OPERATION.md](docs/MT5_SETUP_AND_OPERATION.md)
> (owner runbook), [docs/README.md](docs/README.md) (documentation map).

---

## What is AEGIS?

AEGIS is the certification and governance layer around `mql5bot`. Its
core claim is deliberately narrow: **nothing in this repository is
declared valid beyond the evidence that actually exists for it.** The
system separates five evidence classes and never lets one impersonate
another:

1. **Software evidence** — deterministic Python tests (this sandbox can prove it).
2. **Gold semantic evidence** — frozen fixtures proving the Python, DSL
   and MQL5 semantics agree on controlled data (Gold #1, Gold #2).
3. **MT5 runtime evidence** — actual compile / Strategy Tester /
   reconciliation artifacts produced on the owner's Windows terminal.
4. **Empirical evidence** — statistical robustness across regimes and
   tester models (separate lane, ≥100 trades per regime).
5. **Demo / live evidence** — live-like and real-money operation
   (separate, later states).

## Current status (honest, not collapsed)

| Item | State | Evidence |
|---|---|---|
| Python toolkit + tests | **IMPLEMENTED, RESEARCH-VALIDATED** | deterministic suite (see CI) |
| Gold #1 / Gold #2 semantic parity (Python↔DSL) | **GOLD_SEMANTIC_PASS** (local) | `artifacts/gold/`, `artifacts/gold_2/` — frozen, hash-chained |
| MQL5 compile / Strategy Tester / reconciliation | **BLOCKED_OWNER_ENVIRONMENT** | no owner artifacts exist yet |
| Real-tick coverage | **REAL_TICK_COVERAGE_UNKNOWN** | honest default until owner evidence |
| Empirical lane | **PENDING_OWNER** | package defined (`docs/AEGIS_EMPIRICAL_LANE_PACKAGE.md`), not executed |
| Demo / Live | **NOT_READY** | demo never auto-starts; no live capital in this workflow |
| Overall | **REALITY_GATE_BLOCKED · PRODUCTION = NOT_READY · verifier OWNER_EXECUTION_READY** | `docs/AEGIS_REALITY_GATE_AUDIT.md` §85–§90 |

**Status vocabulary — these are NOT synonyms:**

- **IMPLEMENTED** — code exists and is unit-tested.
- **RESEARCH-VALIDATED** — validated by the deterministic Python research pipeline.
- **GOLD_SEMANTIC_PASS** — the frozen gold fixtures reconcile exactly
  across runtimes. Semantic CORRECTNESS evidence only: no trade-count
  minimum applies (Gold #2 is valid with its 56 trades), and it never
  implies MT5-VALIDATED or VERIFIED.
- **MT5-VALIDATED** — proven in the MetaTrader 5 Strategy Tester on
  owner-produced, hash-bound artifacts.
- **EMPIRICAL-VALIDATED / DEMO-VALIDATED / LIVE-VALIDATED / VERIFIED** —
  later, separate states with their own prerequisites
  (`docs/CERTIFICATION.md`).
- **BLOCKED_OWNER_ENVIRONMENT** — requires the owner's
  Windows/MetaEditor/terminal; never converted to PASS by assumption.

This repository state **must not be read as real-money validation**:
no MT5 runtime evidence exists yet, and nothing here implies
profitability.

## The execution-surface boundary (binding)

The EA's five built-in strategy engines (`ema_crossover`,
`rsi_reversal`, `donchian_breakout`, `bollinger_reversal`,
`macd_momentum`) are the ONLY MQL5 execution surface — the EA contains
no DSL interpreter, so a generated/DSL strategy cannot enter EA
execution unless it maps onto one of those five engines. Generated
strategies run on the Python research stack; their MT5 path beyond the
five built-ins is BLOCKED_OWNER_ENVIRONMENT. Binding scope model:
`docs/CERTIFICATION.md` §Certification scope surfaces.

| Surface | What it is | Evidence class |
|---|---|---|
| **RESEARCH SURFACE** | Python / DSL / Factory — 71 contract-declared indicator kinds | deterministic tests |
| **EXECUTION SURFACE** | MQL5 EA — five built-in strategy engines | owner runtime evidence |
| **OWNER-PENDING SURFACE** | new/generated semantics requiring runtime validation | none yet |

## What can run where

| Capability | Linux/macOS sandbox | Windows + MT5 |
|---|---|---|
| Python toolkit, backtests, reports, dashboard, tests | ✅ | ✅ |
| Factory intake/research/lifecycle, operator console | ✅ | ✅ |
| Gold deterministic regressions, verifier | ✅ | ✅ |
| MetaEditor compile, Strategy Tester, real ticks | ❌ | ✅ |
| SymbolSpec export from a real broker terminal | ❌ | ✅ |
| Owner runtime safety exercises | ❌ | ✅ (demo account) |

CI (`.github/workflows/ci.yml`) runs the Python matrix (3.10–3.12),
ruff lint, Alembic migration smoke and the full test suite. **CI never
compiles MQL5 and never runs the Strategy Tester** — those belong to
the owner environment.

## Quick start (Python toolkit)

Supported Python: **3.10 – 3.12** (`requires-python >=3.10`; CI matrix
3.10/3.11/3.12).

```bash
# 1. Install the package (development mode incl. pytest)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2. Generate data (or export from MT5: File -> Save As... CSV)
mql5bot data --symbol EURUSD --timeframe H1 --days 730 --out data/EURUSD_H1.csv

# 3. Backtest a strategy with realistic costs
mql5bot backtest --data data/EURUSD_H1.csv --strategy ema_crossover \
    --spread 1.0 --slippage 0.5 --commission 7 --risk 1 \
    --trail 2.5 --daily-loss 5 --report results/report.html

# 4. Compare all five strategies
mql5bot compare --data data/EURUSD_H1.csv --report results/compare.html

# 5. Grid-search parameters
mql5bot optimize --data data/EURUSD_H1.csv --strategy ema_crossover \
    --grid '{"fast":[8,10,12,16],"slow":[25,30,40]}' --jobs 4

# 6. Walk-forward validation
mql5bot walkforward --data data/EURUSD_H1.csv --strategy rsi_reversal \
    --grid '{"period":[10,14,21]}' --windows 4

# 7. Live dashboard
mql5bot dashboard --port 8000

# 8. Run the test suite
.venv/bin/python -m pytest
```

Optional extras: `pip install -e ".[optimize]"` (optuna) and, on
Windows with a running terminal, `pip install -e ".[live]"`
(MetaTrader5 data bridge — data only, never order authority).

Full setup details: [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Running the EA (owner environment)

```bash
# copy EA + includes + presets into the MT5 data folder
python scripts/install_mql5.py            # or --folder <path>

# strict compile (Windows, PowerShell) — 0 errors / 0 warnings required
powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict

# consume a returned owner evidence directory
python tools/verify_owner_mt5_gate.py <evidence-dir> --repo . --out report.json
```

The complete owner runbook — compile, SymbolSpec export, Gold legs,
safety, reconciliation, evidence binding, verification — is
[docs/MT5_SETUP_AND_OPERATION.md](docs/MT5_SETUP_AND_OPERATION.md) and
`artifacts/owner_mt5_gate/README.md`.

## The Reality Gate / owner execution step

The repository ships a complete owner-evidence pipeline:

- `artifacts/owner_mt5_gate/` — the frozen execution package (frozen
  inputs, manifest template, checklist, report template, owner manual).
- `tools/verify_owner_mt5_gate.py` — the evidence consumer: one command
  verifies completeness, freshness, identity bindings, tester-model
  identity, real-tick coverage, gold reconciliation, first divergence,
  safety evidence; exit 0 only on a positive verdict.
- `tools/owner_evidence_bind.py` — computes every hash binding; the
  owner never hand-types a hash.

A filename is not evidence; a screenshot is not evidence; a selected
tester mode is not evidence. Only a cryptographically bound,
provenance-consistent artifact chain is evidence
(`docs/AEGIS_REALITY_GATE_AUDIT.md` §88–§90).

## Strategy lifecycle (short form)

```
IDEA → intake → DSL/spec → schema gate → research → statistical gates
     → OOS/robustness → promotion ladder (human approvals) → allocation
     → monitoring → drift → decay/retirement
```

Factory may SPECIFY strategies; it can never EXECUTE trades. Only the
EA's TradeManager has execution authority; Risk holds the capital veto;
the Kill Switch is the emergency veto; Meta only reduces allocation.
Details: [docs/FACTORY_GUIDE.md](docs/FACTORY_GUIDE.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
`docs/SPEC.md`, `docs/SAFETY_GOVERNANCE.md`.

## What this system does NOT guarantee

- No guarantee of **profitability** — backtests are research evidence,
  not forecasts.
- No guarantee of **broker compatibility** — every broker SymbolSpec
  must be exported and compared on the owner's terminal first.
- No guarantee of **MT5 runtime behavior** — until owner tester
  evidence reconciles against the gold fixtures.
- No **automatic demo or live trading** — demo requires MT5 validation
  + clean reconciliation + safety evidence + broker confirmation +
  human approval; live requires everything after that, independently.

## Where the detailed documents live

`docs/README.md` is the documentation map. Canonical engineering
documents: `docs/SPEC.md`, `docs/SYSTEM_INVARIANTS.md`,
`docs/STATE_MODEL.md`, `docs/CERTIFICATION.md`,
`docs/MT5_ROUNDTRIP.md`, `docs/DECISIONS.md`. Human-facing guides:
`docs/INSTALLATION.md`, `docs/USER_GUIDE.md`,
`docs/MT5_SETUP_AND_OPERATION.md`, `docs/FACTORY_GUIDE.md`,
`docs/CERTIFICATION_GUIDE.md`, `docs/TROUBLESHOOTING.md`,
`docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`,
`docs/RELEASE_CHECKLIST.md`.

Historical state: `HANDOFF.md` (agent/engineering continuity),
`PROGRESS.md` (execution history), `TASKS.md` (work queue),
`CHANGELOG.md`. The `docs/AEGIS_*.md` audit records are engineering
evidence — users should not need them to operate the project.

## Research evidence, not promises

Every historical result in this repository — Python engine,
walk-forward, staged pipeline, MT5 Strategy Tester — is research
evidence produced under explicit modelling assumptions (fills,
spreads, slippage, tick reconstruction), not a forecast and not a
guarantee of live results. FAST/screening results are selection
signals only — never final, never a profit claim.

## Safety

- Validate every parameter set in the Python backtest (with costs!)
  before running the EA on any account.
- Always start on a **demo account**; the framework has no guarantee of
  profitability.
- Every position needs a protective stop or a contractual recovery
  path; the daily-loss and drawdown limits are last lines of defence;
  the Kill Switch latches before any new entry.
- No live capital inside the certification workflow — Strategy Tester
  and controlled demo only, owner-approved.

## License

MIT — see `LICENSE`.
