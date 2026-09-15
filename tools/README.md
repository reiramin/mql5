# tools/ — AEGIS build & research tooling

Windows-side tooling for the AEGIS research / performance upgrade mission
(docs/SPEC.md §14/§17 DoD: compile with **0 errors / 0 warnings, log
attached**).  Everything here is invoked by the **owner** (or a Windows
runner) and its output is pasted back into the session — this sandbox has no
MetaEditor and no MetaTrader 5, so **no compile or backtest result may ever
be claimed without a real tool log** (HANDOFF §10).

## Canonical owner protocol (single source of truth)

The tools in this directory execute the canonical TEN-step owner sequence
defined in `docs/MT5_ROUNDTRIP.md`: `compile.ps1` = steps 1–2 (strict
compile + compiler-log verification), `broker_symbol_parity.py` +
`Mql5BotExportSymbolSpec.mq5` = step 3 (SymbolSpec export), fixture/data
preparation = step 4, `run_mt5_backtest.py` = steps 5–7 (M1-OHLC /
Every-Tick / real-ticks tester legs incl. raw archive + parse),
`certify_strategy.py` = steps 5–8 + 10 (legs, Python↔MT5 comparison,
state assignment), archive/manifest = step 9. Any shortened checklist of
these tools is a SHORTCUT and must map its items onto those canonical
step numbers.

## compile.ps1 — MetaEditor compile round-trip

Builds the mql5bot EA from the command line and produces one reproducible
compile log.

### Requirements

- Windows with MetaTrader 5 installed (any broker build; portable installs
  work too — see `-DataFolder`).
- Windows PowerShell 5.1+ (`powershell`, not only `pwsh`).
- The repo checked out (sources under `mql5/`).

### Owner flow (one round-trip)

```powershell
# from the repo root
powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict
```

The script:

1. Locates `metaeditor64.exe` — `-MetaEditorPath`, env `MQL5BOT_METAEDITOR`,
   then beside known terminal roots (registry `DataPath` / `origin.txt`
   portable entries), then `Program Files\MetaTrader*\`, Start-menu
   shortcuts, then `PATH`.
2. Resolves the MT5 **data folder** (the tree that contains `MQL5\`) —
   `-DataFolder`, env `MQL5BOT_DATA_FOLDER`, then the same known roots, then
   the newest `%APPDATA%\MetaQuotes\Terminal\<hash>\` that contains `MQL5`.
   Includes are resolved by MetaEditor inside that tree, which is why
   sources are installed there first (step 3).
3. Installs (copies) `mql5/Include|Experts|Scripts|Presets/Mql5Bot/*` into
   `<data>\MQL5\...` (skip with `-SkipInstall`).
4. Compiles every `*.mq5` under `Experts\Mql5Bot` and `Scripts\Mql5Bot`:
   `metaeditor64.exe /compile:"<file>" /log:"<file>.log"`, one invocation
   per file.
5. **Gates on real compiler output**: the produced `.ex5` must exist AND be
   newer than the compile start (an old `.ex5` from a previous build is not
   proof), and the compiler log is captured verbatim.  English severity
   tokens (`error` / `warning`) are counted when present; a non-English
   MetaEditor simply produces no tokens, so the `.ex5` freshness check is
   the authoritative signal and the raw log is always kept for human review.
6. Writes one combined reproducible log to
   `logs\compile-<UTC timestamp>.log` (host, versions, command lines,
   per-file verdicts, verbatim compiler logs, SHA-256 of every produced
   `.ex5`).  `logs/` is gitignored — nothing generated is committed.

### Parameters

| Parameter          | Meaning                                                        |
| ------------------ | -------------------------------------------------------------- |
| `-MetaEditorPath`  | Full path to `metaeditor64.exe` (auto-detected when omitted)   |
| `-DataFolder`      | MT5 data folder containing `MQL5\` (auto-detected when omitted)|
| `-Strict`          | Exit 3 when the compiler log contains any `warning` token      |
| `-SkipInstall`     | Don't copy repo sources; compile what is already in the data folder |
| `-RepoRoot`        | Repo root (default: `tools\..`)                                |
| `-OutDir`          | Combined-log directory (default `<RepoRoot>\logs`)             |

Environment fallbacks: `MQL5BOT_METAEDITOR`, `MQL5BOT_DATA_FOLDER`.

### Exit codes

| Code | Meaning                                                        |
| ---- | -------------------------------------------------------------- |
| 0    | PASS — every file compiled; 0 errors (warnings allowed unless `-Strict`) |
| 2    | FAIL — compile errors / `.ex5` not refreshed                   |
| 3    | FAIL — `-Strict` and warnings present                          |
| 1    | FAIL — `metaeditor64.exe` not found                            |
| 4    | FAIL — data folder not found / nothing to compile              |
| 5    | FAIL — script exception                                        |

### What to paste back into the session

The final `[compile] RESULT: ...` line(s) and the combined log path, e.g.:

```
[compile] Mql5Bot.mq5 : PASS (exit 0, ex5 fresh=True)
[compile] RESULT: PASS — 1 file(s) compiled clean
# combined log: C:\repo\logs\compile-20260904-120000.log
```

A green claim requires `RESULT: PASS` **plus** the log file (DoD item 1:
"log attached").  Anything less is `COMPILE NOT VERIFIED`.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `metaeditor64.exe not found` | Pass `-MetaEditorPath` explicitly. |
| `MT5 data folder not found` | Pass `-DataFolder` (a dedicated portable terminal folder works; it must contain `MQL5\`). |
| `FAIL ... ex5 fresh=False` with empty log | Another MetaEditor instance may hold the file open — close MetaEditor/GUI and re-run. |
| Warnings you disagree with | `-Strict` fails the run; review the warning lines in the combined log, fix the source, re-run. Non-English MetaEditor builds cannot report token counts — rely on the verbatim log. |
| Running on the Phase-2 dedicated portable terminal | `-MetaEditorPath <portable>\metaeditor64.exe -DataFolder <portable>` — compile and tester then share one data tree. |

## run_mt5_backtest.* — headless Strategy Tester (Phase 2)

Batch backtest driver with **no GUI clicking**: generate `.set` presets and
tester `.ini` files, run `terminal64.exe /config:<ini>` headless, parse the
MT5 HTML report into canonical JSON metrics, and keep every raw artifact.

- `python/mql5bot/mt5tester.py` — deterministic, unit-tested core
  (`.set` parse/render with optimization ranges preserved verbatim,
  `[Tester]`+`[TesterInputs]` ini generation, locale-tolerant HTML report
  parser, sequential batch runner).  Pure Python; runs anywhere.
- `tools/run_mt5_backtest.py` — CLI: `generate-set`, `generate-ini`,
  `matrix` (strategy × symbol × timeframe jobs.json), `parse`, `run`
  (Windows only), `batch`.
- `tools/run_mt5_backtest.ps1` — strict logged PowerShell wrapper for the
  owner/Windows runner.

### Owner flow (Windows round-trip)

```powershell
# 1. write a deterministic tester ini for one run
powershell -ExecutionPolicy Bypass -File tools\run_mt5_backtest.ps1 `
  generate-ini --ea "Experts\Mql5Bot\Mql5Bot.ex5" --symbol EURUSD `
  --timeframe H1 --model 1 --from 2023.01.01 --to 2024.01.01 `
  --deposit 10000 --currency USD --leverage 100 `
  --input InpStrategy=0 --input InpSlAtr=2.5

# 2. run it headless against a (portable) terminal and parse the report
powershell -ExecutionPolicy Bypass -File tools\run_mt5_backtest.ps1 `
  run --terminal-dir D:\MT5 --data-folder D:\MT5 --out-dir results `
  --symbol EURUSD --timeframe H1 --from 2023.01.01 --to 2024.01.01

# 3. batch matrix
powershell -ExecutionPolicy Bypass -File tools\run_mt5_backtest.py matrix `
  --symbols EURUSD,GBPUSD,XAUUSD --timeframes H1,H4 --strategies 0,1,2 `
  --output jobs.json
powershell -ExecutionPolicy Bypass -File tools\run_mt5_backtest.ps1 `
  batch --jobs jobs.json --terminal-dir D:\MT5 --data-folder D:\MT5
```

### Determinism contract

Every run sets symbol, timeframe, model, FromDate/ToDate, deposit,
currency and leverage explicitly; the same inputs produce the same
`Report=<Symbol>_<TF>_<from>_<to>` stem and the same ini text.  MT5 itself
applies the broker symbol conditions (spread source, tick history), which
is a documented environment property, not a hidden knob — execution-cost
scenarios (BASE/STRESSED/SEVERE) live in the Python execution model and are
compared against these MT5 runs with explicit tolerances (Phase 4/6).

### Report parsing

`parse` reads the tester HTML report into `{settings, fields, metrics}`:
`settings` classifies the header rows (expert/symbol/period/deposit/…),
`fields` preserves every raw label/value pair (locale labels included),
`metrics` holds typed canonical values — money, pct, count, and composite
rows such as drawdowns `949.00 (10.79%)` or won-%-rows `60 (100.00%)`.
Unmatched rows are kept raw, never guessed.  Raw `.htm` reports are copied
into `results/runs/<run_id>/` before parsing, plus `tester.ini`,
`report.json`.

### Exit codes (CLI and wrapper)

| Code | Meaning |
| ---- | ------- |
| 0 | OK |
| 1 | runtime/parse failure (see `results/runs/<id>/`, log) |
| 2 | usage/config error |
| 3 | `run`/`batch` on a non-Windows host |
| 4 | wrapper failure (python missing, log unwritable) |

### What to paste back into the session

The wrapper prints `[mt5tester] RESULT: OK|FAIL`, the exit code, and the
log path (`logs/mt5tester-<command>-<stamp>.log`).  A green headless-backtest
claim needs that output plus at least one preserved raw report.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| exit 3 on Linux/macOS | expected — `generate-*`, `matrix`, `parse` work everywhere; `run`/`batch` need Windows. |
| `report not found` | download history for the symbol first (open a chart in the terminal), confirm `<data>\tester\` exists and is writable, check the terminal log. |
| Terminal does not exit | pass a shorter `--timeout` and check whether the account is logged in — a tester run needs a logged-in (demo) account. |
| Locale-labelled report values | `fields` keeps them raw; add/confirm synonyms in `python/mql5bot/mt5tester.py` METRIC_DEFS on the owner round-trip. |

## profile_research.py — performance profiling (Phase 18, planned)

Benchmark evidence for every optimization (see TASKS.md).
