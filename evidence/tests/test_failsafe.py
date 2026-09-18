"""Tests for the persisted fail-safe state machine and its file format.

Mirror of ``mql5/Include/Mql5Bot/StateStore.mqh`` +
``RiskManager.mqh`` transition rules (SPEC §3.5/§8.C, DoD #13/#14): a
restart NEVER resets the daily loss or forgets the drawdown peak; only an
explicit reset clears ENGINE_HALT.
"""

from datetime import date

from mql5bot.failsafe import (
    ENGINE_HALT,
    ENGINE_NO_NEW_TRADES,
    ENGINE_NORMAL,
    REASON_ADOPTED,
    REASON_DAILY_LOSS,
    REASON_MANUAL,
    REASON_MAX_DRAWDOWN,
    REASON_NONE,
    REASON_SL_GUARD,
    STATE_HEADER,
    TicketRecord,
    day_key,
    day_rollover_transition,
    decode_state_file,
    encode_row,
    explicit_reset,
    guard_pause_may_clear,
    pause_daily,
    state_reason_code,
    state_reason_string,
    trip_drawdown,
    trip_sl_guard,
)


# ---------------------------------------------------------------------------
# Reason code <-> name mapping (fixed, versioned)
# ---------------------------------------------------------------------------
def test_reason_mapping_roundtrip():
    for code in (REASON_NONE, REASON_MANUAL, REASON_MAX_DRAWDOWN, REASON_DAILY_LOSS,
                 REASON_SL_GUARD, REASON_ADOPTED):
        assert state_reason_code(state_reason_string(code)) == code


def test_reason_names_match_state_store():
    assert state_reason_string(REASON_NONE) == ""
    assert state_reason_string(REASON_MANUAL) == "manual"
    assert state_reason_string(REASON_MAX_DRAWDOWN) == "max_drawdown"
    assert state_reason_string(REASON_DAILY_LOSS) == "daily_loss"
    assert state_reason_string(REASON_SL_GUARD) == "sl_guard"
    assert state_reason_string(REASON_ADOPTED) == "adopted_unsafe"
    assert state_reason_string(99) == ""
    assert state_reason_code("bogus") == REASON_NONE


def test_day_key():
    assert day_key(date(2026, 9, 4)) == 20260904
    assert day_key(date(2025, 1, 1)) == 20250101
    assert day_key(date(2024, 12, 31)) == 20241231


# ---------------------------------------------------------------------------
# Transition rules
# ---------------------------------------------------------------------------
def test_daily_loss_pause_expires_at_rollover():
    assert day_rollover_transition(ENGINE_NO_NEW_TRADES, REASON_DAILY_LOSS) == (
        ENGINE_NORMAL,
        REASON_NONE,
    )


def test_kill_switch_never_clears_at_rollover():
    # drawdown halt and manual trip survive any number of day rollovers
    assert day_rollover_transition(ENGINE_HALT, REASON_MAX_DRAWDOWN) == (
        ENGINE_HALT,
        REASON_MAX_DRAWDOWN,
    )
    assert day_rollover_transition(ENGINE_HALT, REASON_MANUAL) == (ENGINE_HALT, REASON_MANUAL)
    # SL-guard halt is also permanent until explicit reset
    assert day_rollover_transition(ENGINE_HALT, REASON_SL_GUARD) == (ENGINE_HALT, REASON_SL_GUARD)


def test_rollover_keeps_other_pauses():
    assert day_rollover_transition(ENGINE_NO_NEW_TRADES, REASON_SL_GUARD) == (
        ENGINE_NO_NEW_TRADES,
        REASON_SL_GUARD,
    )
    assert day_rollover_transition(ENGINE_NORMAL, REASON_NONE) == (ENGINE_NORMAL, REASON_NONE)


def test_explicit_reset_is_the_only_exit_from_halt():
    assert explicit_reset() == (ENGINE_NORMAL, REASON_NONE)


def test_guard_pause_clears_only_when_all_secured():
    assert guard_pause_may_clear(ENGINE_NO_NEW_TRADES, REASON_SL_GUARD, True)
    assert not guard_pause_may_clear(ENGINE_NO_NEW_TRADES, REASON_SL_GUARD, False)
    # daily-loss pause clears at the boundary regardless (rollover rebases)
    assert guard_pause_may_clear(ENGINE_NO_NEW_TRADES, REASON_DAILY_LOSS, True)
    assert not guard_pause_may_clear(ENGINE_HALT, REASON_MAX_DRAWDOWN, True)
    assert not guard_pause_may_clear(ENGINE_NORMAL, REASON_NONE, True)


def test_trips_harden_or_pause():
    # drawdown and SL-guard escalation harden ANY state into ENGINE_HALT
    assert trip_drawdown() == (ENGINE_HALT, REASON_MAX_DRAWDOWN)
    assert trip_sl_guard() == (ENGINE_HALT, REASON_SL_GUARD)


def test_daily_breach_pauses_only_normal_engine():
    assert pause_daily(ENGINE_NORMAL) == (ENGINE_NO_NEW_TRADES, REASON_DAILY_LOSS)
    # a daily breach NEVER softens an existing pause or halt
    assert pause_daily(ENGINE_HALT) is None
    assert pause_daily(ENGINE_NO_NEW_TRADES) is None


# ---------------------------------------------------------------------------
# Cold-state row format (AEGIS_STATE v1)
# ---------------------------------------------------------------------------
def _rec(**over):
    base = {
        "ticket": 987654321012,
        "strategy_id": "ema_crossover",
        "symbol": "EURUSD",
        "ptype": 0,
        "entry": 1.10456789,
        "open_time": 1_765_000_000,
        "lots": 0.17,
        "partial_done": True,
        "be_done": False,
    }
    base.update(over)
    return TicketRecord(**base)


def test_row_roundtrip():
    rec = _rec()
    row = encode_row(rec)
    assert row.startswith("T|")
    # %I64u ticket, %.8f entry/lots, integer time, 0/1 flags
    assert row == (
        "T|987654321012|ema_crossover|EURUSD|0|1.10456789|1765000000|"
        "0.17000000|1|0"
    )
    records, quarantine = decode_state_file(STATE_HEADER + "\n" + row + "\n")
    assert not quarantine
    assert len(records) == 1
    got = records[0]
    assert got == rec


def test_float_precision_survives_roundtrip():
    rec = _rec(entry=1.104567895, lots=0.170000004)
    records, _ = decode_state_file(STATE_HEADER + "\n" + encode_row(rec) + "\n")
    # the MQL side writes %.8f; the reader must accept exactly that
    assert records[0].entry == round(rec.entry, 8)
    assert records[0].lots == round(rec.lots, 8)


def test_wrong_header_quarantines_everything():
    records, quarantine = decode_state_file("NOT THE HEADER\nT|1|a|b|0|1.0|0|0.01|0|0\n")
    assert quarantine
    assert records == []


def test_empty_file_quarantines():
    records, quarantine = decode_state_file("")
    assert quarantine
    assert records == []


def test_malformed_rows_are_skipped_not_applied():
    body = (
        STATE_HEADER + "\n"
        "T|1|ema_crossover|EURUSD|0|1.10000000|1765000000|0.01000000|0|0\n"  # good
        "T|2|ema_crossover|EURUSD|0|1.10000000|1765000000|0.01\n"  # 9 fields: skip
        "garbage line\n"
        "T|0|ema_crossover|EURUSD|0|1.10000000|1765000000|0.01000000|0|0\n"  # ticket 0
        "T|3||EURUSD|0|1.10000000|1765000000|0.01000000|0|0\n"  # empty strategy id
        "T|4|ema_crossover|EURUSD|0|notanumber|1765000000|0.01000000|0|0\n"  # bad entry
        "T|5|ema_crossover|EURUSD|0|1.10000000|1765000000|0.01000000|0|0\n"  # good
    )
    records, quarantine = decode_state_file(body)
    assert not quarantine
    assert [r.ticket for r in records] == [1, 5]


def test_row_with_sell_and_flags():
    rec = _rec(ticket=42, ptype=1, partial_done=False, be_done=True)
    records, _ = decode_state_file(STATE_HEADER + "\n" + encode_row(rec) + "\n")
    assert records[0].ptype == 1
    assert records[0].partial_done is False
    assert records[0].be_done is True
