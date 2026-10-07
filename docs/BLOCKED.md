# BLOCKED — open items (updated 2026-10-07)

Blocks 1 (task 1a needs mql5/) and 3 (task 3 needs artifacts/gold +
frozen_inputs.json) are CLEARED: the owner added scoped exceptions to
CLAUDE.md on 2026-10-07. Task 1a is done under exception 1; see DECISIONS
SAFETY-GATE-1 / SAFETY-GATE-2.

## Still blocked: no `gate-reports` branch

`git ls-remote origin` (2026-10-07, after the merge of PR #34) shows no
`gate-reports` branch, and no `reports/gate_runNN/` folder exists. These
tasks need gate runs from the Windows runner, which this session cannot
start:
- task 2 (the 8 safety files VALID for gold2);
- task 3's iteration to gold1 VALID/MATCH;
- task 4 (FULL run, stages 9-10).

No MT5 result is invented. This file is deleted once a gate run report
exists to work from.
