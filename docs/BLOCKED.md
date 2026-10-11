# BLOCKED / WAITING — open items (updated 2026-10-11)

Nothing below is a code blocker that this session can fix. Each item waits
on an owner action or an input this session cannot produce.

## gold1 stage 4: the stale custom symbol EURUSD.G1 (owner action)

gate_run41, gate_run42 and gate_run43 (`gate-reports`, `-Golds gold1`;
gate_run43 is at master `4b8cad0`, after IMPORT-CHART-1) all end with
stage 4 FAIL. The importer REFUSED EURUSD.G1 at `symbol_state`:
- SYMBOL_SPREAD_FLOAT and SYMBOL_SPREAD of the surviving custom symbol
  differ from the manifest;
- they cannot be re-applied on a selected symbol (5306);
- `SymbolSelect(false)` failed (4305).

gate_run43's ini names `Symbol=EURUSD` / `Period=H1` (IMPORT-CHART-1), and
the refusal is unchanged. As docs/DECISIONS.md IMPORT-CHART-1 predicted,
the importer's own chart was not the cause.

**Why the session stops here.** The importer
(`mql5/Scripts/Mql5Bot/Mql5BotImportFixture.mq5`) is outside CLAUDE.md
exception 1, so it is not changed. Still unknown:
- what keeps EURUSD.G1 selected;
- what changed its spread properties (gold1's manifest `spread_points` is
  1.0 before and after S8-GOLD1-REGEN).

**Owner step (in the MT5 terminal, not in the repo).** Remove the stale
symbol so the importer takes its `created_fresh` path. On that path the
symbol is created unselected and its properties are set before it is ever
selected, so no deselect is needed.
1. Start MT5 with the gate's data folder. Close any chart on EURUSD.G1.
2. In the Strategy Tester, make sure the selected symbol is not EURUSD.G1.
   (Unverified hypothesis: the tester's last symbol may be what keeps it
   selected.)
3. Open View → Symbols (Ctrl+U). Under Custom, select EURUSD.G1:
   - "Hide" it, which removes it from Market Watch;
   - then "Delete Symbol".
   If either is refused, the terminal's own message names what holds the
   symbol; that message is the missing fact.
4. Close MT5 and re-run `tools\owner_gate.ps1 ... -Golds gold1`.

A fresh create is still proven by the same read-back and round-trip
verification as before. No acceptance rule changes. gold2 (EURUSD.G2) is
not affected: gate_run39 imported it VALID/MATCH.

If a later re-run refuses again on a survivor, the same drift is back. The
cause then needs an owner decision about the importer under a new
exception.

## Waiting on the owner's demo environment (task 2: restart, netting, hedging)

gate_run39 (`f29b7fa`, `-Golds gold2`) has 5/8 safety files VALID:
kill_switch, risk_veto, meta_reduce, sl_verify and lost_response. The
other three are MISSING because the demo harness was not run. The
SUMMARY says: "%USERPROFILE%\.mql5bot\demo_accounts.json does not exist;
MQL5BOT_DEMO_ACCOUNTS not set".

They need the owner steps in `docs/SAFETY_DEMO_PLAN.md` ("What the owner
must do by hand"):
- a NETTING demo account;
- the accounts file;
- one `tools/demo_safety_harness.py run --test <t>` per test, in market
  hours;
- then a gate run that picks up `evidence/demo_safety`.

No code change can produce that evidence.

## Waiting on the items above

- **Task 4** (FULL run, stages 9-10) needs both golds and all 8 safety
  files VALID.
- **Task 5** (docs/SHOWCASE.md) states the final verdict, so it follows
  task 4.

No MT5 result is invented. This file is deleted once nothing in it is
waiting.
