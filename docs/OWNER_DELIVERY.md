# Owner Delivery — what you are receiving, and what is proven

Read this before anything else. It is written for a competent
non-programmer. Every claim below is backed by a named file (with its
SHA-256 fingerprint where one was produced, so you can check it has not
changed) or is marked plainly as **NEVER RUN**. No result here is a
promise of profit; profitability is unknown and is not claimed anywhere
in this repository.

This note reports one specific run of the automated certification gate:

- **When and where:** 2026-09-20, on your Windows machine —
  MetaTrader 5 build 6184, Windows 10 19045.
- **What was graded:** repository commit
  `81520e66144a83361ef0c7d290e95a5201efeba3`, which descends from the
  frozen source anchor `a85cba3757eecbde74951068bfbccd0e43a59e84`.
- **Where the evidence is:** `evidence\owner_gate\20260920-092713`
  on the machine that ran the gate — one `stage_<n>.json` per stage,
  plus `gate_summary.json`.
- **The verdict:** `GATE_RESULT=tester_legs`. The gate walked stages
  0 through 4 clean, **failed at stage 5 (the MetaTrader tester legs),
  stopped, and refused to certify anything further.** That refusal is
  the design working, not the design breaking — but it means this
  delivery is not certified.

## 1. What has never been proven (read this first)

- **No strategy in this project has ever been certified VERIFIED.**
  The Python research funnel produces only two labels:
  `SOFTWARE_PASS` ("every software stage ran exactly to spec — this
  claims nothing about any strategy's performance") and
  `EMPIRICAL_VALIDATION_PENDING` ("the statistical gates passed, but
  the MT5 verification ladder has not run"). Nothing has ever climbed
  past them.

- **Stage 8 reconciliation has never run.** The binding claim of this
  whole architecture is that the Python engine and the MQL5 EA behave
  identically — the same strategy, the same data, the same executed
  trades, compared field by field. That comparison is stage 8, and it
  has never happened. Nothing in this delivery demonstrates
  cross-engine parity on executed trades. Stages 6–10
  (reconciliation including 8a–8d, archive, certify) were **NEVER
  RUN** — the gate stopped before reaching them.

- **The DSL bundle path was never exercised in MT5.** The tester ran
  with the `InpDslBundleFile` input empty, so the EA executed its
  compiled-in default strategy — not a bundle produced from a user's
  natural-language description. The path from "describe a strategy in
  plain language" to "that strategy trades in MetaTrader" has never
  been walked end to end.

- **No parsed backtest metrics exist.** MT5 build 6184 does not write
  the `[Tester]` Report file, so there is nothing to parse. Two of the
  six tester legs (the gold #2 legs) DID run complete backtests —
  2880 bars, history quality 100% — which proves the EA loads and
  executes inside the tester, and proves nothing about whether it
  trades correctly or profitably. Those legs produced **zero trades**.

- **The gold #1 legs never ran at all.** The gold #1 H1 fixture is 120
  bars — too short. MT5 reserves preceding history for indicator
  warm-up and moved the test start past the end of the data (the log
  lines are quoted in §4).

- **No demo-account run. No real-account run. No VPS deployment. No
  uptime or recovery drill.** The Telegram channel and the Persian
  console were built and unit-tested; neither has ever run against a
  live system.

## 2. What IS proven, and the exact evidence class of each claim

The labels below are the project's fixed vocabulary. They are never
blurred into one another:

- **IMPLEMENTED** — the code exists and passes unit tests; no
  MetaTrader-runtime proof.
- **RESEARCH-VALIDATED** — proven by the Python research funnel only
  (backtests and statistics on this machine; never a performance claim).
- **GOLD_SEMANTIC_PASS** — the implementations agree on a frozen,
  controlled fixture; never implies MT5 validation or VERIFIED.
- **MT5-VALIDATED** — owner evidence produced on the real MetaTrader 5
  terminal and verified against the frozen record.
- **VERIFIED** — the entire ladder passed, including real MT5 tester
  runs with every required leg succeeding. **Nothing in this project
  holds this label.**
- **BLOCKED_OWNER_ENVIRONMENT** — the leg's own tester log proves a
  clean run, but the owner environment withheld the proving artifact
  (here: the Report file). **This is not a pass.** The gate stops on it.

### The 2026-09-20 run, stage by stage

**Stage 0 — self-protection: PASS (MT5-VALIDATED).** Before grading
anything, the gate proved it was grading the right thing: source anchor
verified, working tree clean, line-ending config correct, the frozen
MQL5 hashes plus 42 DSL-bound files byte-verified, the MT5 toolchain
located, and the `mql5bot` Python package resolved **from inside this
repository** (v1.0.0) — not from some other installation.

**Stage 1 — strict compile: PASS (MT5-VALIDATED).** All five targets
compiled with **0 errors, 0 warnings**: `DslParityRunner.mq5`,
`Mql5Bot.mq5`, `Mql5BotDownloadData.mq5`, `Mql5BotExportSymbolSpec.mq5`,
`Mql5BotImportFixture.mq5`.
Evidence: `compile-20260920-092716.log` · sha256
`0264bfc5d6483ff9e50d19acffbdf2626753eeeb72b64951b74c1d89444a2e8a`.

**Stage 2 — DSL parity: PASS (MT5-VALIDATED).** The compiled MQL5 DSL
runtime reproduced all **14 of 14** frozen parity fixtures EXACTLY, and
a deliberately tampered bundle was refused. This proves the two DSL
implementations agree on the frozen fixtures when run on your terminal;
it does not prove anything about tester-executed trades (that is
stage 8, never run).
Evidence: `dsl_compare_report.txt` · sha256
`32a053bc4eedbee8e0c84d48026bca03f45eaf708b43141e6067d8c76bdc76bf`.

**Stage 3 — broker parity: PASS (MT5-VALIDATED).** **12 MATCH rows**
against your broker's real symbol economics. Crypto is PENDING and was
excluded (`BTC:sizer.behaviour`, `BTC:tick_value_denomination`) — do
not size BTC trades with this bot until that verdict exists.
Evidence: `parity_report.json` · sha256
`e083e79b9e8aa24dd1d234778271de1303e579aa5c4b1d481b03bec5581f3a08`.

**Stage 4 — fixture import: PASS (MT5-VALIDATED).** Both gold fixtures
were imported into MT5 as custom symbols, and the round-trip dataset
hash matched the manifest — the data MT5 holds is byte-identical to the
data this repository ships. Both fixtures were re-checked and found
intact AFTER the tester legs ran: the legs mutated no frozen input.
Evidence:
`EURUSD.G1.json` · sha256
`0d0c8c71718d37f25fd538a90d7c5564c6dcb9db6c74fc8a3d531b6c87068513`;
`EURUSD.G2.json` · sha256
`4501b4b12c2e5226284b44672637589044a6555b1534d97eec7e684b59e38ff4`;
gold #1 dataset hash
`2b1730cbb43e959291a115c53db8a0c8620ea80ccf00b2251bf01dd236ebd764`;
gold #2 dataset hash
`59cd339f6ebd2070ffa726c9b4dbaf6074ef232fd2a391afcacb8c3e8bf3dd79`.

**Stage 5 — tester legs: FAIL.** Six legs, four distinct verdicts,
each judged only on its own window of the tester log:

| Leg | Verdict | Its own log window says |
|---|---|---|
| gold1_m1_ohlc | **FAIL** — INSUFFICIENT_FIXTURE_HISTORY | "EURUSD.G1: start time changed to 2024.01.06 00:00 to provide data at beginning" / "EURUSD.G1,H1: 0 ticks, 0 bars generated" |
| gold1_every_tick | **FAIL** — INSUFFICIENT_FIXTURE_HISTORY | same two lines |
| gold1_real_ticks | **FAIL** | its window contains no "successfully finished" and no symbol-attributed "N bars generated" line, so it cannot be classified BLOCKED |
| gold2_m1_ohlc | **BLOCKED_OWNER_ENVIRONMENT** | "successfully finished in 0:00:03.499" / "EURUSD.G2,M1: 11520 ticks, 2880 bars generated" |
| gold2_every_tick | **BLOCKED_OWNER_ENVIRONMENT** | "successfully finished in 0:00:04.296" / "EURUSD.G2,M1: 1894944 ticks, 2880 bars generated" |
| gold2_real_ticks | **FAIL** | no proving line inside its window |

A BLOCKED leg is not a pass: the gold #2 backtests ran to completion,
but build 6184 wrote no Report file, so there is no parseable result to
grade — and an ungraded run is never accepted as a passing one.

**Stages 6–10 — reconciliation (incl. 8a–8d), archive, certify: NEVER
RUN.**

The Python-side research funnel remains, as before, at
**RESEARCH-VALIDATED** at best (`SOFTWARE_PASS` /
`EMPIRICAL_VALIDATION_PENDING`), and the frozen gold-fixture agreements
remain **GOLD_SEMANTIC_PASS** — neither is, or ever substitutes for,
MT5-VALIDATED or VERIFIED.

## 3. What the gate caught — defects that would otherwise have shipped

This gate exists because it finds things. Real defects it caught before
they could reach an account:

- **A ~15% over-sizing bug.** `ProfitToDeposit` was multiplied against
  a tick value that was already denominated in account currency —
  double-applying the conversion and over-sizing every trade by roughly
  15%. The broker-parity stage caught it against real broker numbers.
- **A classifier reading outside its leg.** An earlier run's verdict
  logic read evidence from outside the window of the leg it was
  judging. The gate refused its own evidence and was fixed: each leg is
  now judged strictly on its own log window (which is why
  `gold1_real_ticks` above is FAIL, not BLOCKED — its own window proves
  nothing, and borrowing a neighbour's lines is forbidden).
- **A toolchain grading the wrong code.** An earlier run resolved the
  `mql5bot` Python package from outside the repository — the gate was
  grading a different mql5bot than the repo shipped. It refused, and
  stage 0 now requires the package to resolve IN-REPO before anything
  else runs.

Those two refusals — the gate rejecting its own evidence rather than
waving it through — are the product. A pipeline that cannot say "I
refuse my own result" cannot be trusted to say "certified" either.

## 4. Known limitations — each with its measured cause

- **Gold #1 fixture history is too short to test.** Measured: MT5
  logged "EURUSD.G1: start time changed to 2024.01.06 00:00 to provide
  data at beginning" and "EURUSD.G1,H1: 0 ticks, 0 bars generated". The
  fixture is 120 H1 bars; MT5 reserves preceding history for warm-up
  and moved the start past the end of the data. Fix: a longer fixture.
- **Build 6184 writes no `[Tester]` Report file.** Measured: the gold #2
  legs finished cleanly ("successfully finished in 0:00:03.499" and
  "0:00:04.296") yet produced no report to parse — hence
  BLOCKED_OWNER_ENVIRONMENT, hence no backtest metrics anywhere in this
  delivery.
- **The real-ticks legs left no proving line.** Measured: their log
  windows contain neither "successfully finished" nor a
  symbol-attributed "N bars generated" line, so they FAIL — the gate
  does not guess.
- **BTC denomination is still PENDING** (`BTC:sizer.behaviour`,
  `BTC:tick_value_denomination`, excluded from stage 3). Do not size
  BTC trades until a verdict exists.
- **Calculated tick values are non-authoritative on custom symbols.**
  MT5 computes `SYMBOL_TRADE_TICK_VALUE_PROFIT/_LOSS` itself, rejects
  attempts to set them (error 5307), and on a bars-only Forex custom
  symbol they can read back 0. The fixture import therefore certifies
  strategy logic and the execution path — never tick-value economics,
  which are certified separately by stage 3 against your real broker
  symbols. This is recorded in the evidence as a named limitation,
  never a silent pass.
- **Single instance only.** All charts share one state file — never run
  two instances of this EA at once.
- **One strategy + one symbol per EA attachment.** No multi-symbol or
  multi-strategy on a single attachment.
- **No runtime kill switch.** The emergency stop resets via EA inputs
  only (reload/reset) — no live button while it runs.
- **Console has no launcher and no authentication.** It does not start
  MT5 for you; treat it as a local, trusted-only tool.
- **Natural-language intake is untested in MT5.** The deterministic
  template interpreter and the optional LLM interpreter (which grounds
  every number in code and falls back to the templates without an API
  key) are Python-side and unit-tested only; no bundle either produced
  has ever been executed by the EA (see §1, DSL bundle path).
- **The bot trades only while MetaTrader 5 is running and connected.**
  Close the terminal or sleep the PC and it stops. Unattended operation
  requires a VPS (an always-on Windows server) running MT5.

## 5. Before any real money — in order

1. **Rebuild the gold #1 fixture with enough H1 history** for MT5's
   warm-up reservation, and re-run the gate so all six tester legs can
   actually run.
2. **Resolve the missing Report file on your terminal** (build 6184
   wrote none) so the tester legs can be graded — until then they stay
   BLOCKED, and BLOCKED is not a pass.
3. **Run the tester legs to a real PASS**, including a leg where
   `InpDslBundleFile` points at a generated bundle — otherwise the
   tester only ever proves the compiled-in default strategy.
4. **Run stage 8 reconciliation** — Python and MQL5 executed trades
   compared field by field. This is the binding claim of the
   architecture; nothing is certified without it.
5. **Get a BTC denomination verdict** before sizing any BTC trade.
6. **Let stages 9–10 (archive, certify) complete** — only a run that
   ends `GATE_RESULT=certified` puts VERIFIED on anything.
7. **Run at least 4 weeks on a demo account and collect at least 30
   trades** before drawing any conclusion.
8. **Deploy to a VPS and perform an uptime/recovery drill** — neither
   has ever been done — before connecting a real account.

## 6. How to run it

The gate is one command, run on your Windows machine from the
repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 `
    -TerminalPath "C:\Program Files\MetaTrader 5\terminal64.exe" `
    -DataFolder <your MT5 data folder>
```

Every decision it makes lives in committed code, never in a prompt. It
self-protects (stage 0), walks stages 1–10, stops at the first failure,
and never patches a divergence — it records it.

- **What a PASS looks like:** the run ends with the line
  `GATE_RESULT=certified` and exit code 0.
- **What a FAIL looks like:** the run ends with
  `GATE_RESULT=<name of the stage that stopped it>` and exit code 1.
  This delivery's run ended `GATE_RESULT=tester_legs`.
- **Where the evidence lands:** a new append-only folder
  `evidence\owner_gate\<UTC timestamp>\` containing one
  `stage_<n>.json` per stage, every produced artifact with its SHA-256,
  and a machine-readable `gate_summary.json`. This delivery's folder is
  `evidence\owner_gate\20260920-092713`.

---

*Entry point for the whole project. Engineering detail lives in
`docs/README.md`; honest project status lives in `README.md`.*
