"""mql5bot.owner_gate — owner MT5 evidence intake + offline verification.

FINAL REALITY GATE: the evidence CONSUMER.  The owner returns one
directory of raw artifacts; this module answers mechanically, without
human interpretation:

  1.  is the evidence complete?         (scan_package)
  2.  is the evidence fresh?            (verify_compile timestamp rules)
  3.  does it bind the frozen source?   (anchor identity, never the
                                         branch name)
  4.  does the EX5 match the compile?   (hash + timestamp binding)
  5.  is the SymbolSpec the right broker/symbol/terminal?
  6.  was the intended tester model actually used? (requested vs
      report-reported vs journal — CLI selection alone never proves it)
  7.  was real-tick coverage actually established? (FULL/PARTIAL/
      UNKNOWN; selection is not proof; UNKNOWN never promotes)
  8.  did Gold #1 match? 9. did Gold #2 match?   (field-by-field)
  10. where is the FIRST divergence?    (first_divergence)
  11. what class of mismatch?           (deterministic taxonomy map)
  12. can certification continue? 13. what remains blocked?  (verdict)

Fail-closed by construction: missing, stale, wrong, partial or
simulated evidence can NEVER become a positive verdict.  This module
VERIFIES owner evidence; it never PRODUCES MT5 evidence — a green
verifier self-test is not an MT5 claim.

Gold #2 stays the 56-trade semantic fixture: the verifier never asks
for 100 trades on the gold lane (that threshold belongs to the
empirical lane only).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# artifact validity states (§7 — never collapsed into one boolean)
# ---------------------------------------------------------------------------
MISSING = "MISSING"
PRESENT_UNVERIFIED = "PRESENT_UNVERIFIED"
VALID = "VALID"
INVALID = "INVALID"
STALE = "STALE"
MISMATCHED = "MISMATCHED"
PENDING_OWNER = "PENDING_OWNER"
ARTIFACT_STATES = (MISSING, PRESENT_UNVERIFIED, VALID, INVALID, STALE,
                   MISMATCHED, PENDING_OWNER)

# ---------------------------------------------------------------------------
# explainable verdicts (§26 — canonical vocabulary only, no synonyms)
# ---------------------------------------------------------------------------
NOT_VERIFIED_MISSING_MT5_EVIDENCE = "NOT_VERIFIED_MISSING_MT5_EVIDENCE"
NOT_VERIFIED_RECONCILIATION_MISSING = "NOT_VERIFIED_RECONCILIATION_MISSING"
NOT_VERIFIED_ARTIFACT_MISMATCH = "NOT_VERIFIED_ARTIFACT_MISMATCH"
NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN = \
    "NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN"
MT5_VALIDATED = "MT5_VALIDATED"
# A SCOPED (partial) verification that would otherwise be MT5_VALIDATED: the
# scoped golds' evidence verified, the excluded golds not examined at all. It
# is deliberately NOT a positive verdict and certifies nothing.
MT5_VALIDATED_PARTIAL_SCOPE = "MT5_VALIDATED_PARTIAL_SCOPE"
# S8-CEILING-1 (owner decision 2026-10-06): every condition of MT5_VALIDATED
# holds, but the real-tick coverage is a VALID REAL_TICK_COVERAGE_NONE record
# (bar-only fixtures): validated on the bar models only, no real-tick claim.
# MT5_VALIDATED itself stays FULL-coverage only. A scoped run maps it to the
# _PARTIAL_SCOPE form, which is not positive.
MT5_VALIDATED_BAR_MODELS = "MT5_VALIDATED_BAR_MODELS"
MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE = \
    "MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE"
BAR_MODELS_REASON = "no real-tick claim; m1_ohlc + every_tick only"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
EMPIRICAL_VALIDATED = "EMPIRICAL_VALIDATED"
DEMO_VALIDATED = "DEMO_VALIDATED"
VERIFIED = "VERIFIED"
POSITIVE_VERDICTS = (MT5_VALIDATED, MT5_VALIDATED_BAR_MODELS,
                     EMPIRICAL_VALIDATED, DEMO_VALIDATED, VERIFIED)

# ---------------------------------------------------------------------------
# deterministic owner-evidence directory layout (§6)
# ---------------------------------------------------------------------------
GOLDS = ("gold1", "gold2")
MODELS = ("m1_ohlc", "every_tick", "real_ticks")
SAFETY_TESTS = ("kill_switch", "risk_veto", "meta_reduce", "sl_verify",
                "lost_response", "restart")

LAYOUT: dict[str, str] = {
    "compile_log": "compile/compile.log",
    "compile_metadata": "compile/compile_metadata.json",
    "ex5": "compile/Mql5Bot.ex5",
    "symbolspec": "symbolspec/symbolspec.json",
    "real_tick_coverage": "real_tick_coverage.json",
    "reconciliation_gold1": "reconciliation/gold1.json",
    "reconciliation_gold2": "reconciliation/gold2.json",
    "netting": "safety/netting.json",
    "hedging": "safety/hedging.json",
    "environment": "environment.json",
    "archive_manifest": "archive_manifest.json",
}
for _g in GOLDS:
    for _m in MODELS:
        LAYOUT[f"raw_{_g}_{_m}"] = f"{_g}/{_m}.htm"
        LAYOUT[f"parsed_{_g}_{_m}"] = f"parsed/{_g}_{_m}.json"
for _t in SAFETY_TESTS:
    LAYOUT[f"safety_{_t}"] = f"safety/{_t}.json"

# STAGE 5 R7: a leg for which MT5 wrote NO report but whose own tester-log
# window graded PASS_FROM_LOG hands stage 8 a log trade list instead
# (tools/owner_gate_decide.py stage5-leg --trades-out). It stands in for that
# leg's raw + parsed report ONLY when no raw report exists, and every place
# that accepts it records the trade source as the log — it is never read as
# a report. The comparison (first_divergence / _field_divergent) is unchanged.
LOG_SOURCED = "LOG_SOURCED"
TRADE_SOURCE_REPORT = "report"
TRADE_SOURCE_LOG = "tester agent log"
LOG_TRADE_LIST_SCHEMA = "mql5bot.log_trade_list/1"


def log_trades_rel(gold: str, model: str) -> str:
    return f"log_trades/{gold}_{model}.json"


def log_window_rel(gold: str, model: str) -> str:
    """The package copy of a log-sourced leg's window capture: the bytes its
    log trade list's ``window_sha256`` names (S8-SLTP-1 reads the entry
    request lines' sl/tp from it)."""
    return f"log_windows/{gold}_{model}.txt"


# Event pairing states the gate builder writes (stage8_package) and the
# verifier counts (S8-COUNT-1). Not divergence classifications.
PAIRED_BY_TIME = "PAIRED_BY_TIME"
MISSING_IN_MT5 = "MISSING_IN_MT5"
EXTRA_IN_MT5 = "EXTRA_IN_MT5"
# S8-TS-1: the python fill time has minute resolution (M1 bars), so a paired
# event's timestamp is compared at fill-BAR level -- and only together with
# an exact entry_price match on the same event.
TS_BASIS_FILL_BAR = "fill_bar_minute (S8-TS-1)"
# S8-TICKPATH-1: a tick-generating leg compares volume against the python
# path only up to its first exit that differs from the m1_ohlc leg; after
# it, against the frozen sizing rule on MT5's own pre-entry equity.
TICK_PATH_DIVERGENCE = "TICK_PATH_DIVERGENCE"
TICK_PATH_REFERENCE = "m1_ohlc"
TICK_PATH_MODELS = ("every_tick", "real_ticks")
VOLUME_BASIS_MT5_EQUITY = "mt5_equity_sizing (S8-TICKPATH-1)"


def deal_time_iso(stamp) -> str | None:
    """``2024.01.03 08:32:01`` -> ``2024-01-03T08:32:01`` (seconds kept;
    ``:00`` when the stamp has none). None when unparsable."""
    m = re.match(r"^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$",
                 str(stamp or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, sec = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{sec or '00'}"


def log_entry_deals(deals: list[dict]) -> list[dict]:
    """The ENTRY deals of a log trade list: those whose own MT5 request line
    is not a close (``entry == "open"``, set by tester_log_grader from the
    request line before the ``deal #N`` line). An exit triggered by SL/TP has
    no request line (entry None) and is never counted as an entry."""
    return [d for d in deals
            if isinstance(d, dict) and d.get("entry") == "open"]


def _deal_key(deal: dict) -> tuple:
    return (deal.get("time"), deal.get("side"), deal.get("volume"),
            deal.get("price"), deal.get("pnl"))


def tick_path_divergence(ref_deals: list[dict], tick_deals: list[dict]
                         ) -> tuple[dict | None, str]:
    """S8-TICKPATH-1: the first EXIT deal where a tick-generating leg's
    deal list differs from the m1_ohlc leg's (time or price), walking both
    lists deal for deal. Returns (record, note).

    The record is an OBSERVATION (classification TICK_PATH_DIVERGENCE), not
    a python<->MT5 field: from that exit on, the two legs book different pnl
    and their equity paths differ. None when the lists never differ, or
    when the first difference is NOT an exit time/price difference (an
    entry, side or volume difference first): the tick-path rule then does
    not apply and the leg stays fully strict -- the note says why."""
    for k, (ref, tick) in enumerate(zip(ref_deals, tick_deals)):
        if _deal_key(ref) == _deal_key(tick):
            continue
        exit_deal = ref.get("entry") != "open" and tick.get("entry") != "open"
        same_order = (ref.get("ticket") == tick.get("ticket")
                      and ref.get("side") == tick.get("side")
                      and ref.get("volume") == tick.get("volume"))
        moved = (ref.get("time") != tick.get("time")
                 or ref.get("price") != tick.get("price"))
        if not (exit_deal and same_order and moved):
            return None, (f"first deal difference at index {k} (ticket "
                          f"{tick.get('ticket')}) is not an exit time/price "
                          "difference: no tick-path divergence, the leg "
                          "stays fully strict")

        def side_of(d: dict) -> dict:
            return {"ticket": d.get("ticket"), "time": d.get("time"),
                    "price": d.get("price"), "pnl": d.get("pnl"),
                    "side": d.get("side"), "volume": d.get("volume"),
                    "lines": list(d.get("lines") or [])}
        return ({"classification": TICK_PATH_DIVERGENCE, "observed": True,
                 "reference_model": TICK_PATH_REFERENCE,
                 "deal_index": k, "ticket": tick.get("ticket"),
                 "reference_deal": side_of(ref), "tick_deal": side_of(tick),
                 "note": ("first exit whose time/price differs from the "
                          "m1_ohlc leg; every deal before it is identical "
                          "(time, side, volume, price, pnl). Observed and "
                          "named, never a python<->MT5 divergence by "
                          "itself.")},
                f"first differing exit at deal index {k}")
    if len(ref_deals) != len(tick_deals):
        return None, ("deal lists agree on their common prefix but differ "
                      f"in length ({len(ref_deals)} vs {len(tick_deals)}): "
                      "no exit divergence, the leg stays fully strict")
    return None, "deal lists identical: no tick-path divergence"


def frozen_rule_lots(spec, risk: dict, equity: float, stop_distance: float,
                     weight: float = 1.0) -> float:
    """The frozen sizing rule: size_position (risk percent of ``equity`` over
    ``stop_distance``, broker_spec volume step / min / max) then the meta
    floor at ``weight`` (floor to volume_step; below volume_min -> 0)."""
    import math

    from mql5bot.sizer import size_position

    step, vmin = float(spec.volume_step), float(spec.volume_min)
    approved = round(float(size_position(
        spec, mode=risk["mode"], equity=equity, stop_distance=stop_distance,
        value=float(risk["risk_percent"])).lots), 6)
    final = math.floor(approved * weight / step + 1e-9) * step
    return round(final, 6) if vmin <= final <= approved + 1e-12 else 0.0


def sizing_reference(repo: Path | str, frozen_gold: dict) -> dict | None:
    """S8-TICKPATH-1 verifier input: broker_spec + risk_config from the gold
    manifest and the frozen stop_distance per expected_execution row --
    ONLY when both files' bytes equal the frozen record's pins
    (manifest_sha256, expected_execution_sha256). None otherwise
    (fail-closed: MT5-equity volumes are then not verifiable)."""
    fixture = frozen_gold.get("fixture")
    if not fixture:
        return None
    base = (Path(repo) / fixture).parent
    man, exp = base / "manifest.json", base / "expected_execution.json"
    if not (man.is_file() and exp.is_file()) or \
            sha256_file(man) != frozen_gold.get("manifest_sha256") or \
            sha256_file(exp) != frozen_gold.get("expected_execution_sha256"):
        return None
    m, e = _load_json(man), _load_json(exp)
    try:
        return {"broker_spec": dict(m["broker_spec"]),
                "risk_config": dict(m["risk_config"]),
                "stop_distance_by_row": {
                    i: float(r["stop_distance"])
                    for i, r in enumerate(e["entries"])
                    if r.get("stop_distance")}}
    except (KeyError, TypeError, ValueError):
        return None


_ENTRY_REQUEST_RE = re.compile(
    r"\b(?:market|instant)\s+(buy|sell)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+at\s+"
    r"(-?\d+(?:\.\d+)?)\s+sl:\s*(-?\d+(?:\.\d+)?)\s+tp:\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE)
_ANY_REQUEST_RE = re.compile(r"\b(?:market|instant)\s+(buy|sell)\b",
                             re.IGNORECASE)
_DEAL_LINE_RE = re.compile(
    r"\bdeal #(\d+)\s+(buy|sell)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+at\s+",
    re.IGNORECASE)


def entry_request_levels(window_text: str, symbol: str) -> dict[int, dict]:
    """S8-SLTP-1: ticket -> {sl, tp, request_line, deal_line} from MT5's own
    ``instant buy|sell VOL SYMBOL at PRICE sl: X tp: Y`` request line, for
    the ``deal #N`` line that directly follows it (same side, volume and
    symbol). A deal with no such request (a close, an SL/TP trigger) has no
    entry here; nothing is inferred."""
    out: dict[int, dict] = {}
    last: str | None = None
    for raw in (window_text or "").splitlines():
        line = raw.strip()
        if _ANY_REQUEST_RE.search(line) and symbol in line:
            last = line
            continue
        m = _DEAL_LINE_RE.search(line)
        if not m or m.group(4) != symbol:
            continue
        req = _ENTRY_REQUEST_RE.search(last) if last else None
        request_line, last = last, None
        if req and req.group(3) == symbol and \
                req.group(1).lower() == m.group(2).lower() and \
                float(req.group(2)) == float(m.group(3)):
            out.setdefault(int(m.group(1)), {
                "sl": float(req.group(5)), "tp": float(req.group(6)),
                "request_line": request_line, "deal_line": line})
    return out


# OWNER DECISION 2026-10-03 (DECISIONS.md, option 2): a bar-only gold's
# real_ticks leg is NOT_APPLICABLE_BAR_ONLY_FIXTURE -- never launched, so it
# has no raw or parsed report. The gate copies its own stage_5.json record into
# the package at GATE_STAGE5_REL; a leg that record names NOT_APPLICABLE is
# state NOT_APPLICABLE here: never MISSING, never present, never a pass. Only
# the real_ticks model can be NOT_APPLICABLE. Its real-tick coverage is
# REAL_TICK_COVERAGE_NONE, which can never yield MT5_VALIDATED.
NOT_APPLICABLE = "NOT_APPLICABLE"
STAGE5_NOT_APPLICABLE = "NOT_APPLICABLE_BAR_ONLY_FIXTURE"
GATE_STAGE5_REL = "gate/stage_5.json"
TRADE_SOURCE_NOT_APPLICABLE = "not applicable (leg not launched)"
_NA_LEG_RE = re.compile(r"\b(gold\d)_(real_ticks): "
                        + STAGE5_NOT_APPLICABLE + r":")


def not_applicable_legs(root: Path | str) -> set[tuple[str, str]]:
    """(gold, model) legs the gate's own stage-5 record names
    NOT_APPLICABLE_BAR_ONLY_FIXTURE. The record must be the stage-5
    tester_legs record; anything else names no leg (fail-closed: the slots
    then stay MISSING)."""
    doc = _load_json(Path(root) / GATE_STAGE5_REL)
    if not isinstance(doc, dict) or doc.get("stage") != 5 \
            or doc.get("name") != "tester_legs":
        return set()
    return {(m.group(1), m.group(2))
            for m in _NA_LEG_RE.finditer(str(doc.get("reason") or ""))
            if m.group(1) in GOLDS}


def log_sourced_legs(root: Path | str) -> set[tuple[str, str]]:
    """(gold, model) legs whose trade source is a log trade list: the list
    exists AND no raw report exists (a report, when present, always wins)."""
    root = Path(root)
    return {(g, m) for g in GOLDS for m in MODELS
            if (root / log_trades_rel(g, m)).is_file()
            and not (root / LAYOUT[f"raw_{g}_{m}"]).exists()}

# ---------------------------------------------------------------------------
# mismatch taxonomy (§15 — the closed canonical set, no CLOSE_ENOUGH)
# ---------------------------------------------------------------------------
SIGNAL_MISMATCH = "SIGNAL_MISMATCH"
INDICATOR_MISMATCH = "INDICATOR_MISMATCH"
WARMUP_MISMATCH = "WARMUP_MISMATCH"
SESSION_MISMATCH = "SESSION_MISMATCH"
SIZING_MISMATCH = "SIZING_MISMATCH"
ROUNDING_MISMATCH = "ROUNDING_MISMATCH"
META_MISMATCH = "META_MISMATCH"
RISK_MISMATCH = "RISK_MISMATCH"
EXECUTION_MISMATCH = "EXECUTION_MISMATCH"
DATA_MISMATCH = "DATA_MISMATCH"
TIMESTAMP_MISMATCH = "TIMESTAMP_MISMATCH"
STATE_MISMATCH = "STATE_MISMATCH"
BROKER_SPEC_MISMATCH = "BROKER_SPEC_MISMATCH"
UNKNOWN = "UNKNOWN"
TAXONOMY = (SIGNAL_MISMATCH, INDICATOR_MISMATCH, WARMUP_MISMATCH,
            SESSION_MISMATCH, SIZING_MISMATCH, ROUNDING_MISMATCH,
            META_MISMATCH, RISK_MISMATCH, EXECUTION_MISMATCH,
            DATA_MISMATCH, TIMESTAMP_MISMATCH, STATE_MISMATCH,
            BROKER_SPEC_MISMATCH, UNKNOWN)

# deterministic classification: first divergent field -> class (§15).
# Owner-declared classes are NEVER trusted: the machine map decides.
FIELD_CLASS: dict[str, str] = {
    "signal": SIGNAL_MISMATCH,
    "direction": SIGNAL_MISMATCH,
    "entry_side": SIGNAL_MISMATCH,
    "warmup": WARMUP_MISMATCH,
    "in_warmup": WARMUP_MISMATCH,
    "session": SESSION_MISMATCH,
    "session_state": SESSION_MISMATCH,
    "volume": SIZING_MISMATCH,
    "requested_lots": SIZING_MISMATCH,
    "fill_volume": SIZING_MISMATCH,
    "sl": ROUNDING_MISMATCH,
    "tp": ROUNDING_MISMATCH,
    "entry_price": EXECUTION_MISMATCH,
    "exit_price": EXECUTION_MISMATCH,
    "exit": EXECUTION_MISMATCH,
    "exit_reason": EXECUTION_MISMATCH,
    "kill_switch": EXECUTION_MISMATCH,
    "meta_weight": META_MISMATCH,
    "meta_veto": META_MISMATCH,
    "risk_approved": RISK_MISMATCH,
    "risk_veto": RISK_MISMATCH,
    "timestamp": TIMESTAMP_MISMATCH,
    "bar_time": TIMESTAMP_MISMATCH,
    "state": STATE_MISMATCH,
    "position_identifier": STATE_MISMATCH,
    "broker_point": BROKER_SPEC_MISMATCH,
    "broker_tick_value": BROKER_SPEC_MISMATCH,
    "price": DATA_MISMATCH,
    "close": DATA_MISMATCH,
}
# any field starting with one of these prefixes maps likewise
_PREFIX_CLASS = (("indicator", INDICATOR_MISMATCH),
                 ("broker", BROKER_SPEC_MISMATCH),
                 ("session", SESSION_MISMATCH),
                 ("meta", META_MISMATCH),
                 ("risk", RISK_MISMATCH))

# ---------------------------------------------------------------------------
# SymbolSpec contract (§9) and comparison classes (§8)
# ---------------------------------------------------------------------------
SYMBOLSPEC_REQUIRED = (
    "broker", "server", "symbol", "point", "tick_size",
    "tick_value_profit", "contract_size", "volume_min", "volume_max",
    "volume_step", "volume_limit", "stops_level_points",
    "freeze_level_points", "trade_mode", "filling_mode_mask",
    "expiration_mode_mask", "currency_profit", "timestamp",
    "terminal_build",
)
EXACT_MATCH = "EXACT_MATCH"
# S8-SPEC-3: a custom symbol's CALCULATED tick value reads back 0 (the
# importer's named limitation); it equals the frozen value only through two
# independent same-run witnesses (verify_symbolspec)
DERIVED_EXACT_MATCH = "DERIVED_EXACT_MATCH"
SEMANTICALLY_COMPATIBLE = "SEMANTICALLY_COMPATIBLE"
DECISION_CHANGING_MISMATCH = "DECISION_CHANGING_MISMATCH"
UNSUPPORTED_BROKER_DIFFERENCE = "UNSUPPORTED_BROKER_DIFFERENCE"
SYMBOLSPEC_CLASSES = (EXACT_MATCH, DERIVED_EXACT_MATCH,
                      SEMANTICALLY_COMPATIBLE,
                      DECISION_CHANGING_MISMATCH,
                      UNSUPPORTED_BROKER_DIFFERENCE)
# S8-SPEC-3: the custom symbol each gold's tester legs trade (the gate's
# stage-4 import names them; tools/owner_gate.ps1 $goldImports) and the
# folder the importer creates them in (InpSymbolGroup "Mql5Bot\gold")
GOLD_TESTER_SYMBOLS = {"gold1": "EURUSD.G1", "gold2": "EURUSD.G2"}
CUSTOM_SYMBOL_PATH_PREFIX = "Custom\\Mql5Bot\\gold\\"


def symbolspec_import_rel(gold: str) -> str:
    """The package copy of this gold's same-run stage-4 import record."""
    return f"symbolspec/import_{gold}.json"


def tester_ini_rel(gold: str, model: str) -> str:
    """The package copy of a leg's intended tester .ini (stage 5)."""
    return f"tester/{gold}_{model}.ini"
# fields whose difference can change a trading decision (never rewritten
# silently; a DECISION_CHANGING_MISMATCH stops the leg)
_DECISION_FIELDS = frozenset({
    "point", "tick_size", "tick_value_profit", "contract_size",
    "volume_min", "volume_max", "volume_step", "volume_limit",
    "stops_level_points", "freeze_level_points", "trade_mode",
    "filling_mode_mask", "expiration_mode_mask", "currency_profit",
})

# clock-skew tolerance for the freshness check ONLY; never a parity
# epsilon and never a tolerance on trading values
DRIFT_SECONDS = 2 * 86400

REAL_TICK_COVERAGE_NONE = "REAL_TICK_COVERAGE_NONE"
REAL_TICK_COVERAGES = ("REAL_TICK_COVERAGE_FULL",
                       "REAL_TICK_COVERAGE_PARTIAL",
                       "REAL_TICK_COVERAGE_UNKNOWN",
                       REAL_TICK_COVERAGE_NONE)

# execution-relevant paths for the freeze-anchor classification (§5)
EXECUTION_RELEVANT_PREFIXES = (
    "python/mql5bot/", "mql5/", "artifacts/gold/", "artifacts/gold_2/",
    "examples/strategies/", "tools/build_gold",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iso(ts: str) -> float | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")
                                      ).timestamp()
    except (ValueError, TypeError):
        return None


def classify_field(field: str) -> str:
    """Deterministic mismatch class for a divergent field (§15)."""
    key = str(field).lower()
    if key in FIELD_CLASS:
        return FIELD_CLASS[key]
    for prefix, cls in _PREFIX_CLASS:
        if key.startswith(prefix):
            return cls
    return UNKNOWN


# ---------------------------------------------------------------------------
# 1. completeness scan (§6: reject missing/duplicate/ambiguous artifacts)
# ---------------------------------------------------------------------------

def scan_package(root: Path | str) -> dict[str, dict]:
    """State of every mandatory artifact in the owner directory.

    A path that exists as a directory (ambiguous), or that appears more
    than once under case-variant names, is INVALID — never silently
    resolved.
    """
    root = Path(root)
    out: dict[str, dict] = {}
    for key, rel in LAYOUT.items():
        path = root / rel
        if not path.exists():
            state = MISSING
        elif path.is_dir():
            state = INVALID  # ambiguous: a directory where a file belongs
        else:
            siblings = [p for p in path.parent.glob(path.name + "*")
                        if p.is_file()]
            variants = [p for p in path.parent.iterdir()
                        if p.is_file() and p.name.lower() == rel.split("/")[-1].lower()
                        and p != path]
            state = INVALID if variants or len(siblings) > 1 \
                else PRESENT_UNVERIFIED
        out[key] = {"path": rel, "state": state}
    # a log-sourced leg's report slots are not missing: the log trade list
    # replaces them, and is itself listed so it is visibly the source
    for gold, model in sorted(log_sourced_legs(root)):
        out[f"raw_{gold}_{model}"]["state"] = LOG_SOURCED
        if out[f"parsed_{gold}_{model}"]["state"] == MISSING:
            out[f"parsed_{gold}_{model}"]["state"] = LOG_SOURCED
        out[f"log_trades_{gold}_{model}"] = {
            "path": log_trades_rel(gold, model), "state": PRESENT_UNVERIFIED,
            "trade_source": TRADE_SOURCE_LOG}
    # a NOT_APPLICABLE leg (never launched) has no report by design: its
    # slots are NOT_APPLICABLE. A report present for a leg the gate says it
    # never launched is a contradiction -> INVALID.
    for gold, model in sorted(not_applicable_legs(root)):
        for kind in ("raw", "parsed"):
            slot = out[f"{kind}_{gold}_{model}"]
            slot["state"] = (NOT_APPLICABLE if slot["state"] == MISSING
                             else INVALID)
    return out


# ---------------------------------------------------------------------------
# 2. compiler evidence (§8: identity + freshness, attack-resistant)
# ---------------------------------------------------------------------------

ANCHOR_RELATION_EXACT = "EXACT_ANCHOR"
ANCHOR_RELATION_DESCENDANT = "DESCENDANT_FROZEN_BYTES_IDENTICAL"
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")


def frozen_file_pins(frozen_inputs: dict) -> list[tuple[str, str, str]]:
    """(repo path, sha256 pin, label) for EVERY file hash frozen_inputs.json
    lists: both golds' fixture / manifest / expected_execution and gold_2's
    full artifact_hash_chain. Stage 0 (gate_selfcheck.verify_frozen_hashes)
    and S8-ANCHOR-REL-1 read the same list."""
    g1 = frozen_inputs.get("gold_1") or {}
    g2 = frozen_inputs.get("gold_2") or {}
    pins = [
        ("artifacts/gold/gold_fixture.csv", g1.get("fixture_sha256", ""),
         "gold_1 fixture"),
        ("artifacts/gold/manifest.json", g1.get("manifest_sha256", ""),
         "gold_1 manifest"),
        ("artifacts/gold/expected_execution.json",
         g1.get("expected_execution_sha256", ""), "gold_1 expected"),
        ("artifacts/gold_2/gold2_fixture.csv", g2.get("fixture_sha256", ""),
         "gold_2 fixture"),
        ("artifacts/gold_2/manifest.json", g2.get("manifest_sha256", ""),
         "gold_2 manifest"),
        ("artifacts/gold_2/expected_execution.json",
         g2.get("expected_execution_sha256", ""), "gold_2 expected"),
    ]
    pins += [(f"artifacts/gold_2/{fn}", want, f"gold_2 chain {fn}")
             for fn, want in (g2.get("artifact_hash_chain") or {}).items()]
    return [p for p in pins if p[1]]


def anchor_relation(repo: Path | str, anchor: str, commit: str,
                    frozen_inputs: dict, runner=None) -> dict:
    """S8-ANCHOR-REL-1 (owner decision 2026-10-04): how a recorded commit
    relates to the frozen anchor. DESCENDANT_FROZEN_BYTES_IDENTICAL only when
    BOTH hold:

    * the anchor is an ancestor of the commit (git merge-base --is-ancestor);
    * every file hash frozen_inputs.json lists equals the sha256 of that
      file's bytes AT the commit (git show <commit>:<path>) AND at the
      anchor (git show <anchor>:<path>), recomputed here -- never a
      builder's boolean. The anchor check refuses a descendant that
      changed an artifact and its pin together.

    ``runner(args) -> CompletedProcess`` replaces git in tests. Returns
    {"relation": str|None, "reasons": [...], "frozen_files": {...}}."""
    def git(args: list[str], text: bool = True):
        if runner is not None:
            return runner(args)
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=text, check=False)

    anchor = str(anchor or "").strip().lower()
    commit = str(commit or "").strip().lower()
    out: dict = {"anchor": anchor, "commit": commit, "relation": None,
                 "reasons": [], "frozen_files": {}}
    why = out["reasons"]
    if commit and commit == anchor:
        out["relation"] = ANCHOR_RELATION_EXACT
        return out
    if not _FULL_SHA_RE.fullmatch(commit):
        why.append(f"recorded commit {commit!r} is not a full 40-hex SHA")
        return out
    if not _FULL_SHA_RE.fullmatch(anchor):
        why.append(f"frozen anchor {anchor!r} is not a full 40-hex SHA")
        return out
    if repo is None and runner is None:
        why.append("no repository to evaluate the anchor relation in")
        return out
    for sha, label in ((commit, "recorded commit"), (anchor, "anchor")):
        if git(["cat-file", "-e", sha + "^{commit}"]).returncode != 0:
            why.append(f"{label} {sha} is not a commit in this repository")
    if why:
        return out
    if git(["merge-base", "--is-ancestor", anchor, commit]).returncode != 0:
        why.append(f"anchor {anchor} is not an ancestor of {commit}")
        return out
    pins = frozen_file_pins(frozen_inputs)
    if not pins:
        why.append("frozen_inputs.json lists no file hash to compare")
    def sha_at(ref: str, rel: str) -> str | None:
        cp = git(["show", f"{ref}:{rel}"], text=False)
        data = cp.stdout if cp.returncode == 0 else None
        if isinstance(data, str):
            data = data.encode()
        return hashlib.sha256(data).hexdigest() if data is not None else None

    # every pin must hold at the ANCHOR as well as at the commit: the pins
    # are read from the frozen record at HEAD, so a descendant that changed
    # an artifact AND its pin together would otherwise pass
    for rel, want, label in pins:
        at_anchor, got = sha_at(anchor, rel), sha_at(commit, rel)
        out["frozen_files"][rel] = {"pin": want, "at_anchor": at_anchor,
                                    "at_commit": got}
        if at_anchor is None:
            why.append(f"{label}: {rel} absent at the anchor {anchor}")
        elif at_anchor != want.lower():
            why.append(f"{label}: {rel} sha256 at the anchor {anchor} != "
                       "frozen pin (the pin does not hold at the anchor)")
        if got is None:
            why.append(f"{label}: {rel} absent at {commit}")
        elif got != want.lower():
            why.append(f"{label}: {rel} sha256 at {commit} != frozen pin")
    if not why:
        out["relation"] = ANCHOR_RELATION_DESCENDANT
    return out


def source_commit_relation(recorded, frozen_source_commit: str,
                           relation_of=None) -> dict:
    """A recorded source commit is accepted iff it == the frozen anchor, or
    ``relation_of(recorded)`` (anchor_relation bound to a repo) returns
    DESCENDANT_FROZEN_BYTES_IDENTICAL. Nothing else is accepted."""
    rec = str(recorded or "").strip().lower()
    want = str(frozen_source_commit or "").strip().lower()
    if rec and rec == want:
        return {"accepted": True, "relation": ANCHOR_RELATION_EXACT,
                "recorded": rec, "anchor": want, "reasons": []}
    if relation_of is None:
        return {"accepted": False, "relation": None, "recorded": rec,
                "anchor": want, "reasons": [
                    "no repository bound: only HEAD == anchor is accepted"]}
    rel = relation_of(rec)
    return {"accepted": rel.get("relation") == ANCHOR_RELATION_DESCENDANT,
            "relation": rel.get("relation"), "recorded": rec,
            "anchor": want, "reasons": list(rel.get("reasons") or []),
            "frozen_files": rel.get("frozen_files") or {}}


def verify_compile(root: Path | str, frozen_source_commit: str,
                   relation_of=None) -> dict:
    root = Path(root)
    report: dict = {"checks": {}, "state": MISSING, "reasons": []}
    log = root / LAYOUT["compile_log"]
    meta = root / LAYOUT["compile_metadata"]
    ex5 = root / LAYOUT["ex5"]

    for name, path in (("compile_log", log), ("compile_metadata", meta),
                       ("ex5", ex5)):
        if not path.is_file():
            report["reasons"].append(f"{name} missing")
            report["state"] = MISSING
            return report

    doc = _load_json(meta)
    if not isinstance(doc, dict):
        report["state"] = INVALID
        report["reasons"].append("compile metadata unparsable")
        return report

    checks = report["checks"]
    required = ("SOURCE_COMMIT", "COMPILER_VERSION", "TERMINAL_BUILD",
                "EX5_SHA256", "COMPILE_TIMESTAMP", "COMPILER_LOG_SHA256",
                "ERRORS", "WARNINGS")
    missing = [f for f in required if f not in doc]
    checks["provenance_fields"] = "VALID" if not missing else "INVALID"
    if missing:
        report["reasons"].append(f"metadata missing fields: {missing}")

    # EX5 identity: recorded hash must equal the actual bytes
    actual_ex5 = sha256_file(ex5)
    checks["ex5_hash"] = ("VALID" if doc.get("EX5_SHA256") == actual_ex5
                          else MISMATCHED)
    if doc.get("EX5_SHA256") != actual_ex5:
        report["reasons"].append("EX5 bytes do not match the recorded "
                                 "hash (stale/foreign EX5)")

    # compiler-log identity: recorded log hash must equal the log bytes
    actual_log = sha256_file(log)
    checks["log_hash"] = ("VALID"
                          if doc.get("COMPILER_LOG_SHA256") == actual_log
                          else MISMATCHED)
    if doc.get("COMPILER_LOG_SHA256") != actual_log:
        report["reasons"].append("compile log bytes do not match the "
                                 "recorded hash (stale/edited log)")

    # source identity: commit identity, never the branch name (§4); a
    # descendant is accepted only through S8-ANCHOR-REL-1 (relation_of)
    rel = source_commit_relation(doc.get("SOURCE_COMMIT"),
                                 frozen_source_commit, relation_of)
    report["source_commit_relation"] = rel
    checks["source_commit"] = "VALID" if rel["accepted"] else MISMATCHED
    if checks["source_commit"] != "VALID":
        report["reasons"].append("source commit does not match the frozen "
                                 "anchor" + (f" ({'; '.join(rel['reasons'])})"
                                             if rel["reasons"] else ""))

    # zero errors / zero warnings — declared counts AND a token scan of
    # the raw log (MetaEditor `file(line,col): error|warning ...` rows)
    text = log.read_text(encoding="utf-8", errors="replace")
    err_lines = len(re.findall(r"\)\s*:\s*error\b", text, re.IGNORECASE))
    warn_lines = len(re.findall(r"\)\s*:\s*warning\b", text, re.IGNORECASE))
    checks["zero_errors"] = ("VALID" if doc.get("ERRORS") == 0
                             and err_lines == 0 else INVALID)
    checks["zero_warnings"] = ("VALID" if doc.get("WARNINGS") == 0
                               and warn_lines == 0 else INVALID)
    if checks["zero_errors"] != "VALID":
        report["reasons"].append("compile errors present")
    if checks["zero_warnings"] != "VALID":
        report["reasons"].append("compile warnings present (-Strict)")

    # freshness: EX5 not older than the recorded compile timestamp.
    # A small drift band tolerates machine clock skew only; an EX5 even
    # minutes older than the recorded compile is stale evidence.
    ts = _iso(doc.get("COMPILE_TIMESTAMP", ""))
    now = time.time()
    if ts is None:
        checks["freshness"] = INVALID
        report["reasons"].append("COMPILE_TIMESTAMP missing/unparsable")
    elif ts > now + DRIFT_SECONDS:
        checks["freshness"] = INVALID
        report["reasons"].append("COMPILE_TIMESTAMP in the future "
                                 "(impossible evidence)")
    elif ex5.stat().st_mtime < ts - DRIFT_SECONDS:
        checks["freshness"] = STALE
        report["reasons"].append("EX5 older than the compile timestamp "
                                 "(stale binary)")
    else:
        checks["freshness"] = "VALID"

    ok = all(v == "VALID" for v in checks.values())
    report["state"] = "VALID" if ok else (
        STALE if checks.get("freshness") == STALE else
        MISMATCHED if any(v == MISMATCHED for v in checks.values())
        else INVALID)
    return report


# ---------------------------------------------------------------------------
# 3. SymbolSpec verification (§9)
# ---------------------------------------------------------------------------

def _custom_identity_class(name, path, scope: tuple[str, ...]
                           ) -> tuple[str, dict]:
    """S8-SPEC-3: a custom symbol's name is EXACT_MATCH only when it IS the
    tester symbol the gate declares for an in-scope gold AND it lives in the
    importer's folder. Anything else is DECISION_CHANGING."""
    golds = [g for g in scope if GOLD_TESTER_SYMBOLS.get(g) == name]
    path_ok = isinstance(path, str) and path.startswith(
        CUSTOM_SYMBOL_PATH_PREFIX)
    basis = {"rule": "S8-SPEC-3 custom-symbol identity",
             "name": name, "path": path,
             "declared_tester_symbols": {g: GOLD_TESTER_SYMBOLS[g]
                                         for g in scope},
             "name_is_declared_tester_symbol": bool(golds),
             "gold": golds[0] if golds else None,
             "path_prefix_required": CUSTOM_SYMBOL_PATH_PREFIX,
             "path_prefix_ok": path_ok}
    return (EXACT_MATCH if golds and path_ok
            else DECISION_CHANGING_MISMATCH), basis


def _bound_bytes(root: Path, rel: str) -> tuple[bytes | None, str]:
    """A package file's bytes, ONLY when archive_manifest.json binds it by a
    hash equal to those bytes; else (None, why)."""
    path = root / rel
    if not path.is_file():
        return None, f"{rel} missing from the package"
    man = _load_json(root / LAYOUT["archive_manifest"])
    arts = man.get("artifacts") if isinstance(man, dict) else None
    want = arts.get(rel) if isinstance(arts, dict) else None
    if not isinstance(want, str):
        return None, f"{rel} not bound in archive_manifest.json"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != want.lower():
        return None, f"{rel} bytes != its archive_manifest.json hash"
    return data, ""


def _ini_tester_value(data: bytes, key: str) -> str | None:
    """`<key>=` of an ini's [Tester] section (utf-8/utf-16, BOM-aware)."""
    text = (data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff")
            else data.decode("utf-8-sig", errors="replace"))
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
        elif section == "tester" and \
                line.lower().startswith(key.lower() + "="):
            return line.split("=", 1)[1].strip()
    return None


def _ini_currency(data: bytes) -> str | None:
    """`Currency=` of an ini's [Tester] section (utf-8/utf-16, BOM-aware)."""
    return _ini_tester_value(data, "Currency")


def ini_deposit(data: bytes) -> float | None:
    """`Deposit=` of an ini's [Tester] section as a number, else None."""
    raw = _ini_tester_value(data, "Deposit")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _custom_tick_value_class(root: Path, doc: dict, name, actual, expected,
                             scope: tuple[str, ...]) -> tuple[str, dict]:
    """S8-SPEC-3: a custom symbol's tick_value_profit export readback of 0
    is the importer's named limitation (CALCULATED, derived lazily on a
    bars-only symbol). It is DERIVED_EXACT_MATCH only when BOTH same-run
    witnesses equal the frozen value:

    (a) the package's import record (symbolspec/import_<gold>.json, bound
        in archive_manifest.json) shows the settable SYMBOL_TRADE_TICK_VALUE
        read back == frozen with ok:true;
    (b) tick_size * contract_size == frozen exactly AND currency_profit ==
        the tester deposit Currency of every packaged leg .ini of that gold
        (each bound in archive_manifest.json).

    Any witness missing or unequal -> DECISION_CHANGING."""
    golds = [g for g in scope if GOLD_TESTER_SYMBOLS.get(g) == name]
    gold = golds[0] if golds else None
    basis: dict = {"rule": "S8-SPEC-3 custom-symbol tick_value_profit",
                   "export_readback": actual, "frozen": expected,
                   "gold": gold, "witness_a": {}, "witness_b": {},
                   "reasons": []}
    why = basis["reasons"]
    if actual != 0:
        why.append(f"export readback {actual!r} is not the importer's named "
                   "limitation (0): no derivation is applied")
    if gold is None:
        why.append(f"symbol {name!r} is no in-scope gold's tester symbol")
    # (a) same-run import record
    a = basis["witness_a"]
    if gold is not None:
        rel = symbolspec_import_rel(gold)
        a["file"] = rel
        raw, bad = _bound_bytes(root, rel)
        rec = None
        if raw is None:
            why.append(f"witness (a): {bad}")
        else:
            try:
                rec = json.loads(raw.decode("utf-8-sig"))
            except ValueError:
                why.append(f"witness (a): {rel} unparsable")
        if isinstance(rec, dict):
            rows = [r for r in rec.get("verified_properties") or []
                    if isinstance(r, dict)
                    and r.get("enum") == "SYMBOL_TRADE_TICK_VALUE"]
            if len(rows) != 1:
                why.append(f"witness (a): {rel} carries {len(rows)} "
                           "SYMBOL_TRADE_TICK_VALUE verified_properties rows "
                           "(exactly 1 required)")
            else:
                row = rows[0]
                try:
                    readback = float(row.get("readback"))
                except (TypeError, ValueError):
                    readback = None
                a.update({"readback": row.get("readback"),
                          "ok": row.get("ok")})
                if row.get("ok") is not True:
                    why.append("witness (a): SYMBOL_TRADE_TICK_VALUE "
                               "read-back ok is not true")
                if readback != expected:
                    why.append(f"witness (a): SYMBOL_TRADE_TICK_VALUE "
                               f"readback {row.get('readback')!r} != frozen "
                               f"{expected!r}")
    # (b) arithmetic + deposit currency
    b = basis["witness_b"]
    ts, cs, cp = (doc.get("tick_size"), doc.get("contract_size"),
                  doc.get("currency_profit"))
    try:
        product = float(ts) * float(cs)
    except (TypeError, ValueError):
        product = None
    b.update({"tick_size": ts, "contract_size": cs, "product": product,
              "currency_profit": cp, "deposit_currency": {}})
    if product is None or product != expected:
        why.append(f"witness (b): tick_size*contract_size {product!r} != "
                   f"frozen {expected!r}")
    if gold is not None:
        inis = sorted((root / "tester").glob(f"{gold}_*.ini"))
        if not inis:
            why.append(f"witness (b): no tester/{gold}_*.ini in the package")
        for p in inis:
            rel = f"tester/{p.name}"
            raw, bad = _bound_bytes(root, rel)
            cur = _ini_currency(raw) if raw is not None else None
            b["deposit_currency"][rel] = cur
            if raw is None:
                why.append(f"witness (b): {bad}")
            elif cur is None:
                why.append(f"witness (b): {rel} states no [Tester] Currency")
            elif cur != cp:
                why.append(f"witness (b): {rel} deposit Currency {cur!r} != "
                           f"currency_profit {cp!r}")
    return (DECISION_CHANGING_MISMATCH if why
            else DERIVED_EXACT_MATCH), basis


def verify_symbolspec(root: Path | str,
                      frozen_expected: dict | None,
                      golds: tuple[str, ...] | list[str] | None = None
                      ) -> dict:
    """``golds`` is the verified scope (default: every gold); S8-SPEC-3
    accepts only an in-scope gold's declared tester symbol."""
    root = Path(root)
    path = root / LAYOUT["symbolspec"]
    if not path.is_file():
        return {"state": MISSING, "reasons": ["symbolspec missing"]}
    doc = _load_json(path)
    if not isinstance(doc, dict):
        return {"state": INVALID, "reasons": ["symbolspec unparsable"]}

    missing = [f for f in SYMBOLSPEC_REQUIRED if f not in doc]
    if missing:
        return {"state": INVALID,
                "reasons": [f"symbolspec missing fields: {missing}"]}

    identity = {k: doc[k] for k in ("broker", "server", "symbol",
                                    "timestamp", "terminal_build")}
    report: dict = {"state": PRESENT_UNVERIFIED, "identity": identity,
                    "field_classes": {}, "reasons": []}

    if not isinstance(frozen_expected, dict) or not frozen_expected:
        # nothing frozen to compare against: present but unverified, and
        # the comparison itself stays PENDING — never assumed compatible
        report["reasons"].append("no frozen expectations to compare "
                                 "(comparison PENDING_OWNER)")
        return report

    # The frozen broker_spec convention names the symbol under `name`, while
    # the SymbolSpec doc names it under `symbol`. Translate so a frozen symbol
    # identity is ACTUALLY enforced when provided — otherwise `doc.get("name")`
    # is always None -> UNSUPPORTED_BROKER_DIFFERENCE -> silently ignored, and
    # a leg run on the WRONG symbol whose decision numerics coincide would pass
    # identity. A wrong symbol identity is decision-changing (STOP).
    # The exporter (mql5bot.broker_export/1) nests the symbol as an OBJECT
    # whose name is `symbol.name`; a flat string is accepted too. Comparing
    # the frozen name to the object could never match.
    _IDENTITY_FIELDS = {"name", "symbol"}
    sym_obj = doc.get("symbol")
    sym_name = (sym_obj.get("name") if isinstance(sym_obj, dict)
                else sym_obj)
    sym_path = (sym_obj.get("path") if isinstance(sym_obj, dict) else None)
    custom = doc.get("custom_symbol") is True
    identity["symbol"] = sym_name
    report["field_bases"] = {}
    scope = tuple(golds) if golds else GOLDS
    decision_changing = []
    for field, expected in frozen_expected.items():
        actual = (sym_name if field in _IDENTITY_FIELDS
                  else doc.get(field))
        if field in _IDENTITY_FIELDS and custom:
            cls, basis = _custom_identity_class(sym_name, sym_path, scope)
            report["field_bases"][field] = basis
        elif (field == "tick_value_profit" and custom
              and actual is not None and actual != expected):
            cls, basis = _custom_tick_value_class(
                root, doc, sym_name, actual, expected, scope)
            report["field_bases"][field] = basis
        elif actual is None:
            cls = UNSUPPORTED_BROKER_DIFFERENCE
        elif actual == expected:
            cls = EXACT_MATCH
        elif field in _DECISION_FIELDS or field in _IDENTITY_FIELDS:
            cls = DECISION_CHANGING_MISMATCH
        else:
            cls = SEMANTICALLY_COMPATIBLE
        if cls == DECISION_CHANGING_MISMATCH:
            decision_changing.append(field)
        report["field_classes"][field] = cls

    if decision_changing:
        report["state"] = MISMATCHED
        report["reasons"].append(
            "DECISION_CHANGING_MISMATCH on: "
            + ", ".join(decision_changing)
            + " — STOP; the gold artifacts are NEVER rewritten")
    else:
        report["state"] = VALID
    return report


# ---------------------------------------------------------------------------
# 4. tester-model identity (§10: requested vs report-reported vs journal)
# ---------------------------------------------------------------------------
MODEL_LABELS = {0: "Every tick", 1: "1 minute OHLC", 2: "Open prices only",
                3: "Every tick based on real ticks", 4: "Real ticks"}


def verify_model_identity(leg: dict) -> dict:
    """The three-way identity must agree; CLI selection alone never
    proves the model actually used."""
    requested = leg.get("requested")
    reported = leg.get("report_reported")
    journal = leg.get("journal")
    if requested is None or reported is None:
        return {"state": INVALID,
                "reasons": [("model identity incomplete "
                            "(requested/report_reported required)")]}
    norm_req = (MODEL_LABELS.get(requested, requested)
                if isinstance(requested, int) else str(requested))
    if str(reported).lower() != str(norm_req).lower():
        return {"state": MISMATCHED,
                "reasons": [("MODEL_IDENTITY_MISMATCH: requested "
                            f"{norm_req!r} but report says {reported!r}")]}
    if journal is not None and \
            str(journal).lower() != str(norm_req).lower():
        return {"state": MISMATCHED,
                "reasons": [("MODEL_IDENTITY_MISMATCH: journal says "
                            f"{journal!r}, requested {norm_req!r}")]}
    return {"state": VALID, "reasons": []}


def _resolve_evidence(root: Path, binding, what: str) -> tuple[str, str,
                                                             Path | None]:
    """Validate one file-bound evidence reference.

    A FILE PATH STRING IS NOT EVIDENCE: the binding must be an object
    {"path": <relative path>, "sha256": <hash>}; the file must exist
    INSIDE the evidence root (path escapes rejected), and its bytes
    must match the recorded hash. Returns (state, reason, path).
    """
    if not isinstance(binding, dict):
        return (INVALID, (f"{what}: evidence must be a file binding "
                "object {{path, sha256}} — a path or prose string is "
                "not evidence"), None)
    rel = binding.get("path")
    digest = binding.get("sha256")
    if not isinstance(rel, str) or not rel:
        return (INVALID, f"{what}: evidence binding has no path", None)
    if not isinstance(digest, str) or len(digest) != 64:
        return (INVALID, f"{what}: evidence binding has no SHA-256",
                None)
    path = (root / rel).resolve()
    root_res = root.resolve()
    if not str(path).startswith(str(root_res) + "/") and path != root_res:
        return (INVALID, (f"{what}: evidence path escapes the evidence "
                "root"), None)
    if not path.is_file():
        return (INVALID, (f"{what}: bound evidence file does not exist "
                f"({rel})"), None)
    if sha256_file(path) != digest.lower():
        return (MISMATCHED, (f"{what}: bound evidence bytes do not match "
                "the recorded SHA-256"), path)
    return ("VALID", "", path)


def _journal_says(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


# ---------------------------------------------------------------------------
# 5. real-tick coverage (§11: selection is not proof)
# ---------------------------------------------------------------------------

def verify_real_tick_coverage(root: Path | str) -> dict:
    root = Path(root)
    path = root / LAYOUT["real_tick_coverage"]
    if not path.is_file():
        return {"state": MISSING, "coverage": None,
                "reasons": ["real-tick coverage record missing"]}
    doc = _load_json(path)
    if not isinstance(doc, dict):
        return {"state": INVALID, "coverage": None,
                "reasons": ["coverage record unparsable"]}
    cov = doc.get("coverage")
    if cov not in REAL_TICK_COVERAGES:
        return {"state": INVALID, "coverage": cov,
                "reasons": [(f"coverage {cov!r} outside the closed "
                            "vocabulary")]}
    if cov == REAL_TICK_COVERAGE_NONE:
        return _verify_coverage_none(root, doc)
    required = ("requested_model", "actual_model_from_report",
                "requested_interval", "actual_interval", "broker",
                "symbol")
    missing = [f for f in required
               if not doc.get(f) or doc.get(f) == "PENDING_OWNER"]

    # cross-checks: coverage must describe the SAME broker/symbol as the
    # owner SymbolSpec, and the actual model must equal the requested
    # one (a silent fallback is never FULL coverage)
    spec = _load_json(root / LAYOUT["symbolspec"])
    if isinstance(spec, dict):
        if doc.get("symbol") not in (None, "PENDING_OWNER") and \
                spec.get("symbol") and \
                doc.get("symbol") != spec.get("symbol"):
            return {"state": MISMATCHED, "coverage": cov,
                    "reasons": [("coverage symbol does not match the "
                                "owner SymbolSpec")]}
        if doc.get("broker") not in (None, "PENDING_OWNER") and \
                spec.get("broker") and \
                doc.get("broker") != spec.get("broker"):
            return {"state": MISMATCHED, "coverage": cov,
                    "reasons": [("coverage broker does not match the "
                                "owner SymbolSpec")]}
    req = doc.get("requested_model")
    act = doc.get("actual_model_from_report")
    if req and act and act != "PENDING_OWNER" and \
            str(req).lower() != str(act).lower():
        return {"state": MISMATCHED, "coverage": cov,
                "reasons": [("actual tester model differs from the "
                            "requested one — silent fallback, never "
                            "FULL coverage")]}
    ri, ai = doc.get("requested_interval"), doc.get("actual_interval")
    if cov == "REAL_TICK_COVERAGE_FULL" and ri and ai and \
            ai != "PENDING_OWNER" and ri != ai:
        return {"state": INVALID, "coverage": cov,
                "reasons": [("FULL coverage requires the actual interval "
                            "to equal the requested interval")]}
    if cov == "REAL_TICK_COVERAGE_FULL":
        # FILE-BOUND evidence: {"path", "sha256"} — the artifact must
        # live inside the evidence root and match its hash; a path or
        # prose string alone is NEVER evidence
        evidence = doc.get("real_tick_availability_evidence")
        if not evidence or evidence == "PENDING_OWNER":
            return {"state": INVALID, "coverage": cov,
                    "reasons": [("coverage FULL claimed without positive "
                                "tick-history evidence — never inferred "
                                "from mode selection")]}
        state, reason, epath = _resolve_evidence(
            root, evidence, "real-tick evidence")
        if state != "VALID":
            return {"state": state, "coverage": cov, "reasons": [reason]}
        # the bound journal must describe THIS symbol and THIS interval
        text = epath.read_text(encoding="utf-8", errors="replace")
        sym = doc.get("symbol")
        if sym and sym != "PENDING_OWNER" and not _journal_says(text, sym):
            return {"state": MISMATCHED, "coverage": cov,
                    "reasons": [("bound journal does not mention the "
                                f"coverage symbol {sym!r}")]}
        ri_s = str(ri or "")
        if ".." in ri_s:
            for date in ri_s.split(".."):
                if date.strip() and not _journal_says(text, date.strip()):
                    return {"state": MISMATCHED, "coverage": cov,
                            "reasons": [("bound journal does not cover "
                                        f"the requested interval "
                                        f"{ri_s!r}")]}
        if missing:
            return {"state": INVALID, "coverage": cov,
                    "reasons": [(f"FULL coverage record incomplete: "
                                f"{missing}")]}
        return {"state": VALID, "coverage": cov, "reasons": []}
    if missing:
        return {"state": INVALID, "coverage": cov,
                "reasons": [f"coverage record incomplete: {missing}"]}
    # PARTIAL and UNKNOWN are VALID records that CONSTRAIN the verdict
    return {"state": VALID, "coverage": cov, "reasons": []}


def _verify_coverage_none(root: Path, doc: dict) -> dict:
    """REAL_TICK_COVERAGE_NONE: no real_ticks leg ran (bar-only fixture).

    VALID only as a record of absence: the leg was not launched, the outcome
    is NOT_APPLICABLE_BAR_ONLY_FIXTURE, the fixture is named, and no actual
    model or interval is claimed (nothing ran, so nothing can be stated).
    Every gold it names must be NOT_APPLICABLE in the gate's own stage-5
    record. A VALID NONE record still constrains the verdict: anything short
    of FULL can never be MT5_VALIDATED (owner decision 2026-10-03)."""
    cov = REAL_TICK_COVERAGE_NONE
    per_gold = doc.get("golds")
    reasons: list[str] = []
    if doc.get("leg_launched") is not False:
        reasons.append("NONE coverage requires leg_launched == false")
    if doc.get("outcome") != STAGE5_NOT_APPLICABLE:
        reasons.append(f"NONE coverage requires outcome "
                       f"{STAGE5_NOT_APPLICABLE!r}")
    if not isinstance(per_gold, dict) or not per_gold or not all(
            isinstance(v, dict) and v.get("fixture")
            for v in per_gold.values()):
        reasons.append("NONE coverage must name each gold's fixture")
    for claim in ("actual_model_from_report", "actual_interval",
                  "real_tick_availability_evidence"):
        if doc.get(claim) not in (None, ""):
            reasons.append(f"NONE coverage cannot state {claim}: no "
                           "real_ticks leg ran")
    if reasons:
        return {"state": INVALID, "coverage": cov, "reasons": reasons}
    na = not_applicable_legs(root)
    stray = sorted(g for g in per_gold if (g, "real_ticks") not in na)
    if stray:
        return {"state": MISMATCHED, "coverage": cov,
                "reasons": [("NONE coverage names golds whose real_ticks "
                             "leg the gate's stage-5 record does not mark "
                             f"NOT_APPLICABLE: {stray}")]}
    spec = _load_json(root / LAYOUT["symbolspec"])
    if isinstance(spec, dict) and spec.get("symbol") and \
            doc.get("symbol") not in (None, spec.get("symbol")):
        return {"state": MISMATCHED, "coverage": cov,
                "reasons": [("coverage symbol does not match the owner "
                            "SymbolSpec")]}
    return {"state": VALID, "coverage": cov, "reasons": []}


# ---------------------------------------------------------------------------
# 6. first-divergence engine + reconciliation (§14/§16)
# ---------------------------------------------------------------------------

def _field_divergent(spec: dict) -> bool:
    """A reconciliation field DIVERGES when the owner declared it
    ``DIVERGENT`` OR the recorded ``python``/``mt5`` values disagree
    (zero tolerance, the gold lane is exact). The owner-supplied
    ``status`` is ADVISORY ONLY: a real divergence can never be hidden by
    labelling a field ``MATCH`` or by omitting the status — the values
    decide. (Previously divergence was read solely from the owner's
    ``status`` string, so a diverging MT5 run could be waved through by
    writing ``"status":"MATCH"``.)"""
    if spec.get("status") == "DIVERGENT":
        return True
    if "python" in spec and "mt5" in spec:
        return spec["python"] != spec["mt5"]
    return False


def _observed_divergences(events) -> dict:
    """Diagnostic view of the recorded events, computed BEFORE any binding
    check so stage 8 can show the comparison even when the package fails.
    ``binding_verified`` is False: this is never the verifier's verdict
    (verify_reconciliation replaces it with a binding-verified one only when
    the full chain holds). ``first_trade_divergence`` walks only per-trade
    events (those carrying ``trade_index``)."""
    if not isinstance(events, list):
        return {"first_divergence": None, "first_trade_divergence": None}
    evs = [e for e in events if isinstance(e, dict)]
    out = {"first_divergence": first_divergence(evs),
           "first_trade_divergence": first_divergence(
               [e for e in evs if "trade_index" in e])}
    for div in out.values():
        if div is not None:
            div["binding_verified"] = False
    return out


def _add_trade_context(div: dict | None, events: list[dict]) -> dict | None:
    """Carry the per-trade index/model of the divergent event, if any."""
    if div is None:
        return None
    for e in events:
        if isinstance(e, dict) and e.get("index") == div.get("event_index"):
            div["trade_index"] = e.get("trade_index")
            div["model"] = e.get("model")
            break
    return div


def first_divergence(events: list[dict]) -> dict | None:
    """The FIRST event with any DIVERGENT field — never just the final
    metrics. Deterministic: events are walked in index order."""
    for event in sorted(events, key=lambda e: int(e.get("index", 0))):
        fields = event.get("fields") or {}
        divergent = {name: spec for name, spec in fields.items()
                     if isinstance(spec, dict) and _field_divergent(spec)}
        if divergent:
            field = min(divergent)
            return {
                "event_index": event.get("index"),
                "bar": event.get("bar"),
                "timestamp": event.get("time") or event.get("timestamp"),
                "symbol": event.get("symbol"),
                "first_divergent_field": field,
                "python_value": divergent[field].get("python"),
                "mt5_value": divergent[field].get("mt5"),
                "python_state": event.get("python_state"),
                "mt5_state": event.get("mt5_state"),
                "input_price": event.get("input_price"),
                "indicator_values": event.get("indicator_values"),
                "session": event.get("session"),
                "meta": event.get("meta"),
                "risk": event.get("risk"),
                "kill_switch": event.get("kill_switch"),
                "execution_state": event.get("execution_state"),
                "classification": classify_field(field),
            }
    return None


_BINDING_FIELDS = ("source_commit", "fixture_sha256", "config_hash",
                   "dataset_hash", "symbolspec_sha256", "ex5_sha256",
                   "expected_execution_sha256", "tester_models",
                   "raw_report_hashes", "parsed_report_hashes")


def _verify_log_trades(root: Path, gold: str, log_models: set[str],
                       bindings: dict) -> tuple[dict, list[str]]:
    """Bind + validate each log-sourced leg's trade list. The list must be
    the stage-5 PASS_FROM_LOG output (flagged from_log / no report), and its
    bytes must equal the hash the reconciliation declares."""
    lth = bindings.get("log_trade_hashes") or {}
    problems: list[str] = []
    docs: dict = {}
    if log_models and (not isinstance(lth, dict) or set(lth) != log_models):
        return docs, [("log_trade_hashes must bind exactly the "
                       f"log-sourced models {sorted(log_models)}")]
    for model in sorted(log_models):
        path = root / log_trades_rel(gold, model)
        if lth[model] != sha256_file(path):
            problems.append(f"{model}: log trade list bytes changed")
            continue
        doc = _load_json(path)
        if not isinstance(doc, dict) or doc.get("from_log") is not True \
                or doc.get("report_present") is not False \
                or doc.get("evidence_class") != "PASS_FROM_LOG" \
                or doc.get("schema") != LOG_TRADE_LIST_SCHEMA \
                or not isinstance(doc.get("deals"), list):
            problems.append(f"{model}: not a PASS_FROM_LOG log trade list "
                            "(from_log/report_present/evidence_class/deals)")
            continue
        docs[model] = doc
    return docs, problems


_PYTHON_SIDE_PAIRINGS = (PAIRED_BY_TIME, MISSING_IN_MT5,
                         "OUT_OF_TESTED_WINDOW", "FROZEN_ONLY_SCHEDULED_WEIGHT")


def _log_leg_checks(root: Path, gold: str, log_docs: dict, events: list,
                    tick_paths: dict, py_count: int,
                    sizing_ref: dict | None = None
                    ) -> tuple[dict, list[dict], list[str], dict]:
    """The log-sourced legs' comparison rules, recomputed from the BOUND
    evidence (log trade lists, window copies, tester ini copies). Returns
    (derived entry-count event, events with S8-TS-1 applied, problems,
    info); any problem makes the reconciliation INVALID.

    * S8-COUNT-1 -- ``entry_count:<model>``: python = the model's
      PAIRED_BY_TIME + MISSING_IN_MT5 events (expected entries INSIDE the
      tested window), mt5 = the entry deals of the bound log list. PAIRED +
      EXTRA_IN_MT5 must equal the MT5 entry deals. A model with no python-
      side event at all while the frozen python trade count is > 0 is not
      comparable (the zero-trade guard cannot be bypassed by omitting the
      expected entries).
    * S8-TS-1 -- a paired timestamp on the fill-bar basis holds only when
      its mt5 minute is the floor of the recorded raw MT5 time, that raw
      time is the bound deal's own, and the same event's entry_price
      matches exactly; otherwise the timestamp field DIVERGES.
    * S8-TICKPATH-1 -- the recorded tick-path divergence must equal the one
      recomputed from the two bound deal lists; a volume compared on MT5's
      own equity is allowed only on a tick-generating leg AFTER that deal,
      with the pre-entry equity = tester ini Deposit + cumulative pnl of
      the leg's earlier deals, recomputed here; after it, every paired
      volume must use that basis; m1_ohlc never does. The expected lots
      are RECOMPUTED here (frozen_rule_lots on that equity, the frozen
      stop_distance of the event's frozen row, the pinned broker_spec):
      the package's python value must equal them (else INVALID) and the
      field's verdict is recomputed lots vs MT5 lots.
    * S8-SLTP-1 -- every paired event carries sl and tp, and their mt5
      values are the ones MT5's own entry request line states (re-parsed
      from the bound window copy whose bytes the log list names)."""
    problems: list[str] = []
    info: dict = {"entry_counts": {}, "tick_path": {}}
    evs = [e for e in events if isinstance(e, dict)]
    fields: dict = {}
    adjusted: dict[int, dict] = {}
    for model in sorted(log_docs):
        doc = log_docs[model]
        deals = [d for d in doc["deals"] if isinstance(d, dict)]
        mine = [e for e in evs if e.get("model") == model]
        paired = [e for e in mine if e.get("pairing") == PAIRED_BY_TIME]
        missing = [e for e in mine if e.get("pairing") == MISSING_IN_MT5]
        extra = [e for e in mine if e.get("pairing") == EXTRA_IN_MT5]
        n_entries = len(log_entry_deals(deals))
        info["entry_counts"][model] = {
            "paired": len(paired), "missing_in_mt5": len(missing),
            "extra_in_mt5": len(extra), "mt5_entry_deals": n_entries,
            "mt5_deals": len(deals)}
        fields[f"entry_count:{model}"] = {
            "python": len(paired) + len(missing), "mt5": n_entries}
        if len(paired) + len(extra) != n_entries:
            problems.append(
                f"{model}: S8-COUNT-1 PAIRED ({len(paired)}) + EXTRA_IN_MT5 "
                f"({len(extra)}) != the bound log list's entry deals "
                f"({n_entries})")
        if py_count > 0 and not any(e.get("pairing") in _PYTHON_SIDE_PAIRINGS
                                    for e in mine):
            problems.append(
                f"{model}: no python-side event at all while the frozen "
                f"python trade count is {py_count}: the expected in-window "
                "entries are not recorded, so entry_count cannot be compared")
        index_of = {d.get("ticket"): k for k, d in enumerate(deals)}

        # --- S8-TICKPATH-1 ------------------------------------------------
        div_idx = None
        if model in TICK_PATH_MODELS:
            ref = log_docs.get(TICK_PATH_REFERENCE)
            expect, note = (tick_path_divergence(ref["deals"], deals)
                            if ref is not None else
                            (None, f"no {TICK_PATH_REFERENCE} log leg"))
            rec = (tick_paths.get(model) or {}).get("record")
            key = ("deal_index", "ticket")
            if tuple((expect or {}).get(k) for k in key) != \
                    tuple((rec or {}).get(k) for k in key):
                problems.append(
                    f"{model}: recorded tick-path divergence "
                    f"{tuple((rec or {}).get(k) for k in key)} != the one "
                    "recomputed from the bound deal lists "
                    f"{tuple((expect or {}).get(k) for k in key)}")
            div_idx = expect["deal_index"] if expect else None
            info["tick_path"][model] = {"record": expect, "note": note}
        deposit = None
        if any(((e.get("fields") or {}).get("volume") or {}).get("basis")
               == VOLUME_BASIS_MT5_EQUITY for e in paired):
            raw, why = _bound_bytes(root, tester_ini_rel(gold, model))
            deposit = ini_deposit(raw) if raw is not None else None
            if deposit is None:
                problems.append(f"{model}: S8-TICKPATH-1 equity needs the "
                                f"bound tester ini Deposit: {why or 'absent'}")
        for e in paired:
            k = index_of.get(e.get("mt5_ticket"))
            vol = (e.get("fields") or {}).get("volume") or {}
            on_equity = vol.get("basis") == VOLUME_BASIS_MT5_EQUITY
            after = div_idx is not None and k is not None and k > div_idx
            if on_equity != after:
                problems.append(
                    f"{model}: ticket {e.get('mt5_ticket')} volume basis "
                    f"{vol.get('basis') or 'python path'!r} but the deal is "
                    f"{'after' if after else 'not after'} the tick-path "
                    "divergence")
                continue
            if on_equity and deposit is not None:
                eq = round(deposit + sum(float(d.get("pnl") or 0.0)
                                         for d in deals[:k]), 2)
                flat = 2 * len(log_entry_deals(deals[:k])) == k
                if e.get("mt5_pre_entry_equity") != eq or \
                        e.get("book_flat_at_entry") is not flat:
                    problems.append(
                        f"{model}: ticket {e.get('mt5_ticket')} records "
                        f"equity {e.get('mt5_pre_entry_equity')!r} / flat "
                        f"{e.get('book_flat_at_entry')!r}; the bound deals "
                        f"give {eq} / {flat}")
                    continue
                stop = ((sizing_ref or {}).get("stop_distance_by_row")
                        or {}).get(e.get("frozen_row_index"))
                if sizing_ref is None or stop is None:
                    problems.append(
                        f"{model}: ticket {e.get('mt5_ticket')} MT5-equity "
                        "volume not verifiable: no hash-pinned broker_spec "
                        "/ frozen stop_distance for frozen row "
                        f"{e.get('frozen_row_index')!r}")
                    continue
                from mql5bot.symbolspec import SymbolSpec

                lots = (frozen_rule_lots(
                    SymbolSpec(**sizing_ref["broker_spec"]),
                    sizing_ref["risk_config"], eq, stop) if flat else None)
                if vol.get("python") != lots:
                    problems.append(
                        f"{model}: ticket {e.get('mt5_ticket')} package "
                        f"states python volume {vol.get('python')!r}; the "
                        f"verifier recomputes {lots!r} (equity {eq}, frozen "
                        f"stop_distance {stop!r})")
                    continue
                if lots != vol.get("mt5"):
                    adjusted[id(e)] = {**e, "fields": {
                        **e["fields"], "volume": {
                            **vol, "status": "DIVERGENT",
                            "verifier_recomputed": lots}}}

        # --- S8-SLTP-1 ----------------------------------------------------
        levels: dict | None = None
        if paired:
            raw, why = _bound_bytes(root, log_window_rel(gold, model))
            if raw is None:
                problems.append(f"{model}: S8-SLTP-1 needs the bound window "
                                f"copy: {why}")
            elif hashlib.sha256(raw).hexdigest() != doc.get("window_sha256"):
                problems.append(f"{model}: window copy bytes != the log "
                                "trade list's window_sha256")
            else:
                symbol = (doc.get("settings") or {}).get("symbol") or ""
                levels = entry_request_levels(
                    raw.decode("utf-8-sig", errors="replace"), symbol)
        for e in paired:
            f = e.get("fields") or {}
            lv = (levels or {}).get(e.get("mt5_ticket"))
            for name in ("sl", "tp"):
                spec = f.get(name)
                if not isinstance(spec, dict) or "mt5" not in spec:
                    problems.append(f"{model}: ticket {e.get('mt5_ticket')} "
                                    f"carries no {name} field (S8-SLTP-1)")
                elif levels is not None and (lv is None
                                             or spec["mt5"] != lv[name]):
                    problems.append(
                        f"{model}: ticket {e.get('mt5_ticket')} {name} mt5="
                        f"{spec['mt5']!r} is not the request line's "
                        f"{(lv or {}).get(name)!r}")

        # --- S8-TS-1 ------------------------------------------------------
        for e in paired:
            f = e.get("fields") or {}
            ts = f.get("timestamp")
            if not isinstance(ts, dict) or ts.get("basis") != TS_BASIS_FILL_BAR:
                continue
            raw_time = e.get("mt5_time_raw")
            k = index_of.get(e.get("mt5_ticket"))
            why = []
            if k is None or deal_time_iso(deals[k].get("time")) != raw_time:
                why.append("raw MT5 time is not the bound deal's time")
            if ts.get("mt5") != str(raw_time)[:16]:
                why.append("mt5 minute is not the floor of the raw MT5 time")
            ep = f.get("entry_price")
            if not (isinstance(ep, dict) and ep.get("python") is not None
                    and ep.get("python") == ep.get("mt5")
                    and ep.get("status") != "DIVERGENT"):
                why.append("no exact entry_price match on this event")
            if why:
                cur = adjusted.get(id(e), e)
                adjusted[id(e)] = {**cur, "fields": {
                    **cur["fields"], "timestamp": {
                        **ts, "status": "DIVERGENT",
                        "s8_ts1_refused": why}}}
    derived = {"index": -1, "symbol": None, "derived": True,
               "source": TRADE_SOURCE_LOG, "fields": fields}
    out = [adjusted.get(id(e), e) for e in events]
    return derived, out, problems, info


def verify_reconciliation(root: Path | str, gold: str, frozen: dict,
                          model_identities: dict) -> dict:
    """Binding chain + field-by-field reconciliation for one gold.

    The reconciliation artifact must bind SOURCE→FIXTURE→CONFIG→
    DATASET→SYMBOLSPEC→EX5→TESTER MODEL→REPORT; any broken edge
    invalidates the leg.

    ANCHORING SCOPE (be precise — do not overclaim): the reconciliation
    must DECLARE the exact frozen ``expected_execution_sha256`` (checked
    below against the frozen record, so it cannot name a different
    expected-execution artifact), it must carry an MT5 observation for
    every reconciled field (completeness gate below), and no field may
    diverge python↔mt5. What is NOT enforced here: byte-level anchoring of
    each event's python column to the bytes of ``expected_execution.json``.
    That artifact is the FROZEN reference (``artifacts/gold*/…``); it is
    not part of the owner evidence LAYOUT and there is no defined
    projection from the per-bar events onto it, so the python column is
    trusted to the extent that the owner declared the correct frozen
    expected-execution hash. Full byte-level python-column anchoring is an
    OWNER/BUILD-side follow-up (same class as the empty ``gold_1
    .config_hash`` note in docs/DECISIONS.md 2026-09-16 Wave 2.2).
    """
    root = Path(root)
    path = root / LAYOUT[f"reconciliation_{gold}"]
    if not path.is_file():
        return {"state": MISSING, "reasons": [(f"{gold} reconciliation "
                                               "missing")]}
    doc = _load_json(path)
    if not isinstance(doc, dict):
        return {"state": INVALID, "reasons": [("reconciliation "
                                              "unparsable")]}

    log_models = {m for g, m in log_sourced_legs(root) if g == gold}
    na_models = {m for g, m in not_applicable_legs(root) if g == gold}
    report_models = set(MODELS) - log_models - na_models
    report: dict = {"state": PRESENT_UNVERIFIED, "reasons": [],
                    "gold": gold,
                    "trade_sources": {
                        m: (TRADE_SOURCE_NOT_APPLICABLE if m in na_models
                            else TRADE_SOURCE_LOG if m in log_models
                            else TRADE_SOURCE_REPORT) for m in MODELS}}
    if na_models:
        report["not_applicable_models"] = sorted(na_models)
    # the comparison as recorded, visible whatever the verdict below
    observed = _observed_divergences(doc.get("events"))
    for key, div in observed.items():
        report[key] = _add_trade_context(div, doc.get("events") or [])

    # --- binding chain (§22) -------------------------------------------
    bindings = doc.get("bindings") or {}
    # the report-hash maps may be empty only when EVERY model is log-sourced
    optional = ({"raw_report_hashes", "parsed_report_hashes"}
                if not report_models else set())
    broken = [f for f in _BINDING_FIELDS
              if f not in optional and (not bindings.get(f)
                                        or bindings.get(f) == "PENDING_OWNER")]
    if broken:
        report["state"] = INVALID
        report["reasons"].append(f"binding chain broken at: {broken}")
        return report
    fman = frozen.get(gold, {})
    # source_commit: == the anchor, or S8-ANCHOR-REL-1's descendant relation
    # (``frozen["relation_of"]``, bound to a repository by run_gate)
    src_rel = None
    if frozen.get("source_commit"):
        src_rel = source_commit_relation(bindings.get("source_commit"),
                                         frozen["source_commit"],
                                         frozen.get("relation_of"))
        report["source_commit_relation"] = src_rel
    cross = (
        ("fixture_sha256", fman.get("fixture_sha256")),
        ("config_hash", fman.get("config_hash")),
        ("dataset_hash", fman.get("dataset_hash_from_manifest")),
        # anchor the PYTHON reference to the frozen truth engine: the
        # reconciliation must DECLARE the exact frozen expected-execution
        # hash (this cross-check forces the declared binding to equal the
        # frozen constant, so the owner cannot name a different
        # expected-execution artifact). NOTE: this does not byte-verify the
        # events' python column against expected_execution.json — see the
        # ANCHORING SCOPE note in the docstring; that is an owner/build
        # follow-up.
        ("expected_execution_sha256",
         fman.get("expected_execution_sha256")),
    )
    mism = [name for name, expected in cross
            if expected and str(bindings.get(name)) != str(expected)]
    if src_rel is not None and not src_rel["accepted"]:
        mism.insert(0, "source_commit")
    if mism:
        report["state"] = MISMATCHED
        report["reasons"].append(
            f"bindings disagree with the frozen record: {mism}"
            + (f" (source_commit: {'; '.join(src_rel['reasons'])})"
               if "source_commit" in mism and src_rel["reasons"] else ""))
        return report

    # the binding hashes must equal the ACTUAL bytes on disk — a
    # downstream record can never conceal upstream tampering
    ex5_path = root / LAYOUT["ex5"]
    spec_path = root / LAYOUT["symbolspec"]
    if ex5_path.is_file() and bindings.get("ex5_sha256") != \
            sha256_file(ex5_path):
        report["state"] = MISMATCHED
        report["reasons"].append("ex5_sha256 binding does not match the "
                                 "actual EX5 bytes")
        return report
    if spec_path.is_file() and bindings.get("symbolspec_sha256") != \
            sha256_file(spec_path):
        report["state"] = MISMATCHED
        report["reasons"].append("symbolspec_sha256 binding does not "
                                 "match the actual SymbolSpec bytes")
        return report
    rrh = bindings.get("raw_report_hashes") or {}
    if not isinstance(rrh, dict) or set(rrh) != report_models:
        report["state"] = INVALID
        report["reasons"].append(
            "raw_report_hashes must bind every report-sourced model: "
            f"{sorted(report_models)} (log-sourced: {sorted(log_models)})")
        return report
    log_docs, log_problems = _verify_log_trades(root, gold, log_models,
                                                bindings)
    if log_problems:
        report["state"] = MISMATCHED
        report["reasons"].append("log trade list binding broken: "
                                 + "; ".join(log_problems))
        return report
    bad_raw = []
    for model in sorted(report_models):
        rpath = root / LAYOUT[f"raw_{gold}_{model}"]
        if not rpath.is_file():
            bad_raw.append(f"{model}: missing raw report")
        elif rrh[model] != sha256_file(rpath):
            bad_raw.append(f"{model}: raw report bytes changed")
    if bad_raw:
        report["state"] = MISMATCHED
        report["reasons"].append("raw report binding broken: "
                                 + "; ".join(bad_raw))
        return report
    prh = bindings.get("parsed_report_hashes") or {}
    if not isinstance(prh, dict) or set(prh) != report_models:
        report["state"] = INVALID
        report["reasons"].append(
            "parsed_report_hashes must bind every report-sourced model: "
            f"{sorted(report_models)} (log-sourced: {sorted(log_models)})")
        return report
    bad_reports = []
    for model in sorted(report_models):
        rpath = root / LAYOUT[f"parsed_{gold}_{model}"]
        if not rpath.is_file():
            bad_reports.append(f"{model}: missing parsed report")
        elif prh[model] != sha256_file(rpath):
            bad_reports.append(f"{model}: parsed report bytes changed")
    if bad_reports:
        report["state"] = MISMATCHED
        report["reasons"].append("report binding broken: "
                                 + "; ".join(bad_reports))
        return report

    # --- tester-model identity for each bound model --------------------
    # tester_models is a REQUIRED binding (above) and must cover EVERY
    # model: otherwise the "was the intended tester model actually used?"
    # check could be silently skipped for a gold leg by omitting its entry.
    tmods = bindings.get("tester_models")
    if not isinstance(tmods, dict) or not set(MODELS) <= set(tmods):
        report["state"] = INVALID
        report["reasons"].append(
            f"tester_models must bind every model: {sorted(MODELS)}")
        return report
    for model, triad in tmods.items():
        claims_na = isinstance(triad, dict) and triad.get("not_applicable")
        if model in na_models or claims_na:
            # a NOT_APPLICABLE leg never ran: its triad must say so
            # explicitly, and only a leg the stage-5 record marks
            # NOT_APPLICABLE may say so -- never a fabricated model
            if model not in na_models:
                report["state"] = MISMATCHED
                report["reasons"].append(
                    f"{model}: tester_models claims not_applicable but the "
                    "gate's stage-5 record does not mark it NOT_APPLICABLE")
            elif claims_na is not True or \
                    triad.get("outcome") != STAGE5_NOT_APPLICABLE or \
                    triad.get("report_reported") is not None or \
                    triad.get("log_reported") is not None:
                report["state"] = MISMATCHED
                report["reasons"].append(
                    f"{model}: NOT_APPLICABLE leg must be bound as "
                    "{not_applicable: true, outcome: "
                    f"{STAGE5_NOT_APPLICABLE}}} with no reported model")
            else:
                model_identities[f"{gold}:{model}"] = {
                    "state": VALID, "reasons": [],
                    "model_source": TRADE_SOURCE_NOT_APPLICABLE,
                    "not_applicable": True}
            continue
        if model in log_models:
            # no report states the model: the log trade list does (the model
            # MT5 said it ran, from the leg's own window). The triad must
            # carry it as `log_reported` and agree with the list.
            stated = (log_docs[model].get("settings") or {}).get("model")
            log_reported = triad.get("log_reported")
            if log_reported is None or stated is None or \
                    str(log_reported).lower() != str(stated).lower():
                report["state"] = MISMATCHED
                report["reasons"].append(
                    f"{model}: log_reported {log_reported!r} does not equal "
                    f"the model the log trade list states ({stated!r})")
                continue
            triad = {**triad, "report_reported": log_reported}
        ident = verify_model_identity(triad)
        ident["model_source"] = (TRADE_SOURCE_LOG if model in log_models
                                 else TRADE_SOURCE_REPORT)
        model_identities[f"{gold}:{model}"] = ident
        if ident["state"] != VALID:
            report["state"] = MISMATCHED
            report["reasons"].extend(ident["reasons"])
    if report["state"] == MISMATCHED:
        return report

    # --- events: python column must equal the frozen expectation -------
    events = doc.get("events")
    derived: list[dict] = []
    if log_models:
        # S8-COUNT-1 (owner decision 2026-10-06): the frozen python trade
        # count (all frozen trades, whole range) and len(deals) (entries +
        # exits, tester window only) are different units and ranges. The
        # derived event is entry_count:<model> -- expected in-window
        # entries vs the bound log list's entry deals. A ZERO-deal list
        # stays an honest observation: 0 MT5 entries against N > 0
        # expected in-window entries diverges. The frozen count is kept
        # (recorded, uncompared) for the python-side presence guard.
        py_count = fman.get("python_trade_count")
        if not isinstance(py_count, int):
            report["state"] = INVALID
            report["reasons"].append(
                f"{gold}: no hash-verified Python trade count in the frozen "
                "record, so log-sourced entry counts cannot be guarded")
            return report
        if not isinstance(events, list):
            report["state"] = INVALID
            report["reasons"].append("reconciliation carries no events")
            return report
        count_event, events, problems, leg_info = _log_leg_checks(
            root, gold, log_docs, events,
            doc.get("tick_path_divergence") or {}, py_count,
            fman.get("sizing_reference"))
        report["log_trade_counts"] = {
            m: len(log_docs[m]["deals"]) for m in sorted(log_models)}
        report["entry_counts"] = leg_info["entry_counts"]
        report["tick_path_divergence"] = leg_info["tick_path"]
        report["python_trade_count"] = py_count
        if problems:
            report["state"] = INVALID
            report["reasons"].extend(problems)
            return report
        derived.append(count_event)
    if not isinstance(events, list) or (not events and report_models):
        # empty owner events are acceptable only when every model's trades
        # come from a log list (the derived counts then carry the comparison)
        report["state"] = INVALID
        report["reasons"].append("reconciliation carries no events")
        return report
    events = derived + events

    # A real python<->MT5 reconciliation must actually carry the MT5 side.
    # `_field_divergent` treats a field with no `mt5` key (or mt5 null) as
    # NON-divergent, so a python-only package — one never run on MT5 —
    # would otherwise reach MATCH/VALID and feed MT5_VALIDATED. Reject
    # incompleteness here, fail-closed: every reconciled field (a dict
    # carrying a `python` value) MUST also carry a non-null `mt5`
    # observation, and there must be at least one such field.
    reconciled = incomplete = 0
    for event in events:
        for spec in (event.get("fields") or {}).values():
            if isinstance(spec, dict) and "python" in spec:
                reconciled += 1
                if spec.get("mt5") is None:
                    incomplete += 1
    if reconciled == 0:
        report["state"] = INVALID
        report["reasons"].append(
            "reconciliation events carry no comparable python/mt5 fields")
        return report
    if incomplete:
        report["state"] = INVALID
        report["reasons"].append(
            f"reconciliation incomplete: {incomplete} field(s) carry a "
            "python value with no MT5 observation (mt5 null/missing) — the "
            "gold lane requires a real MT5 side for every reconciled field")
        return report

    div = _add_trade_context(first_divergence(events), events)
    if div is not None:
        div["binding_verified"] = True
    report["first_divergence"] = div
    trade_div = _add_trade_context(first_divergence(
        [e for e in events if "trade_index" in e]), events)
    if trade_div is not None:
        trade_div["binding_verified"] = True
    report["first_trade_divergence"] = trade_div
    if div is None:
        report["state"] = VALID
        report["result"] = "MATCH"
    else:
        report["state"] = MISMATCHED
        report["result"] = "DIVERGENT"
        report["reasons"].append(
            f"first divergence at event {div['event_index']} field "
            f"{div['first_divergent_field']!r}: python="
            f"{div['python_value']!r} mt5={div['mt5_value']!r} -> "
            f"{div['classification']}")
    return report


# ---------------------------------------------------------------------------
# 7. safety runtime evidence (§20/§21: raw evidence, never screenshots)
# ---------------------------------------------------------------------------
_SAFETY_FIELDS = ("action", "initial_state", "resulting_state",
                  "observed_result", "expected_result", "raw_evidence")
# SAFETY-RESULT-1 (owner review of PR #31): the required outcome of each
# tester-runnable safety test is pinned HERE, never read from the file, and
# the verifier re-grades the bound windows itself (_regrade_safety).
SAFETY_PINNED_EXPECTED = {
    "kill_switch": "ZERO_NEW_ORDERS_WHILE_LATCHED",
    "risk_veto": "ENTRIES_VETOED_FOR_THE_DAY",
    "meta_reduce": "ALL_SIZES_LE_RISK_APPROVED",
    "sl_verify": "SL_STRIPPED_AND_RESTORED",
}
_BASELINE_RE = re.compile(r"^safety/raw/baseline_(gold\d)_m1_ohlc_window\.txt$")


def _regrade_safety(root: Path, name: str, doc: dict
                    ) -> tuple[str | None, str]:
    """Re-grade a tester safety file from its BOUND windows (the test
    window = raw_evidence, the baseline = baseline_evidence; both must be
    bound by archive_manifest.json with bytes equal to the file's declared
    hashes) with mql5bot.safety_legs. Returns (observed_result, problem)."""
    from mql5bot import safety_legs as sl

    raw_ref = doc.get("raw_evidence") or {}
    base_ref = doc.get("baseline_evidence")
    if not isinstance(base_ref, dict):
        return None, f"{name}: no baseline_evidence binding to re-grade with"
    m = _BASELINE_RE.match(str(base_ref.get("path") or ""))
    if not m or m.group(1) not in GOLD_TESTER_SYMBOLS:
        return None, (f"{name}: baseline_evidence is not a gold m1_ohlc "
                      "window (safety/raw/baseline_<gold>_m1_ohlc_window.txt)")
    texts = []
    for ref in (raw_ref, base_ref):
        data, why = _bound_bytes(root, str(ref.get("path") or ""))
        if data is None:
            return None, f"{name}: {why}"
        if hashlib.sha256(data).hexdigest() != str(ref.get("sha256")).lower():
            return None, (f"{name}: {ref.get('path')} bytes != the file's "
                          "declared sha256")
        texts.append(data.decode("utf-8-sig", errors="replace"))
    regraded = sl.grade(name, texts[0], texts[1],
                        GOLD_TESTER_SYMBOLS[m.group(1)])
    return regraded["observed_result"], ""


def verify_safety(root: Path | str) -> dict:
    root = Path(root)
    out: dict[str, dict] = {}
    for name in SAFETY_TESTS + ("netting", "hedging"):
        path = root / LAYOUT.get(name, f"safety/{name}.json")
        if not path.is_file():
            out[name] = {"state": MISSING,
                         "reasons": [f"{name} evidence missing"]}
            continue
        doc = _load_json(path)
        if not isinstance(doc, dict):
            out[name] = {"state": INVALID,
                         "reasons": [f"{name} evidence unparsable"]}
            continue
        if doc.get("blocked_owner_environment"):
            # legitimate ONLY for hedging on an account that cannot
            # exercise it — recorded, never a fabricated pass
            if name == "hedging":
                out[name] = {"state": VALID,
                             "result": "BLOCKED_OWNER_ENVIRONMENT",
                             "reasons": []}
            else:
                out[name] = {"state": INVALID,
                             "reasons": [(f"{name} may not claim an "
                                         "environment blocker")]}
            continue
        missing = [f for f in _SAFETY_FIELDS
                   if not doc.get(f) or doc.get(f) == "PENDING_OWNER"]
        if missing:
            out[name] = {"state": INVALID,
                         "reasons": [f"{name} missing fields: {missing}"]}
            continue
        ev = doc.get("raw_evidence")
        # FILE-BOUND: {"path", "sha256"} inside the evidence root.
        # A filename string, a "journal:..." claim, prose, or a
        # screenshot is NOT evidence.
        state, reason, epath = _resolve_evidence(root, ev, name)
        if state != "VALID":
            out[name] = {"state": state, "reasons": [reason]}
            continue
        if epath.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif",
                                    ".bmp"):
            out[name] = {"state": INVALID,
                         "reasons": [(f"{name} evidence is screenshot-"
                                     "only — raw artifacts required")]}
            continue
        if name in SAFETY_PINNED_EXPECTED:
            pinned = SAFETY_PINNED_EXPECTED[name]
            if doc.get("expected_result") != pinned:
                out[name] = {"state": INVALID, "reasons": [
                    (f"{name} expected_result "
                     f"{doc.get('expected_result')!r} is not the pinned "
                     f"{pinned!r}")]}
                continue
            regraded, why = _regrade_safety(root, name, doc)
            if why:
                out[name] = {"state": INVALID, "reasons": [why]}
                continue
            if regraded != doc.get("observed_result"):
                out[name] = {"state": INVALID, "result": regraded,
                             "reasons": [
                                 (f"{name} file states "
                                  f"{doc.get('observed_result')!r}; the "
                                  "verifier re-grades the bound windows "
                                  f"as {regraded!r}")]}
                continue
        # SAFETY-RESULT-1 (2026-10-06): a safety file is VALID only when
        # what MT5 showed IS the required outcome. A failed or inconclusive
        # test is recorded with its observation, never accepted as evidence
        # (before, any observed_result -- even a failure -- was VALID).
        if doc.get("observed_result") != doc.get("expected_result"):
            out[name] = {"state": INVALID,
                         "result": doc.get("observed_result"),
                         "reasons": [(f"{name} observed "
                                     f"{doc.get('observed_result')!r}, "
                                     "required "
                                     f"{doc.get('expected_result')!r}")]}
            continue
        out[name] = {"state": VALID,
                     "result": doc.get("observed_result"), "reasons": []}
    return out


def verify_environment(root: Path | str) -> dict:
    """Environment metadata must bind the run and agree with the owner
    SymbolSpec — a contradiction between evidence classes is itself a
    finding (§9)."""
    root = Path(root)
    path = root / LAYOUT["environment"]
    if not path.is_file():
        return {"state": MISSING, "reasons": [("environment metadata "
                                              "missing")]}
    doc = _load_json(path)
    if not isinstance(doc, dict):
        return {"state": INVALID, "reasons": [("environment metadata "
                                              "unparsable")]}
    required = ("os", "terminal_build", "broker", "server",
                "account_mode", "symbol", "timezone", "run_timestamp")
    missing = [f for f in required
               if not doc.get(f) or doc.get(f) == "PENDING_OWNER"]
    if missing:
        return {"state": INVALID,
                "reasons": [(f"environment metadata missing fields: "
                            f"{missing}")]}
    spec = _load_json(root / LAYOUT["symbolspec"])
    reasons = []
    if isinstance(spec, dict):
        for field in ("broker", "server", "symbol"):
            if spec.get(field) and doc.get(field) != spec.get(field):
                reasons.append(f"environment {field} contradicts the "
                               "owner SymbolSpec")
    if reasons:
        return {"state": MISMATCHED, "reasons": reasons}
    return {"state": VALID, "reasons": []}


def _gold_keys(gold: str) -> set[str]:
    """LAYOUT keys that belong to one gold (reports + reconciliation)."""
    return ({f"{kind}_{gold}_{m}" for kind in ("raw", "parsed")
             for m in MODELS} | {f"reconciliation_{gold}"})


def verify_archive_manifest(root: Path | str, frozen: dict,
                            golds: tuple[str, ...] = GOLDS) -> dict:
    """The manifest must bind EVERY required artifact by hash plus the
    source/fixture/config identities — a manifest that merely lists
    filenames proves nothing (§10)."""
    root = Path(root)
    path = root / LAYOUT["archive_manifest"]
    if not path.is_file():
        return {"state": MISSING, "reasons": [("archive manifest "
                                              "missing")]}
    doc = _load_json(path)
    if not isinstance(doc, dict):
        return {"state": INVALID, "reasons": [("archive manifest "
                                              "unparsable")]}
    arts = doc.get("artifacts")
    if not isinstance(arts, dict):
        return {"state": INVALID,
                "reasons": [("archive manifest lists no artifact hash "
                            "map — filenames alone are not a binding")]}
    # every mandatory artifact except the manifest itself must be bound
    log_legs = {(g, m) for g, m in log_sourced_legs(root) if g in golds}
    na_legs = {(g, m) for g, m in not_applicable_legs(root) if g in golds}
    replaced = {f"{kind}_{g}_{m}" for g, m in log_legs | na_legs
                for kind in ("raw", "parsed")}
    for gold in set(GOLDS) - set(golds):     # a scoped run binds its golds
        replaced |= _gold_keys(gold)
    required = [rel for key, rel in LAYOUT.items()
                if key != "archive_manifest" and key not in replaced]
    required += [log_trades_rel(g, m) for g, m in sorted(log_legs)]
    # S8-SLTP-1: the window copy the request-line sl/tp are read from
    required += [log_window_rel(g, m) for g, m in sorted(log_legs)]
    if na_legs:
        required.append(GATE_STAGE5_REL)
    unbound = [rel for rel in required if rel not in arts]
    if unbound:
        return {"state": INVALID,
                "reasons": [(f"archive manifest does not bind: "
                            f"{sorted(unbound)}")]}
    bad = []
    for rel, digest in arts.items():
        fpath = root / rel
        if not fpath.is_file():
            bad.append(f"{rel}: bound file missing")
        elif not isinstance(digest, str) or len(digest) != 64:
            bad.append(f"{rel}: no SHA-256 recorded")
        elif sha256_file(fpath) != digest.lower():
            bad.append(f"{rel}: bytes do not match recorded hash")
    if bad:
        return {"state": MISMATCHED, "reasons": sorted(bad)}
    # provenance identities must agree with the frozen record
    ident = doc.get("identity") or {}
    cross = [("source_commit", frozen.get("source_commit")),
             ("gold1_fixture_sha256",
              frozen.get("gold_1", {}).get("fixture_sha256")),
             ("gold2_fixture_sha256",
              frozen.get("gold_2", {}).get("fixture_sha256"))]
    mism = [name for name, expected in cross
            if expected and str(ident.get(name)) != str(expected)]
    if mism:
        return {"state": MISMATCHED,
                "reasons": [(f"manifest identity disagrees with the "
                            f"frozen record: {mism}")]}
    return {"state": VALID, "reasons": []}


# ---------------------------------------------------------------------------
# 8. freeze-anchor change classification (§5)
# ---------------------------------------------------------------------------

def classify_anchor_changes(changed_paths: list[str]) -> dict:
    """EXECUTION_RELEVANT vs NON_EXECUTION_RELEVANT for every file
    changed since the freeze anchor. A documentation-only commit never
    invalidates the golds; an execution-relevant change never hides
    behind the anchor."""
    execution, non_execution = [], []
    for p in changed_paths:
        norm = p.replace("\\", "/")
        if any(norm.startswith(pref) for pref in EXECUTION_RELEVANT_PREFIXES):
            execution.append(norm)
        else:
            non_execution.append(norm)
    return {"execution_relevant": execution,
            "non_execution_relevant": non_execution,
            "golds_still_frozen": not execution}


# ---------------------------------------------------------------------------
# 9. the gate: completeness -> identity -> reconciliation -> verdict
# ---------------------------------------------------------------------------

def run_gate(evidence_dir: Path | str, frozen_inputs: dict,
             golds: tuple[str, ...] | list[str] = GOLDS,
             repo: Path | str | None = None) -> dict:
    """Consume the owner directory; produce the machine-readable report
    and the explainable verdict. Never returns a positive verdict on
    missing, stale, wrong, partial or simulated evidence.

    ``repo`` binds S8-ANCHOR-REL-1: a recorded source commit other than the
    anchor is accepted only when anchor_relation() in that repository says
    DESCENDANT_FROZEN_BYTES_IDENTICAL. Without it only HEAD == anchor is.

    ``golds`` scopes the verification (owner_gate.ps1 -Golds). A scoped run
    examines ONLY those golds; the others are OUT_OF_SCOPE (not missing, not
    verified), and the best verdict it can reach is
    MT5_VALIDATED_PARTIAL_SCOPE, which is not a positive verdict."""
    unknown = sorted(set(golds) - set(GOLDS))
    if unknown or not golds:
        raise ValueError(f"unknown or empty gold scope: {list(golds)}")
    scope = tuple(g for g in GOLDS if g in golds)
    partial = scope != GOLDS
    excluded = [{"gold": g, "reason": "excluded from this scoped "
                 "verification: not examined, not validated"}
                for g in GOLDS if g not in scope]
    scope_fields = {"scope": list(scope), "partial": partial,
                    "excluded": excluded}
    root = Path(evidence_dir)
    if not root.is_dir():
        return {"verdict": NOT_VERIFIED_MISSING_MT5_EVIDENCE,
                "reasons": [f"evidence directory missing: {root}"],
                "artifacts": {}, "gold": {}, "safety": {},
                "missing": sorted(LAYOUT), **scope_fields}

    scan = scan_package(root)
    for gold in GOLDS:
        if gold in scope:
            continue
        for key in _gold_keys(gold):
            scan[key]["state"] = OUT_OF_SCOPE
        for key in [k for k in scan if k.startswith(f"log_trades_{gold}_")]:
            scan[key]["state"] = OUT_OF_SCOPE
    missing = sorted(k for k, v in scan.items() if v["state"] == MISSING)
    ambiguous = sorted(k for k, v in scan.items()
                       if v["state"] == INVALID)

    frozen_source = frozen_inputs.get("source", {}).get("commit", "")
    relations: dict[str, dict] = {}

    def relation_of(commit: str) -> dict:
        if commit not in relations:
            relations[commit] = anchor_relation(repo, frozen_source, commit,
                                                frozen_inputs)
        return relations[commit]

    rel_fn = relation_of if repo is not None else None
    compile_rep = verify_compile(root, frozen_source, rel_fn)
    spec_expected = frozen_inputs.get("symbolspec_expectations")
    spec_rep = verify_symbolspec(root, spec_expected if isinstance(
        spec_expected, dict) else None)
    cov_rep = verify_real_tick_coverage(root)
    na_legs = sorted(f"{g}:{m}" for g, m in not_applicable_legs(root)
                     if g in scope)
    if na_legs and cov_rep["state"] == VALID and \
            cov_rep["coverage"] != REAL_TICK_COVERAGE_NONE:
        # a leg that never ran cannot sit beside a coverage claim
        cov_rep = {**cov_rep, "state": MISMATCHED,
                   "reasons": cov_rep["reasons"] + [
                       (f"real_ticks NOT_APPLICABLE for {na_legs} but the "
                        f"coverage record says {cov_rep['coverage']!r}, not "
                        f"{REAL_TICK_COVERAGE_NONE!r}")]}

    model_identities: dict = {}
    gold_reps = {
        g: verify_reconciliation(root, g, {
            "source_commit": frozen_source,
            "relation_of": rel_fn,
            "gold1": frozen_inputs.get("gold_1", {}),
            "gold2": frozen_inputs.get("gold_2", {}),
        }, model_identities) for g in scope}

    safety_rep = verify_safety(root)
    env_rep = verify_environment(root)
    man_rep = verify_archive_manifest(root, {
        "source_commit": frozen_source,
        "gold_1": frozen_inputs.get("gold_1", {}),
        "gold_2": frozen_inputs.get("gold_2", {}),
    }, scope)

    # ---- verdict ladder (fail-closed, explainable) --------------------
    reasons: list[str] = []
    if missing:
        reasons.append(f"missing artifacts: {missing}")
    if ambiguous:
        reasons.append(f"ambiguous/invalid artifacts: {ambiguous}")
    if compile_rep["state"] != VALID:
        reasons.append(f"compile evidence {compile_rep['state']}: "
                       f"{compile_rep['reasons'] or 'artifact absent'}")
    if spec_rep["state"] in (MISSING, INVALID, MISMATCHED):
        reasons.append(f"symbolspec {spec_rep['state']}: "
                       f"{spec_rep['reasons'] or 'artifact absent'}")
    for key, ident in model_identities.items():
        if ident["state"] != VALID:
            reasons.append(f"model identity {key}: {ident['reasons']}")

    recon_missing = [g for g, r in gold_reps.items()
                     if r["state"] == MISSING]
    recon_bad = [g for g, r in gold_reps.items()
                 if r["state"] in (INVALID, MISMATCHED)]
    if recon_missing:
        reasons.append(f"reconciliation missing for: {recon_missing}")
    if recon_bad:
        reasons.append(f"reconciliation invalid/mismatched for: "
                       f"{recon_bad}")
    if env_rep["state"] in (INVALID, MISMATCHED):
        reasons.append(f"environment {env_rep['state']}: "
                       f"{env_rep['reasons']}")
    if man_rep["state"] in (INVALID, MISMATCHED):
        reasons.append(f"archive manifest {man_rep['state']}: "
                       f"{man_rep['reasons']}")
    safety_missing = [n for n, r in safety_rep.items()
                      if r["state"] == MISSING]
    safety_invalid = [n for n, r in safety_rep.items()
                      if r["state"] == INVALID]
    if safety_missing:
        reasons.append(f"safety evidence missing: {safety_missing}")
    if safety_invalid:
        reasons.append(f"safety evidence invalid: {safety_invalid}")

    # ladder order matters: identity/integrity failures are MISMATCH;
    # absence of evidence is MISSING/RECONCILIATION_MISSING; coverage
    # limits are their own explicit state. The ceiling this gate can
    # ever assign is MT5_VALIDATED — empirical/demo/VERIFIED belong to
    # later, separate evidence layers.
    # MISMATCH requires evidence that EXISTS but is wrong/inconsistent;
    # absent evidence is MISSING / RECONCILIATION_MISSING instead.
    if (ambiguous or recon_bad or safety_invalid
            or compile_rep["state"] in (INVALID, MISMATCHED, STALE)
            or spec_rep["state"] in (INVALID, MISMATCHED)
            or env_rep["state"] in (INVALID, MISMATCHED)
            or man_rep["state"] in (INVALID, MISMATCHED)
            or cov_rep["state"] == MISMATCHED
            or any(i["state"] != VALID for i in model_identities.values())):
        verdict = NOT_VERIFIED_ARTIFACT_MISMATCH
    elif recon_missing:
        verdict = NOT_VERIFIED_RECONCILIATION_MISSING
    elif (missing or safety_missing
            or compile_rep["state"] == MISSING
            or spec_rep["state"] == MISSING):
        verdict = NOT_VERIFIED_MISSING_MT5_EVIDENCE
    elif cov_rep["state"] != VALID:
        verdict = NOT_VERIFIED_MISSING_MT5_EVIDENCE
        reasons.append(f"real-tick coverage record {cov_rep['state']}: "
                       f"{cov_rep['reasons']}")
    elif cov_rep["coverage"] == REAL_TICK_COVERAGE_NONE:
        # S8-CEILING-1: a VALID NONE record (state checked above) -- the
        # bar models validated, nothing claimed about real ticks
        verdict = MT5_VALIDATED_BAR_MODELS
    elif cov_rep["coverage"] != "REAL_TICK_COVERAGE_FULL":
        # PARTIAL keeps the limitation explicit; UNKNOWN never promotes
        verdict = NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN
    else:
        verdict = MT5_VALIDATED

    if verdict == MT5_VALIDATED:
        reasons = [("all owner evidence verified against the frozen "
                   "record — gold parity holds on the owner terminal")]
    elif verdict == MT5_VALIDATED_BAR_MODELS:
        reasons = [("all owner evidence verified against the frozen "
                    "record on the bar models — " + BAR_MODELS_REASON)]
    if partial:
        if verdict == MT5_VALIDATED:
            verdict = MT5_VALIDATED_PARTIAL_SCOPE
            reasons = [(f"scoped verification of {list(scope)} only: its "
                        "evidence verified against the frozen record")]
        elif verdict == MT5_VALIDATED_BAR_MODELS:
            verdict = MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE
            reasons = [(f"scoped verification of {list(scope)} only: its "
                        "evidence verified against the frozen record on "
                        "the bar models — " + BAR_MODELS_REASON)]
        reasons.append(f"PARTIAL: excluded {[e['gold'] for e in excluded]} "
                       "were not examined — this verifies nothing about "
                       "them and certifies nothing")
    if na_legs:
        reasons.append(f"{na_legs}: {STAGE5_NOT_APPLICABLE} (bar-only "
                       "fixture, leg not launched): no report exists and "
                       "none is required; real-tick coverage NONE never "
                       "yields MT5_VALIDATED")
    log_legs = sorted(f"{g}:{m}" for g, m in log_sourced_legs(root)
                      if g in scope)
    if log_legs:
        # never let a log-sourced leg read as report-backed evidence
        reasons.append(f"trade source for {log_legs}: {TRADE_SOURCE_LOG} "
                       "(PASS_FROM_LOG log trade list; no report exists)")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "artifacts": scan,
        "compile": compile_rep,
        "symbolspec": spec_rep,
        "real_tick_coverage": cov_rep,
        "model_identities": model_identities,
        "gold": gold_reps,
        "safety": safety_rep,
        "environment": env_rep,
        "archive_manifest": man_rep,
        "missing": missing,
        "first_divergence": {g: r.get("first_divergence")
                             for g, r in gold_reps.items()},
        "first_trade_divergence": {g: r.get("first_trade_divergence")
                                   for g, r in gold_reps.items()},
        "not_applicable_legs": na_legs,
        "trade_sources": {g: r.get("trade_sources")
                          for g, r in gold_reps.items()},
        "log_sourced_legs": log_legs,
        **scope_fields,
    }


__all__ = [
    "ARTIFACT_STATES",
    "BAR_MODELS_REASON",
    "DECISION_CHANGING_MISMATCH",
    "DEMO_VALIDATED",
    "EMPIRICAL_VALIDATED",
    "EXACT_MATCH",
    "FIELD_CLASS",
    "GATE_STAGE5_REL",
    "GOLDS",
    "INVALID",
    "LAYOUT",
    "LOG_SOURCED",
    "LOG_TRADE_LIST_SCHEMA",
    "MISMATCHED",
    "MISSING",
    "MODELS",
    "MODEL_LABELS",
    "MT5_VALIDATED",
    "MT5_VALIDATED_BAR_MODELS",
    "MT5_VALIDATED_BAR_MODELS_PARTIAL_SCOPE",
    "MT5_VALIDATED_PARTIAL_SCOPE",
    "NOT_APPLICABLE",
    "NOT_VERIFIED_ARTIFACT_MISMATCH",
    "NOT_VERIFIED_MISSING_MT5_EVIDENCE",
    "NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN",
    "NOT_VERIFIED_RECONCILIATION_MISSING",
    "OUT_OF_SCOPE",
    "PENDING_OWNER",
    "POSITIVE_VERDICTS",
    "PRESENT_UNVERIFIED",
    "REAL_TICK_COVERAGES",
    "REAL_TICK_COVERAGE_NONE",
    "SAFETY_TESTS",
    "SEMANTICALLY_COMPATIBLE",
    "STAGE5_NOT_APPLICABLE",
    "STALE",
    "SYMBOLSPEC_CLASSES",
    "SYMBOLSPEC_REQUIRED",
    "TAXONOMY",
    "TRADE_SOURCE_LOG",
    "TRADE_SOURCE_NOT_APPLICABLE",
    "TRADE_SOURCE_REPORT",
    "UNSUPPORTED_BROKER_DIFFERENCE",
    "VALID",
    "VERIFIED",
    "classify_anchor_changes",
    "classify_field",
    "first_divergence",
    "log_sourced_legs",
    "log_trades_rel",
    "not_applicable_legs",
    "run_gate",
    "scan_package",
    "sha256_file",
    "verify_compile",
    "verify_model_identity",
    "verify_real_tick_coverage",
    "verify_reconciliation",
    "verify_safety",
    "verify_symbolspec",
]
