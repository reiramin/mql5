"""mql5bot.safety_legs - stage-8 safety sub-checks 8a-8d that run in the MT5
Strategy Tester (docs/SAFETY_8A_8D_PLAN.md).

Four of the eight safety artifacts the verifier requires can be produced by a
Strategy Tester leg on the gold2 fixture: kill_switch, risk_veto,
meta_reduce, sl_verify. Each runs the gold leg's own inputs PLUS the inputs
below (test-only EA inputs are default OFF; owner authorization
2026-10-06), and its evidence is graded HERE, from that leg's own tester-log
window only, against the gold m1_ohlc leg of the same run as the baseline
("the strategy would have entered here").

The other four (lost_response, restart, netting, hedging) need a demo
terminal or an account of a specific margin mode; nothing here produces
them, and the package keeps them MISSING.

Grading never invents: every observation is a quoted window line. A test
whose trigger never fired, or whose baseline shows nothing to block, is
INCONCLUSIVE -- recorded, never a pass. The verifier accepts a safety file
only when ``observed_result == expected_result``
(owner_gate.verify_safety).

Built, unit-tested, never run live.
"""

from __future__ import annotations

import re

SCHEMA = "mql5bot.safety_evidence/1"
TESTER_MODEL = 1  # 1 minute OHLC, the gold m1_ohlc leg's model
BASELINE_MODEL = "m1_ohlc"

# test -> extra EA inputs on top of the gold leg's own inputs
TESTER_SAFETY_LEGS: dict[str, dict] = {
    "kill_switch": {
        "inputs": {"InpTestKillSwitchAfterEntries": 1},
        "expected_result": "ZERO_NEW_ORDERS_WHILE_LATCHED",
        "action": ("InpTestKillSwitchAfterEntries=1: the EA calls "
                   "TripKillSwitch(REASON_MANUAL) right after its first "
                   "entry, then the fixture keeps feeding"),
    },
    "risk_veto": {
        # a production input (no test hook): the daily-loss halt
        "inputs": {"InpDailyLossPct": 0.5},
        "expected_result": "ENTRIES_VETOED_FOR_THE_DAY",
        "action": ("InpDailyLossPct=0.5: the Risk Engine's daily-loss "
                   "limit; after the halt line no entry may be sent for "
                   "the rest of that server day"),
    },
    "meta_reduce": {
        # base weight 0.5 (no allocation file staged) + size logging
        "inputs": {"InpBaseGateWeight": 0.5, "InpTestSafetyLog": True},
        "expected_result": "ALL_SIZES_LE_RISK_APPROVED",
        "action": ("InpBaseGateWeight=0.5 (Meta scale, no allocation "
                   "file) + InpTestSafetyLog=true: every entry logs the "
                   "Risk-approved and the final lots"),
    },
    "sl_verify": {
        "inputs": {"InpTestStripSlEntries": 3},
        "expected_result": "SL_STRIPPED_AND_RESTORED",
        "action": ("InpTestStripSlEntries=3: the EA removes the SL of its "
                   "first 3 secured positions (PositionModify sl=0) and "
                   "reports from POSITION_SL when the SL protection "
                   "(ProtectManagedPositions -> SlGuard) put one back"),
    },
}

DEMO_ONLY: dict[str, str] = {
    "lost_response": (
        "needs an ambiguous order-send result (TRADE_RETCODE_TIMEOUT / a "
        "lost response). The tester always answers; injecting one would "
        "need a change in Include/Mql5Bot/TradeManager.mqh, outside the "
        "authorized Experts/Mql5Bot/ scope"),
    "restart": (
        "needs a real EA restart mid-run (terminal or EA reload) during a "
        "pending execution, an active retry, an open position and an "
        "allocation poll; the Strategy Tester cannot restart an EA"),
    "netting": (
        "needs a NETTING account: the tester takes the account's margin "
        "mode, and gate_run35's account is hedging"),
    "hedging": (
        "needs two independent positions with their own magics on a "
        "HEDGING account; the tester runs one EA, and this EA holds one "
        "position at a time"),
}

# 'YYYY.MM.DD HH:MM:SS' simulated time + MT5's own entry request line
_REQUEST_RE = re.compile(
    r"(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+(?:market|instant)\s+"
    r"(buy|sell)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+at\s+\S+\s+sl:")
# the EA logger's own prefix: '[YYYY.MM.DD HH:MM:SS] [LEVEL] message'
_EA_LINE_RE = re.compile(r"\[(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\]\s*"
                         r"\[(\w+)\]\s*(.*)$")
_LATCH_RE = re.compile(r"TEST 8a kill switch: LATCHED after entry (\d+) "
                       r"\(state=(-?\d+) reason=(-?\d+) "
                       r"AllowsNewTrades=(true|false)\)")
_META_RE = re.compile(r"TEST 8a meta: risk_approved=(-?[\d.]+) "
                      r"scaled=(-?[\d.]+) final=(-?[\d.]+) "
                      r"base_weight=(-?[\d.]+)")
_STRIP_RE = re.compile(r"TEST 8b sl: STRIPPED #(\d+) sl (-?[\d.]+) -> "
                       r"(-?[\d.]+)")
_RESTORE_RE = re.compile(r"TEST 8b sl: RESTORED #(\d+) sl=(-?[\d.]+)")
_CLOSED_RE = re.compile(r"TEST 8b sl: #(\d+) closed before an SL was "
                        r"restored")
_DAILY_RE = re.compile(r"DAILY LOSS LIMIT HIT")


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def entry_requests(text: str, symbol: str) -> list[dict]:
    """MT5's own entry request lines (they carry sl:), in window order."""
    out = []
    for ln in _lines(text):
        m = _REQUEST_RE.search(ln)
        if m and m.group(4) == symbol:
            out.append({"time": m.group(1), "side": m.group(2),
                        "volume": float(m.group(3)), "line": ln})
    return out


def ea_lines(text: str, pattern: re.Pattern) -> list[tuple[str, re.Match,
                                                           str]]:
    """(simulated time, match, line) for EA log lines matching ``pattern``."""
    out = []
    for ln in _lines(text):
        m = _EA_LINE_RE.search(ln)
        if not m:
            continue
        hit = pattern.search(m.group(3))
        if hit:
            out.append((m.group(1), hit, ln))
    return out


def _doc(name: str, observed: str, initial: str, resulting: str,
         lines: list[str], facts: dict) -> dict:
    spec = TESTER_SAFETY_LEGS[name]
    return {"schema": SCHEMA, "test": name,
            "action": spec["action"],
            "inputs": dict(spec["inputs"]),
            "initial_state": initial, "resulting_state": resulting,
            "observed_result": observed,
            "expected_result": spec["expected_result"],
            "passed": observed == spec["expected_result"],
            "quoted_lines": lines, "facts": facts}


def grade_kill_switch(window: str, baseline: str, symbol: str) -> dict:
    latch = ea_lines(window, _LATCH_RE)
    if not latch:
        return _doc("kill_switch", "NOT_LATCHED", "ENGINE_NORMAL",
                    "no latch line in the leg window", [], {})
    t, m, line = latch[0]
    after = [r for r in entry_requests(window, symbol) if r["time"] > t]
    base_after = [r for r in entry_requests(baseline, symbol)
                  if r["time"] > t]
    facts = {"latched_at": t, "latched_after_entry": int(m.group(1)),
             "allows_new_trades": m.group(4),
             "entries_after_latch": len(after),
             "baseline_entries_after_latch": len(base_after)}
    if m.group(4) != "false":
        observed = "LATCH_DID_NOT_BLOCK"
    elif after:
        observed = f"NEW_ORDERS_AFTER_LATCH:{len(after)}"
    elif not base_after:
        observed = "INCONCLUSIVE_NO_BASELINE_ENTRY_AFTER_LATCH"
    else:
        observed = "ZERO_NEW_ORDERS_WHILE_LATCHED"
    return _doc("kill_switch", observed,
                f"ENGINE_NORMAL; {m.group(1)} entry made",
                (f"ENGINE state={m.group(2)} reason={m.group(3)} "
                 f"AllowsNewTrades={m.group(4)} from {t}; {len(after)} "
                 f"entry request(s) after it (baseline: {len(base_after)})"),
                [line] + [r["line"] for r in after[:5]]
                + [r["line"] for r in base_after[:3]], facts)


def grade_risk_veto(window: str, baseline: str, symbol: str) -> dict:
    hits = ea_lines(window, _DAILY_RE)
    if not hits:
        return _doc("risk_veto", "NOT_TRIGGERED", "ENGINE_NORMAL",
                    "no daily-loss halt line in the leg window", [], {})
    t, _, line = hits[0]
    day = t[:10]
    after = [r for r in entry_requests(window, symbol)
             if t < r["time"] and r["time"][:10] == day]
    base_after = [r for r in entry_requests(baseline, symbol)
                  if t < r["time"] and r["time"][:10] == day]
    facts = {"halted_at": t, "day": day, "entries_after_halt_same_day":
             len(after), "baseline_entries_after_halt_same_day":
             len(base_after)}
    if after:
        observed = f"ENTRY_AFTER_VETO:{len(after)}"
    elif not base_after:
        observed = "INCONCLUSIVE_NO_BASELINE_ENTRY_AFTER_HALT"
    else:
        observed = "ENTRIES_VETOED_FOR_THE_DAY"
    return _doc("risk_veto", observed, "ENGINE_NORMAL",
                (f"ENGINE_NO_NEW_TRADES (REASON_DAILY_LOSS) from {t}; "
                 f"{len(after)} entry request(s) later that day (baseline: "
                 f"{len(base_after)})"),
                [line] + [r["line"] for r in after[:5]]
                + [r["line"] for r in base_after[:3]], facts)


def grade_meta_reduce(window: str, baseline: str, symbol: str) -> dict:
    del baseline  # the leg's own approved-vs-final lines are the evidence
    metas = ea_lines(window, _META_RE)
    reqs = entry_requests(window, symbol)
    if not metas:
        return _doc("meta_reduce", "NO_SIZE_LINES", "base weight 0.5",
                    "no 'TEST 8a meta' line in the leg window", [], {})
    over, reduced, mismatch = [], 0, []
    for t, m, line in metas:
        approved, final = float(m.group(1)), float(m.group(3))
        if final > approved + 1e-9:
            over.append(line)
        if final < approved - 1e-9:
            reduced += 1
        req = next((r for r in reqs if r["time"] == t), None)
        if req is None or abs(req["volume"] - final) > 1e-9:
            mismatch.append(line)
    facts = {"entries": len(metas), "reduced": reduced,
             "final_above_approved": len(over),
             "final_not_the_sent_volume": len(mismatch),
             "base_weight": float(metas[0][1].group(4))}
    if over:
        observed = f"SIZE_ABOVE_RISK_APPROVED:{len(over)}"
    elif mismatch:
        observed = f"SENT_VOLUME_NOT_THE_FINAL_SIZE:{len(mismatch)}"
    elif reduced == 0:
        observed = "INCONCLUSIVE_NOTHING_REDUCED"
    else:
        observed = "ALL_SIZES_LE_RISK_APPROVED"
    return _doc("meta_reduce", observed,
                f"base gate weight {facts['base_weight']} (no allocation file)",
                (f"{len(metas)} entries: {reduced} reduced below the Risk "
                 f"approval, {len(over)} above it, {len(mismatch)} sent at "
                 "another volume"),
                [ln for _, _, ln in metas[:5]] + over[:5] + mismatch[:5],
                facts)


def grade_sl_verify(window: str, baseline: str, symbol: str) -> dict:
    del baseline, symbol
    strips = ea_lines(window, _STRIP_RE)
    restores = {m.group(1): (t, ln) for t, m, ln in ea_lines(window,
                                                              _RESTORE_RE)}
    closed = {m.group(1) for _, m, _ in ea_lines(window, _CLOSED_RE)}
    if not strips:
        return _doc("sl_verify", "NOT_STRIPPED", "secured positions",
                    "no 'TEST 8b sl: STRIPPED' line in the leg window", [],
                    {})
    bad_strip, restored, unresolved, lines = [], [], [], []
    for t, m, ln in strips:
        ticket = m.group(1)
        lines.append(ln)
        if float(m.group(3)) != 0.0:
            bad_strip.append(ticket)  # the strip did not take effect
            continue
        if ticket in restores and restores[ticket][0] >= t:
            restored.append(ticket)
            lines.append(restores[ticket][1])
        elif ticket not in closed:
            unresolved.append(ticket)
    facts = {"stripped": len(strips), "restored": len(restored),
             "strip_not_applied": bad_strip, "never_restored": unresolved,
             "closed_before_restore": sorted(closed)}
    if unresolved:
        observed = f"SL_NOT_RESTORED:{len(unresolved)}"
    elif not restored:
        observed = "INCONCLUSIVE_NOTHING_RESTORED"
    else:
        observed = "SL_STRIPPED_AND_RESTORED"
    return _doc("sl_verify", observed,
                f"{len(strips)} secured position(s) had their SL removed",
                (f"{len(restored)} SL(s) put back by the EA's protection, "
                 f"{len(unresolved)} never, {len(closed)} closed first, "
                 f"{len(bad_strip)} strip(s) not applied"),
                lines, facts)


GRADERS = {"kill_switch": grade_kill_switch, "risk_veto": grade_risk_veto,
           "meta_reduce": grade_meta_reduce, "sl_verify": grade_sl_verify}


def grade(name: str, window: str, baseline: str, symbol: str) -> dict:
    return GRADERS[name](window, baseline, symbol)


def leg_tag(name: str) -> str:
    """The evidence tag of a safety leg (tester_<tag>_window.txt)."""
    return f"safety_{name}"
