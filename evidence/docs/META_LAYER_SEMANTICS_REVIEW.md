# META LAYER — SEMANTICS REVIEW (empirical-gate mission, Phase 1)

Audits contract v1.1.1 against the implementation (`meta_layer.py`,
`meta_oos.py`, `Allocation.mqh`, `Mql5Bot.mq5`).  Verdict: internally
consistent; ONE wording blur found and corrected (ML-9, contract
1.1.0 → 1.1.1).  No behavior changed.

## The four controls are DIFFERENT — ownership table

| control | what it limits | owner | Meta may |
|---|---|---|---|
| **A. weight-change limit** (`max_weight_change`) | Δweight between two meta decisions | Meta Layer (allocation policy) | own |
| **B. daily-loss limit** (`InpDailyLossPct` / Risk Engine) | maximum permitted ACCOUNT loss per day | Risk Engine ONLY | never compute, target, or override; may only reduce exposure, which mechanically reduces daily loss potential |
| **C. drawdown kill-switch** (`InpMaxDrawdownPct` / Risk Engine) | maximum equity drawdown | Risk Engine ONLY | same as B |
| **D. exposure cap** (`gross_exposure_cap`, `max_strategy_weight`, `max_positions` in Meta; hard notional/margin caps in Risk Engine) | maximum allocation (meta budgets) / maximum account exposure (risk) | BOTH, distinct layers: Meta pre-scales its allocation; Risk Engine vetoes at order time | own its ALLOCATION budgets; never touch the risk-side hard caps |

Binding rule: a Meta output is a WEIGHT in [0,1] per strategy.  Weights
multiply already-risk-approved lots.  No quantity named "daily loss",
"drawdown", "risk %", "margin" or "kill switch" exists as an input,
config field, state field, or branch in `meta_layer.py` (pinned by
`tests/test_meta_gate.py::test_no_risk_authority_concepts_in_surface`).

## The ten audited semantics

| # | item | owner | exact semantics today | consistent? |
|---|---|---|---|---|
| 1 | daily weight-change limit | Meta | `max_weight_change` clamps Δweight vs the PERSISTED previous decision; hard zeros bypass it (immediate); re-entry restarts from 0 (contract §10) | yes (tests: change-limit, restart-clamp) |
| 2 | daily-loss budget | Risk Engine | absent from the Meta Layer by construction; ML-9 removed the blurred §5.2 wording | yes AFTER ML-9 |
| 3 | drawdown | Risk Engine | absent from the Meta Layer by construction (`InpMaxDrawdownPct` in the EA is Risk Engine state, S2-persisted) | yes |
| 4 | gross exposure | BOTH (distinct) | Meta: `gross_exposure_cap` scales ALLOCATION weights (≤ 1).  Risk Engine: hard notional/margin caps veto orders.  Different quantities, different owners — documented | yes |
| 5 | portfolio heat | Risk Engine | the EA `RiskManager` owns heat checks on live exposure; Meta's Σ\|w\| budget is an ALLOCATION heat PRE-SCALE, not the account heat authority | yes (wording distinguished here) |
| 6 | per-strategy cap | Meta | `max_strategy_weight` bounds one strategy's allocation share; redistribute-to-uncapped-eligible only | yes |
| 7 | correlation penalty | Meta | simultaneous snapshot: pairwise historical corr (as-of bounded, min-30-obs) × PREVIOUS persisted weights; floor 0.1; positive corr only; global-failure ⇒ equal-weight fallback | yes |
| 8 | previous allocation | Meta (persisted state) | ONLY previous final weights + zero reasons + config/decision version + activation; consumed by the change limit and the correlation prior; never "last known good weights" as a fallback | yes |
| 9 | eligibility | Meta | ten hard-block reasons evaluated BEFORE scoring; required source missing ⇒ UNCERTIFIED; unknown regime ⇒ fail-safe zero | yes |
| 10 | fallback | Meta | equal weight ONLY on GLOBAL optional-source failure (source named in journal); all-blocked ⇒ SAFE HOLD; never last-known-good; hard zeros stay zero | yes |

## Chain audit (mission Phase 2)

```
strategy signal (existing strategies, MagicMap id)
  → MetaLayer.decide(...)            weights ∈ [0,1], journal
  → in/allocation.json               (schema 1, digest, versions)
  → CAllocation (MQL5)               strict consumer, stale/malformed ⇒ base gate
  → g_alloc.ScaleLots(...)           AFTER RiskManager.GetLots — reduce-only
  → volume-step renormalization      round DOWN; below min ⇒ NO trade
  → TradeManager                     canonical engine seam
  → Risk Engine                      daily loss / drawdown / spread / margin veto
```

No `OrderSend`/`CTrade` reference exists in `Allocation.mqh`
(structurally pinned).  The lot path is
SIGNAL → META(scale) → RISK-APPROVED LOTS → step-normalize → EXECUTION
→ RISK VETO at order time.

## Correction applied

- **ML-9** (DECISIONS.md): §5.2 rewording only — the Meta Layer owns
  allocation budgets; daily-loss and drawdown remain Risk-Engine
  authorities the layer never sees.  Contract bumped to 1.1.1.
