# AEGIS — CV / WFA STATE CONTRACT

Phase 3 Final Hardening deliverable. Defines exactly which state may
cross a fold/window boundary and which may never, for BOTH resampling
mechanisms in the research stack:

* **CPCV** — `mql5bot.pipeline.purged_cv_stage` (combinatorial purged
  cross-validation, fold-isolated);
* **WFA** — `mql5bot.optimizer.walk_forward` (continuous walk-forward on
  one scheduled engine run).

This document is the semantic contract the implementation is tested
against (`tests/test_cv_state_leakage.py`,
`tests/test_pipeline.py`, `tests/test_strategies_optimizer.py`).
Companions: `docs/STATE_MODEL.md` (state inventory of the engine),
`docs/WFA_CONTRACT.md` (WFA interval geometry),
`docs/STAGED_PIPELINE.md` (the S1–S5 funnel).

---

## 0. The distinction this document exists for

**DATA leakage** — an observation (bar, trade outcome, label) from a
fold's TEST region contributing to that fold's TRAINING score.

**STATE leakage** — the *state* created by observations outside a scored
region influencing that region's simulation, even when the observations
themselves are filtered out of the score. Removing a trade from the
scoring dataframe does NOT remove the state impact that trade had on a
full-sample simulation: equity-based sizing, daily-loss state, the
permanent drawdown halt, open positions and exposure counters all carry
forward bar by bar. The pre-hardening `purged_cv_stage` (one full-sample
backtest per configuration, trades masked per fold) suffered exactly
this leak; it was replaced by the fold-isolated design in §2.

---

## 1. Fold geometry and state model (CPCV as implemented)

Inputs: `n` bars, `n_splits` (even, ≥ 4), `n_test = n_splits // 2`,
`embargo_bars`, `purge_bars`, `warmup_bars`.

```
blocks      : _block_edges(n, n_splits) — contiguous, last absorbs remainder
test spans  : each test block expanded by embargo_bars on both sides,
              adjacent expanded blocks merged (_embargoed_test_spans)
train spans : maximal contiguous complements of the test spans
              (_complement_spans) — embargo margins belong to the TEST
              side and are never scored for training
warmup      : per scored span, the contiguous run of bars immediately
              before the span, TRUNCATED so it never reaches a raw
              (un-embargoed) test-block interior of the same fold
              (_warmup_allowed)
```

Every scored span — train or test, for every candidate configuration —
is evaluated on its **own isolated simulation**:

```
slice   = df[span_start - warm : span_end]        (contiguous)
engine  = fresh run, cold start
warm    = first `warm` bars: signals computed, NO entries (engine
          `warmup_bars`); indicator history only
score   = Sharpe of entry-bar-attributed realised pnl of trades entered
          within the span (train spans: trades exiting within the last
          `purge_bars` bars are boundary-censored and dropped)
```

### Explicit state table for one scored span

| State | At span start | During the span |
|---|---|---|
| engine initialization | fresh engine instance per span; no cross-span engine object | — |
| capital state | `cash = initial_capital` | realized pnl/fees accumulate span-locally; never imported or exported |
| position state | flat (no books, no legs) | positions opened/closed inside the slice; a trade can never outlive the span (force-closed at slice end = boundary-censored) |
| daily-loss state | `day_start_equity` initialized from span-local server days; no halt carried in | halt fires on span-local day boundaries only; resets per server day exactly like a live run |
| drawdown state | `peak = initial_capital`; no peak carried in | kill switch is span-local (permanent within the span, as in a live run) |
| strategy state | none (signals recomputed on the slice) | signal computation sees the slice + its price-only warmup; no strategy cooldown/counter state exists in the engine today (see STATE_MODEL §2) |
| parameter state | fixed candidate parameters for the whole span | no fitting, calibration, selection or hyperparameter search inside a scored span |

### What can cross a CPCV span boundary

| Allowed | Justification |
|---|---|
| **price history for indicator warmup** (non-test bars only, entries blocked) | prices are inputs, not outcomes; truncation keeps test-interior prices out of training indicators |
| **the fold definition itself** (block edges, embargo widths) | structural, data-independent |
| **candidate parameter values** | fixed ex ante by the caller; identical for every fold |

### What can NEVER cross a CPCV span boundary

| Forbidden | Enforced by |
|---|---|
| realized cash / equity | cold start per span (tested: `test_cv_state_leakage.py`) |
| open positions / carried books | cold start per span (adversarial test 4) |
| drawdown peak / permanent halt | cold start per span (adversarial test 1) |
| daily-loss halt state | cold start per span (adversarial test 3) |
| exposure counters / caps state | no books exist at span start; caps bind span-locally (adversarial test 5) |
| **another span's test-interior prices** (as warmup) | `_warmup_allowed` truncation |
| selected parameters / selection statistics of other folds | each fold selects independently on its own IS scores |
| fitted models, calibrations, feature selections | none exist inside the CV stage; folds see only `params_list` given by the caller |
| OOS-certification results | S3 never touches the OOS dataset or `OosRegistry` |

### Adversarial guarantee (tested)

For every fold whose train spans exclude a set of bars `M`, the fold's
IS scores and its selected configuration are an exact function of
`(train spans + their truncated warmup slices, candidate params)` —
modifying `M` (prices *or* outcomes) cannot change them. The test suite
modifies only test regions (huge profit, huge loss, halt triggers) and
asserts `selected`/`is_scores` are bit-identical while `oos_sharpe`
changes. Each trigger test also demonstrates that a full-sample
stateful backtest + trade masking (the pre-hardening design, replicated
inline as `_full_sample_is_scores`) *does* change its masked training
scores — the leak these tests exist to catch.

---

## 2. WFA boundary semantics (contrast)

WFA is a *different, documented policy*
(`docs/WFA_CONTRACT.md`): ONE continuous scheduled engine run; account
state (cash, equity, open positions, drawdown peak, daily-loss state)
**carries across OOS boundaries** because that is the production
question ("how does the system behave as time passes"). Selection
however is window-local:

| Crosses a WFA OOS boundary | Never crosses a WFA OOS boundary |
|---|---|
| runtime account state (cash, equity) | selected parameters of *later* windows |
| open positions (policy: continuous run) | model fitting / calibration (none exists; when ML arrives: fit inside the window's train interval only) |
| realized cash | training statistics of later windows |
| drawdown peak | feature-selection results |
| daily risk state | hyperparameters of later windows |
| released test data (earlier windows' OOS is later windows' history) | the *current* window's OOS data into its own selection (embargo/purge enforce) |

The invariant both mechanisms share: **research/training knowledge never
flows backwards in time and never flows from an evaluation region into
the selection that produced it.**

---

## 3. CPCV must never accidentally reuse

1. **Fitted parameters** — the stage receives `params_list` and evaluates
   each candidate on every fold; no per-fold fitting exists. If a future
   phase adds per-fold fitting, the fit must run on the fold's train
   spans only and be re-run per fold (no shared fit object).
2. **Cached training outputs** — the pipeline cache (`run_stages`)
   keys S3 by `(strategy, survivor params, dataset version, n_splits,
   embargo_bars, purge_bars, warmup_bars, seed, run_kwargs)`. Changing
   ANY fold-geometry input produces a different cache key. Cache entries
   store manifests, never live engine state.
3. **OOS-derived state** — S3 operates only on the development frame.
   The OOS frame is passed exclusively to `oos_stage` (S5), never to
   screening, cost-stress or CV. The Optuna objective (S-optional)
   receives the development frame only and is guarded against OOS
   reuse (see `optuna_optimize`'s `oos_guard_df` and
   `tests/test_optuna_hardening.py`).
