# The last four safety tests — lost_response, restart, netting, hedging

Owner authorization (Sal, 2026-10-06):
- `mql5/Include/Mql5Bot/TradeManager.mqh` may get a test-only fault hook,
  default OFF;
- `mql5/Experts/Mql5Bot/` may get test-only inputs, default OFF.

At their defaults, the gold legs must behave as before.

**Status (gate_run59, 2026-10-13).** All four ran and are VALID:
lost_response `LOST_RESPONSE_ADOPTED_NO_DUPLICATE` (Strategy Tester leg in
stage 8), restart `RESTART_RECOVERED_NO_DUPLICATE`, netting
`NET_ONE_POSITION_PER_SYMBOL`, hedging `INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC`
(live demo, stage 7). The mechanism below is the one that produced them.
Built, unit-tested, never run live: the SPEC-WAIT-2 retry/give-up path and
the HARNESS-SUSPEND-1 abort (gate_run59 needed neither).

**The live-demo mechanism, by decision ID:**
- **DEMO-IN-GATE-1** — stage 7 runs the harness inside the gate with that
  run's own stage-1 EX5 (a separately run harness is bound to another
  compile and rejected, gate_run47).
- **DEMO-LOGIN-PERSIST-1** — every run ends on the hedging account with the
  password kept in the terminal's own store, proven by a credential-less
  launch that must connect.
- **DEMO-CHECK-CRLF-1** — generated ini files are written with
  `newline=""`, so no path carries a stray `\r` (gate_run52).
- **DEMO-HARNESS-RELAUNCH-1** — one relaunch when the EA initialises before
  the demo login completes.
- **HARNESS-INIT-FAIL-1** — a launch whose EA init fails is a named
  `[ea_init_failed]`, not a 900 s timeout.
- **SPEC-WAIT-1/2** — a relaunch on a not-yet-synchronized symbol waits in
  WAITING_SYMBOL (no new positions, no START line, bounded at 180 s,
  `SymbolSelect` + value logging each second) instead of failing init.
- **RESTART-GRADE-1** — the restart grader orders events by log position,
  not by the stale `TimeCurrent()` stamp.
- **HARNESS-SUSPEND-1** — a run spanning a host suspend (>300 s
  wall-clock gap) is INTERRUPTED; stage 7 FAILs `[demo_host_suspended]`.

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

## restart / netting / hedging — the demo harness

**Command (Windows agent, no clicking).** Run one per test:

    python tools\demo_safety_harness.py run --test restart ^
        --terminal "C:\Program Files\MetaTrader 5\terminal64.exe" ^
        --data-folder "%APPDATA%\MetaQuotes\Terminal\<id>"

Output: `evidence\demo_safety\<test>\ealog.txt` + `run.json` (gitignored).
A standalone run like this is for diagnosis only: stage 8 accepts demo
evidence only from the EX5 that same gate compiled, so the gate runs the
harness itself in stage 7 (`-DemoSafety`, DEMO-IN-GATE-1).

**What the harness does.**
- **Preset.** Writes `MQL5\Presets\mql5bot_demo_<test>_<probe>.set`: the EA
  defaults plus `InpTestDemoProbe` (no secrets).
- **Login.** Reads Login / Password / Server from the LOCAL accounts file:
  `%USERPROFILE%\.mql5bot\demo_accounts.json`, or the path in
  `MQL5BOT_DEMO_ACCOUNTS`. A file inside the repo is refused.
- **Startup config.** Writes a `[StartUp]` ini (`[Common]` login with
  `KeepPrivate=1`,
  `[Experts] AllowLiveTrading=1`, `Expert=Mql5Bot\Mql5Bot`,
  `Symbol=EURUSD`, `Period=M1`) to a fresh TEMP directory outside the repo.
  It deletes the ini as soon as the EA prints `TEST demo: START`, and
  always on exit.
- **Launch and follow.** Starts `terminal64.exe /config:<ini>` and follows
  the EA's own log `MQL5\Files\Mql5Bot\Logs\mql5bot_EURUSD_M1_<date>.log`.
  The file is UTF-16 and re-created on every EA start, so the harness
  buffers lines as they appear.

**Closing restore (SAFETY-DEMO-RESTORE-1).** Every run, passed or failed,
ends with one more start: the terminal logs back in to the `hedging`
account with the cleanup probe (3). That START line must report
`margin_mode=2` (hedging). The harness writes the restore lines to
`restore_ealog.txt` (kept out of the graded `ealog.txt`) and records in
`run.json`:
- `restore.login_sha256`: sha256 of `mql5bot-demo-login:` + the login.
  It identifies the account without writing it; a login is a short
  number, so this hash is NOT secret-grade.
- `restore.margin_mode`: re-derived from the restore log.
- `status`: `FAILED` when any step or the restore failed, else
  `COMPLETED`.

The builder uses only a COMPLETED run with a restore log that shows
hedging. The verifier re-reads both bound files (`run_evidence`,
`restore_evidence`) and re-checks them; the record's own claim is never
trusted.

**Persist and verify (DEMO-LOGIN-PERSIST-1).** The restore above ends in a
hard kill. gate_run40/44/46 then FAILed stage 3 with `sync_unmet="terminal
not connected"`: the gate launches the terminal WITHOUT credentials, and
the password was not kept. So every run then does two more steps:
1. **Persist.** One more hedging login, with `KeepPrivate=1` (the terminal
   keeps the password in its own encrypted store, never a repo file), that
   runs the gate's exporter with `ShutdownTerminal=1`. The terminal exits
   by itself; it is never killed.
2. **Verify.** A credential-less launch shaped exactly like the gate's
   stage-3 export (no `[Common]`). It must report `sync_unmet` other than
   `terminal not connected`, and `account_margin_mode` 2. Otherwise the
   run is `FAILED`.

The check writes to `MQL5\Files\Mql5Bot\demo_connect_check\`, never the
gate's `broker_exports`. That export holds the account login, so it is
deleted after reading. `run.json` keeps only `restore.connect_check`
(`sync_unmet`, `synced`, `margin_mode`).

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

## Inside the gate: `owner_gate.ps1 -DemoSafety` (DEMO-IN-GATE-1)

gate_run47 rejected all three gate_run46 demo runs. Their EX5 sha256 was
`4f03256d…`, while the gate's own stage-1 EX5 was `d9a5609c…`, at the SAME
HEAD: MetaEditor output differs per compile. A demo run is bound to the
binary it ran, and that rule stays. So the runs must come from the same
gate run as the stage-1 compile:

    tools\owner_gate.ps1 -DataFolder "<data folder>" -Golds gold2 -DemoSafety
        [-DemoAccounts <local accounts file>]

1. **Stage 0 preflight** (`owner_gate_decide.py demo-preflight`). It is a
   named FAIL, never a pass, when:
   - the accounts file lacks a complete `hedging` or `netting` entry
     (`[demo_accounts_missing]`);
   - the market is closed (`[market_closed]`): Friday 20:00 – Sunday
     22:15 UTC, and the daily rollover 20:45 – 22:15 UTC;
   - `-DemoEvidence` is also passed (`[demo_args_conflict]`): that
     evidence was bound to another compile.
2. **Stages 1–5** run as usual. Stage 1 compiles the EX5 the harness will
   run.
3. **Stage 7 `demo_safety`**:
   - re-checks the market (named FAIL);
   - runs the harness for restart, netting and hedging into
     `<this run's evidence>\demo_safety`, using `MQL5\Experts\Mql5Bot\Mql5Bot.ex5`
     (the file stage 1 compiled);
   - asks `demo-in-gate-outcome` whether every run's restore left the
     terminal on the hedging account, password kept, connected without
     credentials (DEMO-LOGIN-PERSIST-1).

   A run the host suspended FAILs first, as `[demo_host_suspended]`
   (HARNESS-SUSPEND-1), and no later demo test runs. Otherwise, if a
   restore did not hold, it FAILs loudly (`[demo_terminal_not_restored]`):
   every later gate launch would fail stage 3. A PASS here is not a safety
   grade.
4. **Stage 8** grades this run's demo folder with the unchanged builder
   and verifier, including the EX5 binding.

Without `-DemoSafety` nothing changes: there is no stage 7, and stage 8
reads `-DemoEvidence` or `evidence\demo_safety` as before.

Ran live in every `-DemoSafety` gate since gate_run52; stage 7 PASS in
gate_run55 and gate_run59.

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
4. **Compile.** Run the demo through the gate (`-DemoSafety`), so the
   runs use the EX5 that gate run compiled. A separate harness session is
   bound to another compile's EX5 and is rejected at stage 8 (gate_run47).
5. **Close terminals.** Close every running terminal of that data folder
   before a harness run (a second launch would hand the config to the
   running instance).
6. **Market hours.** Run while EURUSD trades on the demo server: Monday
   00:05 – Friday 23:50 server time. Avoid the daily rollover (~23:55 –
   00:05) and weekends; market orders are refused when the market is
   closed. Each run takes about 2–4 minutes.

## Formerly untested, now measured (gate_run59)

- **Compile.** The MQL5 edits compile clean in every stage 1.
- **Harness.** Ran on Windows / MT5 in stage 7 (process handling,
  `[StartUp]` keys, UTF-16 log reading, kill semantics).
- **Account mode.** MetaQuotes-Demo reports `ACCOUNT_MARGIN_MODE` 0
  (netting) and 2 (hedging) as expected.
- **Tester deal comment.** lost_response graded
  `LOST_RESPONSE_ADOPTED_NO_DUPLICATE`, so the adoption matched.

Still not run live: the SPEC-WAIT-2 WAITING_SYMBOL give-up path and the
HARNESS-SUSPEND-1 INTERRUPTED abort.
