# AEGIS — WFA / CPCV FORMAL REVIEW (Phase 3 integrity gate)

Cross-audit of `docs/CV_STATE_CONTRACT.md`, `docs/WFA_CONTRACT.md` and
`docs/STATE_MODEL.md`.  Result: **the three documents agree; no
contradiction exists between CPCV fold isolation, rolling WFA
selection, continuous WFA state carry and per-window parameter
recomputation.**  The governing rule everywhere is:

> **STATE CARRY ≠ KNOWLEDGE CARRY.**
> Runtime account state may move per the documented boundary policy;
> research knowledge (selections, fits, statistics) may never leak from
> an evaluation region into the selection that produced it, nor
> backwards in time.

---

## 1. State matrix

Legend — CPCV fold = one scored span of
`pipeline.purged_cv_stage` (fold-isolated, cold start).  Continuous WFA
= one scheduled `PortfolioEngine` run over the full sample
(`optimizer.walk_forward`, boundary policy `CARRY_ALLOWED`).

| Item                   | CPCV Fold | Continuous WFA |
| ---------------------- | --------- | -------------- |
| cash                   | cold start: `initial_capital` at every span start; never crosses | carries (`CARRY_ALLOWED`) |
| equity                 | rebuilt span-locally from `initial_capital` | one continuous curve; carried |
| open positions         | none at span start (flat); a trade cannot outlive its span (force-closed at slice end = boundary-censored) | carried across `b0(w)` boundaries; never force-closed, never re-priced (`FORCE_FLAT` not implemented) |
| drawdown peak          | reset to `initial_capital` per span; kill switch span-local | carried (permanent within the run) |
| daily-loss state       | span-local server days; no halt carried in | carried; resets per server day per `DayClock` |
| strategy runtime state | none (signals recomputed on slice + truncated price-only warmup) | carried in the run's books/legs; no cooldown/counter state exists today (STATE_MODEL §2) |
| parameters             | fixed candidate set given ex ante; identical for every fold | frozen per segment from `b0(w) - 1`; **recomputed by `grid_search` on every window's own embargoed IS slice** |
| feature selection      | none inside a fold; caller-provided inputs only | none today; when ML arrives: inside each training window only (STATE_MODEL §3) |
| model fit              | none inside a fold | none today; same rule as feature selection |
| calibration            | none inside a fold | none today; same rule |
| OOS results            | per-fold OOS scores are development diagnostics; never re-enter selection; never touch S5 | per-window OOS metrics reported; never re-enter selection; certification is S5-only |

## 2. Consistency checks (all verified)

1. **Selection isolation agrees.**  WFA_CONTRACT §3: every candidate
   backtest inside `grid_search` starts from `initial_capital` within
   the IS slice — selection is state-isolated by construction, matching
   the CPCV cold-start rule.  CPCV is the stricter generalization
   (isolation per scored span, not just per candidate run).
2. **Knowledge never carries backwards.**  A later window's frozen
   params influence only NEW decisions (WFA_CONTRACT §4); CPCV folds
   are selected independently (each fold's IS scores come only from its
   own spans).
3. **Parameter recomputation.**  Both contracts require per-window
   recomputation: WFA re-runs `grid_search` per window on that window's
   train interval; CPCV performs no fitting at all (fixed candidate
   set).  Neither caches selections across windows/folds
   (CV_STATE_CONTRACT §3).
4. **Purge/embargo semantics agree.**  WFA: selection never scores the
   embargo margin and boundary-censored trades are purged.  CPCV: the
   embargo margin belongs to the TEST side of the fold; purge is
   boundary censoring at train-span ends.  Same principle, applied to
   each mechanism's geometry.
5. **Warmup.**  WFA: registry defaults before the first OOS start,
   excluded from aggregates; per-candidate indicator warmup is
   slice-local.  CPCV: price-only warmup, entries blocked, truncated so
   it never reaches a raw test-block interior.  Consistent: warmup
   prices are inputs, never outcomes.
6. **STATE_MODEL ground rule** ("account state carries only per the
   boundary policy; research knowledge never") is exactly the
   STATE CARRY ≠ KNOWLEDGE CARRY rule instantiated twice: WFA chooses
   `CARRY_ALLOWED`, CPCV chooses full isolation.  Both are explicit
   policies — neither is accidental.

## 3. Enforcement map

| Guarantee | Where enforced | Tests |
|---|---|---|
| CPCV span isolation | `purged_cv_stage` isolated runs + `_warmup_allowed` truncation | `tests/test_cv_state_leakage.py` (14 + 7-scenario matrix), `tests/test_pipeline.py` |
| WFA selection isolation | `grid_search` on the IS slice (fresh runs from `initial_capital`) | `tests/test_strategies_optimizer.py` |
| WFA state carry is the documented policy | one scheduled run in `walk_forward` | `tests/test_scenarios_matrix.py::test_scenario_wfa_state_carries_across_oos_boundary`, `tests/test_metamorphic.py::test_g_*` |
| OOS results never re-enter selection | S5 one-look registry + stage wiring | `tests/test_oos_registry.py`, `tests/test_pipeline.py` |

## 4. Known, documented non-equivalences (by design)

* A cold-split re-run of a later segment is NOT equal to the continuous
  run's continuation: carried equity reference, drawdown peak and open
  positions do not exist in the cold start.  Pinned quantitatively in
  `tests/test_metamorphic.py::test_g_cold_split_divergence_is_documented_state_reset`.
* CPCV fold scores are NOT comparable to continuous-run window scores:
  different state policies answer different questions (cross-validation
  robustness vs live-like trajectory).  Neither may substitute for the
  other in certification (S5 remains the only certification look).

---

## Phase 7/8 exit gate — mandated leakage-vector coverage map

Every vector mandated by the AEGIS Phase 7/8 exit gates, with its pinned
test. All green at commit `1e6f466` (suite: 722 passed, 1 skipped).

| Mandated vector | Pinned by |
|---|---|
| monotonic timestamps | `data.sort_index` on load; disorder → audit `timestamp_disorder` (`test_inv_data_2`, `test_inv_data_3`); equity strictly time-sorted (`test_inv_pos_2`) |
| bar-close availability (signals use only closed bars) | `test_indicator_prefix_immune_to_future_mutation` (all indicators), `test_strategy_signal_prefix_immune_to_future_mutation` (all strategies) |
| next-open execution convention | engine entries fill at the bar's open (`test_variable_spread_changes_entry_fill`, `test_reject_mask_and_gap_block_entries` pin open-priced fills) |
| warmup | `test_warmup_never_reaches_test_interior`, `test_engine_warmup_blocks_entries_and_state` |
| rolling windows | indicator prefix immunity suite (rolling std, EMA, ATR, …) |
| regime lookback | `test_regime_features_depend_only_on_their_span` |
| WFA purge/embargo | `test_embargo_spans_expand_merge_and_train_complement`, `test_fold_training_score_is_a_function_of_its_span_slice_only` |
| CPCV span isolation | `test_modified_test_segment_cannot_change_training`, `test_cpcv_pbo_known_good_low_known_bad_high` |
| future injection → OHLC | `test_future_only_perturbation_matrix` (7-scenario master matrix) |
| future injection → spread | `test_future_spread_injection_cannot_change_earlier_fills` (this phase) |
| future injection → reject/execution state | `test_future_reject_mask_cannot_change_earlier_entries` (this phase) |
| future injection → regime/vol/corr/feature | prefix-immunity suite + `test_regime_features_depend_only_on_their_span`; meta-input surfaces covered by `test_meta_metamorphic.py` weight-property pins |
| TRAIN/PURGE/EMBARGO/WARMUP/OOS geometry | `test_embargo_spans_*`, `test_stage_records_state_model_and_fold_geometry` |
| TRAINING KNOWLEDGE resets (state ≠ knowledge) | adversarial state suite `test_adversarial_1..5` (drawdown/equity-sizing/daily-loss/open-position/exposure-cap) |
| open-position boundary policy | `test_adversarial_4_open_position_carry`; boundary policy documented in §1 state matrix above |
| future-only mutation changes OOS, never training selection | `test_future_only_perturbation_matrix` + `test_modified_test_segment_cannot_change_training` |

Exit statement: **every mandated vector has a machine-pinned test; the
future-injection surface covers OHLC, spread, execution-reject state,
regime, per-span features and the 7 equity-path scenarios.** Phase 7/8
exit gates: MET (Python side; MT5-side truth remains owner-gated).
