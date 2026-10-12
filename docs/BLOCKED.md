# BLOCKED / WAITING — open items (updated 2026-10-12, FILL-MODE-1)

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

## Demo safety tests (task 2: restart, netting, hedging): waiting on a demo run

gate_run40's three demo runs FAILED for three reasons. All three are now
addressed, but none is proven on the terminal yet:
1. **The "hedging" login was a netting account.** The owner fixed the
   accounts file (2026-10-12):
   - "hedging" is now a real hedging account;
   - "netting" is a netting account;
   - the terminal is logged in to the hedging account again.
2. **FILL-MODE-1, the EA filling-mode bug.** Fixed under CLAUDE.md
   exception 1.c (DECISIONS FILL-MODE-1): built, unit-tested, never run
   live.
3. **The EA started before the demo login.** The harness relaunches once
   (DEMO-HARNESS-RELAUNCH-1): built, unit-tested, never run live.

**Next:** the runner's `[runner: demo]` run in FX market hours, then a
gate run that grades `evidence/demo_safety`. That gold2 run must still
reconcile 37/37. Any change there stops the work and is reported.

## Waiting on the items above

- **Task 4** (FULL run, stages 9-10) needs both golds and all 8 safety
  files VALID.
- **Task 5** (docs/SHOWCASE.md) states the final verdict, so it follows
  task 4.

No MT5 result is invented. This file is deleted once nothing in it is
waiting.
