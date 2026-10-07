"""mql5bot.safety_legs - stage-8 safety sub-checks 8a-8d that run in the MT5
Strategy Tester (docs/SAFETY_8A_8D_PLAN.md).

Five of the eight safety artifacts the verifier requires can be produced by a
Strategy Tester leg on the gold2 fixture: kill_switch, risk_veto,
meta_reduce, sl_verify, and (TradeManager fault hook, owner authorization
2026-10-06) lost_response. Each runs the gold leg's own inputs PLUS the inputs
below (test-only EA inputs are default OFF; owner authorization
2026-10-06), and its evidence is graded HERE, from that leg's own tester-log
window only, against the gold m1_ohlc leg of the same run as the baseline
("the strategy would have entered here").

The other three (restart, netting, hedging) need a demo terminal or an
account of a specific margin mode: mql5bot.demo_harness runs them
(docs/SAFETY_DEMO_PLAN.md) and their graders live here too.

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
    "lost_response": {
        # TradeManager.mqh fault hook (owner authorization 2026-10-06)
        "inputs": {"InpTestLostResponses": 1, "InpTestUnsentTimeouts": 1},
        "expected_result": "LOST_RESPONSE_ADOPTED_NO_DUPLICATE",
        "action": ("InpTestUnsentTimeouts=1 + InpTestLostResponses=1: the "
                   "first entry send is suppressed (TIMEOUT, nothing sent) "
                   "and must be queued and retried once; the next FILLED "
                   "entry's answer is dropped (TIMEOUT) and must be found in "
                   "deal history (open_verified) with no re-send"),
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

# not tester legs: the demo harness (mql5bot.demo_harness,
# docs/SAFETY_DEMO_PLAN.md) produces their evidence on demo accounts
DEMO_ONLY: dict[str, str] = {
    "restart": (
        "needs a real EA/terminal restart while a position is open; the "
        "Strategy Tester cannot restart an EA -- demo harness"),
    "netting": (
        "needs a NETTING account: the tester takes the account's margin "
        "mode, and gate_run35's account is hedging -- demo harness"),
    "hedging": (
        "needs independent positions with their own magics on a HEDGING "
        "account under live execution -- demo harness"),
}
DEMO_EXPECTED = {
    "restart": "RESTART_RECOVERED_NO_DUPLICATE",
    "netting": "NET_ONE_POSITION_PER_SYMBOL",
    "hedging": "INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC",
}
DEMO_ACTIONS = {
    "restart": ("demo harness: EA with InpTestDemoProbe=1 opens one probe "
                "position; the terminal process is KILLED while it is open "
                "and relaunched; the EA must reload its state with the same "
                "magic and never hold a second own position"),
    "netting": ("demo harness on a NETTING account, InpTestDemoProbe=2: "
                "buy vmin, then sell 2*vmin on the same symbol; the account "
                "must hold ONE net position (sell vmin)"),
    "hedging": ("demo harness on a HEDGING account, InpTestDemoProbe=2: buy "
                "vmin, sell 2*vmin, then a buy with ANOTHER magic; the two "
                "own positions stay independent tickets and the EA's "
                "registry holds only its own magic"),
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


# --- 8c lost_response (tester; TradeManager fault hook) -----------------
_MQL_RE = re.compile(r"(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+"
                     r"\[mql5bot\] (.*)$")
_SUPP_RE = re.compile(r"TEST 8c lost_response: SUPPRESSED send of (\S+) ")
_DROP_RE = re.compile(r"TEST 8c lost_response: DROPPED response of (\S+) ")
_EXEC_RE = re.compile(r"EXEC\|([^|]+)\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|"
                      r"(.*)$")


def _mql_lines(text: str) -> list[tuple[str, str, str]]:
    out = []
    for ln in _lines(text):
        m = _MQL_RE.search(ln)
        if m:
            out.append((m.group(1), m.group(2), ln))
    return out


def grade_lost_response(window: str, baseline: str, symbol: str) -> dict:
    del baseline
    mql = _mql_lines(window)
    reqs = entry_requests(window, symbol)
    execs: dict[str, list[tuple[str, str]]] = {}
    for t, msg, _ in mql:
        m = _EXEC_RE.search(msg)
        if m:
            execs.setdefault(m.group(2).strip(), []).append((t, m.group(1)))
    supp = [(t, _SUPP_RE.search(msg).group(1), ln) for t, msg, ln in mql
            if _SUPP_RE.search(msg)]
    drop = [(t, _DROP_RE.search(msg).group(1), ln) for t, msg, ln in mql
            if _DROP_RE.search(msg)]
    if not supp and not drop:
        return _doc("lost_response", "NOT_TRIGGERED", "fault hook armed",
                    "no SUPPRESSED / DROPPED line in the leg window", [], {})
    bad: list[str] = []
    lines = [ln for _, _, ln in supp + drop]
    retried = adopted = 0
    for t, comment, _ in supp:
        ex = execs.get(comment, [])
        queued = [x for x in ex if x[1] == "open_queued"]
        retry = [x for x in ex if x[1] in ("open_retry",
                                           "open_retry_verified")]
        if not queued or not retry or any(x[1] == "open_retry_giveup"
                                          for x in ex):
            bad.append(f"RETRY_NOT_DONE:{comment}")
            continue
        sent = [r for r in reqs if t <= r["time"] <= retry[0][0]]
        if len(sent) != 1:
            bad.append(f"DUPLICATE_SEND:{comment}:{len(sent)}")
            continue
        retried += 1
    for t, comment, _ in drop:
        ex = execs.get(comment, [])
        if not any(x[1] == "open_verified" for x in ex) or \
                any(x[1] == "open_queued" for x in ex):
            bad.append(f"NOT_ADOPTED:{comment}")
            continue
        sent = [r for r in reqs if r["time"] == t]
        if len(sent) != 1:
            bad.append(f"DUPLICATE_SEND:{comment}:{len(sent)}")
            continue
        adopted += 1
    facts = {"suppressed": len(supp), "retried_once": retried,
             "dropped": len(drop), "adopted_from_history": adopted,
             "failures": bad}
    if bad:
        observed = bad[0]
    elif not retried or not adopted:
        observed = "INCONCLUSIVE_ONE_FAULT_KIND_MISSING"
    else:
        observed = "LOST_RESPONSE_ADOPTED_NO_DUPLICATE"
    return _doc("lost_response", observed,
                f"{len(supp)} send(s) suppressed, {len(drop)} answer(s) "
                "dropped by the fault hook",
                (f"{retried} suppressed send(s) queued and retried once; "
                 f"{adopted} dropped answer(s) found in deal history with no "
                 f"re-send; failures: {bad or 'none'}"), lines, facts)


# --- demo harness graders (EA log of a demo run, no baseline) -----------
_START_RE = re.compile(r"TEST demo: START probe=(\d+) magic=(-?\d+) "
                       r"own_positions=(\d+) registry=(\d+) engine=(-?\d+) "
                       r"margin_mode=(-?\d+)")
_PROBE_RE = re.compile(r"TEST demo: PROBE position opened")
_SNAP_RE = re.compile(r"TEST demo: SNAPSHOT (\S+)(.*?) margin_mode=(-?\d+) "
                      r"own_positions=(\d+) registry=(\d+) positions=\[(.*)\]")
MARGIN_NETTING = 0   # ACCOUNT_MARGIN_MODE_RETAIL_NETTING
MARGIN_HEDGING = 2   # ACCOUNT_MARGIN_MODE_RETAIL_HEDGING


def _demo_doc(name: str, observed: str, initial: str, resulting: str,
              lines: list[str], facts: dict) -> dict:
    return {"schema": SCHEMA, "test": name, "action": DEMO_ACTIONS[name],
            "inputs": {"InpTestDemoProbe": 1 if name == "restart" else 2},
            "initial_state": initial, "resulting_state": resulting,
            "observed_result": observed,
            "expected_result": DEMO_EXPECTED[name],
            "passed": observed == DEMO_EXPECTED[name],
            "quoted_lines": lines, "facts": facts}


def _positions(text: str) -> list[dict]:
    out = []
    for item in [x for x in text.split(",") if x]:
        t, side, vol, magic = item.split(":")
        out.append({"ticket": t, "side": side, "volume": float(vol),
                    "magic": int(magic)})
    return out


def _snapshots(log: str) -> list[dict]:
    out = []
    for t, m, ln in ea_lines(log, _SNAP_RE):
        out.append({"time": t, "label": m.group(1), "detail": m.group(2),
                    "margin_mode": int(m.group(3)),
                    "own": int(m.group(4)), "registry": int(m.group(5)),
                    "positions": _positions(m.group(6)), "line": ln})
    return out


def grade_restart(log: str, baseline: str = "", symbol: str = "") -> dict:
    del baseline, symbol
    starts = ea_lines(log, _START_RE)
    probe = ea_lines(log, _PROBE_RE)
    snaps = _snapshots(log)
    lines = [ln for _, _, ln in starts] + [ln for _, _, ln in probe]
    facts = {"starts": len(starts), "probe_opened": len(probe)}
    if not probe:
        return _demo_doc("restart", "PROBE_NOT_OPENED", "flat", "no probe "
                         "position", lines, facts)
    after = [s for s in starts if s[0] >= probe[0][0]]
    if not after:
        return _demo_doc("restart", "NO_RESTART", "probe position open",
                         "no START after the probe opened", lines, facts)
    _, first, _ = starts[0]
    t1, again, _ = after[0]
    later = [s for s in snaps if s["time"] >= t1 and
             s["label"] == "heartbeat"]
    dup = [s for s in later if s["own"] > 1]
    facts.update({"magic_before": first.group(2), "magic_after":
                  again.group(2), "own_at_restart": int(again.group(3)),
                  "engine_at_restart": int(again.group(5)),
                  "heartbeats_after_restart": len(later),
                  "max_own_after_restart": max([s["own"] for s in later],
                                               default=None)})
    lines += [s["line"] for s in later[:3]] + [s["line"] for s in dup[:3]]
    if again.group(2) != first.group(2):
        observed = "MAGIC_CHANGED"
    elif int(again.group(3)) != 1:
        observed = "POSITION_LOST_AT_RESTART"
    elif int(again.group(5)) != 0:
        observed = "ENGINE_NOT_NORMAL_AFTER_RESTART"
    elif not later:
        observed = "INCONCLUSIVE_NO_HEARTBEAT_AFTER_RESTART"
    elif dup:
        observed = f"DUPLICATE_EXPOSURE:{len(dup)}"
    elif later[0]["registry"] != 1:
        observed = "REGISTRY_NOT_RECOVERED"
    else:
        observed = "RESTART_RECOVERED_NO_DUPLICATE"
    return _demo_doc("restart", observed,
                     f"probe position open (magic {first.group(2)}); "
                     "terminal process killed",
                     (f"relaunched: magic {again.group(2)}, own positions "
                      f"{again.group(3)}, engine {again.group(5)}; "
                      f"{len(later)} heartbeat(s), max own "
                      f"{facts['max_own_after_restart']}"), lines, facts)


def _account_grade(name: str, log: str, mode: int) -> dict:
    snaps = {s["label"]: s for s in _snapshots(log)}
    lines = [s["line"] for s in snaps.values()]
    a, b = snaps.get("after_A"), snaps.get("after_B")
    if a is None or b is None:
        return _demo_doc(name, "NOT_RUN", "no probe snapshots",
                         "after_A / after_B missing", lines, {})
    facts = {"margin_mode": b["margin_mode"], "after_A": a["positions"],
             "after_B": b["positions"]}
    m = re.search(r"buy (\d+(?:\.\d+)?)", a["detail"])
    vmin = float(m.group(1)) if m else None
    magic = None
    starts = ea_lines(log, _START_RE)
    if starts:
        magic = int(starts[-1][1].group(2))
    own_b = [p for p in b["positions"] if p["magic"] == magic]
    if b["margin_mode"] != mode:
        return _demo_doc(name, f"WRONG_ACCOUNT_MODE:{b['margin_mode']}",
                         f"account margin_mode {b['margin_mode']} (required "
                         f"{mode})", f"after_B positions {b['positions']}",
                         lines, facts)
    if name == "netting":
        ok = (len(a["positions"]) == 1 and len(own_b) == 1
              and len(b["positions"]) == 1 and own_b[0]["side"] == "sell"
              and vmin is not None and abs(own_b[0]["volume"] - vmin) < 1e-9)
        observed = "NET_ONE_POSITION_PER_SYMBOL" if ok else \
            f"NOT_NETTED:{len(b['positions'])}"
        return _demo_doc(name, observed, f"netting account, buy {vmin}",
                         f"after sell {2 * vmin if vmin else '?'}: "
                         f"{b['positions']}", lines, facts)
    f = snaps.get("after_F")
    if f is None:
        return _demo_doc(name, "NOT_RUN", "hedging probe started",
                         "after_F missing", lines, facts)
    facts["after_F"] = f["positions"]
    foreign = [p for p in f["positions"] if magic is not None
               and p["magic"] == magic + 1]
    sides = sorted(p["side"] for p in own_b)
    ok = (len(own_b) == 2 and sides == ["buy", "sell"]
          and len({p["ticket"] for p in own_b}) == 2 and foreign
          and f["own"] == 2 and f["registry"] == 2)
    observed = "INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC" if ok else \
        (f"NOT_INDEPENDENT:{len(own_b)}" if len(own_b) != 2 else
         f"NOT_ISOLATED:own={f['own']},registry={f['registry']}")
    return _demo_doc(name, observed, f"hedging account, magic {magic}",
                     (f"own {own_b}; foreign {foreign}; registry "
                      f"{f['registry']}"), lines, facts)


def grade_netting(log: str, baseline: str = "", symbol: str = "") -> dict:
    del baseline, symbol
    return _account_grade("netting", log, MARGIN_NETTING)


def grade_hedging(log: str, baseline: str = "", symbol: str = "") -> dict:
    del baseline, symbol
    return _account_grade("hedging", log, MARGIN_HEDGING)


GRADERS = {"kill_switch": grade_kill_switch, "risk_veto": grade_risk_veto,
           "meta_reduce": grade_meta_reduce, "sl_verify": grade_sl_verify,
           "lost_response": grade_lost_response,
           "restart": grade_restart, "netting": grade_netting,
           "hedging": grade_hedging}


def check_restore(log: str) -> dict:
    """SAFETY-DEMO-RESTORE-1: the EA log of the harness's closing step,
    which logs the terminal back in to the "hedging" account with the
    cleanup probe. The restore holds ONLY when the LAST cleanup START line
    (probe=3) reports margin_mode == MARGIN_HEDGING. Anything else (no
    such line, another mode) is a failed restore."""
    starts = [m for _, m, _ in ea_lines(log, _START_RE)
              if int(m.group(1)) == 3]
    if not starts:
        return {"ok": False, "margin_mode": None,
                "reason": "no cleanup START line (probe=3) in the restore log"}
    mode = int(starts[-1].group(6))
    if mode != MARGIN_HEDGING:
        return {"ok": False, "margin_mode": mode,
                "reason": (f"restore account margin_mode {mode} is not "
                           f"hedging ({MARGIN_HEDGING})")}
    return {"ok": True, "margin_mode": mode, "reason": ""}


def grade(name: str, window: str, baseline: str, symbol: str) -> dict:
    return GRADERS[name](window, baseline, symbol)


def leg_tag(name: str) -> str:
    """The evidence tag of a safety leg (tester_<tag>_window.txt)."""
    return f"safety_{name}"
