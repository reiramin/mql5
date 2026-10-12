# BLOCKED / WAITING — open items (updated 2026-10-12, DEMO-CHECK-CRLF-1)

Nothing below is a code blocker that this session can fix. Each item waits
on an owner action or an input this session cannot produce.

## Demo safety files (restart, netting, hedging): stage 7 connection check (DEMO-CHECK-CRLF-1)

**gate_run52** (`c8bc022`, `-Golds gold2 -DemoSafety`):
- stages 0-5 PASS, `symbol_state` created_fresh;
- stage 7 FAILED `[demo_restore_not_connected]` for all three tests;
- stage 8 did not run, so the gold2 reconciliation was not measured in
  this run.

The terminal journal shows the credential-less launch WAS connected
("authorized ... synchronized ... demo account - hedging mode"). The
exporter failed: `cannot open Mql5Bot\demo_connect_check\ EURUSD.json
err=5004`.

**Cause:** the "space" is a carriage return.
- The harness joined its preset/ini lines with CRLF and wrote them in text
  mode; on Windows every LF became CRLF, so lines ended CR CR LF.
- MT5 kept the stray CR in `InpExportDir`.

**Fix,** built, unit-tested, never run live:
- the three CRLF files are written byte-exact (`newline=""`);
- a test parses them as MT5 does: no whitespace around any value, and the
  export path is exactly `Mql5Bot\demo_connect_check\EURUSD.json`;
- the gate now records its own exit code (`gate_exit_code.txt`,
  `gate_summary.json` `exit_code`, a `GATE_EXIT_CODE=` line), since
  gate_run52's wrapper captured none.

**Next:** the `[runner: demo-in-gate]` run (gold2 `-DemoSafety`, FX market
hours). Expected evidence:
- stage 7 PASS;
- stage 8 grading all 8 safety files;
- gold2 MATCH 37/37.

## gold1 stage 8: MATCH (gate_run53) — resolved by S8-PATH-1

**gate_run53** (`93d6e45`): gold1 `result: MATCH`, `state: VALID`.
- 18/18 paired in m1_ohlc and every_tick, with no divergence.
- every_tick's first different exit is recorded as a tick path, as
  designed.

The run's verdict is still `NOT_VERIFIED_ARTIFACT_MISMATCH`, only because
the three demo safety files are missing (it was not a `-DemoSafety` run).

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
