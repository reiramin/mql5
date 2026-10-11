# BLOCKED / WAITING — open items (updated 2026-10-11)

The `gate-reports` block is CLEARED: the branch exists, with gate_run38 and
gate_run39. Nothing below is a code blocker; each item waits on an input
this session cannot produce.

## Waiting on the owner's demo environment (task 2: restart, netting, hedging)

gate_run39 (`f29b7fa`, `-Golds gold2`) has 5/8 safety files VALID:
kill_switch, risk_veto, meta_reduce, sl_verify and lost_response. The
other three are MISSING because the demo harness was not run. The
SUMMARY says: "%USERPROFILE%\.mql5bot\demo_accounts.json does not exist;
MQL5BOT_DEMO_ACCOUNTS not set".

They need the owner steps in `docs/SAFETY_DEMO_PLAN.md` ("What the owner
must do by hand"):
- a NETTING demo account;
- the accounts file;
- one `tools/demo_safety_harness.py run --test <t>` per test, in market
  hours;
- then a gate run that picks up `evidence/demo_safety`.

No code change can produce that evidence.

## Waiting on reports

- A Windows pytest re-run after WIN-NEWLINE-1 (the merge commit asks for
  it with `[runner: pytest]`). The 80 failures at `3337bfa` are fixed and
  emulated on Linux; they are not yet proven on Windows itself.
- A gold1 gate run at or after `46fcdd6` (task 3: gold1 VALID/MATCH).
- Task 4 (FULL run, stages 9-10) comes after both golds and all 8 safety
  files are VALID.
- Task 5 (docs/SHOWCASE.md) states the final verdict, so it follows
  task 4.

No MT5 result is invented. This file is deleted once nothing in it is
waiting.
