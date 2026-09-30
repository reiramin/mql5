# AUTONOMOUS_LOG

Append-only. One dated entry per agent session (see `CLAUDE.md`): branch,
commits, test exit codes, what was done, what was NOT done and why.

---

## 2026-09-29 — branch `autonomous/2026-09-29`

**Commits**
- `3075a8e` — CLAUDE.md (Job 1).
- `52cb00b` — review polish: repository identity, README 15-minute path,
  HANDOFF process, TASKS, CONSOLE v2 in PROGRESS/CHANGELOG/docs README,
  `ml_interfaces.py` docstring, link check (Job 2 a–g).
- `e6d7b15` — PROGRESS.md "Verification of the reviewed tree" (Job 2 h).
  Annotated tag `v0.1-review` created on it locally (Job 2 i).
- the commit that adds this entry — `docs/AUTONOMOUS_WORKER.md` (Job 3) and
  this log.

**Checks (exit codes read, not summary lines)** — each commit's tree was
checked before it was committed:
- `ruff check python/ tests/ tools/ factory/` with ruff 0.16.9: exit 0 on
  every tree.
- `python -m pytest tests/`: exit 0 on every tree; 2105 passed, 4 skipped.
- Python 3.11.15, Linux container.
- Link check over every tracked `.md`: 99 relative links, 0 broken.

**Done**
- CLAUDE.md written with the rule set as given.
- `raminhdev/mql5bot` replaced with `reiramin/mql5` everywhere outside
  `mql5/` except two deliberate mentions in HANDOFF.md (the frozen-file note
  and the history). The CI badge was kept because `.github/workflows/ci.yml`
  exists. `mql5/Experts/Mql5Bot/Mql5Bot.mq5` line 24 untouched and noted
  in HANDOFF.md.
- `docs/AUTONOMOUS_WORKER.md`: name, daily schedule and self-contained
  prompt for the "AEGIS autonomous worker".

**NOT done, and why**
- **Tag not on GitHub.** `v0.1-review` exists only in this session's clone.
  `git push origin v0.1-review` was refused four times ("the remote end hung
  up unexpectedly"). Branch pushes worked. This session's git proxy does not
  accept tag refs. The owner must create and push it:
  `git tag -a v0.1-review e6d7b15 -m "Reviewed tree: stages 0-4 PASS, stage 5 FAIL, 6-10 never run; nothing certified" && git push origin v0.1-review`.
- **The scheduled Routine is not created.** Creating triggers is disabled in
  this session, and the in-session scheduler dies with the container. The
  owner creates the Routine from `docs/AUTONOMOUS_WORKER.md`.
- **CI on `master` is red and not fixed here.** On `b06c7b3` the Python 3.10
  job fails with a collection error in `tests/test_factory_adapter.py`. It
  was not reproduced because only Python 3.11 is available here, and it is
  out of this branch's scope.
- The preinstalled ruff 0.15.8 reports 99 findings on `python/ tests/
  tools/`. The current ruff that CI installs (0.16.9) reports none. No lint
  code changes were made.
- Nothing was merged to `master`. No PR was opened. The gate result is
  unchanged: stages 0–4 PASS, stage 5 FAIL, stages 6–10 never run, and
  nothing is certified.

## 2026-09-29 — branch `feat/stage5-log-grading`

Based on `autonomous/2026-09-29` (d8f7e0d), because `CLAUDE.md` and this log
exist only on that branch. Its PR #1 is closed and not merged.

**Commits**
- `67b579e` — STAGE 5 R7: PASS_FROM_LOG, a log-based grading path for stage 5
  (`python/mql5bot/tester_log_grader.py`, `owner_gate_decide.py stage5-leg
  --window`, the stage-5 flow in `owner_gate.ps1`, tests, and docs).
- the commit that adds this entry.

**Checks (exit codes read)** — on the tree of `67b579e`, macOS, Python
3.13.1 (`.venv`), ruff 0.16.1:
- `ruff check python/ tests/ tools/ factory/`: exit 0.
- `python -m pytest tests/`: exit 0. The progress output shows 2136 passed
  and 1 skipped (`addopts = "-q"` plus `-q` suppresses the summary line).
- `owner_gate.ps1` parsed with pwsh's parser: 0 errors.

**Done**
- PASS_FROM_LOG is its own evidence class. It requires all of: "successfully
  finished", bars > 0 for the leg's symbol, a history-quality line, and a
  stated model equal to the requested one. Anything less keeps the R6
  verdict. Stage 5 records `PASS_FROM_LOG`, never `PASS`, and the gate
  cannot end in `certified` on it.
- A PASS_FROM_LOG leg writes `tester_<leg>_log_trades.json`, flagged
  `from_log: true`, for stage 8's parsed-report slot. Stage 8 is unchanged
  and was not run.

**NOT done, and why**
- **The captured gold2 window does not grade PASS_FROM_LOG.** The only
  real gold2 lines in the repo (DECISIONS.md) contain no line in which MT5
  states the model it ran, and rule 2 requires one. The grader does not
  infer the model. That test asserts BLOCKED. The PASS_FROM_LOG test adds
  a model line in MT5's format, marked as not captured.
- **No real captured deal or final-balance line exists in the repo.** The
  `tester_*_window.txt` artifacts are owner-side and gitignored. The EA
  DEAL format is pinned to `Mql5Bot.mq5` by a test. The MT5 journal formats
  are unverified.
- **Stage 8 still cannot pass a log-only leg.** Its binding chain requires
  the raw `.htm` hash for every model. Changing that is out of scope.
- Nothing ran on MT5. The gate record is unchanged: stages 0–4 PASS,
  stage 5 FAIL, stages 6–10 never run, and nothing is certified.

## 2026-09-30 — branch `feat/stage5-log-real-lines`

Stacked on `feat/stage5-log-grading` (PR #3), because PR #3 was still
open and unmerged when this work started. The PR for this branch targets
that branch and needs retargeting to `master` after #3 merges.

**Commits**
- `e74b88f` — STAGE 5 R8: the real gate-run-16/17 tester-log lines as a
  fixture; the grader reads the measured model statement; stage 8 accepts a
  PASS_FROM_LOG log trade list.
- the commit that adds this entry.

**Checks (exit codes read)** — tree of `e74b88f`, macOS, Python 3.13.1
(`.venv`), ruff 0.16.1:
- `ruff check python/ tests/ tools/ factory/`: exit 0.
- `python -m pytest tests/`: exit 0. The progress output shows 2160 passed
  and 1 skipped; 24 of the passes are new tests.
- `owner_gate.ps1` parsed with pwsh's parser: 0 errors.

**Done**
- `tests/data/owner_gate/tester_log_gate_runs_16_17.txt` holds the owner's
  six lines verbatim, with a citation to gate runs 16/17. The tests read
  real lines from it and do not retype them.
- The grader reads the model from `<SYM>,<TF> (<server>): <phrase>
  generating`, using the text after the last colon: "1 minutes OHLC ticks"
  is 1 and "every tick" is 0. The model-4 phrase is marked UNCONFIRMED.
  It also reads `final balance <n> <ccy>`. The real gold2 M1-OHLC window
  now grades PASS_FROM_LOG. The same window without the model line stays
  BLOCKED, and a test covers that.
- Stage 8 accepts `log_trades/<gold>_<model>.json` as a leg's trade source
  when no report exists, and records the source as "tester agent log" (in
  the report, the verdict reasons and the .ps1 stage-8 record). Zero deals
  is compared, not rejected. `first_divergence` and `_field_divergent`
  were not changed.
- Housekeeping: dropped `stash@{0}` ("pre-stage5-log-grading…"). Its README
  and INSTALLATION lines were already on `autonomous/2026-09-29`. Its
  CHANGELOG link was deliberately replaced on that branch because no v1.0.0
  tag exists. `stash@{1}` ("commit-2 docs in progress") is unrelated and
  was kept. Removed the `../mql5bot-ci-py310` worktree after checking it
  was clean and that `fix/ci-py310` (eac04cd) was pushed. This git version
  has no `worktree remove`, so the directory was deleted and then pruned.

**NOT done, and why**
- **"No trades on both sides" is not what gold2 gives.** The frozen gold2
  record says "56 trades is the semantic contract", and the
  hash-verified `reconciliation.json` has 56 trades. A zero-deal gold2 log
  is therefore compared as 56 vs 0 and reported DIVERGENT at
  `trade_count:<model>`, not MATCH. Runs 16/17 also predate the R5
  DEFECT 2 fix, so the EA ran its compiled-in defaults, not gold2's
  strategy. That last point is an inference from the R5 record.
- **Gold1 has no hash-pinned reconciliation** in the frozen record, so a
  log-sourced gold1 leg is INVALID in stage 8 (fail-closed). Adding a pin
  would change frozen inputs, which is forbidden.
- **The model-4 phrase and MT5's own deal/close lines are still
  UNCONFIRMED.** Only gold2_m1_ohlc has a captured model line.
- `owner_gate.MODEL_LABELS` (GUI enum) and `mt5tester.MT5_MODEL_LABELS`
  (config enum) still disagree for 3/4. This is documented, not changed.
- The gate does not copy `tester_<leg>_log_trades.json` into the owner
  package. The owner places it at `log_trades/<gold>_<model>.json`.
- Nothing ran on MT5. Record unchanged: stages 0–4 PASS, stage 5 FAIL,
  stages 6–10 never run, nothing certified.

## 2026-09-30 — branch `feat/stage5-legs-run-gold-strategy`

Stacked on `feat/stage5-log-real-lines` (PR #4). PRs #2, #3 and #4 were
all still open and unmerged, so the PR for this branch targets #4's branch
and needs retargeting as they merge.

**Commits**
- `ff26973` — STAGE 5 R9: each tester leg runs the strategy its gold
  manifest pins.
- the commit that adds this entry.

**Checks (exit codes read)** — tree of `ff26973`, macOS, Python 3.13.1
(`.venv`), ruff 0.16.1:
- `ruff check python/ tests/ tools/ factory/`: exit 0.
- `python -m pytest tests/`: exit 0. The progress output shows 2187 passed
  and 1 skipped; 27 of the passes are new tests.
- `owner_gate.ps1` parsed with pwsh's parser: 0 errors. ASCII-only.

**Done**
- Leg inputs are derived from the gold manifest (read-only). Strategy:
  spec_hash → `examples/strategies/<spec>.json` → DSL bundle →
  `InpDslBundleFile`. Also sizing mode, risk %, allow-short and deposit,
  each recorded with its source. An underivable field fails the leg
  before launch, naming it. A pre-launch assertion requires a non-empty
  selector naming the manifest's `strategy_id`.
- The bundle is staged into `MQL5\Files` and every tester agent sandbox,
  sha-checked. The rendered gold2 .ini carries
  `InpDslBundleFile=Mql5Bot\gold_bundles\gold2_multifactor_v1_EURUSD.G2.bundle.json`
  (tested).
- The window is captured and attached for every leg. Log trade lists are
  copied into the package at `log_trades/<gold>_<model>.json`
  automatically before stage 8.
- With an expected strategy, the grader requires the EA's `generic DSL
  execution enabled: <id>` line to pass from log.

**NOT done, and why**
- **Gold1 legs now fail before launch on `engine_config.allow_short`.**
  The gold1 manifest does not pin it, and no EA default may substitute.
  Adding it would edit a frozen manifest, which is the owner's call.
- **The bundle's `spec_hash` differs from the manifest's.** The EA's frozen
  market guard requires the bundle symbol to equal the chart symbol
  (`EURUSD.G2`), and the market is part of the hash. The retarget is proven
  to change only `market.symbol` and is recorded. The owner should accept
  or reject this explicitly.
- **Agent-sandbox staging is unmeasured.** Nobody has confirmed that MT5
  keeps a file placed in `Tester\...\Agent-*\MQL5\Files` for the next test.
  The EA does not declare `#property tester_file`, and `mql5/` is frozen.
  The next owner run's window will show "generic DSL execution enabled"
  or "DSL bundle refused".
- **The rest of the stage-8 package is not built** (reconciliation events
  and bindings, compile/symbolspec/safety evidence, archive manifest).
  Stage 8 still reports what is missing.
- **The package default moved** from `artifacts\owner_mt5_gate\evidence`
  (tracked and frozen, and writing there dirties the tree) to the
  gitignored `evidence\owner_mt5_package`.
- Nothing ran on MT5. Record unchanged: stages 0–4 PASS, stage 5 FAIL,
  stages 6–10 never run, nothing certified.

## 2026-09-30 — branch `master` (merge of PRs #2–#5)

The owner cannot merge in the GitHub UI, so the open PRs were merged
locally with `--no-ff` and pushed. History was not rewritten and nothing
was force-pushed. The merge ran in a separate worktree, so the uncommitted
work on `feat/gate-scoped-gold2-run` was left untouched.

**Commits**
- `9e8bbba` — Merge PR #2: CI loads on Python 3.10 (`origin/fix/ci-py310`).
- `93ae7dc` — Merge PR #5 (includes #3, #4): stage-5 log grading, real
  lines, legs run the gold strategy (`origin/feat/stage5-legs-run-gold-strategy`
  at `322cb46`). No conflicts.
- the commit that adds this entry.

**Checks (exit codes read)** — tree of `93ae7dc`, macOS, `.venv` Python:
- `ruff check python/ tests/ tools/ factory/` → exit 0.
- `pytest -q` (full suite) → exit 0.

**PR state after push**
- #2: MERGED. #3: MERGED (GitHub detected it; commented "merged via #5").
- #4: CLOSED with the comment "merged via #5".
- #5: still OPEN. Its base is `feat/stage5-log-real-lines`, and GitHub
  refuses `gh pr edit --base master` ("Cannot change the base branch
  because the pull request is part of a stack"). Its head `322cb46` is
  in master.

**NOT done, and why**
- #5 is not marked merged on GitHub, because the stack lock blocks the
  retarget. It must be retargeted or closed by hand.
- No code changed and nothing ran on MT5. Record unchanged: stage 5 FAIL,
  stages 6–10 never run, nothing certified.

## 2026-09-30 — branch `fix/stage5-strictmode-and-gold-scope` (from `origin/master` 0c5da2f)

Worked in a separate worktree. The uncommitted scoped-run draft on
`feat/gate-scoped-gold2-run` in the main checkout was left untouched. Its
code and docs diff was copied in as the starting point for Task B, then
changed to match the spec: stages 9–10 REFUSED, `certifiable` added.

**Commits**
- `44a712b` — STAGE 5 R10 + scoped runs.
- the commit that adds this entry.

**Checks (exit codes read)** — macOS, `.venv` Python, ruff 0.16.1:
- `ruff check python tests tools factory` → exit 0.
- `pytest tests/` (full suite) → exit 0. The progress output shows 2221
  passed and 1 skipped.

**Done (checkable in tests)**
- R10: `Get-DataProp` in `tools/owner_gate.ps1`. No bare `.data.<prop>`,
  `$recon.<prop>` or `$fd.<prop>` read remains
  (`tests/test_gate_strictmode.py`). The stage-5 leg-input block is
  EXECUTED under StrictMode 2.0 with the real decider on the real
  manifests. The three gold1 legs are recorded `[input_underivable]
  engine_config.allow_short ... -- leg NOT launched`, all three gold2 legs
  derive `gold2_multifactor`, and `$legOk` stays false, so stage 5 is still
  FAIL. The old bare read reproduces the gate_run21 crash.
- Scoped runs: `-Golds gold2` ends `GATE_RESULT=partial_<stage>`, and
  `gate_summary.json` has `"scope": ["gold2"]` and `"certifiable": false`.
  Stages 9 and 10 are recorded REFUSED and not run; the refusal block is
  executed in a test. The default run is unchanged (tests in
  `tests/test_gate_scope.py`).

**NOT done, and why**
- No doc contained `pip install -e python`. `git grep` found none, so
  nothing was changed.
- Nothing ran on MT5 or Windows. Built, unit-tested, never run live.
  Record unchanged: stage 5 FAIL, stages 6–10 never run, nothing
  certified.

## 2026-09-30 — branch `fix/golds-param-shadowing` (from `origin/master` 6416d6b)

Worked in a separate worktree. The uncommitted draft in the main checkout
was left untouched.

**Evidence acted on:** gate_run22 (HEAD 6416d6b, `-Golds gold2`), stage 4
FAIL: `The property 'gold' cannot be found on this object (script line 703)`.
The stage-4 local `$golds` is the `[string[]]$Golds` parameter, because
PowerShell names are case-insensitive.

**Commits**
- `5a58a39` — rename the stage-4 local to `$goldImports`; add
  `tests/test_gate_param_shadowing.py` (a static shadowing check and a pwsh
  run of the real param block, scope block and gold list); update the
  `test_gate_scope.py` text check; add a DECISIONS.md entry.
- the commit that adds this entry.

**Checks (exit codes read)** — macOS, `.venv` Python, ruff 0.16.1:
- `ruff check python tests tools factory` → exit 0.
- full `pytest` → exit 0. The only skip is `tests/test_pipeline.py:444`
  (optuna).
- PowerShell tests: 27 ran, 0 skipped. Hiding pwsh (`env -i`, empty HOME)
  makes those 4 files skip exactly 27 tests.

**PRs**
- #9 (this branch) is open and not merged.
- A comment on #8 (the log-only PR for the PR #7 merge) says to merge it
  together with #9.

**NOT done, and why**
- Nothing was merged, as instructed.
- Nothing ran on MT5 or Windows. The fix is built, unit-tested, never run
  live, and gate_run22's stage 4 has not been re-run. Record unchanged: stage
  5 FAIL, stages 6–10 never run, nothing certified.
