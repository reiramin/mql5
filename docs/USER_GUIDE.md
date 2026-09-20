# User / Operator Guide

Written for the project owner. Exact contracts live in `SPEC.md`,
`SYSTEM_INVARIANTS.md` and `SAFETY_GOVERNANCE.md`; this guide explains
how the pieces behave together. Numbers and semantics here always defer
to those documents.

> **Status — read first.** Nothing in this project is certified. The first
> full owner gate run (2026-09-20) reached stages 0–4 PASS, stage 5 FAIL,
> and stages 6–10 never ran; no strategy is VERIFIED and none has traded a
> demo or a live account. The account of record is
> [OWNER_DELIVERY.md](OWNER_DELIVERY.md). The bot trades **only while
> MetaTrader 5 is running and connected** — close the terminal or sleep the
> PC and it stops (see [MT5_SETUP_AND_OPERATION.md](MT5_SETUP_AND_OPERATION.md)
> and [DEPLOYMENT.md](DEPLOYMENT.md)).

## High level

On every new bar (and, depending on the engine, on tick events), the EA:

1. **Session filter** — is this an allowed trading day/time? If not,
   manage exits only.
2. **Signal engine** — the selected built-in engine produces a
   desired-position signal from *completed* bars only (shift ≥ 1 —
   never lookahead).
3. **Meta allocation** — may only REDUCE the requested exposure
   (reduce-only), never increase it.
4. **Risk engine** — capital veto: sizes the position by risk-% over
   the stop distance against the broker SymbolSpec (tick value, volume
   min/max/step/limit, stops level, margin). A veto rejects the entry
   entirely; nothing bypasses it.
5. **Kill Switch** — emergency latch (daily-loss / drawdown / manual).
   While latched: **zero new orders**, existing positions still managed.
6. **TradeManager** — the ONLY execution authority: market/pending
   entries, retry with fill verification, SL/TP placement, SL
   verification after fill (SlGuard), position management.
7. **PositionGuard** — ATR trailing, breakeven, partial scale-out,
   max-bars timeout.
8. **Telemetry/Logger** — file log + optional HTTP events (heartbeat,
   trade, alert).

The Python toolkit mirrors the same five engines with the same
semantics; Gold #1 and Gold #2 are the frozen proofs that the mirrors
agree (see `CERTIFICATION_GUIDE.md`).

## The five built-in strategies

`ema_crossover`, `rsi_reversal`, `donchian_breakout`,
`bollinger_reversal`, `macd_momentum` — selected by the `InpStrategy`
enum input. This is the entire MQL5 execution surface: there is no DSL
interpreter in the EA, so nothing else can execute there.

## Order execution and retries

- Entries are market or pending-stop per configuration.
- On a retryable broker retcode the EA retries statefully with a
  bounded attempt cap and backoff, then verifies the actual fill —
  retries are idempotent (no duplicated exposure).
- On a lost response (e.g. terminal restart), the EA re-adopts its own
  positions by magic number — it adopts, never duplicates.

## Magic identity

Each strategy identity maps to a deterministic magic number (FNV-1a of
the strategy id, `symbolspec.py` / `MagicMap.mqh`). The EA touches
only positions carrying its own magic: manual trades and other EAs are
never interfered with, and attribution survives restarts.

## Netting vs hedging

- **Netting account:** opposite-direction fills reduce the position;
  the invariant is weighted-net correctness with stable attribution.
- **Hedging account:** opposite-direction fills open isolated positions;
  each carries its own identifier and attribution.
  If the account type cannot exercise hedging, that leg is recorded as
  `BLOCKED_OWNER_ENVIRONMENT` — never converted into a pass.

## Risk sizing, conceptually

`lots = (equity × risk%) / (stop distance in ticks × tick value)`,
then normalized to the broker's volume step and clamped to
min/max/limit; margin-checked; reduced or rejected rather than rounded
into danger. Kelly-based sizing exists in the research sizer, is capped
at 0.25 and is OFF by default. The EA's RiskManager implements the
canonical SPEC math; the Python `sizer.py` is its twin.

## Stop protection

Every position must have a protective stop-loss (or a contractual
recovery path) before the entry is considered complete. SlGuard
verifies the SL after the fill and modifies if missing. Stops respect
the broker's stops/freeze levels; a configuration that cannot place a
legal stop is rejected, not approximated.

## Failure behaviors

| Situation | Behavior |
|---|---|
| Broker execution fails (retryable retcode) | bounded stateful retry + fill verification |
| Broker execution fails (terminal retcode) | recorded; no blind resubmission |
| Missing/invalid configuration | EA refuses to trade; logs the exact missing item |
| Factory unavailable | irrelevant to execution — the EA never depends on the Factory at runtime |
| Insufficient history/indicators warming up | warmup semantics: no signal until the indicator contract is computable (see `DECISIONS.md`) |
| Risk veto | entry rejected; the veto is journaled |
| Defensive state (daily loss / drawdown / manual latch) | Kill Switch latched: zero new orders until explicitly reset; exits still managed |

## The owner surfaces you can run

Each is **built, unit-tested, and never run live**, and none can place an
order or mark a strategy LIVE.

| Command | What it is |
|---|---|
| `python -m mql5bot ...` | the quant-toolkit CLI (data, backtest, compare, optimize, walkforward, dashboard); add `--lang fa` for Persian output |
| `python -m mql5bot.factory.cli ...` | the Factory CLI — research/spec only, never trades |
| `python -m mql5bot.api` | the operator console — six pages (home, strategies, new-strategy conversation, trades, certification, settings/health) with owner-token auth and live updates; Persian at `?lang=fa` (needs `uvicorn`). Full guide: [CONSOLE.md](CONSOLE.md) |
| `python -m mql5bot.notify.telegram_ops` | the Telegram operator — daily digest, per-trade notifications, and the `status`/`positions`/`report`/`stop` commands |
| `python -m mql5bot.telemetry_bridge` | the collector the EA POSTs heartbeat/trade/alert events to |

**Stopping vs starting is asymmetric.** You can stop trading from Telegram
(`stop`, immediate, no confirmation), but you can never resume from Telegram —
resuming is a console action only. See [TELEGRAM.md](TELEGRAM.md) and
[KILL_SWITCH.md](KILL_SWITCH.md).

**Describing a strategy in words.** The guided conversation
([FACTORY_GUIDE.md](FACTORY_GUIDE.md)) takes Persian text → a restatement you
must accept → a question for anything you left unspecified → a schema check.
Its pass means **SCHEMA-VALIDATED — structure only; the strategy has NOT been
tested**. Testing it (backtest/robustness/out-of-sample) and reaching MT5 are
separate, not-yet-done steps.

## Safety rules for operators

1. Demo before anything else; live only after the full certification
   ladder (`CERTIFICATION_GUIDE.md`) and explicit human approval.
2. Never edit gold fixtures, strategy parameters or risk limits to make
   a result match — a mismatch is evidence.
3. Keep the daily-loss and drawdown limits enabled; treat the Kill
   Switch as a tested seam, not decoration.
4. Collect evidence as raw artifacts — screenshots are not evidence.
