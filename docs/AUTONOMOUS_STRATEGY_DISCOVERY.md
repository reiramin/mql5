# Autonomous Strategy Discovery (AEGIS)

**Status: IMPLEMENTED (core), PARTIAL: research hardening.** Honest scopes are marked per section.

## What this is

The owner provides ONLY: natural-language ideas, community links/URLs, pasted text, data files, or spec fragments. AEGIS turns those into validated, lifecycle-managed strategies — no per-strategy code is ever written by the owner or an agent (§6/§103). The full chain: SOURCE → INTAKE → INTERPRET → DSL → VALIDATE → CANDIDATES → BACKTEST → OOS → ROBUSTNESS → COST → REGIME → PORTFOLIO → DISCOVERY SCORE → SHADOW → HUMAN APPROVAL → LIVE_SMALL → SAFE SCALE-UP → LIVE, with an independent KILL SWITCH / CIRCUIT BREAKER / EXTERNAL WATCHDOG outside that chain.

## Components (as built)

| Component | Module | Status |
|---|---|---|
| Gap matrix | `docs/AUTONOMOUS_STRATEGY_DISCOVERY_GAP.md` | DONE (commit `ca6418b`) |
| Indicator universe + contracts | `mql5bot/indicator_universe/` | DONE (71 kinds) |
| DSL wiring for the universe | `mql5bot/dsl/` | DONE (schema/normalize/parse/runtime) |
| Governance domain | `mql5bot/discovery/domain.py` | DONE |
| Transparent discovery score | `mql5bot/discovery/score.py` | DONE |
| Staged candidates + orchestrator | `mql5bot/discovery/candidates.py`, `orchestrator.py` | DONE (engine glue = adapter layer, PARTIAL) |
| Safety triad | `mql5bot/discovery/safety.py` | DONE |
| Decay/ramp controllers | `mql5bot/discovery/governance.py` | DONE |
| Allocation governor | `mql5bot/discovery/governor.py` | DONE |
| Portfolio assembly | `mql5bot/discovery/portfolio.py` | DONE |
| Operator console | `mql5bot/api/` | DONE (FastAPI+Jinja2+HTMX, no React) |
| Campaign persistence | `factory/models.py` + `migrations/0002` | DONE |
| Research source providers | `factory/providers.py`, `research.py` | carried from mission 2 |
| ML estimation layer | `ml_interfaces.py` | carried; see ML_VS_LLM_BOUNDARY.md |

## Invariants (§0 absolutes, enforced in code)

1. No LLM/Factory ever trades; only the existing Meta→Risk→Execution chain sizes orders.
2. SCORE ≠ PERMISSION: `discovery.score` has no path to orders (see DISCOVERY_SCORE.md).
3. Kill switch overrides every new-entry authorization; reset is explicit + audited.
4. No future data anywhere (registry-wide causality property test).
5. Claims (AUTHOR_CLAIM) and measurements (AEGIS_MEASURED) are never merged.
6. Ambiguity is surfaced, never auto-filled; invalid specs are rejected whole.
7. Resource budgets are never silently raised (`LimitExceeded` on the 33rd indicator).
8. 0% gross exposure is a legitimate portfolio outcome; gross ≠ risk%.
9. No automatic live promotion: autonomy default `RESEARCH_AUTOMATION`; `LIVE_SMALL→LIVE` requires `FULL_AUTOMATION` PLUS audited human approvals PLUS owner MT5 phase (never faked).

## Staged campaigns (§7/§63)

`stage1_single_indicator → stage2_two_factor → stage3_multi_factor → stage4_portfolio_aware → stage5_mutations`, each budget-capped from `factory/policies/discovery.yaml` (`search:` block). Campaigns are resumable: per-stage progress is persisted (`discovery_campaigns`), completed stages are never re-run, and progress earned under a different policy hash is REFUSED (attack 13). Final OOS is never used to tune the search (§17).

## Evidence ladder (§30)

`E0_IDEA … E7_LIVE_PROVEN` (`discovery/domain.py:EvidenceLevel`) — a separate axis from lifecycle state and from the discovery score. Ranking only considers stage-eligible candidates (OOS_SURVIVOR and beyond); unequal evidence is never compared as equal.
