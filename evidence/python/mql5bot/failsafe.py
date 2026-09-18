"""mql5bot.failsafe — persisted fail-safe state machine + state-file format
(SPEC §3.5/§8.C, DoD #13/#14).

Release-A seed model for the MQL5 port in
``mql5/Include/Mql5Bot/StateStore.mqh`` and ``RiskManager.mqh``:

* engine states (``ENUM_ENGINE_STATE``) and trip reasons
  (``ENUM_STATE_REASON``), their integer codes and string names;
* the transition rules that must survive restarts:
  ``ENGINE_HALT`` only clears via an explicit reset; the daily-loss pause
  (``ENGINE_NO_NEW_TRADES``) expires at the server day rollover; the SL-guard
  pause expires at a rollover only when every managed position is secured;
* the strict cold-state row format (``AEGIS_STATE v1``, one ``T|`` row per
  ticket) with the same strict reader semantics as the MQL port: a wrong
  header means quarantine (never apply partially), malformed rows are
  skipped, and rows without ticket/strategy/symbol are rejected.

Nothing here touches terminal or account state; the day key helper mirrors
``CRiskManager::CurrentDayKey`` (server date -> ``YYYYMMDD`` int).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# --- engine states (match ENUM_ENGINE_STATE in Config.mqh) -----------------
ENGINE_NORMAL: int = 0  # trading allowed (within limits)
ENGINE_NO_NEW_TRADES: int = 1  # manage open positions only
ENGINE_HALT: int = 2  # close everything and stay down

# --- trip reasons (match ENUM_STATE_REASON in StateStore.mqh) --------------
REASON_NONE: int = 0
REASON_MANUAL: int = 1
REASON_MAX_DRAWDOWN: int = 2
REASON_DAILY_LOSS: int = 3
REASON_SL_GUARD: int = 4
REASON_ADOPTED: int = 5

_REASON_NAMES: dict[int, str] = {
    REASON_NONE: "",
    REASON_MANUAL: "manual",
    REASON_MAX_DRAWDOWN: "max_drawdown",
    REASON_DAILY_LOSS: "daily_loss",
    REASON_SL_GUARD: "sl_guard",
    REASON_ADOPTED: "adopted_unsafe",
}


def state_reason_string(code: int) -> str:
    """Mirror ``StateReasonToString``; unknown codes yield ''."""
    return _REASON_NAMES.get(code, "")


def state_reason_code(name: str) -> int:
    """Mirror ``StateReasonToCode``; unknown names yield REASON_NONE."""
    for code, n in _REASON_NAMES.items():
        if n == name:
            return code
    return REASON_NONE


def day_key(d: date) -> int:
    """Mirror ``CRiskManager::CurrentDayKey``: YYYY*10000 + MM*100 + DD."""
    return d.year * 10000 + d.month * 100 + d.day


def explicit_reset() -> tuple[int, int]:
    """The only way out of ENGINE_HALT: an explicit, acknowledged reset."""
    return ENGINE_NORMAL, REASON_NONE


def day_rollover_transition(state: int, reason: int) -> tuple[int, int]:
    """State change at a server day rollover (mirror RiskManager.OnNewDay).

    The daily-loss pause expires at the reset boundary; the kill switch and
    the SL-guard pause never clear here (guard pause has its own gate,
    :func:`guard_pause_may_clear`).
    """
    if state == ENGINE_NO_NEW_TRADES and reason == REASON_DAILY_LOSS:
        return ENGINE_NORMAL, REASON_NONE
    return state, reason


def guard_pause_may_clear(state: int, reason: int, all_secured: bool) -> bool:
    """EA rule: a NO_NEW_TRADES pause clears at a rollover boundary once
    every managed position carries a valid SL and the SL guard is idle."""
    if state != ENGINE_NO_NEW_TRADES:
        return False
    if reason not in (REASON_DAILY_LOSS, REASON_SL_GUARD):
        return False
    return all_secured


def trip_drawdown() -> tuple[int, int]:
    """CheckLimits drawdown path: hardens ANY state into ENGINE_HALT."""
    return ENGINE_HALT, REASON_MAX_DRAWDOWN


def trip_sl_guard() -> tuple[int, int]:
    """SL-guard escalation path (EA TripKillSwitch): ENGINE_HALT."""
    return ENGINE_HALT, REASON_SL_GUARD


def pause_daily(state: int) -> tuple[int, int] | None:
    """EA daily-breach policy: pauses a NORMAL engine; returns None for a
    paused or halted engine so a daily breach can NEVER soften an active
    guard pause or the kill switch (mirror of the EA OnTimer gate)."""
    if state == ENGINE_NORMAL:
        return ENGINE_NO_NEW_TRADES, REASON_DAILY_LOSS
    return None


# --- cold-state row format ("AEGIS_STATE v1", strict reader) ---------------

STATE_HEADER = "AEGIS_STATE v1"
_ROW_FIELDS = 10  # T|<ticket>|<strategyId>|<symbol>|<type>|<entry>|<openTime>|<lots>|<partial>|<be>


@dataclass(frozen=True)
class TicketRecord:
    """One managed-position record (mirror STicketRec in StateStore.mqh)."""

    ticket: int
    strategy_id: str
    symbol: str
    ptype: int  # POSITION_TYPE_BUY=0 / SELL=1
    entry: float
    open_time: int  # seconds since epoch
    lots: float
    partial_done: bool  # persisted so partial-once survives restarts
    be_done: bool


def encode_row(rec: TicketRecord) -> str:
    """Mirror the MQL FileWrite row: %.8f floats, %I64u ticket/time, 0/1 bools."""
    return (
        f"T|{rec.ticket}|{rec.strategy_id}|{rec.symbol}|{rec.ptype}"
        f"|{rec.entry:.8f}|{int(rec.open_time)}|{rec.lots:.8f}"
        f"|{1 if rec.partial_done else 0}|{1 if rec.be_done else 0}"
    )


def decode_state_file(text: str) -> tuple[list[TicketRecord], bool]:
    """Strict reader mirroring ``CStateStore::Load``.

    Returns ``(records, quarantine)``: ``quarantine=True`` when the header is
    missing/wrong (content must be set aside and never applied partially);
    malformed rows are skipped with the rest applied.
    """
    lines = text.splitlines()
    if not lines or lines[0] != STATE_HEADER:
        return [], True
    records: list[TicketRecord] = []
    for row in lines[1:]:
        if not row.startswith("T|"):
            continue
        parts = row.split("|")
        if len(parts) != _ROW_FIELDS:
            continue  # malformed row: skip
        try:
            ticket = int(parts[1])
            entry = float(parts[5])
            open_time = int(parts[6])
            lots = float(parts[7])
        except ValueError:
            continue
        sid, symbol = parts[2], parts[3]
        if ticket == 0 or sid == "" or symbol == "":
            continue
        records.append(
            TicketRecord(
                ticket=ticket,
                strategy_id=sid,
                symbol=symbol,
                ptype=int(parts[4]),
                entry=entry,
                open_time=open_time,
                lots=lots,
                partial_done=int(parts[8]) == 1,
                be_done=int(parts[9]) == 1,
            )
        )
    return records, False
