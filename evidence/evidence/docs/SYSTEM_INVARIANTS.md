# SYSTEM INVARIANTS — Mission 3 / AEGIS Phase 1

Machine-checkable statements that must hold for every run of this repository's
Python engine, meta layer, data layer and tooling. Each invariant has a stable
ID, an exact statement, a tolerance, and a pinned regression test. A change
that violates any invariant is a defect **by definition** — regardless of
whether PnL improves.

Status legend: `tested` = pinned in `tests/test_system_invariants.py` and
passing at the commit recorded below. Invariants live **above** individual
tests: a new execution path (engine, meta, data, tooling) that cannot satisfy
them must not be merged.

Baseline: commit `0bf5724` — 686 passed, 1 skipped, ruff clean.

## Tolerance conventions

| Area | Tolerance |
|---|---|
| Equity / accounting identities | `1e-6` absolute (per-currency) |
| Meta weights / allocation vectors | `1e-9` absolute |
| Volume bounds | exact broker `volume_min` / `volume_step` grid |
| Digests / manifests | byte-exact |

## Accounting (INV-ACC)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-ACC-1 | `starting_equity + Σ realized trade pnl == ending_equity` for every run. | 1e-6 | `test_inv_acc_1_equity_identity` |
| INV-ACC-2 | `Σ trade pnl == reported net_profit`; each realized trade is counted exactly once (no double-count on restart/replay). | 1e-6 | `test_inv_acc_2_realized_pnl_counted_exactly_once` |
| INV-ACC-3 | Per-trade `pnl == direction·(exit−entry)·lots·contract_size − fees` under BASE/STRESSED cost kwargs; spread and slippage are embedded in fill prices, never double-charged. | 1e-6 | `test_inv_acc_3_fees_charged_exactly_once` |
| INV-ACC-4 | The ZERO cost profile charges exactly zero fees/costs on every trade. | exact 0 | `test_inv_acc_4_zero_profile_charges_nothing` |

## Position / volume (INV-POS)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-POS-1 | Every filled volume lies on the broker volume grid: `volume_min ≤ lots`, `lots ≤ max_lots`, and `lots` is a positive multiple of `volume_step` (floored, never overshot). | exact grid | `test_inv_pos_1_volume_bounds` |
| INV-POS-2 | The equity series is finite, strictly positive and time-sorted (monotonic timestamps). | — | `test_inv_pos_2_equity_series_well_formed` |
| INV-POS-3 | Every trade direction is exactly `long` or `short` — no residual/unknown sides. | — | `test_inv_pos_3_sides_are_long_or_short` |

## Risk (INV-RISK)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-RISK-1 | Harsher execution profiles (BASE→STRESSED→SEVERE→EXTREME) never improve net profit on the same inputs (empirical, fixture-pinned). | 1e-9 | `test_inv_risk_1_cost_profiles_only_worsen` |
| INV-RISK-2 | Every meta weight is finite and in `[0, 1]` for ANY input — including NaN/inf/hostile allocations. | exact | `test_inv_risk_2_meta_weights_bounded_under_hostile_inputs` |
| INV-RISK-3 | The EA seam arithmetic (`apply_seam`) can only shrink or preserve the approved risk budget — reduce-only, floor-and-drop on the volume grid. | exact grid | `test_inv_risk_3_meta_reduce_only_lot_grid` |
| INV-RISK-4 | Doubling `risk_percent` exactly doubles the raw size budget. Behavioral pin: the FIRST trade (identical initial equity in both runs) satisfies `base ≤ doubled ≤ 2·base + volume_step`; subsequent trades compound on realized equity (documented divergence — the fixture bounds the ratio coarsely), and the structural guarantee is the sizer floor against the approved budget. | +1 volume_step | `test_inv_risk_4_risk_percent_never_overshoots_approval` |

## Meta layer authority (INV-META)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-META-1 | A strategy without a valid certification gets **exactly zero** weight in every mode (hard zero can never become positive). | exact | `test_inv_meta_1_hard_zero_never_positive_any_mode` |
| INV-META-2 | Total source failure falls back to equal weight and is flagged (`fallback=True`); fallback never resurrects a zeroed strategy. | exact | `test_inv_meta_2_fallback_never_resurrects` |

## Stops (INV-STOP)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-STOP-1 | The sizing path returns ZERO lots with `REASON_NO_VALID_STOP` when no valid stop distance exists — no position is ever opened without a validated SL. | — | `test_inv_stop_1_engine_refuses_entry_without_valid_stop` |
| INV-STOP-2 | The Python SlGuard mirror exposes the post-fill SL verification verdict ladder (`sl_verdict`), and every remediation outcome is a refusal or a corrective action — never a naked position. | — | `test_inv_stop_2_slguard_remediation_ladder_present` |

## Failure safety (INV-FAIL)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-FAIL-1 | A rejected allocation returns the ORIGINAL weights and mutates nothing. | exact | `test_inv_fail_1_rejected_allocation_mutates_nothing` |
| INV-FAIL-2 | Corrupt/truncated meta state raises (`MetaFileError`) instead of being silently repaired. | — | `test_inv_fail_2_corrupt_state_refused` |
| INV-FAIL-3 | Any internal exception surfaces as a SAFE HOLD decision (zero influence), never an aggressive fallback. | — | `test_inv_fail_3_internal_failure_is_safe_hold` |

## Determinism (INV-DET)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-DET-1 | Identical inputs ⇒ identical equity curve and trade ledger (byte-level). | exact | `test_inv_det_1_engine_runs_are_reproducible` |
| INV-DET-2 | Same inputs/versions ⇒ byte-identical meta decision journals. | exact | `test_inv_det_2_meta_decisions_and_journals_reproducible` |
| INV-DET-3 | Identical run manifests ⇔ identical run outputs (manifest equivalence). | exact | `test_inv_det_3_manifests_reproducible` |

## Versioning / provenance (INV-VER)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-VER-1 | Every run manifest carries the full semantic identity: strategy, params, data digest, window, cost profile, code versions. | — | `test_inv_ver_1_manifest_repro_block_required` |
| INV-VER-2 | Changing any identity component (params, window, cost profile, data digest) changes the run identity — no colliding manifests. | — | `test_inv_ver_2_oos_identity_components_participate` |
| INV-VER-3 | The canonical cost-profile ladder escalates field-by-field (rates non-decreasing, gap-fraction cap non-increasing; EXTREME strictly exceeds SEVERE where required). | exact | `test_inv_ver_3_cost_profiles_fieldwise_monotone` |

## Data layer (INV-DATA)

| ID | Statement | Tolerance | Test |
|---|---|---|---|
| INV-DATA-1 | The dataset content digest is deterministic, order-stable and collision-checked (canonical JSON, sha256). | exact | `test_inv_data_1_dataset_digest_is_stable_identity` |
| INV-DATA-2 | The audit flags every corruption class: duplicate timestamps, disorder, impossible OHLC, non-positive/non-finite prices, missing columns, empty frames. | — | `test_inv_data_2_quality_audit_catches_corruption` |
| INV-DATA-3 | The committed REAL dataset (VIX daily) is audited AS RAW (known corruption reported, never hidden), cleaned only via an explicit change log, and its manifest sha256 gate is enforced. | — | `test_inv_data_3_real_dataset_audited_then_explicitly_cleaned` |

## Authority model (non-invertible)

`STRATEGY signals → META/PORTFOLIO allocation → RISK + EXECUTION final veto.`
Never: Python→live OrderSend; ML→direct trading; Meta or Strategy bypassing the
Risk Engine. INV-META-*, INV-RISK-3 and INV-STOP-* are the machine pins for
this ordering; Phase 2 (`MQL5_EXECUTION_AUDIT`) extends the audit to the EA side.

## Exit gate — Phase 1

- [x] ≥ 20 invariant tests, each mapping to a stable ID: **27 tests / 28 IDs**
      (INV-RISK-4 and INV-POS-1 share the volume-grid pin; all `tested`).
- [x] Full suite green: 686 passed, 1 skipped (commit `0bf5724`).
- [x] ruff clean.
- [x] This document lists ID + exact statement + tolerance + test name.
