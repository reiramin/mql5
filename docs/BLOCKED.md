# BLOCKED / WAITING — open items (updated 2026-10-12)

Nothing below is a code blocker that this session can fix. Each item waits
on an owner action or an input this session cannot produce.

## gold1 stage 4: not yet re-measured after the owner deleted EURUSD.G1

The owner deleted the stale custom symbol EURUSD.G1 (the step this file
gave after gate_run43). The next gold1 run, gate_run44 (`6894de2`), stopped
at stage 3 (next section), so the importer never ran. Whether it now takes
its `created_fresh` path is **not measured**.

If a later run refuses again, the terminal's own message (or the
importer's `symbol_state` JSON) is the fact to report. `mql5/` is not
touched for it: the importer is outside CLAUDE.md exception 1.

## Stage 3 broker parity: EURUSD denomination probe NOT_SYNCED_AFTER_60s (re-run)

gate_run40 (gold2) and gate_run44 (gold1) both ran at `6894de2` around
22:00 UTC on Sunday 2026-10-11, and both FAILed stage 3 with the same
rows:
- in-scope PENDING `EURUSD sizer.behaviour` / `tick_value_denomination`;
- `denomination_probe: reason="NOT_SYNCED_AFTER_60s" attempts=10`.

BTC, US30 and XAUEUR passed their probes in the same runs. gate_run43, at
14:29 UTC the same Sunday, passed stage 3.

Two differences are visible, and neither is proven to be the cause:
- **The account.** Both runs came straight after the demo harness, whose
  restores ended on the "hedging"-role login. That login is a netting
  account (next section), so stage 3 may have exported on a different
  account than in gate_run43.
- **The time.** Around 22:00 UTC Sunday is the weekly FX re-open
  boundary.

No code defect is shown. The PENDING rule is not relaxed: a probe that
did not run is not a pass. The exporter is in `mql5/Scripts` and is not
changed.

**Next run:** re-run the gate in FX market hours, with the terminal on
the usual hedging account. If stage 3 fails again, include these fields
from that run's `symbolspec_EURUSD.json`: `account_currency`,
`account_margin_mode`, `server`, and the `denomination_probe` /
`sync_unmet` block. Not the login.

## Demo safety tests (task 2: restart, netting, hedging): three owner items

gate_run39 (`f29b7fa`) has 5/8 safety files VALID: kill_switch,
risk_veto, meta_reduce, sl_verify and lost_response.

The owner then ran the demo harness (gate_run40, `6894de2`). All three
runs FAILED, and stage 3 blocked the gate, so the runs were never graded.
The causes, from `reports/gate_run40/`:

1. **The "hedging" login is a netting account (owner: accounts file).**
   - The MT5 journal shows that the login under `hedging` in the local
     accounts file was authorized as `demo account - netting mode`.
   - The EA reports `margin_mode=0` for it.
   - Every restore therefore failed with "restore account margin_mode 0
     is not hedging (2)", and the restart and hedging tests ran on a
     netting account.

   The `hedging` entry must name a HEDGING demo account (margin_mode 2).
   The `netting` entry is correct as a netting account.

2. **EA bug: the filling mode is read as a bitmask with the wrong values
   (owner decision: outside exception 1).**
   - `SpecIsFillingAllowed` in `mql5/Include/Mql5Bot/SymbolSpec.mqh` tests
     `spec.fillingMode & (long)filling`.
   - `ENUM_ORDER_TYPE_FILLING` is an index: ORDER_FILLING_FOK = 0,
     ORDER_FILLING_IOC = 1, ORDER_FILLING_RETURN = 2.
   - `SYMBOL_FILLING_MODE` is a flag mask: SYMBOL_FILLING_FOK = 1,
     SYMBOL_FILLING_IOC = 2.
   - So FOK is never "allowed" (`mask & 0`), and IOC reads as allowed
     exactly when the FOK flag is set.

   gate_run44's live export (`parity_report.json`) records
   `filling_mode_mask`: EURUSD 1 (FOK only), US30 2 (IOC only),
   XAUEUR 3, BTC 1. On EURUSD (mask 1):
   - the EA sends IOC and gets INVALID_FILL;
   - `SpecNextFilling` finds nothing, so the open is rejected.

   On an IOC-only symbol (mask 2) it would try RETURN. Only mask 3 picks
   a mode the broker accepts, and that is by accident.

   That is the once-a-second `EXEC|open_rejected|EURUSD|INVALID_FILL` and
   the journal's `[Unsupported filling mode]` in gate_run40's restart run.
   It would reject every live open on such a symbol.

   Why it is not fixed here:
   - `SymbolSpec.mqh` is not in CLAUDE.md exception 1 (only Mql5Bot.mq5,
     TradeManager.mqh and Scripts).
   - The fix changes the filling the gold legs send, so "gold legs
     identical at default inputs" would need a fresh gold proof.

   Proposed patch, for the owner to authorize:
   - map ORDER_FILLING_FOK to SYMBOL_FILLING_FOK and ORDER_FILLING_IOC to
     SYMBOL_FILLING_IOC;
   - allow ORDER_FILLING_RETURN only when SYMBOL_TRADE_EXEMODE is not
     SYMBOL_TRADE_EXECUTION_MARKET (MQL5 reference: RETURN is not used in
     Market execution);
   - then a stage-1 compile and both gold runs.

3. **The netting run's EA started before the login completed (fixed in
   the harness: built, unit-tested, never run live).**
   - The EA's first lines carry server time `2024.08.23` and
     `InpTestDemoProbe=2 REFUSED: honoured only on a logged-in DEMO
     account`.
   - Then: `symbol spec build failed: tick_value_loss <= 0` and
     `shutting down`.
   - The harness waited the full 900 s for `EA START`.

   `demo_harness` now stops the terminal on that refusal and relaunches
   once; a second refusal fails the run, naming it (DECISIONS
   DEMO-HARNESS-RELAUNCH-1). The safety gate itself is unchanged: the
   probe still runs only on a logged-in DEMO account.

Once item 1 is fixed, the demo runs can be repeated in FX market hours.
Item 2 will still block the restart test on a FOK-only symbol until it is
authorized and fixed.

## Waiting on the items above

- **Task 4** (FULL run, stages 9-10) needs both golds and all 8 safety
  files VALID.
- **Task 5** (docs/SHOWCASE.md) states the final verdict, so it follows
  task 4.

No MT5 result is invented. This file is deleted once nothing in it is
waiting.
