"""S3-SYNC-1 (owner authorization, Sal, 2026-10-05): scoped mql5/ exception
for mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5 ONLY.

gate_run32/33 wrote denomination_probe {ok:false, "BUY OrderCalcProfit
returned non-negative loss", last_error:0} from a headless [StartUp] launch
right after terminal start. The exporter now waits (bounded) for sync
before any probe, retries the witness only on that symptom, and records
attempts / waited_seconds and the observed bid/ask/tick values.

The MQL5 source cannot be compiled here (no metaeditor64.exe); these are
source-level pins only -- the strict-compile 0/0 proof is the owner's
stage-1 gate.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = (REPO / "mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5"
       ).read_text(encoding="utf-8")


def _define(name: str) -> str:
    m = re.search(rf"^#define {name}\s+(\S+)", SRC, re.MULTILINE)
    assert m, name
    return m.group(1)


def _main_body() -> str:
    return SRC[SRC.index("void Main()"):SRC.index("void OnStart()")]


def test_bounds_are_the_authorized_ones():
    assert _define("EXPORT_SYNC_WAIT_MS") == "60000"
    assert _define("EXPORT_SYNC_STEP_MS") == "500"
    assert _define("DENOM_RETRY_MAX") == "10"
    assert _define("DENOM_RETRY_STEP_MS") == "1000"
    assert '#define DENOM_NONNEG_LOSS   "BUY OrderCalcProfit returned ' \
           'non-negative loss"' in SRC


def test_readiness_checks_every_required_condition():
    ready = SRC[SRC.index("string SymbolReadiness"):SRC.index("string WaitForSymbolReady")]
    for cond in ("TerminalInfoInteger(TERMINAL_CONNECTED)",
                 "SymbolIsSynchronized(sym)", "SymbolInfoTick(sym, tick)",
                 "tick.bid > 0.0 && tick.ask > 0.0",
                 "SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE) > 0.0"):
        assert cond in ready, cond
    wait = SRC[SRC.index("string WaitForSymbolReady"):SRC.index("void Main()")]
    assert "SymbolSelect(sym, true)" in wait
    assert "Sleep(EXPORT_SYNC_STEP_MS)" in wait
    assert "(ulong)EXPORT_SYNC_WAIT_MS" in wait  # bounded


def test_wait_happens_before_any_probe():
    body = _main_body()
    wait = body.index("WaitForSymbolReady(sym)")
    assert wait < body.index("OrderCalcMargin(")
    assert wait < body.index("OrderCalcProfit(")


def test_witness_retry_only_on_non_negative_loss():
    body = _main_body()
    assert "for(int attempt = 1; attempt <= DENOM_RETRY_MAX; attempt++)" in body
    assert "Sleep(DENOM_RETRY_STEP_MS)" in body
    assert "if(denomReason != DENOM_NONNEG_LOSS || IsStopped())" in body
    assert 'NOT_SYNCED_AFTER_%ds", EXPORT_SYNC_WAIT_MS / 1000' in body


def test_probe_json_records_attempts_waited_and_never_nulls_observed_values():
    for field in ("attempts", "waited_seconds", "tick_value_at_probe",
                  "synced", "sync_unmet"):
        assert f'JsonQuote("{field}")' in SRC, field
    for field in ("bid", "ask", "tick_value_loss_at_probe",
                  "tick_value_profit_at_probe", "tick_value_at_probe"):
        line = next(ln for ln in SRC.splitlines()
                    if f'JsonQuote("{field}") + ": "' in ln
                    and ln.startswith('   j += "      "'))
        assert "null" not in line, line


def test_other_probe_fields_unchanged_still_null_on_failure():
    for field in ("tick_size_at_probe", "probe_ticks", "lot_size", "move",
                  "buy_loss_profit", "sell_gain_profit"):
        line = next(ln for ln in SRC.splitlines()
                    if f'JsonQuote("{field}") + ": "' in ln)
        assert '(denomOk ? ' in line and '"null"' in line, line


def test_still_an_exporter_no_trading_call():
    for call in ("OrderSend", "PositionOpen", "OpenMarket", "OpenPending",
                 "ClosePosition"):
        assert call not in SRC, call
