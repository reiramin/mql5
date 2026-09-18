# ML vs LLM Boundary (mission §46–§48)

**Status: IMPLEMENTED (boundary); ML layer itself PARTIAL (estimation-only interfaces exist in `ml_interfaces.py`).**

## The boundary

| | LLM (interpreter) | ML layer |
|---|---|---|
| Role | translate owner language / community text / URLs into candidate DSL specs | ESTIMATE parameters (regime classification quality, drift probability, cost fills) from data |
| Authority | NONE — deterministic DSL validation is the only authority (§14/§36) | NONE over safety — estimation only (§46) |
| Outputs | canonical spec JSON, surfaced ambiguities, provenance | probabilities/scores consumed by existing gates |
| May invent | nothing (ranges only from declared research-space config, §16) | nothing (it fits, it never sets policy) |
| Failure mode | refuses + asks; never guesses ambiguity | bounded estimates; gates keep veto order |

## Hard rules

1. The LLM NEVER executes, never trades, never promotes, and its output is validated by the deterministic DSL pipeline (mission-2 security suite: interpreter sanitization, policy_override/state_forgery detectors, injection-as-data regression).
2. The ML layer may only ESTIMATE. Per-layer veto order (kill switch → breaker → governor → Meta → Risk) is untouched by ML outputs: **no layer can remove a lower layer's veto** (§48) — estimates can only make a layer MORE conservative (e.g. drift score feeds the decay controller's demerits).
3. Regime/drift ML estimates enter through `drift_feed.py`/`regime_feed.py` feeds into the decay controller and portfolio context — they can demote/pause, never promote past a gate.
4. Everything the LLM produces is DATA: provenance preserved, AUTHOR_CLAIM vs AEGIS_MEASURED never merged.
