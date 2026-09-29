"""mql5bot.tester_log_grader - grade a stage-5 tester leg from its OWN log window.

MT5 build 6184 writes no ``[Tester]`` Report ``.htm`` even for a run the tester
log records as ``successfully finished`` (docs/DECISIONS.md 2026-09-20, DEFECT
3). Those legs sit at ``BLOCKED_OWNER_ENVIRONMENT``. The tester agent log and
the tester log still carry what a grader needs; this module reads them.

Two rules make it safe:

* SCOPING (R6). The input is the leg's window capture (the lines appended to
  the tester logs while THIS leg ran). Symbol-bearing lines are attributed
  with ``gate_selfcheck._leg_scoped_lines`` — the same function the BLOCKED
  classifier uses — and every other symbol-bearing field here (model, deals)
  counts only when it names this leg's symbol. One leg's lines can never
  grade another.
* NO DEFAULTS THAT LOOK LIKE DATA. Every parsed field is ``None`` when the
  window does not state it. A missing field is recorded as missing, never
  filled in.

``PASS_FROM_LOG`` is its OWN evidence class. It says: MT5 ran this leg to
completion on this symbol with bars > 0, at a stated history quality, in the
requested model. It does NOT say what a report says — there are no report
metrics (profit factor, drawdown, trade statistics), and the deal list is only
what the EA itself printed. It is never relabelled as the report-based PASS.

Line formats and where they come from:

* MEASURED from gate_run17 / the delivery run (docs/DECISIONS.md): the
  ``quality of analyzed history is N%`` line, the ``<SYM>,<TF>: N ticks, M
  bars generated`` line, the ``successfully finished`` line, and ``math
  calculations test mode means no history and no symbol info for <SYM>``.
* FROM THIS REPO'S EA SOURCE (mql5/Experts/Mql5Bot/Mql5Bot.mq5
  ``OnTradeTransaction`` through ``Logger.Write``): ``[<time>] [INFO] DEAL
  #<ticket> <symbol> vol=<v> price=<p> pnl=<pnl>``.
* MT5 TESTER JOURNAL FORMAT, NOT YET SEEN IN A CAPTURED ARTIFACT HERE:
  ``final balance <N> <CCY>``, ``deal #<n> <buy|sell> <vol> <sym> at <price>``
  and the ``..., close #<n> ...`` order-request line, plus a model statement
  that names one of the canonical ``MT5_MODEL_LABELS``. If the owner's
  window does not contain them, the matching field stays ``None`` and — for
  the model — the leg does not pass.
"""

from __future__ import annotations

import hashlib
import re

from mql5bot import gate_selfcheck as gs
from mql5bot import mt5tester as mt

STAGE5_OUTCOME_PASS_FROM_LOG = "PASS_FROM_LOG"
EVIDENCE_SOURCE = "tester agent log"
LOG_TRADE_LIST_SCHEMA = "mql5bot.log_trade_list/1"

# MEASURED: `Tester\tquality of analyzed history is 100%`
_HISTORY_QUALITY_RE = re.compile(
    r"quality of analyzed history is\s+(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
# MT5 journal format (not yet captured here): `final balance 10000.00 USD`
_FINAL_BALANCE_RE = re.compile(
    r"final balance\s+(-?\d+(?:\.\d+)?)(?:\s+([A-Z]{3}))?", re.IGNORECASE)
# MEASURED: `Core 1\tmath calculations test mode means no history and no
# symbol info for EURUSD.G1` — MT5 stating it ran config-file Model=3.
_MATH_MODE_RE = re.compile(r"math(?:ematical)? calculations", re.IGNORECASE)
# EA SOURCE (Mql5Bot.mq5 OnTradeTransaction via Logger.Write):
#   `[2024.01.02 10:00:00] [INFO] DEAL #12 EURUSD.G2 vol=0.10 price=1.10010 pnl=0.00`
_EA_DEAL_RE = re.compile(
    r"\[(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}(?::\d{2})?)\]\s*\[INFO\]\s*"
    r"DEAL #(\d+)\s+(\S+)\s+vol=(-?\d+(?:\.\d+)?)\s+"
    r"price=(-?\d+(?:\.\d+)?)\s+pnl=(-?\d+(?:\.\d+)?)")
# MT5 journal format (not yet captured here):
#   `deal #12 buy 0.10 EURUSD.G2 at 1.10010 done (based on order #12)`
_MT5_DEAL_RE = re.compile(
    r"\bdeal #(\d+)\s+(buy|sell)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+at\s+",
    re.IGNORECASE)
# MT5 journal format (not yet captured here): an order request line; a close
# names the position it closes, e.g. `market sell 0.10 EURUSD.G2, close #12 ...`
_MT5_REQUEST_RE = re.compile(r"\b(?:market|instant)\s+(buy|sell)\b",
                             re.IGNORECASE)
_MT5_CLOSE_RE = re.compile(r",\s*close #\d+", re.IGNORECASE)


def _num(text: str | None) -> float | None:
    return None if text is None else float(text)


def _names_symbol(line: str, symbol: str | None) -> bool:
    return bool(symbol) and symbol in line


def _actual_model(lines: list[str], symbol: str | None) -> dict:
    """The model MT5 SAYS it ran, from lines naming this leg's symbol.

    ``model`` is None when no such line exists or when the window states two
    different models for the symbol (the conflict is recorded, never resolved
    by picking one).
    """
    found: list[tuple[int, str]] = []
    for line in lines:
        if not _names_symbol(line, symbol):
            continue
        if _MATH_MODE_RE.search(line):
            found.append((3, line))
            continue
        low = line.lower()
        if any(lbl.lower() in low for lbl in mt.MT5_MODEL_LABELS.values()):
            mi = mt.model_int_from_text(line)
            if mi is not None:
                found.append((mi, line))
    models = {m for m, _ in found}
    if len(models) != 1:
        return {"model": None,
                "label": None,
                "lines": [ln for _, ln in found],
                "conflict": len(models) > 1}
    model = found[0][0]
    return {"model": model, "label": mt.MT5_MODEL_LABELS.get(model),
            "lines": [found[0][1]], "conflict": False}


def _deals(lines: list[str], symbol: str | None) -> list[dict]:
    """Deals the EA printed for THIS symbol, in window order.

    ``side`` and ``entry`` come only from MT5's own ``deal #N`` line for the
    same ticket (and the order-request line just before it); when those lines
    are absent they stay None — the EA's DEAL line does not state them and
    they are never inferred from pnl.
    """
    mt5_side: dict[str, tuple[str, str | None, str]] = {}
    last_request: str | None = None
    for line in lines:
        if _MT5_REQUEST_RE.search(line) and _names_symbol(line, symbol):
            last_request = line
            continue
        m = _MT5_DEAL_RE.search(line)
        if m and m.group(4) == symbol:
            entry = None
            if last_request is not None:
                entry = "close" if _MT5_CLOSE_RE.search(last_request) else "open"
            mt5_side.setdefault(m.group(1), (m.group(2).lower(), entry, line))
            last_request = None

    out: list[dict] = []
    for line in lines:
        m = _EA_DEAL_RE.search(line)
        if not m or m.group(3) != symbol:
            continue
        ticket = m.group(2)
        side, entry, mt5_line = mt5_side.get(ticket, (None, None, None))
        out.append({
            "ticket": int(ticket),
            "time": m.group(1),
            "symbol": m.group(3),
            "side": side,
            "entry": entry,
            "volume": float(m.group(4)),
            "price": float(m.group(5)),
            "pnl": float(m.group(6)),
            "lines": [line] + ([mt5_line] if mt5_line else []),
        })
    return out


def parse_leg_window(window_text: str, symbol: str | None) -> dict:
    """Parse ONE leg's window capture into a structured result.

    Every field is None when the window does not state it. ``lines`` maps each
    field to the exact window lines it was read from.
    """
    lines = [raw.strip() for raw in (window_text or "").splitlines()
             if raw.strip()]
    scoped = gs._leg_scoped_lines(window_text, symbol)

    finished_ok = True if scoped["finished"] else None

    bars = ticks = None
    bars_lines: list[str] = []
    for line, n_bars in scoped["bars"]:
        m = gs._BARS_GENERATED_RE.search(line)
        n_ticks = int(m.group(1)) if m else None
        bars_lines.append(line)
        # a zero-bars line for this symbol wins: it is the insufficient-
        # history signal and must never be hidden behind a larger count
        if bars is None or n_bars == 0 or (bars != 0 and n_bars > bars):
            bars, ticks = n_bars, n_ticks

    hq = hq_line = None
    for line in lines:
        m = _HISTORY_QUALITY_RE.search(line)
        if m:
            hq, hq_line = float(m.group(1)), line
            break

    balance = currency = balance_line = None
    for line in lines:
        m = _FINAL_BALANCE_RE.search(line)
        if m:
            balance, currency, balance_line = (
                float(m.group(1)), m.group(2), line)
    model = _actual_model(lines, symbol)

    return {
        "symbol": symbol,
        "finished_ok": finished_ok,
        "bars": bars,
        "ticks": ticks,
        "history_quality": hq,
        "final_balance": balance,
        "final_balance_currency": currency,
        "actual_model": model["model"],
        "actual_model_label": model["label"],
        "model_conflict": model["conflict"],
        "deals": _deals(lines, symbol),
        "lines": {
            "finished": scoped["finished"][:1],
            "bars": bars_lines,
            "warmup": scoped["warmup"],
            "history_quality": [hq_line] if hq_line else [],
            "final_balance": [balance_line] if balance_line else [],
            "model": model["lines"],
        },
    }


def grade_leg_from_log(*, window_text: str, symbol: str | None,
                       requested_model: int, leg: str | None = None) -> dict:
    """Grade a leg that has NO report from its own window.

    ``PASS_FROM_LOG`` only when ALL of: "successfully finished" in the window,
    bars > 0 for this symbol, history quality present, and the model MT5 says
    it ran equals ``requested_model``. It is reachable only from a window the
    R6 classifier would call BLOCKED (so a zero-bars window is never graded
    up). Otherwise the leg keeps that classifier's verdict unchanged.
    """
    base = gs.classify_tester_leg_outcome(
        report_present=False, window_text=window_text, symbol=symbol, leg=leg)
    parsed = parse_leg_window(window_text, symbol)
    requested_label = mt.MT5_MODEL_LABELS.get(requested_model)

    checks = {
        "successfully_finished": parsed["finished_ok"] is True,
        "bars_positive": parsed["bars"] is not None and parsed["bars"] > 0,
        "history_quality_present": parsed["history_quality"] is not None,
        "model_matches_requested": (parsed["actual_model"] is not None
                                    and parsed["actual_model"]
                                    == requested_model),
    }
    failed = [name for name, ok in checks.items() if not ok]
    common = {"leg": leg, "symbol": symbol, "source": EVIDENCE_SOURCE,
              "report_present": False, "requested_model": requested_model,
              "requested_model_label": requested_label,
              "base_outcome": base["outcome"], "checks": checks,
              "failed_checks": failed, "parsed": parsed}

    if base["outcome"] == gs.STAGE5_OUTCOME_BLOCKED_ENV and not failed:
        lp = parsed["lines"]
        evidence = (lp["finished"] + lp["bars"][:1] + lp["history_quality"]
                    + lp["model"])
        return {**common,
                "outcome": STAGE5_OUTCOME_PASS_FROM_LOG, "ok": True,
                "evidence_class": STAGE5_OUTCOME_PASS_FROM_LOG,
                "blocked": False, "evidence_lines": evidence,
                "reason": (
                    "PASS_FROM_LOG (evidence class distinct from the "
                    "report-based PASS; source: tester agent log) — this "
                    "leg's own window shows successfully finished, "
                    f"{parsed['bars']} bars for {symbol}, history quality "
                    f"{parsed['history_quality']:g}%, and MT5 ran the "
                    f"requested model {requested_label!r}. No report "
                    "metrics exist for this leg. Tester log (this leg "
                    "only): " + " | ".join(evidence))}

    why = ", ".join(failed) if failed else (
        f"the window classifies {base['outcome']}, not a proven clean run")
    if "model_matches_requested" in failed:
        stated = parsed["actual_model_label"] or (
            "two different models" if parsed["model_conflict"]
            else "no model line naming this symbol")
        why += f" (requested {requested_label!r}; MT5 stated {stated})"
    return {**common,
            "outcome": base["outcome"], "ok": False,
            "evidence_class": base["outcome"],
            "blocked": base["blocked"],
            "evidence_lines": base["evidence_lines"],
            "reason": base["reason"] + f" Not PASS_FROM_LOG: {why}."}


def log_trade_list(grade: dict, window_bytes: bytes) -> dict | None:
    """The deal list a PASS_FROM_LOG leg hands to stage 8 in place of a report.

    Shaped like the parsed-report sidecar (``settings``/``fields``/``metrics``)
    so it can occupy the leg's ``parsed/<gold>_<model>.json`` slot, and flagged
    ``from_log: true`` / ``report_present: false`` so no consumer can mistake
    it for a report. ``metrics`` is empty: nothing a report would state is
    invented. Returns None for any leg that is not PASS_FROM_LOG.
    """
    if grade.get("outcome") != STAGE5_OUTCOME_PASS_FROM_LOG:
        return None
    p = grade["parsed"]
    return {
        "schema": LOG_TRADE_LIST_SCHEMA,
        "from_log": True,
        "report_present": False,
        "evidence_class": STAGE5_OUTCOME_PASS_FROM_LOG,
        "source": EVIDENCE_SOURCE,
        "leg": grade.get("leg"),
        "window_sha256": hashlib.sha256(window_bytes).hexdigest(),
        "tables": 0,
        "settings": {"symbol": p["symbol"],
                     "model": p["actual_model_label"],
                     "history quality": f"{p['history_quality']:g}%"},
        "fields": {},
        "metrics": {},
        "bars": p["bars"],
        "ticks": p["ticks"],
        "final_balance": p["final_balance"],
        "final_balance_currency": p["final_balance_currency"],
        "deals": p["deals"],
        "note": ("Trade list read from the EA's own tester-log lines because "
                 "MT5 wrote no report for this leg. Not a report: no report "
                 "metrics exist, and stage 8's raw-report binding still "
                 "requires the .htm."),
    }


__all__ = [
    "EVIDENCE_SOURCE",
    "LOG_TRADE_LIST_SCHEMA",
    "STAGE5_OUTCOME_PASS_FROM_LOG",
    "grade_leg_from_log",
    "log_trade_list",
    "parse_leg_window",
]
