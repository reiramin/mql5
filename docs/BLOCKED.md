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

## gold1 stage 5: OnInit failed (gate_run48) — fixed by the tester start (WARMUP-FROMDATE-1)

**Cause**, from the redacted EA lines
(`reports/gate_run48/gold1_oninit_lines.txt`):
- the gold1 legs started at the fixture's first day;
- MT5 moved the start to 2024.01.06 and gave the EA 120 H1 bars;
- the EA needs `InpDslBars=500` and its DSL series build failed at OnInit.

The tick-value hypothesis is rejected.

**Fix**, built, unit-tested, never run live: the gold1 legs now start at
`2024.01.30`, the first fixture day with 500 bars of gold1's own constant
warm-up before it. The EA's window is bit-identical to Python's history;
the first expected trade is 2024.02.05. gold2 is unchanged.

**Next:** the `[runner: gold1]` run. Both gold1 legs must pass OnInit, and
gold1 must reach stage 8 and reconcile like gold2.

## Owner change needed (outside exception 1): log WHY the DSL series build failed

gate_run48's line was `[mql5bot] DSL series build failed: ` with nothing
after the colon. In `mql5/Include/Mql5Bot/DslExecution.mqh`,
`DslBuildSeries` returns false on `CopyRates(...) < bars` without recording
a reason, and `CDslRuntime` keeps `m_error` private.

The smallest logging-only fix is at the two call sites in
`mql5/Experts/Mql5Bot/Mql5Bot.mq5`, which CLAUDE.md exception 1 does not
cover (only safety hooks, SAFETY-GATE-1, FILL-MODE-1). The exact change:

```mql5
// Mql5Bot.mq5, OnInit (~line 689)
      if(!DslBuildSeries(g_dslJson,g_dslLoader.Spec(),g_symbol,g_tf,InpDslBars,g_dslRuntime))
        {
         string why=g_dslRuntime.Error();
         if(why=="")
            why=StringFormat("insufficient history: %d bars of %s %s available, InpDslBars=%d",
                             Bars(g_symbol,g_tf),g_symbol,EnumToString(g_tf),InpDslBars);
         Print("[mql5bot] DSL series build failed: ",why);
         return INIT_FAILED;
        }

// Mql5Bot.mq5, per-bar rebuild (~line 263): the same `why` before
//      g_log.Error("DSL series build failed: "+why);
```

It changes no decision, only the message. Gold legs at default inputs are
identical. To make it, the owner adds an exception (or extends 1), and
stage 1's strict compile proves it.

## Waiting on the items above

- **Task 4** (FULL run, stages 9-10) needs both golds and all 8 safety
  files VALID.
- **Task 5** (docs/SHOWCASE.md) states the final verdict, so it follows
  task 4.

No MT5 result is invented. This file is deleted once nothing in it is
waiting.
