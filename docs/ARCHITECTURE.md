# Architecture (for humans)

Readable view of the system. The authoritative contract is `SPEC.md`;
invariants live in `SYSTEM_INVARIANTS.md`. Where this document
summarizes, those documents decide.

## Layered model

```
User / Operator
      |
      v
AEGIS Factory / Research        (intake, DSL spec, campaigns, scores)
      |
      v
Strategy Specification / DSL    (schema-gated; 71 research kinds)
      |
      v
Research / Validation / OOS     (deterministic engine, WFA/CPCV, gates)
      |
      v
Portfolio / Meta                (reduce-only allocation, governor)
      |
      v
Risk Engine                     (capital veto, sizing, limits)
      |
      v
Kill Switch / Safety Veto       (emergency latch, circuit breaker)
      |
      v
Execution Engine (TradeManager) (ONLY order authority)
      |
      v
MT5 Broker
```

## Authority boundaries

| Boundary | Rule |
|---|---|
| **Signal authority** | the five built-in engines in `SignalEngine.mqh` (EA) / their Python twins; completed bars only |
| **Allocation authority** | Meta may only REDUCE requested exposure |
| **Capital veto** | Risk rejects or sizes down; nothing bypasses it |
| **Emergency veto** | Kill Switch latches before new entries; exits still managed |
| **Execution authority** | TradeManager exclusively. Factory, Research, ML, LLM, dashboard and UI have NO order path (source-scan tested) |
| **Factory non-trading boundary** | Factory specifies; never executes; never imports the execution bridge |
| **Five-engine MQL5 limit** | the EA executes exactly the five built-in engines; no DSL interpreter exists in MQL5 |
| **Evidence boundary** | only hash-bound, provenance-consistent artifacts count as evidence (`owner_gate.py`) |
| **Owner certification boundary** | MT5 runtime evidence can only be produced on the owner's Windows terminal; the sandbox verifies, never produces |

## The two runtimes

- **MQL5 EA** (`mql5/`): Config (enums/constants), Session, Signal
  Engine, Risk Manager, Trade Manager, Position Guard, SlGuard, Magic
  Map, Retry Queue, Allocation, Kill Switch, Logger, Telemetry.
- **Python toolkit** (`python/mql5bot/`): strategies, indicators,
  backtest engine, metrics, sizer + SymbolSpec, optimizer, reports,
  dashboard, telemetry bridge, data layer, DSL runtime,
  indicator_universe, factory, discovery, meta layer, certification
  (`certify.py`, `status.py`), owner evidence consumer (`owner_gate.py`),
  MT5 tester tooling (`mt5tester.py`).

The twins agree by construction on completed-bar semantics and are
pinned by the gold fixtures (`artifacts/gold/`, `artifacts/gold_2/`).

## Operator surfaces (`notify/`, `api/`)

Built for the owner; each is **built, unit-tested, and never run live**,
and none has order authority.

- **`notify/`** — the alert/notification channels. `telegram.py` delivers
  Watchdog alerts to Telegram (env-only creds, token scrubbed by value,
  bounded timeout, min-send interval). `telegram_ops.py` adds the daily
  digest, per-trade notifications and the `status/positions/report/stop`
  commands, and trips the Kill Switch on `stop` — asymmetric friction:
  stop from Telegram, resume console-only (see [TELEGRAM.md](TELEGRAM.md),
  [KILL_SWITCH.md](KILL_SWITCH.md)).
- **`api/`** — the FastAPI operator console (`python -m mql5bot.api`): a
  read-and-control surface over the store and the safety chain. It can
  view state, stop the bot, and drive the guided conversation; it can
  never mark a strategy LIVE (source-scan tested). It also serves the
  opt-in Persian RTL status page (`?lang=fa`, see
  [PERSIAN_CONSOLE.md](PERSIAN_CONSOLE.md)).

**Split deployment.** Because the EA POSTs telemetry outward via
`WebRequest` to `telemetry_bridge.py`, the Python side never has to run on
the MT5 machine: MT5 on a small Windows host, the Python services on a
cheap Linux host. This is a documented procedure, never deployed or
drilled — see [DEPLOYMENT.md](DEPLOYMENT.md).

## Data flow (certification)

```
frozen source anchor
   → compile evidence (log, metadata, EX5 hash)
   → broker SymbolSpec export
   → tester legs (3 models × Gold #1/#2) with model-identity triads
   → parsed reports (bound to raw reports)
   → reconciliation (binding chain: SOURCE→FIXTURE→CONFIG→DATASET→
     SYMBOLSPEC→EX5→MODEL→REPORT→RECONCILIATION)
   → first-divergence engine + closed taxonomy
   → safety / netting / hedging raw evidence
   → real-tick coverage record
   → archive manifest (every file hash-bound)
   → verifier verdict (explainable, fail-closed)
```

Any broken edge invalidates the leg; no downstream record conceals an
upstream tamper.

## Where things deliberately do NOT connect

- Factory ↛ execution bridge (import ban, tested).
- UI ↛ LIVE marking (source-scan tested).
- Intake providers ↛ network (SSRF-by-design avoidance, tested).
- Python `MetaTrader5` usage ↛ order sending (data adapter only;
  tree-wide scan enforced).
- Gold fixtures ↛ everything (immutable; only investigation may follow
  a divergence, never a rewrite).
