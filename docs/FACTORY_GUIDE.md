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

## Intake interpreters

Natural-language intake (`factory/interpreter.py`) turns owner text into a
draft spec, and there are two interchangeable interpreters behind one
provider-neutral contract:

- **`TemplateInterpreter`** — fully deterministic, no ML and no network. It
  recognises a small set of phrasings (EMA cross, RSI-above, RSI-low, and an
  ATR stop/target) in English and Persian.
- **`LlmInterpreter`** — an optional provider-agnostic interpreter that keeps
  the template's discipline: it **grounds every number in the source text**,
  refuses invented structural numbers, and falls back to the template with a
  visible note on any error or missing API key. Provider keys are read from the
  environment only. Built and unit-tested; never run against a live provider.

Both **scrub** the input (injection attempts surface as data, never change the
draft) and never guess the market (`§6`: symbol/timeframe are used only when
both are supplied). Anything the owner left unspecified is recorded as an
ambiguity — e.g. `AMBIGUOUS_PARAMETER` for "RSI is low" (which never becomes
"RSI < 30"), `MISSING_SL`, `UNRESOLVED_MARKET` — and surfaced as a question,
never filled in. The operator-facing **restatement is derived from the
SCRUBBED draft**, not echoed from the owner's words, so it reflects exactly
what the system understood.

## The guided strategy conversation

For a non-developer owner, the intake is a step-by-step dialogue
(`factory/conversation.py`, and the routes `POST /guided/start` +
`POST /guided/validate`). The flow is:

```
Persian text
  → a Persian restatement (derived from the scrubbed draft, not the owner's words)
  → a Persian question for every parameter left unspecified (a value is never invented)
  → the OWNER ACCEPTS THE RESTATEMENT   ← required
  → the DSL schema/parse check (structure only)
  → a plain-Persian verdict naming why it passed or failed
```

**Acceptance is required, not optional.** The restatement exists to
catch a misinterpretation *before* anything proceeds, so `validate()`
**refuses** any draft the owner has not explicitly accepted — including a
draft with no open questions (no ambiguity is not the same as
agreement). Acceptance is bound to the draft's *content*: `start()`
returns an `acceptance_token` fingerprinting the exact draft shown with
the restatement, and the owner echoes it back to `validate()`. A token
accepted for one restatement therefore cannot validate a draft that has
since changed — a different draft yields a different token, and a missing
or mismatched token is refused in both Persian and English.

**What the verdict means.** A pass is **SCHEMA-VALIDATED — structure
only; the strategy has NOT been tested.** The only Python check that runs
here is the DSL schema/parse gate (well-formedness); there is no
backtest, robustness, out-of-sample or market data. The flow **ends at
schema validation** and surfaces the two not-yet-done steps explicitly:
the Python research validation (backtest / robustness / out-of-sample,
which needs a dataset and has not run) and the owner-run 11-stage MT5
certification gate. No endpoint here promotes a strategy toward MT5 or a
live account. This surface is **built and unit-tested; never run live.**

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
