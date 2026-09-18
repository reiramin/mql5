# AEGIS exit-gate report — META REALISM / MULTI-ASSET / REGIME / DRIFT (Phase 32)

Mission: make `MetaPortfolioEngine` represent the same causal,
multi-asset, risk-aware process that will eventually influence MT5 —
**without ML, without new strategies, without parameter optimization,
without chasing profit**. Principle held throughout: *do not make Meta
look smarter — make it behave like the real portfolio.*

**Verification at exit (this commit):** full test suite `pytest tests`
exit 0 — 823 collected, 0 failed (baseline at mission start: 776
passed / 1 skipped; +61 gate tests added since), `ruff check python
tests` clean. HEAD: see `git log` — mission delivered across commits
`169a16d`…(this commit) on `arena/01a070b0-mql5bot`. Push pending:
the sandbox GitHub token expired mid-mission (owner: reconnect GitHub
in Arena; commits are safe locally).

## The five limitations — resolved

| # | Limitation at mission start | Resolution |
|---|------------------------------|------------|
| 1 | Single-symbol `GEN` engine | Multi-book `symbol@strategy` contexts on one shared account; per-book streams; symbol/strategy attribution (`tests/test_meta_multi_asset.py`) |
| 2 | Caller-supplied static specs | `InstrumentContext` with explicit `SymbolSpec`+`CostConfig`+conversion+margin; no fallback on the production path; legacy df+specs labelled SYNTH diagnostic |
| 3 | Static regime (hardcoded TREND_UP) | `regime_feed.regime_snapshot` — causal 7-label engine, `regime_as_of` journaled per decision (`asof-1.1`) |
| 4 | Static drift (score 0) | `drift_feed.drift_snapshot` — causal per-book drift, HEALTHY/MILD/SEVERE/UNKNOWN (`asof-1.0`); severe ⇒ hard zero |
| 5 | Incomplete telemetry | Weight journals carry regime+drift provenance; `manifest()` carries git commit, dataset+spec digests, versions, config hash, seed, schedule hash, ineligible journal |

## SOFTWARE_PASS — 27 exit conditions

| # | Condition | Evidence |
|---|-----------|----------|
| 1 | Shared account across symbols/books, one equity path | `test_shared_account_one_equity_and_book_attribution` |
| 2 | Portfolio heat binds across symbols (not per-symbol only) | `test_portfolio_heat_cap_binds_across_symbols` |
| 3 | Conversion: identity when currencies equal (even with bogus input) | `test_conversion_identity_when_currencies_equal`, `test_r1_*` |
| 4 | Conversion: explicit rate enters risk math + manifest | `test_conversion_explicit_rate_scales_pnl` |
| 5 | Conversion: missing pair ⇒ INELIGIBLE, journaled, never fake 1.0 | `test_conversion_missing_context_is_ineligible`, F4 |
| 6 | Per-symbol volume grids respected in LIVE fills | `test_per_symbol_volume_grids_in_live_fills` |
| 7 | Spec echo + dataset digests in manifest | `test_manifest_echoes_specs_datasets_versions` |
| 8 | Per-book independent signal streams | `test_per_book_independent_signal_streams` |
| 9 | All 7 regime labels reachable at the feed | `test_regime_labels_all_seven_reachable` |
| 10 | Regime causality: future mutation cannot change labels | `test_regime_causality_future_mutation_cannot_change_label` |
| 11 | Decision journals carry regime+drift provenance | `test_decision_journal_carries_regime_drift_provenance` |
| 12 | Drift statuses HEALTHY/MILD/SEVERE/UNKNOWN reachable | `test_drift_statuses_reachable` |
| 13 | Drift causality: future trades cannot change snapshots | `test_drift_causality_future_trades_cannot_change_snapshot` |
| 14 | Severe drift ⇒ hard zero for that book | `test_severe_drift_hard_zeroes_book` |
| 15 | Meta weights deterministic + bounded on fresh layers | `test_meta_weights_deterministic_and_bounded` |
| 16 | Snapshot NaN conventions (finite, strictly pre-t, honest) | `test_returns_snapshot_nan_conventions`, `test_r5_*` |
| 17 | Correlation-group cap rejects cross-symbol adds | `test_corr_group_cap_rejects_cross_symbol` |
| 18 | Shared margin basis; exhaustion rejects adds | `test_shared_margin_exhaustion_rejects_entry`, F3 |
| 19 | Netting merges/offsets same-symbol books; hedging keeps them separate | `test_netting_merges_same_symbol_books`, `test_hedging_keeps_same_symbol_books_separate` |
| 20 | Single-position netting == hedging | `test_single_position_netting_equals_hedging` |
| 21 | Weight update = new decisions only (no retro resize/close) | `test_zero_weight_on_one_symbol_leaves_other_untouched` |
| 22 | Metamorphic invariants (permutation, time shift, cap monotonicity, cost monotonicity, cert zeros, input independence, restart) | `tests/test_meta_metamorphic.py` (9 tests) |
| 23 | Failure matrix: every injection ⇒ SAFE HOLD / documented baseline / journaled refusal | `tests/test_meta_failure_matrix.py` (F1–F7) + corrupt-frame gate |
| 24 | Replay conventions + restart equivalence + full manifest | `docs/META_REPLAY_CONVENTIONS.md`, `test_restart_at_rebalance_reproduces_suffix` |
| 25 | Correlation conventions documented AND pinned to code | `docs/CORRELATION_CONVENTIONS.md`, `tests/test_doc_consistency.py` |
| 26 | Perf profiled at 1×3 / 3×5 / 6×10 (no optimization) | `docs/META_PERF_BENCHMARK.json`, `tools/meta_perf_benchmark.py` |
| 27 | Regime matrix measured under a frozen config, no tuning | `docs/REGIME_MATRIX.{md,json}`, `tools/meta_regime_matrix.py` |

Supporting gates: doc-consistency suite (16 pins incl. forbidden-claims
scan), red team round 2 (R1–R5: 2 fixed, 3 verified-safe pins),
real-basket runner honestly reporting 6/6 UNAVAILABLE (exit 2; VIX
never substitutes).

## Key measurements

- **Perf** (synthetic 2880-bar frames, 3 decisions): 1×3 = 182 ms/decision,
  3×5 = 359 ms, 6×10 = 672 ms — linear ~61–72 ms/book, dominated by
  per-book as-of statistics (canonical path, unoptimized by rule).
- **Regime matrix** (frozen config): 24 rebalances; labels live —
  RANGE/TRANSITION dominant on synthetic data, TREND_UP once, no
  TREND_DOWN/UNKNOWN observed (data property; 7-label reachability is
  pinned at feed level). Per-regime stats in REGIME_MATRIX.md.
- **Discovery pinned as semantics**: book-id sort order arbitrates
  shared-account budget when caps bind ⇒ renames that reorder are a
  NEW run (audit register); NaN frames refused at the context boundary
  (would crash tick math); execution-line identity is
  `(symbol, engine_strategy)`.

## Carried red-team status

Round 1 (prior gate): 10 findings, 3 HIGH fixed, 0 CRITICAL.
Round 2 (this mission): R2 duplicate execution-line error moved to
construction; R3 drift regime-key mismatch fixed (latent; no numeric
change); R1/R4/R5 verified safe and pinned. 0 open CRITICAL/HIGH.

## Empirical gate — unchanged, owner-owned (Meta stays DISABLED)

This SOFTWARE_PASS does NOT promote anything. Meta remains DISABLED
pending: (1) MT5 compile + roundtrip truth (owner), (2) real-basket
validation via `tools/meta_real_basket.py` with owner specs/provenance
(currently 6/6 unavailable — sandbox), (3) shadow run, (4) OOS rerun
under `docs/META_OOS_CANONICAL.md` with the standing rule: bootstrap
ΔSharpe CI straddling zero ⇒ no promotion (prior gate: CI
[−0.1121, +0.2173], PSR 0.4367 ⇒ EW retained), (5) owner utility
decision. Certification states were never collapsed; **META ≤ EW ⇒
retain EW** stands.

## Mission-rule compliance

No ML/NN anywhere; no new strategies (registry fixed at 3; books vary
params); no Meta parameter tuning (matrix config frozen pre-results);
no profit chasing (several synthetic runs lose money — reported as
measured). Forbidden words appear nowhere without their gates
(doc-consistency scan).
