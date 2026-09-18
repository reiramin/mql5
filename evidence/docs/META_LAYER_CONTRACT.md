# META LAYER — CONTRACT

**Contract version: 1.1.1** (2026-09-05).  Changelog: 1.1.0 → 1.1.1 — §5.2 clarified: the Meta Layer owns ALLOCATION budgets only; the daily-loss limit and drawdown kill-switch are Risk Engine authorities the layer never computes, receives as a target, or overrides (DECISIONS ML-9).  1.0.0 → 1.1.0 —
correlation-penalty simultaneity (order independence), classified
missing-data policy (global vs per-strategy), all-zero / hard-zero
semantics, explicit normalization pipeline, determinism clauses,
eligibility taxonomy, activation states, daily weight-change limit.
Every change is documented in `docs/DECISIONS.md` (entries
ML-1..ML-7).  No clause is dropped; all corrections preserve the
safety philosophy (Risk Engine final authority; hard zeros never
resurrected).

The implementation built on this contract is specified in
`docs/META_LAYER_IMPLEMENTATION_SPEC.md` and validated in
`docs/META_LAYER_VALIDATION.md`.

---

## 1. Purpose and non-purpose

The Meta Layer combines the outputs of independently certified
strategies into portfolio-level allocation decisions.  It is an
ALLOCATION layer only.  It is NOT:

- a strategy (it generates no entries/exits of its own);
- a risk authority (it sits strictly UNDER the Risk Engine);
- a certified entity (it inherits, never upgrades, the weakest
  certification state among its inputs).

## 2. Inputs (per strategy, per decision timestamp)

| input | meaning | source of truth |
|---|---|---|
| `gate_weight` | 0..1 base weight from the strategy's certification state and gates | certification record (`OosRegistry` entry + status model) |
| `regime_fit` | 0..1 how well the current regime matches the strategy's declared {allowed, preferred, forbidden} regimes | strategy metadata + regime classifier |
| `performance_factor` | realized, out-of-sample attribution-derived factor (0..cap) | OOS-side attribution only — NEVER in-sample or training-window performance |
| `correlation_penalty` | 0..1 multiplier penalizing overlapping exposure, computed from a SIMULTANEOUS snapshot: the historical return-correlation matrix of ALL eligible candidates × the PREVIOUS decision's final weights (equal prior when absent) — never a sequential pass over "already-weighted" strategies | historical strategy return streams (no lookahead) + previous persisted allocation |
| `drift_factor` | 0..1 multiplier decaying weight as live behavior drifts from its certified behavior | drift monitor (documented separately when built) |

All inputs are non-negative finite scalars with documented sources and
bounds.  NaN/±inf inputs are refused or converted to the documented
fallback — never passed through.  A missing source is CLASSIFIED, not
neutralized (§5.3a):

* **REQUIRED source missing** (certification/gate record) → the
  strategy is INELIGIBLE (`UNCERTIFIED`).  No neutral pass.
* **OPTIONAL source missing for ONE strategy** (performance,
  correlation coverage, drift) → bounded conservative fallback value
  (the same factor value a zero-observation strategy receives),
  flagged in the journal.  Never neutral 1.0.
* **OPTIONAL source missing for ALL strategies** (global source
  failure) → the documented GLOBAL FALLBACK of §5.3 applies.

## 3. Weight computation

    weight(strategy, t) = gate_weight
                        × regime_fit
                        × performance_factor
                        × correlation_penalty
                        × drift_factor

The weight is the PRODUCT of the five factors — no learned or tuned
mixing, no hidden coefficients inside the product.  After the product
a DETERMINISTIC PIPELINE produces final weights (§3.1); it never
re-ranks, re-mixes, or optimizes.

### 3.1 Normalization pipeline (normative)

    raw_score_i  (the five-factor product)
      → eligibility mask      (ineligible ⇒ excluded BEFORE normalize)
      → share_i = raw_i / Σ_eligible raw_j   (budget share, Σ = 1)
      → per-strategy cap      (may only reduce; capped mass is
                               redistributed ONLY into uncapped
                               eligible strategies, never into
                               hard/soft zeros)
      → gross budget scaling  (× gross_exposure_cap ≤ 1)
      → portfolio constraints (symbol/currency/position-count/heat —
                               only reduce)
      → daily weight-change limit (only move toward the new weight by
                               the configured per-decision maximum)
      → final weight

Normalization redistributes a fixed budget proportionally to raw
scores; caps, constraints and the change limit only reduce or freeze.
A zero (hard or soft) can never receive redistributed mass, and no
path can turn 0 into a positive weight (no epsilon smoothing).

## 4. Combination modes (exactly four)

| mode | behavior |
|---|---|
| `independent` | each strategy trades its own allocation; no cross-interaction (current behavior) |
| `weighted_netting` | positions of the same symbol are combined netting-style, sized by the product weights (DEFAULT) |
| `vote` | a trade fires only when the weighted vote of eligible strategies agreeing on direction meets the configured threshold |
| `best_of_regime` | per regime, only the highest-weight eligible strategy trades |

Default mode: **`weighted_netting`**.  Mode selection is
configuration, pinned in the run manifest; it can never be chosen
per-decision by the layer itself.

## 5. Safeguards (all mandatory, non-negotiable)

1. **Hard zero.**  Any factor equal to zero produces weight zero —
   a strategy that is uncertified, regime-forbidden, drift-expired,
   or correlation-capped cannot trade through any mode.  No
   epsilon-resurrection of zero weights.
2. **Exposure clamp (ALLOCATION budgets ONLY).**  The layer's total
   contribution is clamped by ITS OWN allocation budgets —
   `gross_exposure_cap`, `max_strategy_weight`, `max_positions`,
   `max_weight_change` — applied BEFORE orders reach the Risk Engine,
   able only to reduce exposure.  These are NOT risk authorities: the
   daily-loss limit, the drawdown kill-switch, per-trade risk %,
   margin safety and every hard exposure limit are computed and
   enforced by the Risk Engine ALONE.  The Meta Layer never computes,
   receives as a target, estimates, or overrides any of them; the
   words "daily loss" and "drawdown" name no input, parameter, or
   branch anywhere in the layer.  (Decision ML-9; see
   docs/META_LAYER_SEMANTICS_REVIEW.md for the four-control
   distinction.)
3. **Equal-weight fallback (GLOBAL ONLY).**  If an OPTIONAL factor
   source is unavailable for ALL strategies simultaneously (global
   source failure, e.g. the drift monitor is down), the layer falls
   back to EQUAL weights across ELIGIBLE strategies and marks the
   decision record `fallback=equal_weight` (with the failing source
   named).  It never falls back to "last known good weights".
   3a. **All-zero vs fallback (binding distinction).**  A zero factor
   with its source PRESENT is a HARD ZERO: the strategy is ineligible
   and receives nothing in every mode; it is never resurrected by any
   fallback or redistribution.  If every candidate is hard-zero the
   decision is a SAFE HOLD (no allocation), not equal weight.  The
   equal-weight fallback exists ONLY for global source failure, when
   scores would be uncomputable for reasons unrelated to the
   strategies themselves.
4. **Explainability.**  Every allocation decision records all five
   factor values, the product, the mode, and any clamp/fallback
   that fired, in the decision journal (human-readable, replayable).
5. **OOS validation.**  The Meta Layer's combination policy is
   itself validated out-of-sample (purged CPCV + one-look OOS
   through the same pipeline discipline as strategies) before it
   may influence certified allocations.  Tuning combination
   hyperparameters on the certification slice is forbidden.
6. **Certification inheritance.**  The portfolio inherits the WEAKEST
   certification state among its contributing strategies.  The layer
   can never upgrade a strategy's state, resurrect a
   `NOT_ELIGIBLE`/`FAILED` strategy, or route around a blocked
   pipeline stage.

## 6. Hard boundaries (the layer can NEVER)

- bypass the Risk Engine (every order still passes the full risk
  path);
- remove, widen, or skip a stop-loss (SL manipulation is reserved
  to the audited SlGuard remediation ladder);
- increase any hard risk limit (per-trade risk %, daily loss,
  drawdown kill-switch thresholds, exposure caps) — the layer may
  only consume headroom, never expand it;
- trade while the kill-switch is latched, for any mode or vote
  outcome;
- emit orders outside the canonical engine seam.

## 7. Acceptance criteria for any future implementation

- the five factors and four modes exist as specified, with the
  product formula and `weighted_netting` default pinned by tests;
- safeguards 1–6 are each pinned by a dedicated test (including
  "zero factor ⇒ zero weight in every mode" and "fallback is
  equal-weight and journaled");
- the layer's decisions are reproducible: same manifests, factors
  and mode ⇒ byte-identical decision journal;
- out-of-sample validation of the combination policy exists BEFORE
  any allocation influence (state-isolation matrix like Phase 5's);
- the hard boundaries are enforced structurally (order flow cannot
  reach the engine except through the risk path) — tested, not
  asserted.

---

*Status: **IMPLEMENTED — SOFTWARE PASS**; **EMPIRICAL VALIDATION:
SHADOW-READY** (software replay on real VIX data, META≈EQUAL_WEIGHT,
activation DISABLED, EW standing policy — see
`docs/META_LAYER_VALIDATION.md` and `docs/META_PRODUCTION_VALIDATION.md`).
MT5 compile / Strategy Tester / demo evidence: **PENDING (owner)**.
This status supersedes the earlier contract-only placeholder note, which described
the repository state before the implementation landed
(`python/mql5bot/meta_layer.py`, `mql5/Include/Mql5Bot/Allocation.mqh`,
consumer wiring in `Mql5Bot.mq5`).


## 8. Determinism (normative)

- Every list is ordered by `strategy_id` ascending (lexical, byte
  order); tie-breaks are `strategy_id` ascending unless a mode
  documents otherwise.  Dictionary insertion order is never
  observable.
- Same inputs (factors, config, previous state, timestamp) ⇒
  byte-identical serialized journal (canonical JSON:
  `sort_keys=True`, compact separators, fixed float repr).
- All arithmetic is plain IEEE-754 double; no randomness, no
  parallel-reduction reordering, no hidden rounding before
  serialization.
- Weights serialize rounded to 10 decimal places; internal arithmetic
  is unrounded.

## 9. Activation states (normative)

`DISABLED` (default) → `SHADOW` → `DEMO` → `LIVE_SMALL` → `ACTIVE`.
Transitions are explicit, operator-issued, audited journal events; no
automatic transition exists in either direction.  In every state the
layer computes full decisions; only in `LIVE_SMALL`/`ACTIVE` may an
allocation influence live sizing — and even then strictly through the
Risk Engine.

## 10. Daily weight-change limit (normative)

Between two consecutive decisions, a strategy's final weight may move
by at most `max_weight_change` (configuration, default 1.0 = off) in
either direction relative to the previous persisted decision;
excess movement is clamped with journal reason `WEIGHT_CHANGE_LIMIT`.
Eligibility loss (hard zero) always takes effect immediately and is
never slowed by this limit; re-entry after ineligibility restarts
from zero weight.
