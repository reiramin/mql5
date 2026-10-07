# BLOCKED — autonomous run of 2026-10-07

The run stopped here because the next tasks would require breaking a
HARD RULE or depend on something that does not exist yet.

## 1. Task 1a needs an edit to mql5/, which CLAUDE.md forbids

**Task 1a.** Gate every 8a-8c test input on `MQLInfoInteger(MQL_TESTER)`,
and `InpTestDemoProbe` on `ACCOUNT_TRADE_MODE_DEMO`. Otherwise log
REFUSED and act as 0.

**Blocker.** The code is `mql5/Experts/Mql5Bot/Mql5Bot.mq5`. CLAUDE.md
says: "NEVER modify mql5/ ... Any change there invalidates the owner
certification gate." The session's permission layer refused the edit on
that rule. The task's own exception list covers only task 3, not mql5/.

**What the owner must decide.** Either:
- make the edit; or
- add a scoped exception to CLAUDE.md for this change.

Earlier PRs (#31, #34) did edit mql5/ under owner authorization recorded
in DECISIONS.md, so the owner should also say whether CLAUDE.md or those
authorizations govern.

**Design, for whoever makes the edit (recorded in DECISIONS
SAFETY-GATE-1):**
- **Effective values.** Add globals `g_tKillAfter`, `g_tStripSl`,
  `g_tSafetyLog`, `g_tLostResp`, `g_tUnsent`, `g_tDemoProbe`. Set them
  once in `OnInit`, right after `g_log.Init(...)`, by `ResolveTestInputs()`.
- **Tester gate.** `tester = MQLInfoInteger(MQL_TESTER) != 0`. The five
  8a-8c inputs pass only when `tester`.
- **Demo gate.** `demo = AccountInfoInteger(ACCOUNT_LOGIN) > 0 &&
  AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO`. The
  login check matters: with no account the trade mode reads 0, which IS
  `ACCOUNT_TRADE_MODE_DEMO`.
- **Refusal.** A non-zero input that is refused logs
  `TEST input <name>=<v> REFUSED: honoured only ... (acting as 0)` and
  becomes 0. A zero input logs nothing, so the gold legs' logs at default
  inputs are byte-identical.
- **Use sites.** Replace every read of the six inputs at the use sites
  with the effective globals.
- **Fail closed.** Re-check `demo` at the top of `TestDemoProbePump()`
  and stop the probe if it no longer holds.
- **Source tests.** Update `tests/test_safety_legs.py` and
  `tests/test_safety_demo.py`, which pin `if(InpTest... > 0)`, to the
  globals. Add tests that pin `ResolveTestInputs()` after `g_log.Init`,
  the `MQLInfoInteger(MQL_TESTER)` and DEMO + login conditions, the
  REFUSED text, and that no use site reads an `InpTest*` input directly.

**Pre-existing finding (same file).** `if(!MQL_TESTER &&
!MQL_OPTIMIZATION)` in OnInit tests enum constants, not
`MQLInfoInteger(...)`, so the live trade-permission check never runs.

## 2. There is no `gate-reports` branch

`git ls-remote origin` on 2026-10-07 lists no `gate-reports` branch, and
no `reports/gate_runNN/` folder exists. Tasks 2 and 4 depend on gate runs
made by the Windows runner, which this session cannot start. No MT5
result is invented.

## 3. Task 3 also touches CLAUDE.md-protected paths

Task 3 regenerates the `artifacts/gold` fixture and re-anchors
`frozen_inputs.json`. CLAUDE.md forbids both ("NEVER modify ...
artifacts/ ... frozen_inputs.json"). The task grants an owner-authorized
scoped exception, but given block 1 the same permission refusal is
expected. Task 3 also comes after task 2, which is blocked. The owner
should record the exception in CLAUDE.md (or DECISIONS, referenced from
CLAUDE.md) before an agent attempts it.

## What WAS done

Task 1b (demo harness restore to the hedging account): built,
unit-tested, never run live. It is on branch
`claude/aegis-safety-fixes-20aen5`, on top of `feat/safety-demo`
(PR #34). See DECISIONS SAFETY-DEMO-RESTORE-1.

PR #34 is NOT merged: task 1a is a required part of it and is blocked.
