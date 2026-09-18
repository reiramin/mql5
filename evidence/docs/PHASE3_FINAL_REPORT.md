# PHASE 3 / PERFORMANCE & SELECTION HARDENING — Final acceptance report

## CURRENT COMMIT

`a943af1` on `arena/01a06cdc-mql5bot` (pushed; base of the A–G chain:
`852c00d`, 265 tests).
Chain commits: `f129621` (A) → `33cc593` (B) → `308fe7b` (C) →
`e4098fa` (D) → `d342ffe` (E) → `ead286b` (F) → `a943af1` (G wording).

## FILES CHANGED

(18, against `852c00d`; all Python/docs — **zero MQL5 files touched**)
`CHANGELOG.md`, `PROGRESS.md`, `README.md`, `pyproject.toml`,
`python/mql5bot/__init__.py`, `python/mql5bot/cli.py`,
`python/mql5bot/dashboard.py`, `python/mql5bot/data.py`,
`python/mql5bot/indicators.py`, `python/mql5bot/metrics.py`,
`python/mql5bot/optimizer.py`, `python/mql5bot/report.py`,
`python/mql5bot/telemetry_bridge.py`, `tests/test_data.py`,
`tests/test_indicators.py`, `tests/test_install.py`,
`tests/test_metrics.py`, `tests/test_strategies_optimizer.py`

## FILES ADDED

(12)
`docs/CERTIFICATION.md`, `docs/STAGED_PIPELINE.md`,
`python/mql5bot/certify.py`, `python/mql5bot/fast_engine.py`,
`python/mql5bot/ml_interfaces.py`, `python/mql5bot/pipeline.py`,
`tests/test_benchmark.py`, `tests/test_certify.py`,
`tests/test_fast_engine.py`, `tests/test_ml_interfaces.py`,
`tests/test_pipeline.py`, `tools/certify_strategy.py`

## TEST COUNT

**357** (265 at the chain base → 357; +38 FAST equivalence, +16 pipeline,
+18 ML-interface/invariants, +11 certification, +11 metrics/opt-in
ranking, +1 bench, minus 3 retired Phase-A artifacts).

## TEST RESULT

All green from the repo root (`python -m pytest tests/`):
**357 passed, 0 failed** on the pinned interpreter (numpy 2.4.6,
pandas 3.0.5, pytest 9.1.1).  Root-level `pytest` works without any
install (`pythonpath = ["python"]` in `pyproject.toml`).  Key pins:
FAST ≡ TRUTH trade-for-trade on 5 strategies × cost/exit/halt/trail/
partial knob sets + engine-style signal exits; purge+embargo CPCV
semantics proven by fold selection on crafted leak/clean configs; ML
invariant checker catches all four violations; certification verdict
honesty (no legs → NOT VERIFIED); benchmark direction (FAST > TRUTH).
No MetaEditor run exists in this sandbox, so no MQL compile claim is
made (see SAFETY GAPS — the line stays NOT VERIFIED, never guessed).

## RUFF RESULT

`ruff check python tests tools` → **All checks passed** (0 errors).
Phase A fixed the pre-existing inventory (31 findings, 24 auto); every
new module/test is clean, including SIM102/C408/BLE001/F841/RUF100/
ISC004/EXE001 class findings.

## BENCHMARK BEFORE/AFTER TABLE

3120 hourly bars (fixture `generate_ohlc(days=130, seed=1)`), min-of-5
walls, this sandbox; bench harness `tests/test_benchmark.py -m bench`.

| Engine / stage | BEFORE (Phase A) | AFTER (Phase C) |
| --- | --- | --- |
| TRUTH `run_backtest` | 63.8 ms/run · 48,888 bars/s · ~1,457 trades/s | 61–65 ms/run · 48–51k bars/s (unchanged — same canonical engine) |
| `walk_forward` (2 windows) | 0.32 s total · 0.16 s/window | 0.31–0.39 s total · 0.15–0.19 s/window |
| peak memory (single run) | ~0.7 MB | ~0.7 MB |
| **FAST `run_fast` (NEW)** | — | 38–42 ms/run · **74–82k bars/s · ~1.55–1.69× vs TRUTH** |
| Equivalence pin | — | FAST ≡ TRUTH: identical trade rows, equity within 1e-8 (38 tests) |

FAST is a screening engine only — never final, never a profit claim;
certification remains the TRUTH engine + MT5 tester (Phase F).

## KNOWN LIMITATIONS

- FAST scope is the single-(symbol, strategy) netting subset; schedules
  (WFA freeze), swap accrual, exposure caps, margin calculators and
  hedging raise `NotImplementedError` — loud, never silent.  Its per-bar
  loop is still Python (no per-bar pandas; arrays/scalars only), hence a
  ~1.6× win, not an order of magnitude.
- Equivalence is pinned on synthetic random-walk fixtures, not on real
  broker history; bench numbers are sandbox-specific and noisy (±~20%
  between runs).
- The purged-CPCV stage (S3) ranks survivors on realized-pnl per-bar
  attribution over the DEVELOPMENT window; it is a diagnostic, never a
  certification, and never touches the S5 dataset.
- The one-look OOS registry is a plain JSON file without locking —
  single-process usage is assumed and documented.
- Phase F certification legs need a Windows MT5 terminal; in this
  sandbox they are reported as not run (verdict NOT VERIFIED).  The
  protocol logic is tested through a fake runner; real-tick outcomes
  are not available here.
- Optuna is an optional extra (`pip install mql5bot[optimize]`); it is
  not installed in this environment, so only its guard and contract are
  tested, not the search itself.
- ML interfaces are stubs by design (no training, no neural networks,
  no ML stack in the package — enforced by a banned-import scan test).

## SAFETY GAPS

- **MQL5/MetaEditor: NOT VERIFIED.** No MQL5 file changed in the A–G
  chain and no MetaEditor compile was run in this sandbox; any compile
  claim would be a guess, so none is made.  An owner round-trip
  (MetaEditor compile + paste of the result line) is required before
  any MQL status can be marked VERIFIED.
- **Live trading:** the Python side never trades live, and nothing in
  this chain creates orders outside the canonical engine seam.  The
  ML-advice seam can only drop/shrink engine orders; the four risk
  invariants are schema-level and runtime-checked.
- **Certification:** no VERIFIED stamp exists for any strategy — the
  Phase F ladder has not run on a terminal.  Backtests are research
  evidence, not a promise of live results (README).
- **OOS policy:** the one-look registry prevents repeat optimisation on
  the same certification slice in code; it does not (and cannot)
  prevent a researcher from silently relabelling a dataset — the
  content digest only covers the frame actually passed in.
- Residual risk in FAST/TRUTH equivalence lives in untested exotic
  corners (multi-day zero-volume gaps, extreme bars with
  open==high==low); scope gates cover the modelled subset.

## NEXT 3 TASKS

1. **Run the Phase F ladder on a Windows terminal host**
   (`tools/certify_strategy.py` with a real `TesterConfig` per regime:
   M1 OHLC → every tick → every tick on real ticks → real ticks;
   100-trade minimum; spread floor; surcharge tiers; degradation vs the
   30–50% band) and record the resulting VERIFIED / NOT VERIFIED
   outcome in the report — binding the S5 manifest id.
2. **MetaEditor compile round-trip** for the MQL5 tree (unchanged this
   chain): owner runs the compile-scan and pastes the result so the
   status line can honestly become VERIFIED or stays NOT VERIFIED with
   the error.
3. **Wire the Phase B–D stack into user surfaces**: expose the OPT-IN
   `selection_metric="composite"` and the staged-pipeline summary
   (screen → x2-cost stress → purged CV → one-look OOS) as
   display-only report/dashboard sections, and exercise the `optimize`
   extra's deterministic TPE/Hyperband stage end-to-end in CI.

*Report compiled 2026-09-04. All gates re-run for this report: 357
passed, ruff clean, bench table re-measured above.*
