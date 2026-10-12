# BLOCKED / WAITING — open items (updated 2026-10-12, RESTART-ORDER-1 + EMPTY-OBJ-1)

Nothing below is a code blocker that this session can fix. Each item waits
on an owner action or an input this session cannot produce.

## Resolved by gate_run55 (`90041fe`, gold2 `-DemoSafety`)

- **Stage 7:** PASS.
- **Stage 8:** PASS, verdict `MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE`,
  nothing missing.
- **gold2:** MATCH, 37/37 in both models.
- **Safety:** all 8 results VALID, including the live demo restart,
  netting and hedging.
- **gold1:** MATCH 18/18 (gate_run53).
- **Proven live:** DEMO-CHECK-CRLF-1, STAGE8-EMPTY-NOTBUILT-1 and
  RESTART-GRADE-1.

## gate_run56 (FULL run, `32664ac`): restart MISSING; SPEC-WAIT-1 is the fix

**Result:**
- gold1 18/18 and gold2 37/37 MATCH in both models;
- 7 of 8 safety results VALID;
- **restart MISSING**: the probe-3 relaunch failed OnInit with `symbol
  spec build failed: tick_value_loss <= 0` while the broker connection
  dropped;
- verdict `NOT_VERIFIED_ARTIFACT_MISMATCH`; no certificate.

**Fix,** built, unit-tested, never run live (owner decision, CLAUDE.md
exception 1.d):
- **SPEC-WAIT-1:** the EA waits in WAITING_SYMBOL, bounded at 60 s, instead
  of failing init on a live start.
- **HARNESS-INIT-FAIL-1:** the harness fails a launch whose EA init fails,
  by name, without the 900 s wait.

**Next:** the `[runner: full]` run. The EX5 changes, so the golds are
re-run. Expected:
- stages 0-10 PASS;
- verdict `MT5_VALIDATED_BAR_MODELS`;
- `GATE_RESULT=certified_with_log_graded_legs`.

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
