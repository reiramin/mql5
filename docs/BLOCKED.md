# BLOCKED / WAITING — open items (updated 2026-10-12, RESTART-ORDER-1 + EMPTY-OBJ-1)

Nothing below is a code blocker that this session can fix. Each item waits
on an owner action or an input this session cannot produce.

## Demo safety files: stage 7 PASS (gate_run54); stage 8 crashed, and restart was mis-graded

**gate_run54** (`422c174`, gold2 `-DemoSafety`):
- stage 7 PASS: restart, netting and hedging all COMPLETED with this run's
  stage-1 EX5, and each restore stayed connected (DEMO-CHECK-CRLF-1
  worked);
- the builder paired gold2 37/37 with 0 missing and 0 extra in both
  models;
- 7 of 8 safety files graded passed by the builder;
- the gate exit code was recorded (1).

**Stage 8 crashed before the verifier ran** (EMPTY-OBJ-1). This was
`UNHANDLED_ERROR: The property 'Name' cannot be found` in the
`not_built` note. Under StrictMode 2.0, `.PSObject.Properties.Name` on an
empty object (`not_built: {}`, i.e. everything built) throws.
`Get-DataProp` had the same latent bug.

**restart was graded `NO_RESTART`** (RESTART-ORDER-1). The grader ordered
events by the EA's stamp, which is TimeCurrent(), stale at OnInit. The
relaunch START was stamped 16:06:55, before the probe's 16:07:21. The
harness's own UTC steps show the relaunch at 13:08:05, after the probe at
13:07:20. The grader now orders events by log position, and only a
probe=1 START counts as the relaunch (stricter).

**Fix,** built, unit-tested, never run live. Both fixes are in tools/ and
python/ only.

**Next:** the `[runner: demo-in-gate]` run. Expected evidence:
- the verifier runs;
- all 8 safety files are graded;
- gold2 is MATCH 37/37.

## gold1 stage 8: MATCH (gate_run53) — resolved by S8-PATH-1

**gate_run53** (`93d6e45`): gold1 `result: MATCH`, `state: VALID`.
- 18/18 paired in m1_ohlc and every_tick, with no divergence.
- every_tick's first different exit is recorded as a tick path, as
  designed.

The run's verdict is still `NOT_VERIFIED_ARTIFACT_MISMATCH`, only because
the three demo safety files are missing (it was not a `-DemoSafety` run).

## Optional owner item (outside exception 1): EA log stamps are stale at OnInit

`Logger.mqh` stamps each line with `TimeCurrent()`, the last known server
tick time. Right after a (re)launch, before the first tick, that time is
stale. In gate_run54 the relaunch START was stamped 16:06:55, before the
probe's 16:07:21. Grading no longer depends on it (RESTART-GRADE-1 orders
events by log position), so this is NOT blocking.

Stamping with `TimeGMT()` or `TimeLocal()` would make the log
chronological. That is an `mql5/` change outside exception 1, so it is
left to the owner.

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
