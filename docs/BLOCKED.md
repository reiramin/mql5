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

## Stage 3 broker parity: EURUSD denomination probe NOT_SYNCED_AFTER_60s (blocks every gate run)

gate_run40, gate_run44 and gate_run45 all FAILed stage 3 with
`EURUSD denomination_probe NOT_SYNCED_AFTER_60s` and in-scope PENDING
rows:
- gate_run40 and gate_run44 at `6894de2`, Sunday about 22:00 UTC;
- gate_run45 at `5fd4368`, **Monday 06:56 UTC, in market hours**.

So it is not the weekend re-open. gate_run43 (`4b8cad0`, earlier on
Sunday) passed stage 3. The first failure, gate_run40, was the first gate
run after the demo harness logged the terminal in to the demo accounts.

Only EURUSD is exported fresh by the gate; the other symbols' passing
probes come from older export files. Until stage 3 passes, no gate run
reaches stage 4+, which includes the gold1 import, the gold2 37/37
reconciliation proof for FILL-MODE-1, and the demo grading.

**What the next report will show.** From STAGE3-SYNC-QUOTE-1 on, the
stage-3 FAIL text quotes the exporter's `synced` / `sync_unmet`: which
readiness condition never held (terminal not connected / symbol not
synchronized / no tick / tick value not > 0). That fact decides the next
step.

Until then, if the owner can, check the following on the terminal:
- whether `symbolspec_EURUSD.json` in the last gate run's evidence folder
  has `"sync_unmet"` in its `denomination_probe` block;
- whether the terminal was on the usual account at stage 3.

The exporter (`mql5/Scripts`) is not changed, and the PENDING rule is not
relaxed.

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
