# The last four safety tests — lost_response, restart, netting, hedging

Owner authorization (Sal, 2026-10-06):
- `mql5/Include/Mql5Bot/TradeManager.mqh` may get a test-only fault hook,
  default OFF;
- `mql5/Experts/Mql5Bot/` may get test-only inputs, default OFF.

At their defaults, the gold legs must behave as before.

**Status.**
- **Built and unit-tested:** the MQL5 edits are pinned by source tests.
- **Harness:** run here only against a fake terminal.
- **Never run against MT5 or a demo account:** nothing below is evidence
  yet.

## Overview

| test | where | how | pinned pass result |
|---|---|---|---|
| lost_response (8c) | **Strategy Tester** (stage-8 safety leg, like PR #31) | TradeManager fault hook | `LOST_RESPONSE_ADOPTED_NO_DUPLICATE` |
| restart (8b) | **demo account** (hedging), demo harness | kill + relaunch the terminal with a probe position open | `RESTART_RECOVERED_NO_DUPLICATE` |
| netting (8d) | **demo account** (netting), demo harness | account-mode probe | `NET_ONE_POSITION_PER_SYMBOL` |
| hedging (8d) | **demo account** (hedging), demo harness | account-mode probe + a second magic | `INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC` |

For every test:
- **Builder.** `stage8_package` writes `safety/<test>.json` from evidence
  this binary produced:
  - lost_response: the tester leg's window;
  - restart / netting / hedging: the harness EA log, accepted ONLY when
    the run's `ex5_sha256` equals this gate's stage-1 compile hash.
- **Verifier.** `verify_safety` re-grades the bound evidence itself with
  `mql5bot.safety_legs`. It requires re-grade == `observed_result` == the
  pinned value (`owner_gate.SAFETY_PINNED_EXPECTED`).
- **Never a pass.** A trigger that never fired, or a missing step, is
  `NOT_*` / `INCONCLUSIVE_*`.

## lost_response — Strategy Tester (implemented)

**Fault hook.** `CTradeManager::TestFaults(drop, suppress)`, armed only
when the EA inputs `InpTestLostResponses` / `InpTestUnsentTimeouts` are
> 0 (both default 0). It affects only `OpenMarket`; retries
(`ExecuteQueued`) are never touched:
- **suppress:** the request is NOT sent; the call sees
  `TRADE_RETCODE_TIMEOUT`. The existing code must find no deal, queue the
  entry, and retry it once with backoff (`EXEC|open_queued` →
  `EXEC|open_retry`).
- **drop:** the order FILLS, but its answer is replaced by
  `TRADE_RETCODE_TIMEOUT`. The existing code must find the fill in deal
  history (`FindRecentDeal`) and record `EXEC|open_verified` with no
  re-send.

**Leg inputs.** `InpTestUnsentTimeouts=1`, `InpTestLostResponses=1`, run as
the fifth stage-8 safety leg.

**Grade.**
- Each suppressed send must be queued and retried, with exactly one entry
  request between suppression and retry.
- Each dropped answer must be `open_verified`, with exactly one entry
  request at that time and no `open_queued`.
- At least one of each kind must occur.

**Unmeasured.** Whether the tester's deal comment equals the request
comment, which `FindRecentDeal` matches on. If it does not, the leg grades
`NOT_ADOPTED` — a real finding, never hidden.

## restart / netting / hedging — the demo harness (implemented, untested on MT5)

**Command (Windows agent, no clicking).** Run one per test:

    python tools\demo_safety_harness.py run --test restart ^
        --terminal "C:\Program Files\MetaTrader 5\terminal64.exe" ^
        --data-folder "%APPDATA%\MetaQuotes\Terminal\<id>"

Output: `evidence\demo_safety\<test>\ealog.txt` + `run.json` (gitignored).
The next gate run picks them up (`-DemoEvidence`, default
`evidence\demo_safety`).

**What the harness does.**
- **Preset.** Writes `MQL5\Presets\mql5bot_demo_<test>_<probe>.set`: the EA
  defaults plus `InpTestDemoProbe` (no secrets).
- **Login.** Reads Login / Password / Server from the LOCAL accounts file:
  `%USERPROFILE%\.mql5bot\demo_accounts.json`, or the path in
  `MQL5BOT_DEMO_ACCOUNTS`. A file inside the repo is refused.
- **Startup config.** Writes a `[StartUp]` ini (`[Common]` login,
  `[Experts] AllowLiveTrading=1`, `Expert=Mql5Bot\Mql5Bot`,
  `Symbol=EURUSD`, `Period=M1`) to a fresh TEMP directory outside the repo.
  It deletes the ini as soon as the EA prints `TEST demo: START`, and
  always on exit.
- **Launch and follow.** Starts `terminal64.exe /config:<ini>` and follows
  the EA's own log `MQL5\Files\Mql5Bot\Logs\mql5bot_EURUSD_M1_<date>.log`.
  The file is UTF-16 and re-created on every EA start, so the harness
  buffers lines as they appear.

**restart** (hedging account):
1. Probe 1 opens ONE position (buy volume_min, SL/TP 500 points). A file
   flag stops a second probe entry across the restart.
2. After 30 s the terminal process is **killed** (TerminateProcess: no
   OnDeinit).
3. After 10 s it is relaunched and observed for 90 s (heartbeat every
   10 s).
4. Probe 3 then closes the probe position.

Grade: same magic before/after, 1 own position at restart, engine NORMAL,
the registry recovered to 1, and never >1 own position afterwards.

**netting** (netting account), probe 2:
1. Buy volume_min.
2. Sell 2×volume_min.
3. A foreign-magic buy.
4. Close all.

Grade: the account mode is NETTING; after the sell there is ONE position
on the symbol, a sell of volume_min.

**hedging** (hedging account), the same probe 2:
- after the sell: two own tickets (buy, sell);
- after a buy with **magic + 1** (a raw order, the second "strategy"): that
  position exists, while the EA's own count and registry stay 2.

**Why not two charts.** A `[StartUp]` ini attaches ONE expert to ONE
chart. Two EA instances would need a chart profile (`.chr` files), whose
format MetaQuotes does not document, so the harness does not write one.
The second magic therefore comes from a test-only raw order in the same
EA. This proves attribution by magic and registry isolation, NOT two
independent EA instances. If the owner requires two instances, the
fallback is `blocked_owner_environment` (the verifier already accepts that
for hedging only), or hand-attaching a second chart.

**Probe mode replaces the strategy.** While `InpTestDemoProbe > 0` the EA
skips its strategy entries and exits, so the probe alone trades. The
restart test therefore covers the **open position** cell of the restart
matrix: state reload, registry/adoption, magic identity, no duplicate
exposure. It does NOT cover:
- restart during a pending execution, an active retry, or an allocation
  poll;
- the strategy's own re-entry logic after a restart.

## What the owner must do by hand

1. **Netting account.** Create a NETTING demo account (MT5: File → Open an
   Account → MetaQuotes-Demo, with "Use hedge in trading" UNCHECKED).
2. **Hedging account.** The gate_run35 account is hedging, so it can serve
   as the hedging/restart account; otherwise create one with "Use hedge"
   checked.
3. **Accounts file.** Write `%USERPROFILE%\.mql5bot\demo_accounts.json`
   OUTSIDE the repo:

       {"hedging": {"login": "...", "password": "...", "server": "MetaQuotes-Demo"},
        "netting": {"login": "...", "password": "...", "server": "MetaQuotes-Demo"}}

   Never commit it or paste it into chat.
4. **Compile.** Compile the EA through the gate (stage 1), so the demo
   runs use the EX5 the gate binds.
5. **Close terminals.** Close every running terminal of that data folder
   before a harness run (a second launch would hand the config to the
   running instance).
6. **Market hours.** Run while EURUSD trades on the demo server: Monday
   00:05 – Friday 23:50 server time. Avoid the daily rollover (~23:55 –
   00:05) and weekends; market orders are refused when the market is
   closed. Each run takes about 2–4 minutes.

## Untested

- **Compile.** The MQL5 edits were never compiled (no metaeditor here).
- **Harness.** Never run on Windows / MT5. The process handling,
  `[StartUp]` keys, UTF-16 log reading, kill semantics and timeouts were
  exercised only against a fake terminal.
- **Account mode.** Whether MetaQuotes-Demo reports `ACCOUNT_MARGIN_MODE`
  0 / 2 as expected.
- **Tester deal comment.** Whether the tester's deal comment matches the
  request comment (affects lost_response).
