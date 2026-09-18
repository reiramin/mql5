# META LAYER — VALIDATION, RED TEAM, ACTIVATION GATE
(Mandate Phases 27-32.  Measured output below was produced by
`tools/meta_validation.py` on this sandbox; everything is reproducible
with that command.  **No profitable / production-ready / verified
claim is made or may be inferred.**)

---

## 1. Measured comparison — META vs EQUAL_WEIGHT

Method: identical strategies, symbols, time periods, cost model, risk
limits and constraints; ONLY the weighting policy differs (contract
v1.1.0).  Development folds use train-side statistics only; the OOS
window is touched once with the frozen config.

(frozen comparison wall time: 1.1s)

## OOS portfolio metrics (45-day OOS window, 4 strategies)

| metric | META | EQUAL_WEIGHT |
|---|---:|---:|
| cagr | -0.0205 | -0.0227 |
| sharpe | -0.6795 | -0.7310 |
| sortino | -0.8794 | -0.9512 |
| calmar | -0.2140 | -0.2167 |
| max_dd | -0.0957 | -0.1046 |
| recovery | -0.8860 | -0.8939 |
| cvar_5 | -0.0048 | -0.0050 |
| expectancy_per_bar | -0.0001 | -0.0001 |
| turnover | 0.0000 | 0.0000 |
| gross_exposure | 1.0000 | 1.0000 |
| concentration_hhi | 0.2602 | 0.2500 |
| n_trades | 121.0000 | 121.0000 |

## Time-period breakdown (development folds, train-side stats only)

| fold | test bars | meta sharpe | equal sharpe | meta max_dd | equal max_dd |
|---:|---:|---:|---:|---:|---:|
| 1 | 1200 | -0.033 | -0.084 | -0.095 | -0.106 |
| 2 | 1200 | -0.216 | -0.219 | -0.105 | -0.110 |

## Per-strategy OOS evidence (the factors see exactly this)

| strategy | OOS trades | expectancy/trade | OOS net |
|---|---:|---:|---:|
| donchian_20 | 35 | -0.42483 | -1486.91 |
| donchian_55 | 35 | -0.42483 | -1486.91 |
| ema_fast | 24 | -0.09954 | -238.90 |
| ema_slow | 27 | -0.17816 | -481.03 |

## Weights (frozen from development-side statistics)

| strategy | META weight | EQUAL weight |
|---|---:|---:|
| donchian_20 | 0.2077 | 0.2500 |
| donchian_55 | 0.2077 | 0.2500 |
| ema_fast | 0.2533 | 0.2500 |
| ema_slow | 0.3314 | 0.2500 |

## Dimensions NOT measurable in this research stack

- **Regime breakdown**: the Python research stack has no regime
  classifier (regime metadata is static per strategy); a regime
  table would be fabricated.  Regime behavior is pinned by the
  regime matrix tests instead.
- **Symbol breakdown**: synthetic single-symbol data; the
  weighting math is symbol-agnostic (book groups by symbol).
- **Profit factor / expectancy at portfolio level**: portfolio
  trades do not exist under fixed weights; per-strategy OOS
  expectancy and trade counts are reported above.

## Performance profile (10 strategies, 500-bar window, shared sandbox)

| step | ms (mean of 20) |
|---|---:|
| correlation matrix (10x10, 500 bars) | 44.96 |
| full decision | 60.66 |
| journal serialization | 0.37 |
| journal canonical json | 0.27 |

## Activation decision input (SYNTHETIC data — not activation-grade)

- meta OOS sharpe > equal-weight OOS sharpe on this synthetic run: True
- decision per the empirical gate: SYNTHETIC comparison CANNOT
  activate anything.  The Meta Layer ships DISABLED by default;
  the maximum honest state today is SHADOW_ONLY, pending real
  data validation, MT5 truth validation, shadow results and
  demo evidence.


## 2. Reading of the measured result (honest)

- On this SYNTHETIC run the four contributing strategies all LOSE out
  of sample; META tilts weight toward the least-bad strategy and lands
  marginally better than equal weight on every risk-adjusted metric —
  a difference far inside run-to-run noise on 45 days of random-walk
  data.
- **This is NOT evidence that Meta Layer improves anything.**  The
  bounded factors (shrunk + winsorized performance, correlation
  penalty, hard-zero eligibility) deliberately keep META close to
  EQUAL_WEIGHT unless development-side evidence is strong.  That is
  the anti-overfit design goal (Phase 16), not a weakness.
- Per Phase 28: no robust OOS outperformance after costs is claimed;
  the comparison harness and discipline now exist for a REAL-data
  decision.

## 3. RED TEAM (Phase 31) — "how can Meta lose while appearing correct?"

| # | attack | outcome |
|---|---|---|
| 1 | order dependence | FIXED (ML-1): simultaneous snapshot; permutation invariance pinned over shuffles in all modes and fallbacks |
| 2 | correlation inversion over time | WAIVED with mitigation: penalty uses only positive correlation, floored at 0.1, change-limit damps swings; inversion is a data property, monitored via drift/eligibility, not silently absorbed |
| 3 | regime misclassification | FIXED fail-safe: any unknown regime (incl. TRANSITION) zeroes the strategy (REGIME_UNKNOWN); over-conservatism accepted and documented |
| 4 | stale OOS data | FIXED: source staleness = STALE_DATA ineligibility; allocation file staleness = decay after 7 days; insufficient correlation coverage = flagged, global fallback |
| 5 | sample-size bias | FIXED: k=20 shrinkage + ±2% winsorized expectancy pinned ("five lucky trades" test) |
| 6 | winner chasing | FIXED: performance factor bounded [0.1,1.0]; identical stats ⇒ identical weights (convergence-to-equal pinned) |
| 7 | weight oscillation | FIXED: max_weight_change clamp between persisted decisions (tested); hard zeros bypass it (immediate) |
| 8 | normalization artifacts | FIXED: ratio preservation + cap hard bounds + bounded redistribution into uncapped eligible only (metamorphic C/D/F) |
| 9 | zero resurrection | FIXED: mask-before-normalize; no epsilon path; all-zero ⇒ SAFE HOLD (B/K tests) |
| 10 | fallback abuse | FIXED: fallback ONLY on global source failure, named source journaled, hard zeros still zero (test_k); never last-known-good (Phase 30 SAFE HOLD) |
| 11 | stale allocation file | FIXED: digest-verified file; reader flags stale; EA decays to base gate after 7 days; malformed refused both sides |
| 12 | version mismatch | FIXED: state carries decision_version + config_hash; a layer refuses state from a different config; journal carries the full version block |
| 13 | restart reset | FIXED: restart-equivalence byte-identical test; persisted state = weights/zero-reasons only |
| 14 | hidden lookahead | FIXED: correlation window cut at as_of (tested); fold stats are train-side only; OOS touched once |
| 15 | allocation/risk mismatch | FIXED structurally: the EA seam scales lots AFTER RiskManager.GetLots and can only reduce (structural pin) |
| 16 | netting attribution errors | FIXED: book contributions sum to the net score exactly (1e-12 test); attribution lives in the journal, never in position comments |
| 17 | live/shadow divergence | COVERED: shadow divergence metrics implemented; SHADOW may_influence_sizing is structurally False |

**No CRITICAL/HIGH finding remains open.**  The single waiver (#2) is
recorded above with its mitigations.

## 4. Activation decision (Phase 28)

`DISABLED` (default) — maximum honest state today: **SHADOW_ONLY**.
The synthetic comparison cannot satisfy the empirical gate; real-data
validation, MT5 truth validation, shadow results and demo evidence
are all still pending.  Transitions remain explicit and audited.

## 5. Phase 32 EXIT GATE — Meta Layer SOFTWARE_PASS (30/30)

| # | criterion | evidence |
|---|---|---|
| 1 | contract audited + versioned | META_LAYER_CONTRACT.md v1.1.0; DECISIONS ML-1..ML-8 |
| 2 | correlation permutation-invariant | metamorphic A (+ corr monotonicity E) |
| 3 | eligibility deterministic | reason table test; fixed check order |
| 4 | hard-zero semantics | unit + metamorphic B/K (never resurrected) |
| 5 | missing-data explicit | classified table + tests (J, adv 06-08) |
| 6 | five factors implemented | gate/regime/performance/correlation/drift with sources+versions+status |
| 7 | product formula pinned | raw == Πfactors exact test |
| 8 | normalization deterministic | share→cap→redistribute→budget; ratio + bounds tests |
| 9 | equal-weight baseline | MetaPolicy.EQUAL_WEIGHT; same machinery, only weights differ (pinned) |
| 10 | four modes work | independent/weighted_netting/vote/best_of_regime tests incl. ties/abstention |
| 11 | attribution works | signed book sums to net exactly; per-strategy contributions |
| 12 | portfolio constraints work | budget/cap/max_positions reduce-only tests |
| 13 | Risk Engine final authority | no order API; EA seam after GetLots reduce-only (structural) |
| 14 | risk-invariant tests pass | tests/test_meta_risk_invariants.py (12 mapped items) |
| 15 | metamorphic tests pass | tests/test_meta_metamorphic.py A-K |
| 16 | regime tests pass | 7-regime matrix |
| 17 | drift tests pass | NO/MILD/SEVERE/MISSING matrix + clamp |
| 18 | adversarial tests pass | 22 scenarios (test_meta_matrix.py) |
| 19 | journal deterministic | byte-identical journals; strategy_id ordering |
| 20 | restart tested | restart equivalence + state-content whitelist |
| 21 | shadow mode works | divergence metrics; no sizing influence |
| 22 | OOS validation exists | meta_oos fold diagnostics + ONE-LOOK registry |
| 23 | meta-vs-equal comparison exists | this document §1 (measured) |
| 24 | no OOS tuning after exposure | second look refused EVEN with changed config (test) |
| 25 | file contract respected | SPEC allocation.json: schema/digest/atomic/stale/missing; EA consumer |
| 26 | python tests pass | full suite green (see final report PYTEST) |
| 27 | ruff passes | ruff clean at gate commit |
| 28 | no uncontrolled live activation | explicit ladder; DISABLED default; illegal transitions raise |
| 29 | failure fails safe | safe_decision → SAFE HOLD; malformed file → refused |
| 30 | no live ML | no learning anywhere; no optuna import (scanned); pure deterministic math |

SOFTWARE_PASS ≠ profitability, production-readiness, or MT5
verification.  The Meta Layer inherits the WEAKEST certification state
of its contributing strategies and can never upgrade one.

---

# EMPIRICAL GATE RECORD (mission 2, 2026-09-05)

Goal: move Meta Layer from SOFTWARE_PASS toward
EMPIRICALLY_VALIDATED / SHADOW-READY without any live-risk influence.

## 1. Contract semantics (Phase 1)

`docs/META_LAYER_SEMANTICS_REVIEW.md`: the four controls (A meta
weight-change limit, B daily-loss limit, C drawdown kill-switch,
D exposure cap) are distinct; ONE wording blur found in §5.2 and
corrected (contract 1.1.0 → 1.1.1, DECISIONS ML-9).  The layer's
surface cannot express a loss/drawdown authority (pinned:
`test_no_risk_authority_concepts_in_surface`).

## 2. Reduce-only proof (Phases 3-4)

Lot grid {1.0, 0.8, 0.5, 0.1, 0.0} × risk-approved sizes
{10, 2.5, 0.5, 0.05, 0}: `final ≤ approved` always; weight 0 ⇒ 0;
sub-minimum meta size ⇒ NO trade (never forced to volume_min — that
would exceed the meta decision; this was a REAL seam defect found and
fixed in this mission).  Margin cannot be violated: final size ≤ the
already-margin-checked size.  Seam order pinned: GetLots → ScaleLots →
floor-to-step → min-drop; no order API in `Allocation.mqh`.

## 3. REAL-data OOS (Phases 12-16) — MEASURED, sandbox limits stated

Egress from this sandbox is allowlisted to github.com: FX/metal/
index-CFD/crypto providers are unreachable and are recorded
**UNAVAILABLE** (manifest + fetch tool committed).  The obtainable
REAL daily OHLC series is the CBOE VIX index (DataHub mirror,
1990-01-02 .. 2026-09-03, 9,265 bars, SHA-256 in
`tests/data/real/manifest.json`).  The identical tool accepts broker
CSVs for the full basket on an owner machine
(`tools/meta_real_validation.py --csv ... --instrument ...`).

### Full-history replay (3 strategies, 10 causal rebalances, 1990→2026)

| metric | META | EQUAL_WEIGHT |
|---|---:|---:|
| net return | −0.4367 | −0.4361 |
| CAGR | −1.62% | −1.62% |
| Sharpe | −0.4003 | −0.4049 |
| Sortino | −0.4734 | −0.4805 |
| Calmar | −0.0339 | −0.0340 |
| max DD | −47.8% | −47.5% |
| PF (daily returns) | 0.9124 | 0.9123 |
| CVaR-5% daily | −0.57% | −0.56% |
| turnover/yr | 0.032 | 0.028 |
| worst month / week | −7.1% / −8.0% | −6.9% / −7.8% |
| longest DD | 12,699 days | 12,699 days |
| max consec losing days | 13 | 13 |

Significance: ΔSharpe +0.0046, moving-block bootstrap 95% CI
[−0.0143, +0.0232] (2,000 draws, seed 7) — **straddles zero**;
p = 0.374; PSR = 0.489.  **META is statistically INDISTINGUISHABLE
from EQUAL_WEIGHT on this real series.**  All contributing strategies
LOSE on VIX with trend rules over 36 years (per-strategy PF 0.66-0.75)
— reported as observed.  PBO: not applicable — nothing was tuned (the
policy is deterministic; the six parameters were fixed by contract,
not searched).

### Per-period (independent REAL windows)

| period | window | Sharpe M/E | maxDD M/E | p |
|---|---|---|---|---:|
| trending | 2016-10..2017-12 | −1.556 / −1.579 | −3.2% / −3.3% | 0.450 |
| range | 2004..2006 | −0.677 / −0.653 | −9.7% / −9.1% | 0.458 |
| high-vol | 2020 | +0.065 / +0.061 | −3.5% / −3.5% | 0.508 |
| stress | 2008-01..2009-06 | +0.615 / +0.596 | −3.6% / −3.5% | 0.406 |
| recent | 2025-09..2026-09 | +0.051 / +0.022 | −3.0% / −3.2% | 0.287 |

No period shows a significant difference (all p ≥ 0.28).  META is not
overfit to any window — it is essentially equal-weight with bounded,
evidence-driven tilts (final weights 0.381/0.293/0.326 vs 1/3 each).

### Regime breakdown (as-of labels on the real series)

| regime | days | Sharpe (META) |
|---|---:|---:|
| HIGH_VOL | 1,368 | −0.55 |
| LOW_VOL | 3,254 | −0.44 |
| RANGE | 4,077 | −0.61 |
| TREND_UP | 80 | +7.82 |
| TREND_DOWN | 85 | −8.50 |

(The ±8 trend-label Sharpes are 80-85-day samples — reported with
their sizes, not extrapolated.)

## 4. Shadow replay (Phases 17-19)

Causal by construction and PINNED on the real frame: perturbing all
data AFTER the last rebalance leaves every recorded weight identical
(`test_replay_no_lookahead_on_real_data`); as-of stats equal
truncated-frame stats.  Shadow acceptance criteria all pinned: no live
influence (structural), no risk bypass (invariants), deterministic
decisions, byte-identical journals, divergence metrics, restart
preserves state + activation, stale/corrupt state fails safe.

## 5. Adversarial REAL-data scenarios (Phase 22) — all 16 pass

winning-strategy crash (share drops, bounded), loser improvement
(bounded tilt), correlation fusion (penalty rises), correlation
instability (deterministic), regime flip (fail-safe zero), drift
appears (mild reduces / severe blocks), strategy disappears
(renormalization only), certification expiry (hard zero), stale file
(decay flag), corrupted file (digest refusal), restart mid-clamp
(byte-identical), kill switch (all zero), daily-loss breach (invisible
to meta — Risk Engine authority), risk rejection (no order from zero
weight), market gaps (real holiday/2015 gaps handled), spread spike
(both policies affected identically; exposure bounded).

## 6. Red team v2 (Phase 28) — 20 attacks

| # | attack | severity | outcome |
|---|---|---|---|
| 1 | order dependence | HIGH | FIXED in mission 1 (ML-1); re-pinned on real data (no-lookahead + permutation) |
| 2 | winner chasing | MEDIUM | FIXED: winsorized shrinkage; the "5 lucky trades" pin; identical stats ⇒ identical weights |
| 3 | delayed zero | HIGH | FIXED: hard zeros bypass the change limit (pinned) |
| 4 | stale weights | MEDIUM | FIXED: persisted weights are the ONLY history; never last-known-good on failure |
| 5 | weight oscillation | MEDIUM | MITIGATED: change-limit clamp (pinned); default off per contract |
| 6 | correlation inversion | MEDIUM | WAIVED w/ mitigation (mission 1); real-data replay measured the effect: bounded tilts only |
| 7 | regime flip | HIGH | FIXED: fail-safe zero on unknown/forbidden (real-data scenario) |
| 8 | drift false positive | MEDIUM | BOUNDED: mild drift reduces ≤ linear factor; block only ≥ 0.5 |
| 9 | drift false negative | MEDIUM | MITIGATED: missing drift = 0.5 (below healthy), never 1.0 |
| 10 | normalization resurrection | HIGH | FIXED: mask-before-normalize; no epsilon (B/K pins) |
| 11 | fallback abuse | HIGH | FIXED: global-only, source-named, hard zeros stay zero |
| 12 | restart reset | HIGH | FIXED: restart-equivalence byte-identical; activation now persists (defect found+fixed this mission) |
| 13 | version mismatch | MEDIUM | FIXED: config-hash refusal; strategy_versions in decisions+files (new) |
| 14 | portfolio constraint bypass | HIGH | FIXED: budget/cap/positions reduce-only pins |
| 15 | Risk Engine bypass | CRITICAL | IMPOSSIBLE structurally: no order API; seam after GetLots |
| 16 | attribution corruption | MEDIUM | MITIGATED: signed book sums to net exactly; journal canonical |
| 17 | malformed allocation | HIGH | FIXED: digest-verified, refused both sides |
| 18 | stale allocation | MEDIUM | FIXED: >7d decay per SPEC; tz-naive comparison bug found+fixed this mission |
| 19 | partial EA update | MEDIUM | WAIVED w/ mitigation: version binding identifies mismatches; owner checklist step 7 verifies sizing equality |
| 20 | clock/timezone mismatch | MEDIUM | FIXED: tz-tolerant staleness (defect found+fixed this mission) |

No CRITICAL/HIGH finding remains open.  Two waivers (#6, #19) carry
documented mitigations.

## 7. Promotion rule (Phase 27, binding)

SHADOW → DEMO requires: software tests pass (this gate); MQL5 compile
VERIFIED by owner log; deterministic shadow behavior; no risk
invariant violated; real-data OOS exists (this document — VIX only;
basket pending owner data); Equal-Weight comparison exists; no
certification-slice tuning; no open critical/high red-team finding.
DEMO → LIVE_SMALL additionally requires: sufficient demo history,
stable execution, no unexpected divergence, risk bounded.

**Current status: SHADOW-READY (software).  The compile and demo
evidence are owner actions; MT5 compile remains NOT RUN IN SANDBOX.**

## 8. Gate verdict (Phase 29) — SOFTWARE + SHADOW READY (17/20 executed, 3 owner-gated)

| # | criterion | verdict |
|---|---|---|
| 1 | contract semantics consistent | PASS (v1.1.1 + review doc) |
| 2 | daily clamp ≠ daily-loss authority | PASS (ML-9 + surface pin) |
| 3 | reduce-only proven | PASS (lot grid + structural) |
| 4 | MQL5 seam structurally safe | PASS (pins; floor+drop fixed) |
| 5 | correlation permutation-invariant | PASS (incl. real-data) |
| 6 | factors correctly sourced | PASS (OOS-only, as-of, classified missing) |
| 7 | hard zeros never resurrected | PASS |
| 8 | equal-weight baseline exists | PASS (same machinery, real-data runs) |
| 9 | real-data OOS comparison exists | PASS on VIX (real, 36y); basket symbols UNAVAILABLE (documented) |
| 10 | stress comparison exists | PASS (2008-09 GFC window measured) |
| 11 | regime breakdown exists | PASS (5 regimes, sizes reported) |
| 12 | shadow replay exists | PASS (causal, no-lookahead pinned) |
| 13 | restart deterministic | PASS |
| 14 | stale/corrupt fails safe | PASS (incl. tz fix) |
| 15 | versions bound | PASS (config/decision/file/state) |
| 16 | adversarial real-data tests pass | PASS (16/16) |
| 17 | pytest passes | PASS (see final report) |
| 18 | ruff passes | PASS |
| 19 | MQL5 compile honestly reported | NOT RUN IN SANDBOX — owner `compile.ps1 -Strict` required before SHADOW→DEMO |
| 20 | no live activation enabled | PASS (DISABLED default; SHADOW_ONLY maximum) |

This gate does NOT declare profitability.  It declares: **software +
validation infrastructure ready for controlled SHADOW/DEMO**, with the
owner-side compile, full-basket real data, and demo evidence as the
remaining gates.
