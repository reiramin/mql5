# BLOCKED / WAITING — open items (updated 2026-10-13, certified by gate_run59)

**Nothing blocks certification.** gate_run59 (gate-reports `db13f55`,
master `ab312d5`) ended `GATE_RESULT=certified_with_log_graded_legs` with
the verifier verdict `MT5_VALIDATED_BAR_MODELS`, stages 0-10 PASS, gold1
18/18 and gold2 37/37 MATCH, and 8/8 safety VALID. The certificate is
`reports/gate_run59/certificate/` on `gate-reports`. Every earlier blocker
in this file (gate_run55-57) is resolved and removed.

## Follow-up (not blocking): IMPORT-SELFHEAL-1

gate_run58 stopped at stage 4 because `CustomRatesDelete` left 5760 bars
on EURUSD.G2. The owner deleted the symbol by hand before gate_run59. The
importer now drops and recreates such a symbol itself (CLAUDE.md exception
1.e). gate_run60 (master `50cdb71`) compiled it and passed stage 4, but both
symbols were adopted cleanly, so the drop+recreate branch was not exercised:
built, unit-tested, never run live.

## Not yet run live (built, unit-tested)

- The SPEC-WAIT-2 WAITING_SYMBOL retry and give-up path.
- The HARNESS-SUSPEND-1 INTERRUPTED abort.

gate_run59 needed neither (docs/DECISIONS.md, "CERTIFIED by gate_run59").

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
