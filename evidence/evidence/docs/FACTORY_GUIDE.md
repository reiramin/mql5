# Factory Guide (AEGIS autonomous strategy layer)

The Factory turns strategy ideas into governed, evidence-bound
candidates. It is a RESEARCH/SPECIFICATION layer: **it may specify
strategies; it can never execute trades.** This guide is the readable
version; contracts live in `SPEC.md`, `STATE_MODEL.md`,
`AUTONOMOUS_STRATEGY_DISCOVERY.md`, `SAFETY_GOVERNANCE.md`.

## Running the Factory

The Factory is operated through its CLI (banner says it all:
*research only — never executes, never trades*):

```bash
python -m mql5bot.factory.cli --help
# subcommands:
#   interpret    NL text -> draft spec        register  register a spec
#   record-run   append a validation run      advance   audited transition
#   status       list strategies and states   meta-feed certification feed
#   research     idea + dataset -> full research chain (never trades)
```

State lives in the factory database (`--db <path>` or
`$AEGIS_FACTORY_DB`; schema managed by the Alembic migrations in
`migrations/`). The governance console (`python/mql5bot/api/`) is a
read/audit UI over the same store — it cannot mark a strategy LIVE.

## The pipeline

```
IDEA → intake → DSL/spec → schema validation → research runs
     → statistical gates → robustness/OOS → promotion ladder
     → allocation → monitoring → drift → decay/retirement
```

1. **Intake** — natural-language/community ideas (EN/FA) enter by
   paste or user-provided file ONLY. The provider layer performs no
   network fetches (source-scan tested); a URL is provenance, never
   dereferenced.
2. **DSL/spec** — the idea becomes a deterministic spec validated
   against `schemas/strategy.schema.json`. Unknown indicator kinds are
   rejected at the schema (`SchemaInvalid`) — the fail-closed first
   layer.
3. **Research** — deterministic engine runs on the research surface:
   backtests, cost models, regime slices. Factory orchestration never
   imports the live-execution bridge or EA tooling (source-scan
   tested).
4. **Statistical gates** — `factory/gates.yaml` thresholds
   (significance, degradation bands, stability). Screening/FAST
   results are selection signals only.
5. **Robustness/OOS** — WFA/CPCV per `WFA_CONTRACT.md`; no tuning on
   the certification slice.
6. **Promotion ladder** — `OOS_SURVIVOR → SHADOW → DEMO → LIVE_SMALL →
   LIVE`, every step evidence-gated with named evidence kinds and
   mandatory human approvals. The operator console can never mark a
   strategy LIVE from the UI (source-scan tested).
7. **Allocation** — the Meta layer combines certified strategies; it
   may only REDUCE exposure, never amplify; the allocation governor and
   circuit breaker cap aggregate risk.
8. **Monitoring / drift / retirement** — decay and recovery per
   `STRATEGY_DECAY.md`; the watchdog and allocation circuit breaker
   (`EXTERNAL_WATCHDOG.md`, `ALLOCATION_CIRCUIT_BREAKER.md`) guard the
   fleet.

## What Factory MAY do

- Parse/validate specs, run deterministic research, compute scores
  (16-component Discovery Score, `DISCOVERY_SCORE.md`), stage
  campaigns, propose promotions with evidence bundles.

## What Factory MAY NOT do

- Send, modify or close orders (no execution authority — TradeManager
  in the EA holds it exclusively).
- Promote without named evidence; resurrect FAILED/NOT_ELIGIBLE
  candidates; bypass gates; fetch network resources during intake.
- Touch ML/LLM as execution agents: ML is a secondary filter, LLM is
  non-execution assistance only (`ML_VS_LLM_BOUNDARY.md`).

## Where human approval is mandatory

Every promotion step on the ladder, every demo/live transition, and
any override of a gate outcome. Approval state is recorded and audited.

## Where risk gates apply

Research gates (statistical), allocation limits (Meta), capital veto
(Risk), emergency veto (Kill Switch) — independent layers; none can be
disabled by the Factory or the UI.

## The execution boundary (read this twice)

The Factory's 71-indicator research universe does not create MT5
execution capability. The EA executes exactly five built-in engines;
there is no DSL interpreter in MQL5. A generated strategy that does
not map onto one of the five engines stays research-only
(BLOCKED_OWNER_ENVIRONMENT) — no workaround, no "same pipeline" claim.

## Artifacts retained

Specs, gate results, OOS reports, promotion evidence, score
breakdowns, allocation files (schema-versioned), decision-journal
events (`trade_intent_created`, `trade_executed`, `trade_reconciled`,
…) — all inspectable; nothing is silently discarded.
