# Owner Delivery — what you are receiving, and what is proven

Read this before anything else. It is written for a competent
non-programmer. Every claim below is either backed by a named file (with
its SHA-256 fingerprint, so you can check it has not changed) or is
marked plainly as **NOT RUN**. No result here is a promise of profit.

## 1. What this is

Two pieces that must behave identically:

- **A Python strategy factory** (`python/mql5bot/`) — researches,
  backtests and scores trading strategies on your computer. It never
  places a real order.
- **An MQL5 execution bot** (`mql5/`) — an Expert Advisor (EA) that runs
  inside MetaTrader 5 and is the only piece allowed to place orders.

The rule binding them: **for the same inputs, both engines must produce
the same trades.** We prove that with "parity" tests — the same strategy
is run through the Python engine and through a byte-for-byte reproduction
of the MQL5 decision logic, and the two trade lists are compared. If they
disagree, the build fails.

## 2. Status table — one row per claim

Labels: **VERIFIED** (a committed artifact proves it) ·
**IMPLEMENTED-UNVERIFIED** (code exists and is unit-tested, but the
MetaTrader-runtime proof has not been produced) · **NOT RUN** (no
evidence exists yet).

| Claim | Status | Evidence (file · sha256) |
|---|---|---|
| Strict EA compile 0 errors / 0 warnings | **NOT RUN** | no `Mql5Bot.ex5` / `compile.log` committed (`artifacts/owner_mt5_gate/verification_report.json` reports both MISSING). You run `tools\compile.ps1 -Strict`. |
| DSL parity 14 / 14 fixtures agree (Python ↔ DSL) | **VERIFIED** | `artifacts/dsl_parity/manifest.json` · `25c1d445f352054187ed44b473396c9288ec376078094eebbc0f24ca37de6d89` (14 fixtures, each hash-pinned) |
| Broker denomination = ACCOUNT_CURRENCY (EURUSD, US30, XAUEUR) | **VERIFIED** | `artifacts/owner_mt5_gate/broker_parity.json` · `02de2360831306771404774877cebcb7f67d5b2c43461f8602503b74b416c4ae` — of 90 rows: 10 MATCH, 2 differ only at the 3rd decimal (`loss_per_lot`, owner-rounded), 2 PENDING (BTC), 76 not-applicable |
| Broker denomination for BTC | **NOT RUN** | same file, status PENDING ("account/profit denomination hypotheses are ambiguous") |
| Gold #1 leg (16 trades) Python ↔ DSL | **VERIFIED** | `artifacts/gold/reconciliation.json` · `b39100591007e3292ebbbce8d76c7a41362d6a2ec4d0530acb71f8e82e753e2d` — `python_vs_dsl: MATCHED` |
| Gold #1 leg Python ↔ MQL5 in MT5 tester | **NOT RUN** | same file — `python_vs_mql5: PENDING_OWNER`, `python_vs_mt5_tester: PENDING_OWNER` |
| Gold #2 leg (56 trades) Python ↔ DSL | **VERIFIED** | `artifacts/gold_2/reconciliation.json` · `caa8a973934c61cd0e416af3755865af787c4339a94ab2779d2facbfe52eb9ff` — `python_vs_dsl: MATCHED`, `python_vs_mql5_source: SOURCE_PARITY` |
| Gold #2 leg in MT5 tester | **NOT RUN** | same file — `python_vs_mt5_tester: PENDING_OWNER` |
| Custom-symbol import of a Gold fixture into MT5 | **NOT RUN** | `mql5/Scripts/Mql5Bot/Mql5BotImportFixture.mq5` exists and self-verifies by hash round-trip. Progress across owner runs: gate_run8 refused at `SYMBOL_VOLUME_MIN` (err 5308, fixed by volume-family ordering, R6); gate_run9 set 13 properties OK and refused at `verify_properties` because MT5 infers base/profit currencies from the symbol name — fixed by renaming to `EURUSD.G1`/`EURUSD.G2` (R7); gate_run10 verified all 16 settable properties but the calculated `SYMBOL_TRADE_TICK_VALUE_PROFIT` read back 0 — this is now a **named, scoped limitation** (see limitations §5), not a blocker (R8): stage 4 passes and certifies strategy logic + execution path, while tick-value economics are certified by stage 3. All fixes are **IMPLEMENTED-UNVERIFIED** until you re-run the gate. |
| Reconciliation report format (17 fields per trade) | **VERIFIED** | `artifacts/gold/reconciliation.json` (`fields` array) |
| Kill-switch / restart / retry logic | **IMPLEMENTED-UNVERIFIED** | Python unit-tested (`python/mql5bot/discovery/safety.py`, `tests/test_retryqueue.py`); MQL5 enforcement is PARTIAL and owner-unproven (`docs/KILL_SWITCH.md` line 23) |
| NETTING account behaviour | **NOT RUN** | `artifacts/owner_mt5_gate/verification_report.json` — `safety/netting.json` MISSING |
| HEDGING account behaviour | **NOT RUN** | same file — `safety/hedging.json` MISSING |

## 3. What has never been proven (read this first)

- **No strategy has passed the statistical gates on real market data.**
- **No demo account has ever run this EA.**
- **No live trading has ever happened.**
- **Profitability is unknown and is not claimed anywhere.**

Everything marked VERIFIED above proves only that the two engines
*agree with each other* on controlled fixture data. Agreement is not
profit, and fixture data is not the market.

## 4. Before you connect any real account — checklist

1. Run **at least 4 weeks on a demo account** and collect **at least 30
   trades** before drawing any conclusion.
2. Get a **BTC denomination verdict** — the one currency question left
   PENDING in `broker_parity.json` (above). Until then, do not size BTC
   trades with this bot.
3. Obtain a **generic DSL runtime certification** — today the EA only
   executes its five built-in engines; any generated/DSL strategy beyond
   those is unproven in MT5 (`README.md` "execution-surface boundary").
4. **Re-run `tools\owner_gate.ps1` on your own machine and your own
   broker.** The hashes in this document pin *this* repository's
   fixtures; your broker's numbers must be captured and compared fresh.

## 5. Known limitations (one line each)

- **Single instance only.** All charts share one state file — never run
  two charts/instances of this EA at once; they will corrupt each other.
- **One strategy + one symbol per instance.** No multi-symbol or
  multi-strategy on a single EA attachment.
- **No runtime kill switch.** The emergency stop is reset via EA
  *inputs* only (reload/reset) — there is no live button while it runs.
- **Console has no launcher and no authentication.** It does not start
  MT5 for you and has no login; treat it as a local, trusted-only tool.
- **Natural-language intake is three regex patterns, no LLM.** The
  deterministic interpreter recognizes three strategy phrasings (EMA
  cross, RSI-above, RSI-low) plus a stop/target extractor; anything else
  is reported as ambiguous. No AI model is attached
  (`python/mql5bot/factory/interpreter.py`).
- **Tick-value is read-only, and may read back 0, on custom symbols.** MT5
  calculates `SYMBOL_TRADE_TICK_VALUE_PROFIT/_LOSS` itself and rejects
  attempts to set them (err 5307). For a bars-only Forex custom symbol they
  can also read back 0 (nothing to derive from). The Gold-fixture import
  therefore does NOT certify broker tick-value economics — it certifies
  strategy logic and the execution path on the fixture; the tick-value
  denomination is certified separately by the stage-3 broker parity check and
  the independent OrderCalcProfit witness. This is recorded as a named
  limitation in the import evidence, never a silent pass.

## 6. How to run it

**Install the Python toolkit** (macOS/Linux/Windows):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

**Run the EA (Windows + MetaTrader 5 only):** copy the EA into MT5 with
`python scripts/install_mql5.py`, compile it strictly with
`tools\compile.ps1 -Strict` (must be 0/0), then attach it to a chart.

**Where inputs go:** the EA's settings are entered in MetaTrader's
"Inputs" tab when you attach it to a chart. The risk inputs mean:

- **risk %** — fraction of account equity risked per trade (the distance
  to your stop-loss decides the lot size).
- **daily-loss %** — the account loses this much in a day → no new trades.
- **trail** — how far (in ATR multiples) a winning trade's stop follows
  price.
- **stop-loss / take-profit** — protective exit distances; every position
  always has a stop.

**Critical:** the bot only trades **while MetaTrader 5 is running and
connected.** If you close the terminal or your PC sleeps, it stops. For
unattended operation you need a **VPS** (an always-on Windows server)
running MT5.

---

*Entry point for the whole project. Engineering detail lives in
`docs/README.md`; honest project status lives in `README.md`.*
