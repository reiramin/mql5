# Automated owner gate (`tools/owner_gate.ps1`)

One command the Windows owner runs. Every DECISION lives in committed code
(`python/mql5bot/gate_selfcheck.py`, invoked through
`tools/owner_gate_decide.py`, plus the existing verifiers), never in a
prompt: the script orchestrates, records, and stops; it does not judge by
hand.

This document describes what the script DOES. Outcomes are produced only
when the owner runs the command on a real terminal, and each is recorded
truthfully (PASS / PASS_FROM_LOG / FAIL / SKIP / BLOCKED / REFUSED) in the
evidence directory.

**Latest result.** gate_run59 (branch `gate-reports`, `db13f55`; master
`ab312d5`, `[runner: full]`) ended `GATE_RESULT=certified_with_log_graded_legs`:
stages 0–10 PASS (stage 5 PASS_FROM_LOG), verifier verdict
`MT5_VALIDATED_BAR_MODELS`, 8/8 safety VALID, certificate issued. MT5
execution-parity and safety certificate, bar models, no real-tick claim, no
profitability claim.

**The stages at a glance** (there is no stage 6; `GATE_RESULT=` names the
first failing stage):

| # | Name | What it proves |
|---|---|---|
| 0 | `self_protection` | clean tree, frozen hashes, anchor relation, tools located, scope valid; with `-DemoSafety` the demo preflight (market open, accounts file) |
| 1 | `strict_compile` | MetaEditor strict compile, 0 errors / 0 warnings, every shipped target |
| 2 | `dsl_parity` | 14/14 DSL fixtures EXACT, tampered bundle refused |
| 3 | `broker_parity` | the live SymbolSpec export matches the frozen spec |
| 4 | `fixture_import` | each gold fixture imported as a custom symbol, round-trip dataset hash = manifest |
| 5 | `tester_legs` | gold legs in `m1_ohlc` and `every_tick` (real_ticks NOT_APPLICABLE on bar-only fixtures) |
| 7 | `demo_safety` | only with `-DemoSafety`: restart, netting, hedging on demo accounts; terminal restored |
| 8 | `reconciliation` | stage-8 package built, the five tester safety legs (8a–8d) run, verifier verdict |
| 9 | `archive_manifest` | `owner_evidence_bind.py manifest` binds the evidence by sha256 |
| 10 | `certify` | certificate of the stage-8 verifier verdict (STAGE10-CERT-1) |

## The single command

```
powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 -DataFolder <MT5 data folder> [-Portable]
```

Optional overrides: `-TerminalPath`, `-MetaEditorPath`, `-SymbolSpecExport`,
`-TimeoutSec`. Environment fallbacks: `MQL5BOT_TERMINAL`,
`MQL5BOT_METAEDITOR`, `MQL5BOT_DATA_FOLDER`, `MQL5BOT_PYTHON`,
`MQL5BOT_EVIDENCE_DIR`.

**The data folder is required.** Pass `-DataFolder` or set
`MQL5BOT_DATA_FOLDER` before running; without either the gate stops at
stage 0 (`SELF_PROTECT_DATA_FOLDER`) — gate_run23's first attempt did
exactly that. It is the terminal's data folder (MT5: File → Open Data
Folder), e.g. `%APPDATA%\MetaQuotes\Terminal\<terminal_id>`:

```
$env:MQL5BOT_DATA_FOLDER = "$env:APPDATA\MetaQuotes\Terminal\<terminal_id>"
```

Stage 5 stages each gold's DSL bundle into every tester agent sandbox it
finds, under `<data folder>\Tester` and under the sibling
`%APPDATA%\MetaQuotes\Tester\<terminal_id>\Agent-*`. If it finds none,
the leg is refused before launch, naming every path searched.

Stage 8 reads its owner evidence package from `MQL5BOT_EVIDENCE_DIR`, or
by default from the gitignored `evidence\owner_mt5_package\`. Stage 5
copies each PASS_FROM_LOG leg's log trade list there automatically
(`log_trades/<gold>_<model>.json`).

All output lands under `evidence\owner_gate\<UTC>\`, append-only: one
`stage_<n>.json` per stage, a `gate_summary.json`, and a final line
`GATE_RESULT=<stage-name>`.

## Stages (stop at the first FAIL)

- **0. Self-protection** (`self_protection`) — aborts with a NAMED reason unless: `HEAD` relates
  to the frozen `source.commit` acceptably (it equals the anchor, or is a
  clean **descendant** of it — a legitimate newer commit, recorded as a NOTE,
  never a hard abort; an **older**, **diverged**, or **unknown** anchor
  fails); the working tree is clean; `core.autocrlf` is not `true`/`input`;
  `frozen_inputs.json` is byte-identical to its committed blob (no
  hand-written record); every frozen hash matches the committed bytes; the
  dsl-parity manifest binds and all 42 files verify; and `terminal64.exe` /
  `metaeditor64.exe` are located. What is certified is that the frozen
  ARTIFACTS are byte-unchanged and the tree is clean, not that `HEAD` is one
  historical SHA. Optionally, pass `-CloneInto <dir>` and the gate refuses by
  name up front if that fresh-clone directory already exists, rather than
  letting a later `git clone` fail and leaving you to move directories by
  hand.
- **1. Strict compile** — runs `compile.ps1 -Strict`, decodes the LOG
  BOM-aware (owner logs are UTF-16 or UTF-8-BOM), and requires `0 errors, 0
  warnings` with every compiled target the repo ships reported clean. The
  target set is derived from the committed sources, so it tracks the tree
  (four sources at the calibration commit; five once the fixture importer is
  present).
- **2. DSL parity** — runs `run_dsl_parity.ps1` and requires `14/14 fixtures
  EXACT` with the tampered bundle refused.
- **3. SymbolSpec + broker parity** — runs `broker_symbol_parity.py`; a
  `MISMATCH` on any row aborts, while a PENDING crypto/BTC row is excluded
  from certification scope (an open owner-side measurement, never a silent
  pass, never an abort).
- **4. Fixture import** — stages each committed gold fixture + its manifest +
  the stage-3 SymbolSpec export under `MQL5\Files`, runs
  `Mql5BotImportFixture.mq5` to build a custom symbol via
  `CustomRatesUpdate`, and requires the round-tripped dataset hash to
  re-derive the manifest `dataset_hash`. The importer refuses and creates
  nothing on any missing property or hash mismatch.
- **5. Tester legs** (`tester_legs`) — the six legs (Gold #1/#2 × m1_ohlc /
  every_tick / real_ticks); the raw report and sidecar are archived and the ACTUAL model
  is read from the report and journal, not the requested one. A gold whose
  fixture is DERIVED bar-only (bar-schema header, no tick dataset in the
  manifest) has its real_ticks leg recorded `NOT_APPLICABLE_BAR_ONLY_FIXTURE`
  and not launched (owner decision 2026-10-03). It is tallied separately,
  never as a pass, and `gate_summary.json` carries `"real_tick_coverage":
  "NONE (bar-only fixture)"` for that gold.
- **7. Demo safety** (`demo_safety`, only with `-DemoSafety`;
  DEMO-IN-GATE-1) — re-checks the market window, then runs the demo harness
  (`tools/demo_safety_harness.py`) for restart, netting and hedging with THIS
  run's stage-1 EX5, and asks `owner_gate_decide.py demo-in-gate-outcome`
  whether every run left the terminal on the hedging account, connected
  without credentials (DEMO-LOGIN-PERSIST-1). Named FAILs:
  `[demo_host_suspended]` (HARNESS-SUSPEND-1, checked first),
  `[demo_terminal_not_restored]` with `[demo_restore_not_connected]` /
  `[demo_run_missing]`, and `demo harness NOT run: [market_closed] ...`. It
  does not grade the tests; stage 8 does. Details: docs/SAFETY_DEMO_PLAN.md.
- **8. Reconciliation** (`reconciliation`) — the full bindings object plus the safety sub-checks
  (kill-switch; restart; retry/adoption/SlGuard; netting and hedging) via
  `verify_owner_mt5_gate.py`. A first divergence is classified
  (`SIZING_MISMATCH` / `RISK_MISMATCH` / ...) and FAILS stage 8 with its
  class named (S8-PATH-1). It is no longer recorded as "EXPECTED for the
  4257f1e sizing fix": both golds were regenerated after that fix. The
  script never patches the gold artifacts.
- **9. Archive manifest** — `owner_evidence_bind.py` only; no hand-typed
  hash.
- **10. Certify** — a certificate OF the stage-8 verifier verdict
  (STAGE10-CERT-1, owner decision 2026-10-12; this replaced
  `certify_strategy.py`). `owner_gate_decide.py issue-certificate` writes
  `certificate/certificate.json` and `certificate.md` only when:
  - the verdict is an unscoped `MT5_VALIDATED` or `MT5_VALIDATED_BAR_MODELS`;
  - nothing is missing;
  - gold1 and gold2 are both MATCH/VALID;
  - all 8 safety results are VALID;
  - the stage-9 archive manifest binds that exact `reconciliation_verify.json`
    by sha256.

  Anything else is a named FAIL. The certificate states its scope (bar
  models: no real-tick claim) and makes no profitability claim.
  - With every gold leg graded from the tester log, a passing run ends
    `GATE_RESULT=certified_with_log_graded_legs`, kept distinct from
    `certified` by design. Only `certified` exits 0.

## The stage-8 evidence package: what the gate builds, what the owner still supplies

gate_run26 (HEAD 918f7bf, `-Golds gold2`) reached stage 8 with a package
holding only `log_trades/gold2_{m1_ohlc,every_tick}.json`. It FAILED
`NOT_VERIFIED_RECONCILIATION_MISSING`, and `first_divergence` was None because
the trade comparison never ran.

Before stage 8 verifies, the gate now runs `owner_gate_decide.py
build-stage8-package` (`python/mql5bot/stage8_package.py`). It fills the
package from that run's own outputs and never types a value by hand. It has
run in every gate that reached stage 8, gate_run59 included.

| Package path | Built from | Notes |
|---|---|---|
| `compile/compile.log` | stage-1 compile log copy | byte copy |
| `compile/compile_metadata.json` | the parsed stage-1 log and `git rev-parse HEAD` | `SOURCE_COMMIT` is the HEAD the gate ran, not the frozen anchor. `TERMINAL_BUILD` is written only if a leg window states it. |
| `compile/Mql5Bot.ex5` | `<data folder>\MQL5\Experts\Mql5Bot\Mql5Bot.ex5` | copied only if its sha256 equals the `ex5=` hash in the stage-1 log |
| `symbolspec/symbolspec.json` | the stage-3 SymbolSpec export | byte copy |
| `gate/stage_5.json` | this run's stage-5 record | the verifier reads NOT_APPLICABLE legs from it |
| `real_tick_coverage.json` | stage 5 | `REAL_TICK_COVERAGE_NONE` only when every scoped gold's real_ticks leg is NOT_APPLICABLE. The leg is "not launched" and the fixture is named. Never FULL. |
| `environment.json` | measured lines only | server from the windows' `(<server>): ... generating` line; symbol from the export; os and timezone from the gate host. Anything unmeasured is listed under `unmeasured` and left out. |
| `reconciliation/<gold>.json` | python: `expected_execution.json` approved entries (fill = signal + 1 bar); mt5: the log trade lists' entry deals | Events pair BY TIME (same fill minute), never by list position. Python trades before the measured MT5 window start (`start time changed to ... to provide data at beginning`, quoted) are `OUT_OF_TESTED_WINDOW`: recorded, uncompared, a named limitation — never the first divergence. Unpaired trades inside the window are `MISSING_IN_MT5` / `EXTRA_IN_MT5` divergences. Per pair: timestamp, volume, plus entry side/price when MT5's own `deal #N buy\|sell VOL SYM at PRICE` journal line states them (python entry price = fixture open at the fill minute). Bindings are hashed from bytes. A NOT_APPLICABLE leg is bound as `{not_applicable: true, outcome: NOT_APPLICABLE_BAR_ONLY_FIXTURE}`. |
| `archive_manifest.json` | `tools/owner_evidence_bind.py manifest` | written LAST |

A NOT_APPLICABLE leg gets no `raw`/`parsed` file. The verifier marks its slots
`NOT_APPLICABLE`: never MISSING, never present, never a pass. A report found
for such a leg is INVALID. `REAL_TICK_COVERAGE_NONE` can never produce
`MT5_VALIDATED`.

`reconciliation_verify.json` always carries `first_divergence` and
`first_trade_divergence` per gold whenever `reconciliation/<gold>.json`
exists, and the stage-8 reason quotes them. `binding_verified: false` means
the binding chain failed. In that case the divergence is shown but never
classified as the expected sizing divergence.

**Former gaps, now closed** (listed as gaps on 2026-10-04):
- The anchor relation: compile evidence and the reconciliation binding now
  accept a clean descendant of the frozen anchor whose frozen bytes are
  identical (S8-ANCHOR-REL-1, `owner_gate.py` `source_commit_relation`).
- The SymbolSpec exporter now writes `broker`, `timestamp` and
  `terminal_build` (`Mql5BotExportSymbolSpec.mq5`).
- `broker`, `terminal_build` and `account_mode` in the environment record
  are still written only when a window states them; anything unmeasured is
  listed under `unmeasured`.
- The log-sourced count comparison no longer compares Python TRADES with
  MT5 DEALS (56 vs 74 in gate_run26): it compares the expected in-window
  entries with the log list's entry deals (`entry_count:<model>`, S8-COUNT-1;
  `owner_gate.py`), and keeps the frozen trade count only as a recorded
  presence guard. gate_run59: gold1 18/18, gold2 37/37 entries paired.

**The eight safety files.** `safety/<test>.json` for kill_switch,
risk_veto, lost_response, meta_reduce, sl_verify, restart, netting and
hedging. Each states `action`, `initial_state`, `resulting_state`,
`observed_result`, `expected_result` and a file-bound `raw_evidence`
`{path, sha256}`; a file is VALID only when the observed result IS the
expected one (SAFETY-RESULT-1). The gate writes them itself:
- **five Strategy Tester legs in stage 8** (SAFETY-8A-8D-1, SAFETY-DEMO-1):
  kill_switch, risk_veto, lost_response, meta_reduce, sl_verify — from each
  leg's graded window (docs/SAFETY_8A_8D_PLAN.md);
- **three live demo tests in stage 7** (DEMO-IN-GATE-1): restart, netting,
  hedging — graded at stage 8 from this run's `demo_safety/<test>/ealog.txt`
  (docs/SAFETY_DEMO_PLAN.md).

gate_run59: all eight VALID.

## Runner trigger tags

The Windows MT5 runner launches the gate when a merge commit on master
carries a tag:

| Tag | Command | What runs |
|---|---|---|
| `[runner: gold1]` / `[runner: gold2]` | `owner_gate.ps1 -Golds gold1` (or `gold2`) | one gold, stages 0-5 and 8; 9-10 REFUSED (scoped) |
| `[runner: demo-in-gate]` | `owner_gate.ps1 -Golds gold2 -DemoSafety` | gold2 plus the live demo tests (stage 7); 9-10 REFUSED (scoped) |
| `[runner: full]` | `owner_gate.ps1 -DemoSafety` (no `-Golds`) | **the certification run**: gold1 + gold2 + demo, stages 0-10. Stage 10 issues the certificate when the verifier's unscoped verdict is `MT5_VALIDATED_BAR_MODELS` (or `MT5_VALIDATED`). |
| `[runner: pytest]` | the full pytest suite on the Windows host (no gate) | Windows-only behaviour of the Python suite; report under `reports/windows_pytest/` |

The exact commands (the data folder is the terminal's, e.g.
`%APPDATA%\MetaQuotes\Terminal\<terminal_id>`):

```
# [runner: gold1] / [runner: gold2]
powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 -DataFolder "<data folder>" -Golds gold1
# [runner: demo-in-gate]
powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 -DataFolder "<data folder>" -Golds gold2 -DemoSafety
# [runner: full]
powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 -DataFolder "<data folder>" -DemoSafety
```

**Market window.** `-DemoSafety` places live demo orders, so the demo
preflight (`owner_gate_decide.py demo-preflight`) runs at stage 0 and again
at the start of stage 7; outside FX market hours (Friday 20:00 UTC to Sunday
22:15 UTC, and the daily 20:45–22:15 UTC rollover) it FAILs
`[market_closed]` and the harness never runs.

**Exit code.** The gate records its own exit code before it exits
(GATE-EXIT-1): `gate_exit_code.txt` in the evidence directory, `exit_code`
in `gate_summary.json`, and a `GATE_EXIT_CODE=` line after `GATE_RESULT=`.
Only `certified` exits 0; `certified_with_log_graded_legs` exits 1 by design.

**Leak check.** Before publishing `reports/gate_run<N>/` to `gate-reports`,
the runner scans every published file for the demo logins and passwords
(raw and UTF-16) and records the count in that run's `SUMMARY.md`
(gate_run59: 34 files, 0 hits). This is the runner's procedure, not repo
code; the gate itself never writes a credential (the harness records only a
hashed login).

The full run needs FX market hours (the demo tests place live demo
orders) and the local demo accounts file. Neither is in the repo.

**Runner rules (HARNESS-SUSPEND-1, gate_run57).**
- The host must not sleep or hibernate during a gate. Disable sleep,
  hibernation and lid-close suspend for the whole run (on a laptop: plugged
  in, "never sleep"). The same holds for the VM the terminal runs in.
- A run that spans a host suspend is **invalid**, whatever it shows. The
  demo harness watches the wall clock between its polling iterations
  (about 1 s apart). A gap of more than 300 s aborts the test at once,
  never continuing it. The run's `run.json` then has `"status":
  "INTERRUPTED"`, an error starting `[host_suspended] host suspended`, and
  a `suspended` record (`from_utc`, `to_utc`, `gap_s`). The harness still
  runs its restore, so the probe position is closed and the terminal is
  left on the hedging account.
- Stage 7 then FAILs with `[demo_host_suspended]`, and no later demo test
  runs in that gate. Re-run the whole gate with the host kept awake.

## Scoped (partial) runs: `-Golds`

```
powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 -DataFolder <MT5 data folder> -Golds gold2
```

`-Golds` names the golds whose fixtures are imported (stage 4) and whose
tester legs run (stage 5). The default is all golds. Stage 8 verifies only
the scoped golds (`verify_owner_mt5_gate.py --golds`). Stages 9 (archive
manifest) and 10 (certify) are **refused**: each is recorded `REFUSED` with
`[refused_scoped_run]` and neither tool runs. The gate has no stage 6.
Stage 7 (`demo_safety`) exists only with `-DemoSafety`
(DEMO-IN-GATE-1; docs/SAFETY_DEMO_PLAN.md).

**A partial run is evidence about the scoped golds only, and it certifies
nothing.**
- It can never end `GATE_RESULT=certified` or
  `certified_with_log_graded_legs`. It always ends
  `GATE_RESULT=partial_<last stage reached>`, for example
  `partial_tester_legs` or `partial_reconciliation`. The exit code is always 1.
  The gate records its own exit code before it exits (GATE-EXIT-1):
  `gate_exit_code.txt` in the evidence directory, `exit_code` in
  `gate_summary.json`, and a `GATE_EXIT_CODE=` console line after
  `GATE_RESULT=`. Only `certified` exits 0.
- `gate_summary.json` carries `"scope"` (e.g. `["gold2"]`),
  `"certifiable": false`, `"partial": true`, `"excluded"`
  (each excluded gold with the reason) and `"unscoped_result"` (what an
  unscoped run would have reported at that point).
- Every `stage_<n>.json` carries `scope` and `partial`, and its reason
  starts `[scope: gold2; PARTIAL run -- certifies nothing]`.
- The best stage-8 verdict for a scoped verification is
  `MT5_VALIDATED_PARTIAL_SCOPE`. That is not a positive verdict: the
  excluded golds were not examined at all.
- An unknown gold name fails stage 0 (`[invalid_scope]`).

## Hard rules (in the script, not the operator)

The script never writes `frozen_inputs.json`; never edits
`certification_manifest.json` outside the binder; never substitutes live
chart history for a committed fixture; never amends or force-pushes (it does
not commit at all); and records/classifies divergences rather than patching
them.

## Re-anchor note

The frozen record is governed by an owner-authority re-anchor (see
`artifacts/owner_mt5_gate/frozen_inputs.json` `source.note` and the
`docs/DECISIONS.md` 2026-09-18, S8-REANCHOR-1 and S8-REANCHOR-2 entries). The
anchor is now `6299de341e3bbc0d5fbd9d0bd7235e8f99c64ae7` (S8-REANCHOR-2,
2026-10-07, the gold1 regeneration); before that it was `734bb8d`
(S8-REANCHOR-1, 2026-10-04) and `a85cba3` — the 227bf66 anchor predated the generic DSL
runtime, the reserved-word compile fix and the P0-1 sizing fix (`4257f1e`),
so it could never be the commit to run. Stage 0 no longer requires `HEAD` to equal the anchor: a clean `HEAD`
that **descends** from the anchor, with every frozen artifact byte-identical,
PASSES with a recorded NOTE (`SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR`). Only an
**older** HEAD, a **diverged** HEAD, an **unknown** anchor, a changed frozen
artifact, a dirty tree, or `core.autocrlf=true/input` fails
(`SELF_PROTECT_HEAD_MISMATCH` / `SELF_PROTECT_FROZEN_HASH_MISMATCH` /
`SELF_PROTECT_DIRTY_TREE` / `SELF_PROTECT_AUTOCRLF_NOT_FALSE`). The owner
performs any re-anchor; the gate never writes `frozen_inputs.json`.

## Verifying the decision engine on any host

`tools/owner_gate_decide.py` and `mql5bot.gate_selfcheck` run anywhere;
`tests/test_owner_gate_ps1.py` exercises the self-protection failures, the
BOM-aware log parse, the parity and broker-scope decisions, and the dataset
hash against the committed calibration fixtures. A green test there proves
the gate fails closed; it is not an MT5 or certification claim.
