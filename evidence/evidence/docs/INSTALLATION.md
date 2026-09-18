# Installation Guide

## Supported Python

**3.10 – 3.12.** `pyproject.toml` declares `requires-python = ">=3.10"`;
CI tests 3.10, 3.11 and 3.12. There is one Python support policy and
it lives in `pyproject.toml`.

## Dependency model (one source of truth)

| Source | Role |
|---|---|
| `pyproject.toml` `[project.dependencies]` | mandatory runtime dependencies (numpy, pandas, SQLAlchemy, alembic, pydantic, PyYAML, fastapi, jinja2, python-multipart) |
| `pyproject.toml` `[project.optional-dependencies]` | `dev` (pytest, httpx — API tests), `optimize` (optuna), `live` (MetaTrader5, Windows-only data bridge) |
| `requirements.txt` | convenience mirror for pip-only environments; CI installs `.[dev]` plus it. Do not add packages here without updating `pyproject.toml` |

`MetaTrader5` and `optuna` are **optional** — the core toolkit, tests,
Factory and certification tooling work without them.

## Python environment

```bash
# clone
git clone https://github.com/raminhdev/mql5bot.git
cd mql5bot

# virtualenv + editable install with dev/test dependencies
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# verify
.venv/bin/mql5bot --help            # CLI entry point
.venv/bin/python -m pytest tests/test_docs_contract.py -q   # smoke
```

Optional extras:

```bash
.venv/bin/pip install -e ".[optimize]"   # optuna-based optimisation tooling
.venv/bin/pip install -e ".[live]"       # MetaTrader5 bridge (Windows only)
```

## What works on Linux / macOS (no MT5)

Everything Python:

- the quant toolkit: `mql5bot data | backtest | compare | optimize |
  walkforward | dashboard`
- the full pytest suite, ruff lint, docs-consistency tests
- Factory intake/research/lifecycle and the operator console
  (`mql5bot/api`)
- gold-standard deterministic regressions (`artifacts/gold/`,
  `artifacts/gold_2/`)
- the owner-evidence verifier (`tools/verify_owner_mt5_gate.py`) and
  binding tool (`tools/owner_evidence_bind.py`) — consuming evidence
  requires no Windows
- reports, dashboards, static validation, Alembic migrations

What does NOT work natively:

- MetaEditor compilation of `.mq5`/`.mqh` sources
- the MT5 Strategy Tester (any model)
- broker SymbolSpec export from a real terminal
- real-tick execution evidence

These require the owner's Windows + MetaTrader 5 environment
(see `MT5_SETUP_AND_OPERATION.md`). The repository sandbox can verify
owner evidence once returned, but can never produce it.

## Windows + MetaTrader 5

Prerequisites:

1. **MetaTrader 5** terminal from your broker (note the build number).
2. **MetaEditor 5** (bundled with the terminal; F4 in MT5).
3. The repository checked out on the Windows machine at the branch you
   intend to certify (`main`).

Locate the terminal data folder: in MT5, **File → Open Data Folder**.
Inside it:

```
MQL5/
  Experts/     Expert Advisors (.mq5 -> compiled .ex5)
  Include/     shared headers (.mqh)
  Scripts/     one-click scripts
  Presets/     (created by our installer)
  Files/       sandboxed file I/O for scripts/EA
```

Install the EA:

```powershell
python scripts\install_mql5.py          # auto-detects the data folder
python scripts\install_mql5.py --folder "<MT5 Data Folder>"
```

or manually:

1. Copy `mql5/Include/Mql5Bot/` → `<Data Folder>/MQL5/Include/Mql5Bot/`
2. Copy `mql5/Experts/Mql5Bot/Mql5Bot.mq5` → `<Data Folder>/MQL5/Experts/Mql5Bot/`
3. Copy the presets from `mql5/Presets/Mql5Bot/` if present.
4. Compile with the strict gate (next section of
   `MT5_SETUP_AND_OPERATION.md`); never treat "MetaEditor opened" as
   compile evidence.

If you use telemetry, add the collector URL in MT5 under
**Tools → Options → Expert Advisors → Allow WebRequest for listed URL**.

## Verifying the installation

```bash
.venv/bin/python -m pytest          # full suite (expected: all green)
.venv/bin/ruff check python tests   # lint
```

If tests fail at install time, see `TROUBLESHOOTING.md` before
changing anything.
