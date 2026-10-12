# BLOCKED / WAITING — open items (updated 2026-10-12, DEMO-IN-GATE-1)

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

## Demo safety files (restart, netting, hedging): run them inside the gate (DEMO-IN-GATE-1)

**What the reports show.**
- **gate_run46** (`fdd7b58`): the demo session COMPLETED all three tests
  (FILL-MODE-1 live: every probe order `done=true`).
- **gate_run47** (same HEAD, gold2): stage 3 PASSED after the owner
  re-saved the hedging login; gold2 MATCH 37/37; 5/8 safety VALID.

  The three demo files were rejected. The demo EX5 (`4f03256d…`) differs
  from the gate's stage-1 EX5 (`d9a5609c…`) at the same HEAD, because
  MetaEditor output differs per compile. The binding rule stays.

**Fixes, all built, unit-tested, never run live:**
- **DEMO-LOGIN-PERSIST-1:** the harness keeps the hedging password in the
  terminal's own store, ends with a clean exit, and proves a
  credential-less launch connects.
- **DEMO-IN-GATE-1:** `owner_gate.ps1 -DemoSafety` runs the harness as
  stage 7 with that run's own stage-1 EX5, FAILs loudly if the terminal is
  not left connected, and stage 8 grades the runs in the same gate run.

**Next:** the `[runner: demo-in-gate]` run, in FX market hours (not Fri
20:00 – Sun 22:15 UTC, not 20:45 – 22:15 UTC daily). Expected evidence:
- stage 7 PASS;
- stage 8's safety block showing restart / netting / hedging graded, not
  MISSING;
- gold2 still MATCH 37/37.

## gold1 stage 5: the EA's OnInit fails on both gold1 legs (gate_run48)

gate_run48 (`fdd7b58`, `-Golds gold1`):
- **Stages 0–4 PASS.** The import is `created_fresh`, round-trip == manifest
  `074530cd…`, so the stale-symbol item is resolved.
- **Stage 5 FAILs.** Both gold1 legs: "EA OnInit returned non-zero: the
  test never ran this leg's strategy … strategy_loaded (expected DSL
  strategy 'ema_crossover_ref'; the EA logged None)". The real_ticks leg
  is NOT_APPLICABLE (bar-only fixture).

The report does not contain the EA's own OnInit error. The tester journal
was excluded for leak reasons, and the stage-5 grade quotes only "OnInit
returns non-zero code 1".

**Needed from the next gold1 run:** the EA's own `[mql5bot]` OnInit lines
from that leg's tester agent log, with account values masked. For example
a `DSL bundle refused: …` or `symbol spec build failed: …` line.

One candidate, unverified: a FRESHLY created bars-only custom symbol may
read back a calculated tick value of 0 (the importer JSON's own
`derived_tick_values` note). The EA's spec build refuses
`tick_value_loss <= 0`. This is the next gold1 item (task 3).

## Waiting on the items above

- **Task 4** (FULL run, stages 9-10) needs both golds and all 8 safety
  files VALID.
- **Task 5** (docs/SHOWCASE.md) states the final verdict, so it follows
  task 4.

No MT5 result is invented. This file is deleted once nothing in it is
waiting.
