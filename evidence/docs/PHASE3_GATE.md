# PHASE 3 — INTEGRITY GATE RECORD (2026-09-05)

Verdict of this record: **PHASE 3 SOFTWARE_PASS** — all 16 exit-gate
criteria hold with evidence.  This is a software-integrity verdict
only: it makes no profitability, production-readiness or MT5-verified
claim.  The Meta Layer remains unimplemented by design; only its
contract exists (`docs/META_LAYER_CONTRACT.md`).

## The 16 exit-gate criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Safe push; remote HEAD == local HEAD; no history rewrite / force push / deleted commits | PASS | push `eb78b9c..611aa81`; `git ls-remote` == `git rev-parse HEAD` == `611aa81`; history is append-only from the `2714bbf` restore commit (documented in PROGRESS.md) |
| 2 | Baseline pytest + `ruff check python tests tools` green before any change | PASS | 436 passed, 1 skipped, 42.0 s, ruff clean (Phase 1, pre-change) |
| 3 | S1–S5 + companions (restart, netting/hedging, attribution, RetryQueue, OnTimer, stop/freeze) re-traced in MQL5 source with test evidence and no stale alternative implementation | PASS | source audit (commits `8d4d204`, `2e554a2`) + `tests/test_mql5_sources.py` (9 tests); Python mirrors `slguard.py`/`failsafe.py`/`retryqueue.py` have their own suites; details in PROGRESS.md |
| 4 | Metamorphic tests A–K verify mathematical relationships, not fixed outputs | PASS | `tests/test_metamorphic.py` 14 tests: zero-movement identity, spread/slippage/commission monotonicity, risk linearity + cap-attribution, cost superposition + ledger identity, G split invariance EXACT (continuous policy) + documented cold-split non-equivalence, netting==hedging equality, rejected-order inertia, cap monotonicity, cost-stress ordering |
| 5 | WFA/CPCV formal audit — three documents agree; 11-row matrix; STATE CARRY ≠ KNOWLEDGE CARRY stated | PASS | `docs/WFA_CPCV_REVIEW.md` (commit `28b34ca`) + `tests/test_docs_contract.py::test_wfa_cpcv_review_matrix_present` |
| 6 | CPCV adversarial: ONLY future data changes across 7 scenarios; train scores + selection bit-identical; OOS free to change | PASS | `tests/test_cv_state_leakage.py::_FUTURE_MATRIX` 21 tests (commit `a97e7b4`): huge profit, huge loss, drawdown trigger, daily-loss trigger, equity spike, exposure-cap trigger, open-position difference |
| 7 | Pipeline: S2 zero survivors ⇒ S3 skipped, S4 skipped, S5 BLOCKED; no fallback candidate certified | PASS | `tests/test_pipeline.py::test_run_stages_zero_survivors_block_certification` (verified present, chain + NOT_ELIGIBLE + registry-untouched all pinned) |
| 8 | OOS one-look identity (8-component digest) + failed-attempt policy; no silent re-certification | PASS | `tests/test_oos_registry.py` incl. `test_failed_attempt_consumes_nothing_retry_permitted_once_locked` + `test_failed_attempt_cannot_be_used_to_shop_parameters` (commit `3e82627`); policy documented in docs/CERTIFICATION.md |
| 9 | FAST: honest scope (no "fully vectorized"), profile, full matrix re-measured, interleaved A/B | PASS | `docs/BENCHMARK_FAST.md` re-run (commit `330a437`): 6-cell matrix fresh; A/B geomean **1.184** (range 1.139–1.230, 12/12 base-slower, trades identical) — prior 1.001 superseded with the discrepancy explained; `tests/test_docs_contract.py` bans the vectorized claim |
| 10 | Performance policy recorded (measured hotspots only; simple-before-complex; no GPU/Rust/Cython/Numba/distributed without evidence) | PASS | `docs/BENCHMARK_FAST.md` §7 (commit `ac3c310`); no further optimization scheduled |
| 11 | Optuna: TPE+Hyperband, training-side pruning only, deterministic seed/study, optional n_jobs, cache, OOS guard; regression tests fail if OOS enters the objective; same seed+data ⇒ same best | PASS | `tests/test_optuna_hardening.py` 12 tests incl. the new OOS-suffix leak regression (commit `8622024`); Optuna verified present this environment (optuna 4.9.0) and exercised |
| 12 | MT5 package complete + exact 10-step owner sequence + five fixed states; MT5 NOT VERIFIED until a real Windows run | PASS | all four tools verified present (`compile.ps1`, `run_mt5_backtest.ps1`+`.py`, `certify_strategy.py`, `benchmark_research.py`); `docs/MT5_ROUNDTRIP.md` 10 steps + 5 states (commit `611aa81`) pinned by `tests/test_docs_contract.py`; `verdict_for` gates confirmed band-free in source. **2026-09-07 canonicalization:** the ten steps were re-canonicalized (compile / compile-log / SymbolSpec export / fixture prep / M1-OHLC / Every-Tick / real-ticks / Python↔MT5 comparison / archive / state) as the single source of truth; the `611aa81` wording is superseded but the gate substance (exact sequence + five states + NOT VERIFIED without a real Windows run) is unchanged |
| 13 | Real-tick degradation REPORTED AS OBSERVED; 30–50% band informative only, never a gate | PASS | `python/mql5bot/certify.py::degradation_report` (report-only, `inside_band` flag, None baselines) + docs/CERTIFICATION.md + docs/MT5_ROUNDTRIP.md + 2 tests in `tests/test_status_model.py` (an 80%-degraded ladder still VERIFIED; a 5% ladder reported truthfully) |
| 14 | Reproducibility: every run records commit, dataset hash, strategy/engine/cost-model/feature versions, seed, configs, protocol version; run-twice equivalence | PASS | `RunManifest.repro` (commit `eb78b9c`) + `tests/test_reproducibility.py` 6 tests (two-run CPCV identity, two-run pipeline identity with shared cache, registry identity components, manifest round-trip) |
| 15 | Full suite + ruff green at gate time | PASS | **482 passed, 1 skipped, 51.6 s**, ruff clean (2026-09-05, commit `611aa81`); 14 warnings = benign numpy invalid-power RuntimeWarnings in `metrics.py:32` CAGR on all-zero-spread equity paths, previously assessed, unchanged |
| 16 | No forbidden claims without evidence; Meta Layer contract only, no implementation | PASS | this record and the final report use only evidenced wording: no "profitable", no "production-ready", no "verified" for any strategy; `docs/META_LAYER_CONTRACT.md` contains inputs/weight/modes/safeguards ONLY — no algorithm code |

## Gate decision

**PHASE 3 SOFTWARE_PASS.**  Proceeding to the Meta Layer CONTRACT
document only (as mandated).  No Meta Layer implementation, no new
strategy, no ML component is created in this phase.

## Known limits (unchanged, stated for the record)

- MT5 compile/tester legs were NEVER executed here (no Windows
  terminal in the sandbox): MT5 status is `NOT VERIFIED`, MQL5 compile
  status is `NOT RUN IN SANDBOX`.
- Equivalence fixtures are synthetic random-walk data; benchmark
  absolute numbers are session-relative (only the in-process A/B
  ratios are decision-grade).
- The OOS registry is single-process JSON without locking
  (documented).
