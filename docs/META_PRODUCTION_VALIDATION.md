# META PRODUCTION VALIDATION — MetaPortfolioEngine gate

Canonical validation record for the Meta Layer **portfolio** process
(`python/mql5bot/meta_portfolio.py` + `engine.PortfolioEngine`), per the
meta-production mission. SOFTWARE EVIDENCE and EMPIRICAL EVIDENCE are
kept strictly separate; synthetic and real data are never mixed;
diagnostic and certification evidence are never mixed.

Baseline: commit recorded in the mission report; suite 776 passed /
1 skipped, ruff clean.

---

## 1. SOFTWARE EVIDENCE (machine-pinned, reproducible in-sandbox)

| Guarantee | Pin |
|---|---|
| Canonical engine: shared account, one capital base, one cost model, netting/hedging | `tests/test_meta_portfolio.py` (netting merge/offset + attribution reconciliation; hedging independence) |
| Old equity-blend path (`meta_replay`) demoted to diagnostic | this document §4; module docstrings |
| Event order documented | `docs/META_PORTFOLIO_EVENT_ORDER.md` |
| Immutable decision snapshot | `MetaSnapshot` (frozen dataclass, MappingProxyType stats, defensive copies); `test_snapshot_is_immutable_and_decisions_reproducible` |
| Causality at first/middle/final rebalance (future OHLC ×5 bombs) | `test_future_perturbation_cannot_change_decision_at_rebalance` |
| Reduce-only seam: `final_lots ≤ approved` for weights {1.0, 0.9, 0.75, 0.5, 0.1, 0.01, 0.0}, grid floored, sub-min DROPPED (EA parity — `normalize_volume`'s min-bump deliberately bypassed) | `test_final_lots_never_exceed_approved_for_weight_ladder`, `test_seam_drops_below_minimum_never_rounds_up` |
| Hostile allocation weights (NaN / −1 / 5 / inf) fail safe | `test_hostile_schedule_weights_fail_safe` |
| Rebalance semantics: new weights touch NEW entries only; existing books keep size/price/attribution | `docs/META_PORTFOLIO_EVENT_ORDER.md` §Rebalance, `test_new_weights_apply_only_to_new_entries` |
| Restart equivalence at 25/50/75% + mid journal | `test_shadow_restart_equivalence_at_fractions`, `test_restart_equivalence_seeded_state_continues_journal` |
| Order permutation invariance; lower gross cap ⇒ no exposure increase; hard-zero stays zero; unknown-id cannot create exposure | `tests/test_meta_portfolio_guarantees.py` Phase-23 block |
| Identical contributors ⇒ identical weights = EW value; same schedule ⇒ same trades (only policy differs) | `test_identical_strategies_meta_weights_equal_ew_and_trades_match` |
| MQL5 allocation digest: native `CryptEncode(CRYPT_HASH_SHA256)` over the exact body substring; wrong/old/malformed/missing digest ⇒ reject; body-substring byte-layout reconciles with the Python writer | `tests/test_allocation_digest.py` (10 pins) |
| Unknown strategy id under FRESH (Meta-authoritative) allocation ⇒ weight 0 (was: silent baseGate — FIXED) | `test_unknown_strategy_id_under_fresh_allocation_gets_zero` |
| Certification gating (hard zero, EW fallback, reduce-only ladder) | prior `tests/test_meta_gate.py` suite (unchanged, still green) |

## 2. EMPIRICAL EVIDENCE (diagnostic — synthetic fixture)

Fixture: 1y synthetic H1 (`generate_ohlc(days=365, seed=5)`), three
strategies (Bollinger reversal, EMA crossover 10/50, MACD momentum),
50 rebalances (weekly from bar 480), netting, 10k capital, 1%/trade.
**This is a MECHANICS diagnostic, not validation of edge.**

| metric | META | EQUAL_WEIGHT |
|---|---|---|
| net profit | 1334.34 | **1414.28** |
| CAGR | 13.34% | **14.14%** |
| Sharpe | **1.4505** | 1.1696 |
| Sortino | **1.8181** | 1.5368 |
| Calmar | **2.4408** | 1.6995 |
| max drawdown | **−5.47%** | −8.32% |
| PF | 1.1071 | 1.0861 |
| expectancy/trade | 0.2026 | 0.2122 |
| CVaR-95 (bar) | **−0.235%** | −0.311% |
| exposure | 85.4% | 92.5% |
| turnover | 42.0 | 40.4 |
| trades | 6587 | 6666 |
| realized corr (mean pair) | 0.330 | 0.291 |

Uncertainty: block-bootstrap ΔSharpe CI **[−0.112, +0.217]**, p 0.277;
P(Meta>EW) (PSR) 0.437. **Verdict: META ≈ EW statistically; EW wins net.
Per the promotion rule (META ≤ EW ⇒ DEFAULT = EQUAL_WEIGHT) the standing
EQUAL_WEIGHT policy is retained; Meta stays DISABLED.** Regime mix of the
run: RANGE 5611 bars, HIGH_VOL 2203, LOW_VOL 946 (no TREND regime in this
fixture — a known synthetic limitation).

## 3. REAL DATA STATUS

Full-basket real validation (EURUSD, GBPUSD, USDJPY, XAUUSD, index CFD,
crypto with verified provenance): **PENDING — owner-gated**. The
committed real VIX daily record (manifest sha256 verified) remains a
DIAGNOSTIC single-series replay path; it is NOT full-basket validation
and is not presented as such.

## 4. OLD PATH STATUS

`meta_replay.run_replay` (independent strategy equity curves, weighted
per-bar blending) is retained **as a diagnostic approximation only**. It
is not the canonical Meta OOS engine and must not be cited as Meta
validation. The canonical path is `MetaPortfolioEngine` — the same
`PortfolioEngine` mechanics the production seam scales through.

## 5. RED TEAM (this gate)

| # | Attack | Severity | Finding / disposition |
|---|---|---|---|
| 1 | Seam min-bump resurrection | **HIGH — FIXED** | The Python seam originally reused `normalize_volume`, whose sub-minimum input is bumped UP to `volume_min` (correct for Risk sizing) — a meta-scaled 0.0099 lot order silently traded 0.01, exceeding the Meta decision. FIXED: explicit floor-to-step + drop (EA parity); pinned. |
| 2 | Unknown-id baseGate bypass | **HIGH — FIXED** | `Allocation.mqh WeightFor` returned full `baseGate` for unknown ids under a FRESH (Meta-active) allocation — an unscored strategy could trade at full gate. FIXED: unknown id ⇒ 0 under FRESH; baseGate retained only for non-authoritative states (STALE/MISSING/MALFORMED); pinned. |
| 3 | Digest "verification" by length | **HIGH — FIXED** | The EA checked digest format only (64 hex chars) and explicitly excused itself in a comment. FIXED: native `CryptEncode(CRYPT_HASH_SHA256)` over the exact body substring; mismatch/malformed/missing ⇒ reject; byte-layout reconciliation pinned from Python. |
| 4 | Restart with empty prior | MEDIUM — FIXED | `run_policy` journaled plain-keyed weights, so restart seeding read an EMPTY prior (correlation penalty then used equal prior). Fixed by journaling the full decision record; restart equivalence now genuinely pinned at 25/50/75%. |
| 5 | Winner chasing via expanding stats | MEDIUM (accepted, bounded) | As-of performance factors inherently favor recent winners; bounded by the factor cap and the max-weight-change clamp; the EW standing policy is the guard. Documented; EW retained. |
| 6 | Path divergence between policies | LOW (inherent) | META and EW run separate accounts; after the first rebalance their equity paths legitimately diverge — comparisons are path-dependent. Handled by block bootstrap on returns, not by averaging. |
| 7 | Weight cut ≠ de-risk of open books | LOW (documented) | Weights apply to new entries only (mission-default policy, EA parity). Existing books are managed by their original stops/PositionGuard. Documented in EVENT_ORDER §Rebalance. |
| 8 | Single-symbol harness scope | MEDIUM (limitation, honest) | The canonical harness runs all specs on one injectable symbol; multi-symbol real-basket replay needs owner data. Marked PENDING; never substituted. |
| 9 | Restart equivalence is decision-level | LOW (documented) | Python restarts start flat; real EA restarts carry open positions (EA-side adoption + SlGuard, source-pinned). The Python pin covers decision continuity; position carry is EA behavior. |
| 10 | Non-ASCII allocation body | LOW — FIXED | `Sha256Hex` refuses non-ASCII bodies (byte-count check) instead of hashing a guessed encoding; canonical writer is ASCII-only. |

CRITICAL: none. HIGH: #1–#3 (all fixed with regression pins).

## 6. Promotion states

SOFTWARE PASS (this gate).  EMPIRICAL VALIDATION: PENDING (real basket,
owner).  SHADOW_READY: software replay machinery passes; activation
remains **DISABLED**, standing policy **EQUAL_WEIGHT**.  No automatic
promotion; MT5 compile / Strategy Tester / demo evidence owner-gated.
