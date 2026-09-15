# FAST engine — scope, profile, benchmark (Phase 3 hardening, Blocker 4)

All numbers below are MEASURED in this repository's sandbox
(CPython 3.11.2, NumPy 2.4.6, pandas 3.0.5, single core, shared
environment; Phase-3-gate re-run 2026-09-05).  The re-measured A/B
shows a **~1.18× engine-level speedup** of the optimized tree over the
pre-optimization baseline (§4.1); an earlier stash-based A/B had
measured 1.001× — both results are kept and the discrepancy is
explained, not hidden (§4.2).  The benchmark harness is
`tools/benchmark_fast.py`; every table here is reproducible with the
commands shown.

---

## 1. Documented scope (honest statement)

`mql5bot.fast_engine.run_fast` is a NumPy-array re-implementation of the
canonical engine's ORCHESTRATION for the single-(symbol, strategy)
netting screening case.  Accounting/sizing formulas are NOT duplicated —
`costs`, `sizer`, `leg_cash` and symbol rounding are called per event.

| Aspect | Status |
|---|---|
| Array-based (no per-bar pandas) | OHLC extraction, signal series, ATR(14), spread/reject series, server-day ids, equity/notional curves, timestamp strings (vectorised strftime on whole-second DatetimeIndex; exact per-element conversion otherwise) |
| Loops that REMAIN Python | the per-bar event loop (risk checks, reconciliation, fills, position management); per-event fill/valuation calls; per-trade row construction |
| Unsupported features (loud `NotImplementedError`) | walk-forward schedule; margin calculator; exposure caps; per-strategy risk map; swap |
| Numba / JIT | **NOT used** — pure Python + NumPy, no C extension |
| Certification | NEVER — TRUTH engine (`engine.py`) and the real MT5 tester are the only certification paths; equivalence pinned by `tests/test_fast_engine.py` |

## 2. Profiler findings (cProfile, 30k bars, 3 runs)

Per run ≈ 0.37 s on a trade-dense parameter set (1,436 trades):

| Hot path | share (cum) | note |
|---|---|---|
| `leg_cash` (via `mark()` per held bar + fills) | ~53 % | single-owner valuation — deliberately not vectorised |
| `run_fast` per-bar loop body | ~27 % (tottime) | pure Python event loop |
| timestamp formatting `[str(t) for t in index]` | ~13 % | pandas `Timestamp.__iter__` + per-element `str()` |
| `compute_metrics` | ~13 % | pandas, SHARED with the TRUTH path — left alone |
| `round()` calls (fills, rows) | ~8 % | exact-accounting rounding — kept |

## 3. Optimizations applied (measured at component level)

| Change | Component measurement | kept? |
|---|---|---|
| vectorised `index.strftime` replacing `[str(t) for t in index]` (whole-second guard, exact fallback) | 300k index: 469.7 ms → 99.0 ms (**4.7×**), strings identical | yes |
| constant spread/reject series via `np.full` instead of per-bar `cost_cfg.spread_at(i)` list-comp (fixed-cost mode only) | 300k bars: 7.18 ms → 0.09 ms (**78×**) | yes |
| hoisted per-entry `merged["sl_atr"/"tp_atr"]` dict lookups | sub-sum measurement noise | yes (trivial) |
| per-book `leg_cash` value cache | no engine-level gain (see §4) | **rejected** (invalidation complexity without measured benefit) |

## 4. Engine-level A/B: baseline vs optimized — MEASURED

### 4.1 Phase-3-gate re-run (2026-09-05): ~1.18×, outside noise

Methodology (no `git stash`, no cross-tree copy errors): the baseline
is the pre-optimization `fast_engine.py` from commit `984a406`,
imported as a parallel package (`mql5bot_base`) next to the live tree
inside ONE process; all accounting modules (`costs`, `sizer`,
`leg_cash`, `metrics`) are byte-identical between the two variants —
the ONLY difference is the FAST engine module.  The full
`tools/benchmark_fast.py` matrix ran interleaved base→opt, two rounds,
same process, identical parameter sets; per-cell trade counts verified
identical across all four runs (235 / 10,880 / 101,576 / 2,314 /
118,757 / 29,914 trades).

| cell (bars × param sets) | base/opt wall r1 | r2 |
|---|---:|---:|
| 3,000 × 1 | 1.206 | 1.139 |
| 3,000 × 100 | 1.169 | 1.165 |
| 3,000 × 1,000 | 1.155 | 1.150 |
| 30,000 × 1 | 1.176 | 1.230 |
| 30,000 × 100 | 1.208 | 1.225 |
| 300,000 × 1 | 1.212 | 1.180 |
| **geometric mean** | | **1.184** |

All 12 measurements have base slower (range 1.139–1.230), entirely
outside the documented ±10 % run-to-run noise, and round 2 (fully
warm) reproduces round 1.  **Conclusion: the §3 component wins
(vectorised strftime, `np.full` constant-cost series, hoisted lookups)
compose into a real, resolvable ~1.18× engine-level speedup** — the
per-bar Python event loop still dominates, exactly as the profile
predicts, so no further acceleration is claimed.

### 4.2 Prior-session A/B (superseded, kept for the record)

The earlier session measured geomean 1.001 (range 0.907–1.156, ratios
straddling 1.0 in both directions) with a `git stash`-applied baseline
re-run as a separate process tree.  Today's no-stash in-process method
removes the two failure modes that method has (baseline tree may not
be what the operator believes; cross-process environment drift), and
its consistently one-sided result contradicts the old oscillating
ratios.  Honest reading: the 1.001 result most plausibly compared a
partially- or wrongly-reverted baseline (the §5.3 defect class) or was
noise-dominated; it is superseded by §4.1 and NOT counted as evidence
for or against any claim.  Memory (fresh single-run tracemalloc probe):
3k 0.8 MB, 30k 8.4 MB, 300k 89.6 MB — identical in both variants (the
optimizations touch no allocation structure).

## 5. Harness defects found while measuring (fixed in
`tools/benchmark_fast.py`)

1. `tracemalloc` enabled around the TIMED loop inflated wall time ~19×
   (3k×100: 49 s traced vs 2.5 s untraced).  Timing and memory probing
   are now separate.
2. The first baseline run was left running as an orphan process during
   early comparisons, skewing them; it was killed and the A/B redone.
3. An early A/B loop omitted `git stash pop`, comparing baseline against
   itself; detected via the ~1.0 ratios and redone correctly.

These are documented because a "speedup" claimed from any of the
affected runs would have been fabricated.

## 6. Absolute numbers (optimized tree, Phase-3-gate re-run, single core)

| bars | param sets | wall s | bars/s | trades/s | peak MB | cpu/wall |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3,000 | 1 | 0.039 | 77,724 | 6,088.3 | 0.8 | 1.00 |
| 3,000 | 100 | 3.297 | 90,992 | 3,300.0 | 0.8 | 1.00 |
| 3,000 | 1,000 | 32.857 | 91,305 | 3,091.4 | 0.8 | 1.00 |
| 30,000 | 1 | 0.302 | 99,374 | 7,665.0 | 8.4 | 1.00 |
| 30,000 | 100 | 26.022 | 115,286 | 4,563.7 | 8.4 | 1.00 |
| 300,000 | 1 | 3.187 | 94,128 | 9,385.8 | 89.6 | 1.00 |

(The 1,000-set sweep at 300k bars is omitted from the default matrix:
~40 min single-core; `--full` runs it.  Absolute wall times vary ±10 %
between sessions on this shared sandbox — the ratios of §4 are the
only meaningful comparison.)

Reproduce:

```bash
PYTHONPATH=python python tools/benchmark_fast.py --output results.json
pytest -m bench -s            # measurement-only bench tests
```

---

## 7. Performance policy (standing, Phase 3 gate)

This is the repository's binding performance policy.  It exists so
that speed work stays **evidence-driven** and can never trade away
research integrity or accounting exactness.

1. **Only measured hotspots are eligible for optimization.**  The
   current measured profile (§2) names exactly: `leg_cash`/`mark`
   (per-event valuation), the per-bar Python event loop, timestamp
   formatting, and `compute_metrics`.  Anything not on a measured
   profile is not a hotspot, whatever intuition says.
2. **Simpler before complex.**  A candidate optimization must first be
   the simplest change that could plausibly help (hoisting a lookup,
   replacing a per-bar construction with one array op).  Complex
   machinery (caches with invalidation, new data structures, compiled
   extensions) requires a component-level measurement showing the
   simple approaches were insufficient.
3. **No GPU / Rust / Cython / Numba-everywhere / distributed** — none
   may be introduced without a benchmark demonstrating the need
   (measured wall-time domination of the exact loop to be moved, and a
   measured prototype win on this workload).  The FAST engine
   deliberately stays pure Python + NumPy (§1).
4. **Accounting is not a valid optimization target.**  `costs`,
   `sizer`, `leg_cash` and symbol rounding are single-owner formulas
   shared with the TRUTH engine and real MT5; they may be cached only
   under a proven-identical key (bit-identical inputs → bit-identical
   outputs) and never approximated.  Any change must keep trade-for-
   trade identity with the TRUTH engine (pinned by
   `tests/test_fast_engine.py`).
5. **Claim discipline.**  No speedup claim without a measurement; an
   effect inside run-to-run noise is reported as NO MEASURABLE SPEEDUP.
   Absolute numbers are session-relative; only same-process interleaved
   ratios are decision-grade (§4.1).
6. **Current status: no further optimization work is scheduled.**  The
   measured ~1.18× A/B (§4.1) already banks the cheap wins; the
   remaining cost is the deliberate per-event accounting design.  New
   performance work requires a fresh profile justifying it.
