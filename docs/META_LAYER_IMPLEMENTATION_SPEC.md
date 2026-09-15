# META LAYER — IMPLEMENTATION SPEC (contract v1.1.0 → code)

Normative for `python/mql5bot/meta_layer.py` and its tests.  The
contract (`docs/META_LAYER_CONTRACT.md` v1.1.0, decisions ML-1..ML-7)
is the authority; this document pins the exact semantics the code
implements and the tests pin.

## 0. Architecture (mandated pipeline, no shortcuts)

    collect eligible candidate signals (strategy_id ascending)
      → collect factor inputs (all sources, timestamped, validated)
      → pairwise correlation matrix (historical, trailing window)
      → raw penalty vector  (ONE simultaneous matrix operation)
      → raw scores          (five-factor product)
      → eligibility mask    (BEFORE normalization)
      → deterministic normalization + caps + redistribution
      → portfolio constraints (only reduce)
      → daily weight-change limit (vs persisted previous weights)
      → combination mode (config-fixed)
      → canonical journal + allocation serialization

No step reads another step's partially-updated current weights.  The
only weight history used is the PREVIOUS decision's persisted state.

## A. Correlation penalty — simultaneous, permutation-invariant

`pen_i = clip(pen_floor, 1, 1 − Σ_{j≠i} prior_j · max(corr_ij, 0))`
with `pen_floor = 0.1`, `prior` = previous persisted final weights
(0 absent → equal prior over eligible).  `corr` = Pearson correlation
of trailing per-strategy return streams (reused
`portfolio.returns_frame`/pairwise math), computed ONCE for the whole
candidate set.  Order of strategies cannot change any `pen_i` (a sum
over j is order-free); pinned by permutation tests.  Pair pairs with
< `corr_min_obs` overlapping observations contribute 0 and are
flagged; a matrix with NO pair meeting the minimum is a GLOBAL
correlation-source failure (§ fallback).  Negative correlations
penalize 0.  NaN/±inf in any stream value ⇒ the pair is treated as
insufficiently observed (flagged), never NaN-propagated.

## B. Authority (restated normative)

Meta may ONLY reduce exposure (weights ≤ proportional budget;
constraints and clamps only reduce).  Daily-loss limit, drawdown
threshold, kill switch, hard risk %, margin safety, exposure hard
caps: defined and enforced by the Risk Engine alone.  Every order the
meta allocation influences STILL passes the entire Risk Engine; the
layer structurally cannot emit orders (no order API exists on the
module — a structural test asserts this).

## C. Determinism

Ordering strategy_id ascending everywhere; tie-breaks lexical;
canonical JSON (`sort_keys=True`, compact separators); floats
serialized `round(x, 10)`; arithmetic in float64, no rounding before
serialization.  Same inputs ⇒ byte-identical journal (test).

## D. Zero semantics

- Factor zero WITH source present → HARD ZERO → strategy INELIGIBLE
  with the specific reason; weight 0.0 in every mode; never
  redistributed to; re-entry restarts from 0.
- ALL candidates hard-zero (or none eligible) → SAFE HOLD: zero
  allocation, journal `fallback="none_eligible"`, NOT equal weight.
- GLOBAL optional-source failure → equal weight across eligible,
  `fallback="equal_weight"` + failing source named.
- Never "last known good weights" (also on crash: SAFE HOLD).

## E. Missing data (classified; conservative)

| source | class | missing for one | missing for all |
|---|---|---|---|
| certification/gate | REQUIRED | UNCERTIFIED (ineligible) | — (each strategy judged) |
| performance stats | OPTIONAL | factor = perf prior 0.5 + flag `MISSING` | equal-weight fallback |
| correlation coverage | OPTIONAL (per pair) | pair → 0, flagged | global → equal-weight fallback |
| drift | OPTIONAL | factor = 0.5 + flag `MISSING` | equal-weight fallback |
| previous weights | OPTIONAL | equal prior | equal prior (flagged) |

The zero-observation performance value IS 0.5 by construction
(shrinkage prior), so "missing" equals "no evidence" exactly — no
free pass, no penalty for absent telemetry beyond losing the edge a
measured factor would have given.

## Domain model (typed; no loose dicts at boundaries)

`MetaFactor(value, source, version, status)` — status ∈
`OK|MISSING_FALLBACK|GLOBAL_FAILURE`; value validated finite, in
[0, factor cap].
`StrategyMetaInput(strategy_id, signal, symbol, regime,
certification_state, gate_weight, performance (MeanStd/n), drift_score,
enabled, cooldown_until, stale, kill_switch, factor timestamps)`.
`Eligibility(eligible: bool, reason: str|None)` — reasons:
`UNCERTIFIED, CERT_FAILED, REGIME_FORBIDDEN, REGIME_UNKNOWN,
DRIFT_BLOCK, STALE_DATA, DISABLED, COOLDOWN, KILL_SWITCH,
CONFIG_INVALID` (all hard-zero causes).
`RawMetaScore(strategy_id, raw_score, factors)` (product of the five,
computed only for eligible).
`MetaWeight(strategy_id, pre_cap_share, final_weight, clamp_reasons)`.
`MetaDecision(as_of, mode, activation, eligibility map, raw scores,
weights, netted book, fallback, zero/clamp reasons, versions,
config_hash, prev_state_hash, manifest identity)`.
`MetaDecisionJournal(decisions, canonical_json())`.
`MetaConfig` — EXACTLY the tunables (Phase 16 budget = 6):
`mode="weighted_netting"`, `vote_threshold=0.6`,
`max_strategy_weight=1.0`, `gross_exposure_cap=1.0`,
`max_weight_change=1.0` (off), `max_positions=None` (off).  All other
numbers in this spec are FIXED CONSTANTS (documented, untunable).

## Factors (exact)

1. `gate_weight` (REQUIRED): certification state → {VERIFIED: 1.0,
   EMPIRICAL_VALIDATION_PENDING: 0.5, SOFTWARE_PASS: 0.5,
   FAILED: 0.0, NOT_ELIGIBLE: 0.0, missing: 0.0}.  0.0 ⇒ `UNCERTIFIED`
   or `CERT_FAILED` hard zero.  Source: caller-supplied certification
   record (OosRegistry/status model).
2. `regime_fit` (REQUIRED metadata): allowed 1.0; preferred 1.0
   (constants; no boost — anti-overfit); forbidden 0.0 ⇒
   `REGIME_FORBIDDEN`; UNKNOWN/TRANSITION regime ⇒ 0.0 ⇒
   `REGIME_UNKNOWN` (fail-safe: the layer does not allocate through
   regime uncertainty).
3. `performance_factor` (OPTIONAL): from OOS-derived stats ONLY
   (per-strategy OOS trade ledger: expectancy and trade count).
   `n < 1 → 0.5`.  Otherwise
   `e = (n·mean_r + k·0) / (n + k)` (shrinkage, k=20 trades prior),
   `factor = clip(0.5 + 5·e, 0.1, 1.0)`.  Small samples are shrunk to
   the neutral prior; five lucky trades cannot dominate hundreds of
   OOS trades.  In-sample/training-window performance is structurally
   unreachable: the input type carries OOS ledgers only.
4. `correlation_penalty` (OPTIONAL per pair): §A above.
5. `drift_factor` (OPTIONAL): divergence score d ∈ [0,1]:
   d < 0.10 → 1.0 (NO_DRIFT); 0.10 ≤ d < 0.50 → 1.0 − (d·1.0) mapped
   linearly to [0.9, 0.5] (MILD); d ≥ 0.50 → `DRIFT_BLOCK` (hard
   zero); source missing → 0.5 + flag (never 1.0).

## Modes (exact; mode fixed in config; never dynamic)

- `independent`: final weights ARE the per-strategy allocations.
- `weighted_netting` (DEFAULT): group by symbol;
  `net_i = Σ_s w_s·dir_s`; book keeps signed contributions
  (`{strategy_id, weight·dir}`) — attribution exact by construction;
  net and gross both journaled.
- `vote`: `agree_mass = Σ w_s(dir=s)`, `against_mass = Σ
  w_s(dir=−s)`; fires direction s iff `agree_mass ≥ vote_threshold ·
  (agree_mass + against_mass)` AND `agree_mass > against_mass`;
  exact tie (equal masses) or no signals ⇒ no trade; abstentions (no
  signal) excluded from both masses.
- `best_of_regime`: highest raw score for the current regime wins the
  whole budget (subject to caps/constraints); tie ⇒ strategy_id
  lexical ascending wins.

## Portfolio constraints (after caps; only reduce)

`gross_exposure_cap` (Σ|w| budget), `max_strategy_weight` (per
strategy), `max_positions` (keep top-k by (weight desc, id asc), zero
the rest with reason `MAX_POSITIONS`), symbol exposure (Σ|w| per
symbol ≤ `max_strategy_weight`·n — uses the strategy cap scale),
currency exposure via symbol→currency map (reuse
`portfolio.currency_exposure` semantics).  Everything the Risk Engine
owns stays owned by the Risk Engine; these are the layer's OWN
pre-scaling budgets.

## Equal-weight baseline (first-class)

`policy="equal_weight"` produces the identical pipeline with all five
factors replaced by 1.0 for eligible strategies (same eligibility,
same caps/constraints/change-limit).  META vs EQUAL_WEIGHT under
identical strategies/symbols/window/costs/limits differs ONLY in
weighting policy (test: same eligibility decisions; same constraint
machinery).

## Shadow mode & activation

Activation ∈ {DISABLED, SHADOW, DEMO, LIVE_SMALL, ACTIVE}, default
DISABLED, explicit transitions only (audited journal event).  In
SHADOW the runner computes decisions + journals and records
divergence vs the actual policy (equal-weight independent): weight
L1, signal flips, trade-count and exposure deltas.  No component
consumes shadow output for sizing — structurally, allocation output
exists only for DEMO/LIVE_SMALL/ACTIVE and the EA consumes the file
only (which Python tests pin to the SPEC contract).

## File contract (`in/allocation.json`, SPEC line 107)

Writer: canonical JSON, `schema_version="1"`, `computed_at` (UTC
ISO), `config_hash`, per-strategy entries `{id, weight, eligible,
reasons, factors{...}, mode, activation}`; atomic temp write +
`os.replace`; self-digest recorded.  Stale (>7 days mtime/`computed_at`)
and missing follow the documented EA behavior (decay to base gate
weight; equal weights capped at global defaults); malformed ⇒ refuse
+ SAFE HOLD — never silently applied.  The EA-side consumer
(`Allocation.mqh`) implements EXACTLY this documented behavior and no
order path (structural tests).

## Restart state

Persisted: previous final weights, as_of, config_hash,
decision_version, clamp/zero flags needed to keep limits continuous.
Never persisted: any training/OOS statistic, factor inputs, future-
derived data.  Restart equivalence: [decide(t1) → save → load →
decide(t2)] == [decide(t1) → decide(t2)] byte-identical (test).

## OOS validation & anti-overfit

Nothing to tune (deterministic policy, 6 explicit params) — therefore
`meta_oos_validation` (a) freezes `config_hash`, (b) runs purged-CPCV
fold diagnostics on DEVELOPMENT data (meta vs equal-weight per fold),
(c) performs ONE look at the untouched OOS window with the frozen
config, recorded with meta_config_version, meta_parameter_hash,
dataset_digest, strategy_versions, engine_version, cost_version,
regime_version.  No Optuna anywhere in the module (banned-import
test).  Meta-vs-equal-weight conclusion may only activate per the
empirical gate (Phase 28); default remains SHADOW_ONLY.

## Failure mode

Any exception inside decide() is caught by `safe_decision()`: SAFE
HOLD (no allocation change, no new trades), journal fallback
`"failure_safe"`, original exception logged.  Corrupt/missing files
never create positions.

## Test map (phases → suites)

12 → `tests/test_meta_risk_invariants.py`; 13 →
`tests/test_meta_metamorphic.py` (A–K); 24–26,17–21,29,30 →
`tests/test_meta_matrix.py`; OOS/baseline → `tests/test_meta_oos.py`.
MQL5 parity → structural pins in `tests/test_mql5_sources.py`
schema/behavior + Python golden-file round-trip.
