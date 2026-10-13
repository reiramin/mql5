# Rules for any agent working in this repository

- NEVER modify mql5/, artifacts/, evidence/, logs_owner/, frozen_inputs.json,
  certification_manifest.json, or any manifest. These are the compile-of-record and
  frozen evidence. Any change there invalidates the owner certification gate.
- No new third-party dependency. Standard library first; fastapi/jinja2/httpx are the
  existing set (see requirements.txt).
- Never state or imply a profit claim, anywhere, in any file.
- The certification gate result is truth: stage 5 is FAIL, BLOCKED is not a pass,
  stages 6-10 have never run. Never describe them otherwise.
- Anything built but never run against a live system is written as
  "built, unit-tested, never run live" — never "done", never "working".
- Every "done" must be checkable against a file, a test, or a hash. Never invent a
  hash, a test count, or a result you did not see in output.
- A verdict may only be justified by evidence scoped to the thing being judged. Never
  let one unit's result justify another's.
- Work on a branch. Never commit to master directly. Never amend or force-push.
- Before committing: ruff on python/ tests/ tools/ factory/ must exit 0, and the full
  pytest suite must exit 0. Read exit codes, do not poll for summary lines.
- Secrets come from environment variables only; never in code, docs, commits or logs.
- End every session by appending a dated entry to AUTONOMOUS_LOG.md: branch, commits,
  test exit code, what was done, what was NOT done and why.
  
## Owner-scoped exceptions (Sal, 2026-10-07) — valid until the final certificate is issued

These narrow the NEVER-modify rule above; everything not listed stays fully protected
(evidence/, logs_owner/, certification_manifest.json are NEVER modified).
1. mql5/Experts/Mql5Bot/Mql5Bot.mq5, mql5/Include/Mql5Bot/TradeManager.mqh and
   mql5/Scripts/Mql5Bot/*.mq5 may be changed ONLY for:
   a. safety-test inputs/hooks that default to OFF and are honoured only under
      MQLInfoInteger(MQL_TESTER) (8a-8c) or on a logged-in DEMO account (demo harness);
      [status: used by SAFETY-8A-8D-1, SAFETY-DEMO-1 and the demo probes; all 8 VALID in gate_run59]
   b. the SAFETY-GATE-1 bug fix (MQLInfoInteger instead of bare MQL_TESTER constants).
      [status: used by SAFETY-GATE-1 / SAFETY-GATE-2; done]
   At default inputs the gold legs must behave identically. Every such change is listed
   in docs/DECISIONS.md and is proven only by the owner terminal's stage-1 strict compile.
   c. FILL-MODE-1: the order filling-mode selection in mql5/Include/Mql5Bot/SymbolSpec.mqh
   (and its callers in TradeManager.mqh) may be fixed so the EA picks a filling mode the
   broker's SYMBOL_FILLING_MODE flags actually allow. Gold-leg results must stay identical
   (proven by the next gate run's reconciliation).
      [status: used by FILL-MODE-1 (#45); gold legs MATCH in gate_run59]
   d. SPEC-WAIT-1 (Sal, 2026-10-12): in Mql5Bot.mq5 / SymbolSpec.mqh, when the symbol spec
   cannot be built at OnInit because the symbol is not yet synchronized (tick value, tick
   size, contract size or point <= 0, or SymbolIsSynchronized false), the EA does NOT fail
   init: it returns INIT_SUCCEEDED in a WAITING_SYMBOL state, opens no new positions,
   retries the spec build on OnTimer/OnTick, and only after a bounded wait
   (InpSpecWaitSeconds, default 60; raised to 180 by SPEC-WAIT-2, owner request
   2026-10-13) logs the error and shuts down. While waiting it manages
   existing positions only if the spec is available; otherwise it just waits. The START
   line is logged only once the spec is built. Gold-leg results must stay identical.
      [status: used by SPEC-WAIT-1 (#52) and SPEC-WAIT-2 (#53); the wait/give-up path never ran live]
   e. IMPORT-SELFHEAL-1 (owner request, 2026-10-13): in
   mql5/Scripts/Mql5Bot/Mql5BotImportFixture.mq5, when the adopt-in-place wipe
   (CustomRatesDelete) leaves bars behind, the importer drops the custom symbol
   (closing any other chart on it) and recreates it on the created_fresh path; it
   refuses only if that drop fails, and still refuses any stale bar on a fresh symbol.
   The round-trip dataset-hash check is unchanged. Gold-leg results must stay identical.
      [status: used by IMPORT-SELFHEAL-1 (#55); built, unit-tested, never run live]
3. artifacts/gold/ (gold1 fixture + expected_execution) and
   artifacts/owner_mt5_gate/frozen_inputs.json may be regenerated/re-anchored ONCE for
   gold1, by the existing S8-REANCHOR procedure, with hashes produced by the tools
   (never hand-typed) and a DECISIONS.md entry.
   [status: used once, by S8-REANCHOR-2 (2026-10-07); exhausted]
4. Status wording: report the gate exactly as the latest gate run on branch
   gate-reports shows it (the "stage 5 is FAIL / stages 6-10 never ran" line above
   describes an older state).
   [status: in force; the latest run is gate_run59, certified_with_log_graded_legs]
