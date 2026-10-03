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

## 2026-09-30 — branch `master` (merge of PR #7), log on `docs/log-pr7`

Worked in a separate detached worktree from `origin/master` `0c5da2f`. The
uncommitted draft in the main checkout was left untouched.

**Commits**
- `6416d6b` — `git merge --no-ff origin/fix/stage5-strictmode-and-gold-scope`
  (PR head `b3f0e75`), pushed to `origin/master` without force or amend.
  The merge body notes that the owner (Sal) approved it together with the
  reviewer in chat. No approving review is recorded on GitHub. An earlier
  local merge, `acf30cf`, had no approval note and was never pushed. It was
  replaced by a fresh merge with the same tree, so the checks below cover
  `6416d6b`'s tree.
- The commit that adds this entry is on branch `docs/log-pr7`. Its PR is left
  open, as the owner asked, to be merged with the next reviewed PR. It is not
  committed to master directly.

**Checks (exit codes read)** — macOS, `.venv` Python:
- `ruff check python tests tools factory` → exit 0.
- full `pytest` → exit 0.

**Done**
- PR #7 shows `MERGED` on GitHub with merge commit `6416d6b`.

**NOT done, and why**
- Nothing ran on MT5 or Windows. The R10 fix and scoped runs are built,
  unit-tested, never run live. Record unchanged: stage 5 FAIL, stages 6–10
  never run, nothing certified.

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

## 2026-10-01 — branch `fix/stage5-agent-sandbox` (from `origin/master` 6f9b845)

I worked in a separate worktree (`../mql5bot-stage5-sandbox`). The main
checkout had uncommitted changes on `feat/gate-scoped-gold2-run`. They were
not mine and I left them untouched.

**Evidence acted on:** gate_run23 (HEAD 6f9b845, `-Golds gold2`, Windows).
- Staging reported `"agent_sandboxes": [], "ok": true`.
- The EA printed `[mql5bot] DSL bundle refused:  ` and the tester printed
  `OnInit returns non-zero code 1`.
- The real_ticks leg printed `no history data, stop testing`.

**Commits**
- `210dc69` — the changes:
  - A: `stage_bundle` also searches the sibling
    `MetaQuotes\Tester\<terminal_id>\Agent-*` and sha256-checks each copy.
    With zero agents it refuses: `missing="tester agent sandbox"`, naming
    every path searched.
  - B: a refusal or OnInit-nonzero line in the leg's window gives a FAIL whose
    reason names the cause. `no history data, stop testing` gives
    `FAIL_NO_TICK_HISTORY`.
  - The verbatim gate_run23 lines are in
    `tests/data/owner_gate/tester_log_gate_run23.txt`.
  - C: a DECISIONS.md entry with the options. The owner has not decided.
  - The owner docs now require `-DataFolder` / `MQL5BOT_DATA_FOLDER`.
- The commit that adds this entry.

**Checks (exit codes read)** — macOS, `.venv` Python, ruff 0.16.1:
- `ruff check python tests tools factory` → exit 0.
- full `pytest tests/` → exit 0. The only skip is `tests/test_pipeline.py:444`
  (optuna).
- PowerShell tests: 27 ran. With pwsh hidden (`env -i`, HOME=/nonexistent),
  the 4 pwsh files skip exactly 27.

**PR:** #10 is open and not merged.

**NOT done, and why**
- Nothing was merged, as instructed.
- The real_ticks leg is not fixed. The fix is an owner decision
  (DECISIONS.md), so I documented it and did not implement it.
- Nothing ran on MT5 or Windows. The staging fix is built, unit-tested, and
  never run live. Whether the EA now loads the bundle inside the tester is
  not measured. The `.ps1` still labels a staging refusal
  `[input_underivable]`; the reason text names the real cause. Record
  unchanged: stage 5 FAIL, stages 6–10 never run, nothing certified.

## 2026-10-01 — fix/ea-bundle-common-files (gate_run24: EA reads bundle via FILE_COMMON)

**Branch:** `fix/ea-bundle-common-files`, from origin/master `150303a`. It was
built in a separate worktree because the main checkout had uncommitted work
from another branch, which I left untouched.

**Evidence acted on:** gate_run24 (HEAD 150303a, `-Golds gold2`). A bundle
staged into the agent's `MQL5\Files` before launch was not readable at
OnInit: `DSL bundle refused:  ` and `OnInit returns non-zero code 1`.

**Owner authorization:** a scoped mql5/ exception (Sal, in chat), covering
only `ReadDslBundleText` and the OnInit refusal Print that follows it in
Mql5Bot.mq5. It is recorded in docs/DECISIONS.md.

**Commits**
- `ef689f1`:
  - The EA tries FileOpen local, then FILE_COMMON, and prints both
    GetLastError codes or the load source.
  - `stage_bundle` requires a sha256-verified copy in
    `<data_folder>\..\Common\Files`.
  - The graders read the new refusal and `loaded from` lines.
  - Tests are in `tests/test_ea_bundle_common_files.py`. Three existing
    tests were updated for the new semantics.
- The commit that adds this entry.

**Checks (exit codes read)** — macOS, `.venv` Python, ruff 0.16.1:
- `ruff check python/ tests/ tools/ factory/` → exit 0.
- full `pytest tests/` → exit 0. The only skip is `tests/test_pipeline.py:444`
  (optuna).
- PowerShell tests: 27 ran. With pwsh hidden, the 4 pwsh files skip exactly 27.

**PR:** #11 is open and not merged.

**NOT done, and why**
- MQL5 was not compiled: there is no MetaEditor on the Mac. Stage 1 on
  Windows is the compile proof.
- Nothing ran on MT5 or Windows. The change is built, unit-tested, and never
  run live. Whether the EA loads the common copy inside the tester is not
  measured.
- The real_ticks leg (no tick history) is untouched; it is still an owner
  decision.
- Nothing was merged, as instructed.
- Record unchanged: stage 5 FAIL, stages 6–10 never run, nothing certified.

## 2026-10-03 — feat/real-ticks-not-applicable (owner decision: option 2) + gate_run25 analysis

**Branch:** `feat/real-ticks-not-applicable`, from origin/master `144bff7`.
It was built in a separate worktree because the main checkout had
uncommitted work on `feat/gate-scoped-gold2-run`, which I left untouched.

**Owner decision:** Sal, in chat, chose option (2) of DECISIONS.md
"real_ticks leg on bar-only fixtures". The decision is recorded in
docs/DECISIONS.md with the gate_run25 evidence as the owner quoted it.

**Commits**
- `ff5dd25`:
  - Bar-only is derived from the fixture header plus the manifest.
  - The real_ticks leg of a bar-only gold is recorded
    `NOT_APPLICABLE_BAR_ONLY_FIXTURE`, not launched, and tallied separately.
    It is never counted as a pass.
  - Stage 5 can pass only when every applicable leg passes. If every leg is
    NOT_APPLICABLE, stage 5 FAILs.
  - `gate_summary.json` gets a `real_tick_coverage` entry per gold.
  - Stage-10 records and the certification report state the coverage.
  - Tests are in `tests/test_stage5_real_ticks_not_applicable.py` (16).
    The `tests/test_gate_scope.py` harness was updated for the new variable.
- `6b6e094`: `docs/analysis/gate_run25_divergences.md`. This is read-only
  analysis of the start-date shift, the lot sizes and the "adopted unknown
  position" log line. No code changed.
- The commit that adds this entry.

**Checks (exit codes read)** — macOS, `.venv` Python, ruff 0.16.1:
- `ruff check python/ tests/ tools/ factory/` → exit 0.
- Full `pytest tests/` → exit 0. The only skip is `tests/test_pipeline.py:444`
  (optuna).
- PowerShell 7.6.6: 31 pwsh-executed tests ran. With pwsh hidden, exactly 31
  skip: the previous 27 plus 4 new.

**NOT done, and why**
- `artifacts/owner_mt5_gate/report_template.md` still offers only
  FULL/PARTIAL/UNKNOWN coverage. It is a frozen path, so I did not edit it;
  the owner must decide.
- The stage-8 verifier is unchanged. A bar-only gold that now passes stage 5
  will still not reach MT5_VALIDATED, because real-tick coverage NONE is
  never promoted. Whether stage 8 should learn NOT_APPLICABLE is an owner
  decision.
- None of the divergence fixes are implemented. The adopted-unknown fix needs
  an owner-authorised `mql5/` change. The alignment fix in stage 8 is a
  separate task.
- Nothing ran on MT5 or Windows. The change is built, unit-tested, and never
  run live.
- Nothing was merged, as instructed.
- The certification record is unchanged: stage 5 is FAIL in every owner run
  so far, stages 6–10 have never run, and nothing is certified.

## 2026-10-03 (2) — feat/stage8-package-from-gate (gate_run26: stage 8 package)

**Branch:** `feat/stage8-package-from-gate`, from origin/master `918f7bf`.
It was built in a separate worktree. The main checkout's uncommitted draft
was not touched.

**Evidence acted on:** gate_run26 (HEAD 918f7bf, `-Golds gold2`), as quoted
by the owner.
- Stage 5 was PASS_FROM_LOG: 74 deals per leg, final balances 8069.20 /
  8017.51. These equal gate_run25. real_ticks was NOT_APPLICABLE.
- Stage 8 FAILED `NOT_VERIFIED_RECONCILIATION_MISSING`. The package held only
  the log trade lists.

**Commits**
- `803c159`:
  - `stage8_package.build_package` builds the package from the gate's own
    outputs and is called by owner_gate.ps1 before verify.
  - Verifier: new `NOT_APPLICABLE` state and new `REAL_TICK_COVERAGE_NONE`
    coverage, plus observed first divergences.
  - The stage-8 reason quotes the divergence.
  - Tests are in `tests/test_stage8_package_from_gate.py` (21). Docs:
    OWNER_GATE.md and DECISIONS.md.
- The commit that adds this entry.

**Checks (exit codes read)** — macOS, `.venv` Python, ruff 0.16.1:
- `ruff check python/ tests/ tools/ factory/` → exit 0.
- Full `pytest tests/` → exit 0. The only skip is `tests/test_pipeline.py:444`
  (optuna).
- PowerShell 7.6.6: 31 pwsh-executed tests ran. With pwsh hidden, exactly 31
  skip. The new stage-8 ps1 tests are source checks only and are not
  executed under pwsh.

**What the built package shows (synthetic tmp tree, not MT5 evidence).** The
verdict is `NOT_VERIFIED_ARTIFACT_MISMATCH`. It is never positive, because:
- `SOURCE_COMMIT` is HEAD, not the frozen anchor `a85cba3`.
- The SymbolSpec export does not emit `broker`, `timestamp` or
  `terminal_build`.
- The environment record is missing `broker`, `terminal_build` and
  `account_mode`.
- The safety files are MISSING.

The NOT_APPLICABLE slots are NOT_APPLICABLE, and coverage is NONE (VALID).
The per-trade first divergence is `timestamp` at trade 0
(TIMESTAMP_MISMATCH), shown with `binding_verified: false`.

**NOT done, and why**
- No safety evidence was built. 8a–8d need a real MT5 run.
- No re-anchor: it is the owner's decision, and frozen inputs may not be
  touched.
- The SymbolSpec exporter is under `mql5/`, which may not be touched.
- The verifier's trade-count rule still compares Python trades with MT5 deals
  (56 vs 74). It is flagged, not changed.
- Report-sourced legs are not packaged by the builder. It refuses them by
  name.
- Nothing ran on MT5 or Windows. The change is built, unit-tested, and never
  run live.
- Nothing was merged.
- The certification record is unchanged: stage 8 FAILs in every owner run so
  far, stages 9–10 are refused for scoped runs, and nothing is certified.

## 2026-10-03 (3) — fix/stage8-trade-pairing (gate_run27: pair by time, never by position)

**Branch**: `fix/stage8-trade-pairing` from `origin/master` 8966969.

**Evidence driving the change (gate_run27, HEAD 8966969, -Golds gold2).**
Stage 8 ran the trade comparison for the first time and paired the 75
reconciliation events BY LIST POSITION: event 0 compared python
2024-01-01T08:01 (1.4 lots) with MT5 2024-01-02T08:01 (0.01 lots) ->
TIMESTAMP_MISMATCH, while MT5 never traded 2024-01-01 at all ("start time
changed to 2024.01.02 00:00 to provide data at beginning", measured in
gate_run23/25/26/27). Positional pairing compared different days; every
later field was noise.

**TASK A — done (built, unit-tested, never run live).**
`stage8_package.py` now pairs python approved entries with MT5 entry deals
BY TIME: same fill minute (signal_time + 1 bar, the manifest's next-M1-
minute contract), each deal used once, both sides in time order.
- Python trades filling before the measured MT5 window-start line (parsed
  from the leg's own window capture, scoped to the leg symbol) are
  `OUT_OF_TESTED_WINDOW` events: the start line is QUOTED, the trade is
  recorded with no compared fields — never dropped, never matched, never a
  divergence. The window is written into `limitations`, not
  `first_divergence`.
- Unpaired trades inside the window are `MISSING_IN_MT5` / `EXTRA_IN_MT5`
  events whose `state` field diverges (closed taxonomy: STATE_MISMATCH).
- Paired events compare timestamp, volume, and — parsed from MT5's own
  journal line in the deal's `lines` (`deal #N buy|sell VOL SYM at PRICE`)
  — entry side and entry price (python price = fixture open at the fill
  minute; omitted, never invented, when unstated). Fields stay unmeasured
  only when no MT5 journal line states them.
- Entry counts compare INSIDE the window; the out-of-window count sits
  beside, uncompared.
VERIFIER LINES CHANGED: none. `owner_gate.py`, `verify_owner_mt5_gate.py`
and `owner_gate.ps1` are untouched; no acceptance rule loosened or changed.

**TASK B — case "no existing file carries the flat fields".**
`Mql5BotExportSymbolSpec.mq5` exports the per-symbol values NESTED under
`symbol` (14 of the 19 `SYMBOLSPEC_REQUIRED` keys) and does not export
`broker`, `terminal_build`, or `timestamp` under any name (`exported_at`
is a different key). No other file produces the verifier's flat shape, so
the gate is not copying a wrong file — the exact missing fields and their
MQL5 sources are written into `docs/DECISIONS.md` S8-SPEC-1 for the
upcoming scoped mql5/ PR. `mql5/` untouched.

**Tests.** `tests/test_stage8_package_from_gate.py` rewritten for time
pairing (26 tests), with the window-start and MT5 journal deal lines in
`tests/data/owner_gate/tester_window_gate_run27_lines.txt` (provenance in
its header: measured FORMATS from the run23/16/17 captures; the run27
package itself is not on this machine, so values carried are the
reported/synthetic ones the header names — never MT5 evidence).

**Exit codes (read, not polled).** ruff python/ tests/ tools/ factory/ ->
0. Full pytest -> 0 (with pwsh 7.6.6 on PATH, so the ps1-executing test
modules ran; test_owner_gate_ps1 / test_gate_scope / test_gate_strictmode /
test_gate_param_shadowing / test_stage5_real_ticks_not_applicable also
re-run standalone -> 0).

**NOT done, and why**
- Nothing ran on MT5 or Windows; the new pairing has never seen a real
  gate run. gate_run28 must confirm it on the owner terminal.
- The symbolspec exporter change itself: `mql5/` may not be touched; it is
  documented in DECISIONS.md S8-SPEC-1 only.
- The verifier's trade-count rule (python trades vs MT5 deals) is still
  unchanged; changing a verifier rule was out of scope and none was.
- The MT5 tested-window END is not measured by any captured line; python
  trades after the last MT5 day remain MISSING_IN_MT5 divergences rather
  than out-of-window.
- Nothing merged. Certification record unchanged: stage 5 FAIL stands in
  the record, stage 8 has never passed, stages 9-10 never ran.

## 2026-10-03 (5) — analysis/gate_run28-divergences (window END fix + run28 analysis)

**Branch**: `analysis/gate_run28-divergences` from `origin/master` 999126a.

**TASK A (python only, built, unit-tested, never run live).** The stage-8
pairer now applies the tester window END as well as the measured start:
python entries at/after the ToDate the gate derives from the fixture
(`mt5tester.fixture_date_range`; MT5 ToDate is exclusive) are
OUT_OF_TESTED_WINDOW with the end's source named — never MISSING_IN_MT5.
gate_run28's 5 python 2024-01-04 entries were wrongly divergences; the
python reference itself holds zero day-4 positions (meta weight 0.0).
Verifier lines changed: none. Tests updated (counts 19 before + 5 after
per model on the real gold2 data) plus an exclusive-boundary unit test.

**TASK B — docs/analysis/gate_run28_divergences.md** (read-only; measured
vs inferred separated; run28 lines quoted as reported — the package is on
the owner terminal):
1. One-bar-late flips: EA closes and returns on flip (Mql5Bot.mq5:999-1004,
   per-bar OnTick gate :1091-1100); python closes and re-enters in the same
   reconcile(bar) (engine.py:854-904; python_trace exits == next entry
   minute). The manifest flip_rule "close opposite (signal_exit); enter
   next bar" read literally specifies the EA behaviour. RECOMMENDED: change
   the python engine (+ owner-authorized gold regeneration); no mql5/
   change needed.
2. Missed day-3 longs: desired series re-run locally is +1 for 14 bars
   (sustained, not a pulse); InpDslBars=500 passes the 10x-period guard and
   seeding tails are <= ~1e-16 (cannot flip comparisons); session and
   one-position rules identical. Two candidates left INFERRED: (a) the
   longs exist as +1-minute EXTRA events (then finding 1 is the single
   root cause) or (b) EA-side desired/sizing divergence; run29 checks named
   (EXTRA event times; EA desired debug; deal list incl. exits 08:30-10:08).
3. Volume drift: one identical 1.0% sizing rule reproduces python approvals
   to <=0.07%; implied MT5 basis from paired volumes 8848/8686/8545 vs
   python 9174/9161/9149 (gap ~326→476→604, 16-30 volume steps — rounding
   cannot explain). Python's basis follows the trace equity under the
   gold's day-stepped meta weights (1.0/0.5/0.1/0.0; all 56 trace lots ==
   approved x day-weight, verified 56/56), while the EA runs weight 1.0
   (no allocation.json in the tester → InpBaseGateWeight=1.0 fallback).
   RECOMMENDED (python/gate side, later PR): compare like-for-like using
   the expected meta.<w>.final_lots table or stage a day-stepped
   allocation file.
4. "adopted unknown position" on every entry: unchanged since run25; owner
   decision bundles the fix with the exporter fields in one later scoped
   mql5/ PR (PR #14, still open/CONFLICTING, needs rebase).

**Exit codes (read, not polled).** ruff -> 0; full pytest -> 0 (pwsh 7.6.6
on PATH, ps1-executing modules ran).

**NOT done, and why**
- No change to the flip timing on either side (analysis task; owner must
  pick the side and authorize gold regeneration).
- No mql5/ change (frozen; the adopted-unknown + exporter fixes remain
  queued for the scoped PR).
- Finding 2 not closed: the discriminating evidence exists only in the
  run28 package / a run29 capture on the owner terminal.
- Nothing ran on MT5. Nothing merged. Certification record unchanged.

## 2026-10-03 (6) — merge PR #13; docs/owner-decisions-reanchor-deferred

*(Entry originally numbered (3); renumbered mechanically when this
branch was rebased after PRs #15 and #16 merged. Content unchanged.)*

**Merge:** PR #13 was merged into master as `8966969` (`--no-ff`, approved
by Sal and the reviewer in chat; no GitHub review recorded). The merge was
done in a separate clean worktree, and the main checkout's draft was not
touched. Before the push, on the merge commit:
- `ruff check python tests tools factory` → exit 0;
- full pytest → exit 0, with the only skip being optuna.

The push to master was a fast-forward, `918f7bf..8966969`, with no force and
no amend. PR #13 shows MERGED.

**Branch:** `docs/owner-decisions-reanchor-deferred`, from `8966969`. It
records two owner decisions in docs/DECISIONS.md:
1. The re-anchor is deferred until the next owner run shows the trade
   comparison.
2. The SymbolSpec exporter fields and the recording of the EA's own new
   entries go into one later scoped `mql5/` PR.

**NOT done, and why**
- No re-anchor, and no `mql5/` change: both were deferred by the owner.
- The docs PR is not merged, as instructed.
- The certification record is unchanged: stage 8 FAILs in every owner run so
  far, and nothing is certified.

## 2026-10-03 (7) — merge PR #16; rebase PR #14; fix/engine-flip-next-bar

**Merges/branch ops (clean worktrees; main checkout untouched):**
- PR #16 merged into master as a02a07a (--no-ff, approved by Sal + reviewer
  in chat; no GitHub review recorded). Pre-push gates on the merge commit:
  ruff exit 0, full pytest exit 0. Push 999126a..a02a07a, no force/amend.
  PR #16 shows MERGED.
- PR #14 rebased onto a02a07a (AUTONOMOUS_LOG conflict resolved keeping
  both sides; its entry renumbered (3)->(6) mechanically, content
  unchanged) and re-pushed with --force-with-lease as instructed. PR #14
  is OPEN and MERGEABLE, NOT merged.

**Branch**: `fix/engine-flip-next-bar` from a02a07a.

**Owner decision recorded** (docs/DECISIONS.md S8-FLIP-1): gate_run28
findings 1-3 are PYTHON-side defects; the EA follows the manifest contract
and does not change.

**TASK A (built, unit-tested, never run live).** engine.py: on a signal
flip the engine closes the opposite position at the current bar (signal
_exit) and defers the new entry to the NEXT bar's open — the named rule
FLIP_RULE_ENTER_NEXT_BAR (the manifest flip_rule verbatim), recorded per
application as a "flip_deferred" event. fast_engine.py mirrors it (its
equivalence to the truth engine is pinned by tests). Session flatten and
SL/TP exits unchanged. Tests: flip closes bar N and enters N+1 with the
event recorded; a one-bar desired pulse never enters (EA parity); go-flat
and stop exits are not deferred.

**TASK B.** stage8_package compares MT5 volume against expected_execution
meta["1.0"].final_lots (the tester weight in force: no allocation file,
EA fallback InpBaseGateWeight=1.0); the column is FIXED and recorded per
event (python_volume_column), approved_lots kept beside it labelled
(python_approved_lots), and a DROP/absent column leaves volume UNCOMPARED
with the reason stated — never substituted, never matched-to-closest.
Verifier lines changed: none.

**TASK C.** artifacts/gold_2 NOT regenerated (frozen). tools/
preview_gold2_regen.py runs the real gold-2 builder into gitignored
evidence/preview/ (refusing unless the preview fixture is byte-equal to
the frozen one — it is, sha 59cd339f6ebd...) and diffs the preview trace
vs the frozen python_trace. MEASURED preview summary: 56 -> 56 trades;
18 entries unchanged; 38 moved +1 bar (flip deferral); 0 vanished; 0
appeared; 45 matched trades changed lots; 8 changed exit_reason.

**xfail list (exactly the frozen-gold parity tests that failed, reason
"frozen gold2 predates flip-next-bar fix; regeneration pending owner
decision"):**
- tests/test_gold2_standard.py::test_every_entry_reconciles_sizing_and_meta
No other test failed; nothing else was weakened.

**Exit codes (read, not polled).** ruff -> 0; full pytest -> 0 (pwsh 7.6.6
on PATH; 0 FAILED lines in the log).

**NOT done, and why**
- artifacts/gold_2 not regenerated: frozen; the preview is the owner's
  decision input.
- mql5/ untouched (owner: the EA does not change).
- PR #14 not merged (as instructed).
- Nothing ran on MT5; the engine change has never seen a live gate run.
- Nothing merged from this branch. Certification record unchanged.
