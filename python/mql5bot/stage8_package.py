"""mql5bot.stage8_package - the owner gate builds the stage-8 evidence package
from ITS OWN measured outputs.

gate_run26 (HEAD 918f7bf, ``-Golds gold2``) reached stage 8 for the first time
and FAILED ``NOT_VERIFIED_RECONCILIATION_MISSING``: the package held only the
two log trade lists, so the trade comparison never ran. This module fills the
package from what the gate itself measured in that same run. It NEVER
hand-types or invents a value:

* every hash is computed from bytes (``sha256``), and ``archive_manifest.json``
  is written by ``tools/owner_evidence_bind.py manifest`` -- the same tool the
  owner uses;
* a field nothing measured is OMITTED, never filled -- the verifier then names
  it missing (compile TERMINAL_BUILD, environment broker, ...);
* a NOT_APPLICABLE leg gets no raw/parsed report: the gate's own
  ``stage_5.json`` record is copied to ``gate/stage_5.json`` and the verifier
  reads the leg's state from it (owner_gate.not_applicable_legs);
* ``safety/*.json`` are never written: 8a-8d have not run on MT5, so they stay
  MISSING and stage 8 keeps FAILING on them.

Which line each value comes from:

* compile: the stage-1 compile log copy (MEASURED format, logs_owner/
  compile-20260917-201954.log): ``# AEGIS compile run <stamp> (UTC)``,
  ``# metaeditor version: <v>``, ``<target>  ex5=<SHA256>``, and the
  ``<N> errors, <M> warnings`` summaries.
* the compiled EA: ``<data folder>\\MQL5\\Experts\\Mql5Bot\\Mql5Bot.ex5``, copied
  ONLY when its sha256 equals the hash the stage-1 log recorded.
* symbolspec: a byte copy of the stage-3 SymbolSpec export the gate used.
* environment server: MEASURED ``<SYM>,<TF> (<server>): ... generating``
  (gate runs 16/17). Terminal build and account mode: UNCONFIRMED patterns
  (``... build NNNN`` on a MetaTester/MetaTrader/terminal line, ``hedging`` /
  ``netting``); when the windows do not state them they are omitted.
* trades: the log trade lists stage 5 produced (tester_log_grader.log_trade_list).

PAIRING (gate_run27, HEAD 8966969, -Golds gold2): the first run of the trade
comparison paired python entry k with MT5 entry k BY LIST POSITION. MT5 never
traded 2024-01-01 ("start time changed to 2024.01.02 00:00 to provide data at
beginning", measured in gate_run23/25/26/27), so event 0 compared a python
2024-01-01 trade with an MT5 2024-01-02 deal and every later field was noise.
Events are now paired BY TIME, never by position: a python entry pairs with an
MT5 entry deal of the same fill minute (signal_time + 1 bar). Python trades
before the MT5 tested window start are OUT_OF_TESTED_WINDOW with the measured
start line quoted -- never dropped, never matched, never a divergence; the
window itself is a named limitation. Unpaired trades INSIDE the window are
MISSING_IN_MT5 / EXTRA_IN_MT5 and ARE divergences.

WINDOW END (gate_run28, HEAD 999126a, -Golds gold2): 5 python 2024-01-04
entries were reported MISSING_IN_MT5 while the MT5 test ended at
2024.01.04 00:00 (the ToDate the gate derives from the fixture; MT5 ToDate
is exclusive). The pairer now applies the window END as well: python
entries at/after it are OUT_OF_TESTED_WINDOW with the end's source named.

FILL MODEL (gate_run29, HEAD 5392cc4, -Golds gold2): the python entry price
was the BARE fixture open, so 19/37 buys differed by +0.00002 while every
sell was equal. The expected column is now a named fill model on every
event: a sell fills at the bid = fixture open (``bid_open``); a buy fills at
the ask = open + manifest ``spread_points`` * point (``ask_open=bid+spread``).
Slippage is NOT added: the engine's cost model (costs.entry_fill) is a MID
convention that slips EVERY fill, sells included, so "slippage on buys only"
has no source; adding it to buys would explain the residual by picking a
term to match MT5. The residual stays a measured divergence.

WINDOW BASIS (gate_run29): the python volume was sized on the frozen run's
equity, which carries the 2024-01-01 trades MT5 never ran AND day weights
0.5/0.1 (the generator's META_SCHEDULE) that the tester leg does not apply.
The builder now re-runs the frozen generator's engine at the tester weight,
flat before the measured MT5 window start, from equity_start; the frozen
sizing rule applied to THAT run's equity is ``python_volume_window_basis``,
and MT5 is compared against it. ``python_volume_frozen_basis`` stays beside
it. Both are refused (frozen basis compared, reason stated) unless the
generator's config_hash equals the manifest's AND the re-run reproduces the
frozen trace trade for trade AND the frozen sizing reproduces every frozen
approval.

EXPECTED ENTRY SET (S8-WEIGHT-1, owner decision, 2026-10-04): the tester
leg runs at the weight in force (InpBaseGateWeight=1.0, no allocation file
staged), while the frozen trace/expected_execution come from the generator's
SCHEDULED-weight run (day weights 1.0/0.5/0.1/0.0). gate_run29's one
MISSING_IN_MT5 (python short 0.02 at 2024-01-02T08:08) was a scheduled-
weight artifact: a persistence re-entry after seven meta_scale_dropped bars
at day weight 0.5 that the weight-1.0 run (and the EA) never makes. The
expected entry set for a tester leg is therefore the guarded weight-1.0
window run itself (entries, side, lots, fill), labelled
``expected_set: weight_in_force_1.0_window_run`` on every event, with a
``frozen_row_index`` cross-reference into expected_execution where one
exists. A frozen row with no weight-1.0 counterpart is
FROZEN_ONLY_SCHEDULED_WEIGHT -- informational, never a divergence, listed
in limitations. Guards (config_hash == manifest, fixture bytes == the
frozen record, measured window start/end, frozen trace + approvals
reproduced, run lots == recomputed lots): if any fails the frozen column
is compared instead and the fallback is stated, never silent. The frozen
artifacts and the anchor do not change.

COUNT / TIMESTAMP / TICK PATH / SL-TP (S8-COUNT-1, S8-TS-1, S8-TICKPATH-1,
S8-SLTP-1, owner decisions 2026-10-06, gate_run35): the verifier's derived
count is entry_count (in-window expected entries vs MT5 entry deals); a
paired timestamp is compared at fill-bar level with the raw MT5 seconds
recorded (held only beside an exact entry price); a tick-generating leg's
volume after its first exit that differs from the m1_ohlc leg is compared
with the frozen sizing rule on MT5's own pre-entry equity (the python path
recorded beside it); every paired event carries sl/tp from MT5's own entry
request line, read from the leg's window copy packaged at
log_windows/<gold>_<model>.txt (bytes == the log list's window_sha256).

Built, unit-tested, never run live.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mql5bot import gate_selfcheck as gs
from mql5bot import mt5tester as mt
from mql5bot import owner_gate as og

GATE_BUILD_REL = "gate/package_build.json"
LEG_MODELS = {"m1_ohlc": 1, "every_tick": 0, "real_ticks": 4}
GOLD_FILES = {
    "gold1": {"manifest": "artifacts/gold/manifest.json",
              "fixture": "artifacts/gold/gold_fixture.csv",
              "expected": "artifacts/gold/expected_execution.json",
              "tester_symbol": og.GOLD_TESTER_SYMBOLS["gold1"]},
    "gold2": {"manifest": "artifacts/gold_2/manifest.json",
              "fixture": "artifacts/gold_2/gold2_fixture.csv",
              "expected": "artifacts/gold_2/expected_execution.json",
              "trace": "artifacts/gold_2/python_trace.json",
              "generator": "tools/build_gold2_standard.py",
              "tester_symbol": og.GOLD_TESTER_SYMBOLS["gold2"]},
}
EA_EX5_REL = Path("MQL5") / "Experts" / "Mql5Bot" / "Mql5Bot.ex5"
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600,
              "H4": 14400, "D1": 86400}

# MEASURED (logs_owner/compile-20260917-201954.log)
_COMPILE_RUN_RE = re.compile(
    r"#\s*AEGIS compile run (\d{8})-(\d{6})\s*\(UTC\)")
_METAEDITOR_RE = re.compile(r"#\s*metaeditor version:\s*(\S+)", re.IGNORECASE)
_EX5_HASH_RE = re.compile(r"^\s*(\S+\.mq5)\s+ex5=([0-9A-Fa-f]{64})\s*$",
                          re.MULTILINE)
# MEASURED (gate runs 16/17): `EURUSD.G2,M1 (MetaQuotes-Demo): 1 minutes OHLC
# ticks generating`
_SERVER_RE = re.compile(r"\S+,\w+\s+\(([^()]+)\):\s*[^:]+?\s+generating\b",
                        re.IGNORECASE)
# UNCONFIRMED: not yet seen in a captured window
_BUILD_RE = re.compile(r"(?:metatester|metatrader|terminal)\b.*?\bbuild\s+"
                       r"(\d{4,5})\b", re.IGNORECASE)
_ACCOUNT_MODE_RE = re.compile(r"\b(hedging|netting)\b", re.IGNORECASE)
# EA source (Logger.Write) deal time: `2024.01.02 08:01:00`
_EA_TIME_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$")
# MT5's own journal deal line, captured by the grader in each deal's `lines`
# (format documented in tester_log_grader; price group added here):
#   `deal #12 buy 0.10 EURUSD.G2 at 1.10010 done (based on order #12)`
_MT5_DEAL_LINE_RE = re.compile(
    r"\bdeal #(\d+)\s+(buy|sell)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+at\s+"
    r"(-?\d+(?:\.\d+)?)", re.IGNORECASE)
# MEASURED (gate_run23 capture, tests/data/owner_gate; same wording reported
# in gate_run25/26/27): `EURUSD.G1: start time changed to 2024.01.06 00:00
# to provide data at beginning` -- MT5 stating the tested window start.
_WINDOW_START_RE = re.compile(
    r"start time changed to (\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2})"
    r"(?::(\d{2}))?\s+to provide data at (?:the )?beginning", re.IGNORECASE)
# python expected_execution side -> MT5 journal side, for the comparison only
_PY_SIDE_TO_MT5 = {"long": "buy", "short": "sell"}
# pairing states (event `pairing` key; NOT divergence classifications --
# those stay the closed owner_gate.TAXONOMY, chosen by the field name)
PAIRED_BY_TIME = og.PAIRED_BY_TIME
OUT_OF_TESTED_WINDOW = "OUT_OF_TESTED_WINDOW"
MISSING_IN_MT5 = og.MISSING_IN_MT5
EXTRA_IN_MT5 = og.EXTRA_IN_MT5
# informational pairing state (S8-WEIGHT-1): a frozen scheduled-weight row
# with no weight-in-force counterpart -- recorded, never a divergence
FROZEN_ONLY_SCHEDULED_WEIGHT = "FROZEN_ONLY_SCHEDULED_WEIGHT"
# expected-set labels, recorded on every event
EXPECTED_SET_WINDOW_RUN = "weight_in_force_1.0_window_run"
EXPECTED_SET_FROZEN = "frozen_scheduled_weight"
# frozen_inputs.json keys per gold (its records use gold_1/gold_2)
FROZEN_GOLD_KEYS = {"gold1": "gold_1", "gold2": "gold_2"}
FROZEN_INPUTS_REL = "artifacts/owner_mt5_gate/frozen_inputs.json"
_NA_FIXTURE_RE = re.compile(
    r"\b(gold\d)_real_ticks: " + og.STAGE5_NOT_APPLICABLE
    + r": fixture (\S+) is bar-only")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(Path(path).read_bytes())


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _unique(values: list[str]) -> str | None:
    """The one value the lines state; None when absent or contradictory."""
    distinct = set(values)
    return values[0] if len(distinct) == 1 else None


# ---------------------------------------------------------------------------
# compile (stage 1)
# ---------------------------------------------------------------------------

def compile_identity(log_text: str) -> dict:
    """What the stage-1 compile log states: run timestamp, MetaEditor
    version, per-target ex5 hashes, and error/warning totals. A value the log
    does not state is absent from the result."""
    out: dict = {"ex5_hashes": {m.group(1): m.group(2).lower()
                                for m in _EX5_HASH_RE.finditer(log_text)}}
    m = _COMPILE_RUN_RE.search(log_text)
    if m:
        out["compile_timestamp"] = datetime.strptime(
            m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc).isoformat()
    m = _METAEDITOR_RE.search(log_text)
    if m:
        out["compiler_version"] = m.group(1)
    summaries = gs._RESULT_SUMMARY.findall(log_text)
    if summaries:
        out["errors"] = sum(int(e) for e, _ in summaries)
        out["warnings"] = sum(int(w) for _, w in summaries)
    return out


# ---------------------------------------------------------------------------
# stage-5 record, windows
# ---------------------------------------------------------------------------

def na_fixtures(stage5: dict | None) -> dict[str, str]:
    """gold -> fixture for every real_ticks leg the stage-5 record names
    NOT_APPLICABLE_BAR_ONLY_FIXTURE (the reason names the fixture)."""
    if not isinstance(stage5, dict):
        return {}
    return {m.group(1): m.group(2)
            for m in _NA_FIXTURE_RE.finditer(str(stage5.get("reason") or ""))}


def window_facts(window_texts: list[str]) -> dict:
    """Server, terminal build and account mode as the leg windows state them.
    Each is None when no line states it or two lines disagree."""
    servers, builds, modes = [], [], []
    for text in window_texts:
        for line in text.splitlines():
            m = _SERVER_RE.search(line)
            if m:
                servers.append(m.group(1).strip())
            m = _BUILD_RE.search(line)
            if m:
                builds.append(m.group(1))
            m = _ACCOUNT_MODE_RE.search(line)
            if m:
                modes.append(m.group(1).lower())
    return {"server": _unique(servers), "terminal_build": _unique(builds),
            "account_mode": _unique(modes)}


def _ea_time_iso(stamp: str) -> str | None:
    m = _EA_TIME_RE.match(str(stamp or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, sec = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{sec or '00'}"


# ---------------------------------------------------------------------------
# reconciliation (python column from expected_execution, mt5 from the log)
# ---------------------------------------------------------------------------

def mt5_entries(deals: list[dict]) -> tuple[list[dict] | None, str]:
    """The entry deals of a netting, one-position-at-a-time run.

    INFERRED pairing rule (not stated by any log line): deals alternate
    open, close, open, close... so the entries are the deals at even
    positions. Checked, never assumed: every even-position deal must carry
    pnl == 0 (an MT5 entry deal books no profit). When the check fails the
    pairing is refused and no per-trade event is built."""
    entries = deals[0::2]
    bad = [d.get("ticket") for d in entries if d.get("pnl") != 0.0]
    if bad:
        return None, (f"entry/exit pairing refused: even-position deals "
                      f"{bad[:5]} carry pnl != 0, so the alternation rule "
                      "does not hold")
    return entries, (f"{len(entries)} entries from {len(deals)} deals "
                     "(INFERRED: alternating open/close, every entry pnl 0)")


# The python volume column the tester comparison uses (gate_run28 finding
# 3): the tester leg stages no allocation.json, so the EA falls back to
# InpBaseGateWeight=1.0 — the like-for-like python expectation is the
# expected_execution meta["1.0"].final_lots table, NEVER the weight-free
# risk approval (approved_lots stays beside it, labelled, uncompared).
# The column is FIXED here; a weight is never picked to match MT5.
TESTER_WEIGHT_COLUMN = "1.0"
TESTER_WEIGHT_SOURCE = (
    'expected_execution meta["1.0"].final_lots — the weight in force on '
    "the tester leg (no allocation file staged; EA fallback "
    "InpBaseGateWeight=1.0)")


def python_entries(expected: dict, timeframe: str) -> tuple[list[dict] | None,
                                                            str]:
    """The approved entries of expected_execution.json, in signal order. The
    fill time is signal_time + one bar (manifest signal_timing_contract:
    action at the next bar open). ``compare_lots`` is the volume the tester
    comparison uses (meta[TESTER_WEIGHT_COLUMN].final_lots when that column
    says SEND; None otherwise, with ``compare_lots_note`` saying why);
    ``lots`` stays the weight-free risk approval."""
    rows = expected.get("entries") if isinstance(expected, dict) else None
    step = TF_SECONDS.get(str(timeframe))
    if not isinstance(rows, list):
        return None, "expected_execution has no 'entries' list (schema not supported)"
    if step is None:
        return None, f"timeframe {timeframe!r} has no bar length"
    out = []
    for idx, row in sorted(enumerate(rows),
                           key=lambda t: str(t[1].get("signal_time"))):
        risk = row.get("risk") or {}
        if risk.get("rejected"):
            continue
        sig = datetime.fromisoformat(str(row["signal_time"]))
        meta = (row.get("meta") or {}).get(TESTER_WEIGHT_COLUMN)
        compare_lots, why = None, None
        if not isinstance(meta, dict):
            why = (f"entry carries no meta[{TESTER_WEIGHT_COLUMN!r}] "
                   "expectation — volume stays uncompared, never "
                   "substituted")
        elif meta.get("action") != "SEND":
            why = (f"meta[{TESTER_WEIGHT_COLUMN!r}] action "
                   f"{meta.get('action')!r}: python sends nothing at this "
                   "weight — volume stays uncompared, never substituted")
        else:
            compare_lots = meta.get("final_lots")
        entry = {"signal_time": row["signal_time"],
                 "fill_time": (sig + timedelta(seconds=step)).isoformat(),
                 "side": row.get("side"),
                 "lots": risk.get("approved_lots"),
                 "compare_lots": compare_lots,
                 # cross-reference into expected_execution.json's entries
                 # array, and the frozen-basis volume column (S8-WEIGHT-1)
                 "frozen_row_index": idx,
                 "frozen_basis_lots": compare_lots}
        if why:
            entry["compare_lots_note"] = why
        out.append(entry)
    return out, (f"{len(out)} approved entries; volume column "
                 f"{TESTER_WEIGHT_SOURCE}")


# Expected entry-fill model (gate_run29 finding a). MT5 bars are BID bars:
# a sell fills at the bid open, a buy at the ask = bid + spread. The
# manifest's slippage_points is NOT part of this column (see module doc).
FILL_MODEL_SELL = "bid_open"
FILL_MODEL_BUY = "ask_open=bid+spread"
FILL_MODEL_NOTE = (
    "python entry price = fixture open (BID bar) for a sell; open + "
    "spread_points * broker_spec.point for a buy, rounded to "
    "broker_spec.digits. The spread is the MEASURED one from the stage-3 "
    "SymbolSpec export's flat spread_points when the export carries it "
    "(S8-SPEC-1; gate_run30: manifest 1.0 vs measured tester fill bid+2 "
    "points), else the manifest cost_config value with the fallback reason "
    "stated. Slippage NOT added: the engine's cost model (costs.entry_fill) "
    "slips EVERY fill, sells included, so no source applies it to buys "
    "only; a residual stays a divergence.")


def _num(v: float) -> str:
    """Render 2.0 as "2" in a fill-model name, other values as-is."""
    f = float(v)
    return str(int(f)) if f.is_integer() else str(f)


def fill_model_buy_name(fill: dict | None) -> str:
    """The buy fill-model name, source included when the fill spec names
    one (``spread_source``)."""
    if fill and fill.get("spread_source"):
        return f"ask_open=bid+{fill['spread_source']}"
    return FILL_MODEL_BUY


def fill_spec_of(manifest: dict,
                 symbolspec: dict | None = None) -> tuple[dict | None, str]:
    """spread_points / point / digits for the expected fill model. The
    spread comes from the SymbolSpec export's flat MEASURED
    ``spread_points`` when ``symbolspec`` carries one (``spread_source``
    then names it), falling back to the manifest cost_config value with
    the reason stated. For a CUSTOM symbol (``custom_symbol`` true) the
    live ``spread_points`` is never used: only a numeric
    ``custom_fixed_spread_points``, else the manifest value. None (with the reason) when point/digits or every
    spread source is missing: the price column is then never built from a
    bare open."""
    cost = manifest.get("cost_config") or {}
    spec = manifest.get("broker_spec") or {}
    out = {"point": spec.get("point"), "digits": spec.get("digits")}
    doc = symbolspec or {}
    custom = doc.get("custom_symbol") is True
    # A CUSTOM symbol's live spread_points is never the tester spread
    # (gate_run34: export 0, tester filled bid+2): only its configured
    # fixed spread is (custom_fixed_spread_points, written when
    # SYMBOL_SPREAD_FLOAT is false).
    key = "custom_fixed_spread_points" if custom else "spread_points"
    measured = doc.get(key)
    if isinstance(measured, bool):
        measured = None
    try:
        measured = float(measured)
    except (TypeError, ValueError):
        measured = None
    if measured is not None:
        out["spread_points"] = measured
        out["spread_source"] = (
            f"custom_fixed_spread({_num(measured)} points, symbolspec "
            "export)" if custom else
            f"measured_spread({_num(measured)} points, symbolspec export)")
        src = out["spread_source"]
    else:
        # fallback: the manifest assumption, with the reason stated; the
        # buy fill-model name stays the generic FILL_MODEL_BUY (no
        # spread_source), the reason lives in this note / inputs_source
        out["spread_points"] = cost.get("spread_points")
        src = ("manifest cost_config" if symbolspec is None else
               "manifest cost_config -- fallback: the custom-symbol export "
               "carries no numeric custom_fixed_spread_points (its live "
               "spread_points is never used for a custom symbol)"
               if custom else
               "manifest cost_config -- fallback: the symbolspec export "
               "carries no numeric flat spread_points")
    gaps = sorted(k for k in ("spread_points", "point", "digits")
                  if out.get(k) is None)
    if gaps:
        return None, (f"manifest lacks {gaps} for the expected fill model"
                      if symbolspec is None else
                      f"no spread/point/digits source for {gaps} "
                      "(symbolspec export + manifest)")
    return out, (f"spread_points {out['spread_points']} ({src}), point "
                 f"{out['point']}, digits {out['digits']}")


def expected_fill(bar_open: float, mt5_side: str, fill: dict
                  ) -> tuple[float, str]:
    """(expected entry price, fill model name) for a market entry at the
    fill bar's open. ``mt5_side`` is buy|sell."""
    if mt5_side == "buy":
        price = bar_open + float(fill["spread_points"]) * float(fill["point"])
        return round(price, int(fill["digits"])), fill_model_buy_name(fill)
    return round(bar_open, int(fill["digits"])), FILL_MODEL_SELL


def _gold_generator(repo: Path, rel: str):
    """Import the frozen gold generator (tools/...) under a private name."""
    import importlib.util

    path = repo / rel
    spec = importlib.util.spec_from_file_location(
        "_s8p_gold_generator_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def expected_set_window_run(repo: Path | str, gold: str,
                            window_start: str | None,
                            window_end: str | None,
                            weight: float = float(TESTER_WEIGHT_COLUMN),
                            frozen_rel: str = FROZEN_INPUTS_REL,
                            spread_points: float | None = None,
                            spread_source: str | None = None,
                            price_basis: str = "bid"
                            ) -> tuple[dict | None, str]:
    """The tester leg's EXPECTED ENTRY SET (S8-WEIGHT-1): the weight-in-
    force run.

    The frozen generator's engine is re-run at the tester ``weight`` with
    the frozen desired-position series flattened before ``window_start``
    (the measured MT5 start), from the manifest's equity_start. The run's
    OWN trades are the expected entries (side, lots, fill), each cross-
    referenced to the frozen expected_execution row at the same fill
    minute (``frozen_row_index``, None when there is none). Frozen
    approved rows with no counterpart come back under ``frozen_only`` with
    a measured reason (before_window_start / scheduled_weight_only /
    at_or_after_window_end) -- informational, never divergences.

    Refused (None, reason) -- the caller then compares the frozen column
    and says so -- unless ALL guards hold:

    * ``window_start`` and ``window_end`` are measured (non-None);
    * the fixture bytes hash to the frozen record's ``fixture_sha256``
      (``frozen_rel``);
    * the generator's config_hash equals the manifest's;
    * the engine re-run with the generator's own schedule reproduces the
      frozen trace trade for trade;
    * the frozen sizing rule reproduces every frozen approved_lots;
    * every window-run entry with a frozen counterpart carries exactly the
      lots the frozen sizing rule gives on the run's signal-bar-close
      equity (meta floor at ``weight``).

    ``spread_points`` (with ``spread_source`` naming where it came from)
    replaces the manifest cost_config spread in the WINDOW run's cost
    model only, so the window-basis volumes are sized on the same
    measured cost the expected fill model uses (S8-SPEC-1). The frozen-
    trace reproduction guard always runs on the manifest value: the
    frozen trace was built with it.

    ``price_basis`` (S8-COST-1, owner decision 2026-10-05) applies to the
    WINDOW run only: "bid" (default) models the tester -- bar prices are
    BID, a buy fills at open + spread, a sell at open, a long closes at the
    bid, a short at the ask (its SL/TP trigger on the ask), slippage 0. The
    frozen-trace reproduction guard always runs at the manifest cost
    ("mid", manifest slippage) and must still reproduce.
    """
    repo = Path(repo)
    files = GOLD_FILES.get(gold, {})
    if not files.get("generator") or not files.get("trace"):
        return None, f"{gold}: no frozen generator/trace wired for a re-run"
    if window_start is None:
        return None, ("no measured MT5 window-start line for this leg: "
                      "the expected set cannot be windowed")
    if window_end is None:
        return None, ("no derivable tester window end "
                      "(mt5tester.fixture_date_range)")
    manifest = _load(repo / files["manifest"])
    expected = _load(repo / files["expected"])
    trace = _load(repo / files["trace"])
    frozen_rec = _load(repo / frozen_rel)
    if not all(isinstance(d, dict)
               for d in (manifest, expected, trace, frozen_rec)):
        return None, f"{gold}: manifest/expected/trace/frozen record unreadable"
    fixture = repo / files["fixture"]
    frozen_fixture = (frozen_rec.get(FROZEN_GOLD_KEYS.get(gold, "")) or {}
                      ).get("fixture_sha256")
    if not frozen_fixture:
        return None, (f"{frozen_rel} carries no fixture_sha256 for {gold}")
    if _sha(fixture) != frozen_fixture:
        return None, (f"{files['fixture']} sha256 != the frozen record's "
                      "fixture_sha256: not byte-identical to the frozen "
                      "fixture")
    try:
        import pandas as pd

        from mql5bot.costs import CostConfig
        from mql5bot.engine import Instrument, PortfolioEngine, RunConfig
        from mql5bot.sizer import size_position
        from mql5bot.symbolspec import SymbolSpec

        gen = _gold_generator(repo, files["generator"])
        if gen._config_hash() != manifest.get("config_hash"):
            return None, (f"{files['generator']} config_hash != manifest "
                          "config_hash: not the frozen generator")
        df = pd.read_csv(fixture, parse_dates=["time"]).set_index("time")
        bars = trace.get("bars") or []
        if [str(b.get("timestamp")) for b in bars] != \
                [ts.isoformat() for ts in df.index]:
            return None, "trace bars do not cover the fixture bar for bar"
        sig = pd.Series([int(b["desired_position"]) for b in bars],
                        index=df.index)
        spec = SymbolSpec(**manifest["broker_spec"])
        ec, cc = manifest["engine_config"], manifest["cost_config"]
        risk = manifest["risk_config"]

        def run(signal, schedule, spread=None, basis="mid"):
            # "mid" = the manifest cost the frozen trace was built with;
            # "bid" = the tester model (S8-COST-1): slippage 0
            costs = CostConfig(symbol=manifest["symbol"],
                               spread_points=(cc["spread_points"]
                                              if spread is None else spread),
                               slippage_points=(cc["slippage_points"]
                                                if basis == "mid" else 0.0),
                               commission_per_lot=cc["commission_per_lot"],
                               price_basis=basis)
            cfg = RunConfig(initial_capital=float(risk["equity_start"]),
                            mode=ec["mode"], allow_short=ec["allow_short"],
                            sizing_mode=ec["sizing_mode"],
                            risk_value=float(risk["risk_percent"]),
                            max_lots=float(spec.volume_max),
                            allow_signal_exit=ec["allow_signal_exit"])
            ins = Instrument(symbol=manifest["symbol"],
                             strategy=manifest["strategy_id"], df=df,
                             costs=costs, spec=spec, profit_to_deposit=1.0,
                             params={"sl_atr": ec["sl_atr"],
                                     "tp_atr": ec["tp_atr"]},
                             signal=signal, allocation_schedule=schedule)
            return PortfolioEngine(cfg).run([ins])

        def trade_rows(res):
            return [(pd.Timestamp(t["entry_time"]).isoformat(), str(t["side"]),
                     round(float(t["lots"]), 6), round(float(t["pnl"]), 6))
                    for _, t in res.trades.iterrows()]

        frozen = [(t["signal_time"], t["side"], t["lots"], t["pnl"])
                  for t in trace.get("trades") or []]
        if trade_rows(run(sig, gen.META_SCHEDULE)) != frozen:
            return None, ("engine re-run with the generator's schedule does "
                          "not reproduce the frozen trace")
        start = pd.Timestamp(window_start)
        win_sig = sig.where(sig.index >= start, 0)
        win = run(win_sig, ((df.index[0], weight),), spread_points,
                  price_basis)
    except Exception as exc:  # noqa: BLE001 -- any failure refuses the set
        return None, f"expected-set re-run failed: {type(exc).__name__}: {exc}"
    step_s = TF_SECONDS[str(manifest.get("timeframe"))]
    bar = pd.Timedelta(seconds=step_s)
    # frozen approved rows by fill minute (original array index kept)
    frozen_by_fill: dict[str, tuple[int, dict]] = {}
    for idx, row in enumerate(expected.get("entries") or []):
        r = row.get("risk") or {}
        if r.get("rejected") or not row.get("stop_distance"):
            continue

        def sized(equity: float, stop: float = float(row["stop_distance"])):
            return size_position(spec, mode=risk["mode"], equity=equity,
                                 stop_distance=stop,
                                 value=float(risk["risk_percent"]))
        if round(float(sized(float(row["sizing_basis"])).lots), 6) != \
                r.get("approved_lots"):
            return None, (f"frozen sizing does not reproduce approved_lots "
                          f"at {row['signal_time']}")
        fill = (pd.Timestamp(row["signal_time"]) + bar).isoformat()
        frozen_by_fill[fill[:16]] = (idx, row)

    def frozen_lots_of(row: dict):
        meta = (row.get("meta") or {}).get(TESTER_WEIGHT_COLUMN) or {}
        return meta.get("final_lots") if meta.get("action") == "SEND" else None

    rows_out: list[dict] = []
    used: set[str] = set()
    for _, t in win.trades.iterrows():
        fill_ts = pd.Timestamp(t["entry_time"])
        fill = fill_ts.isoformat()
        lots = round(float(t["lots"]), 6)
        hit = frozen_by_fill.get(fill[:16])
        if hit is not None:
            used.add(fill[:16])
            idx, row = hit
            # cross-check: the run's lots equal the frozen sizing rule on
            # the run's own signal-bar-close equity, meta-floored at weight
            basis = float(win.equity.loc[fill_ts - bar])
            recomputed = frozen_rule_lots(spec, risk, basis,
                                          float(row["stop_distance"]),
                                          weight)
            if recomputed != lots:
                return None, (f"window run entered {lots} lots at {fill} "
                              f"but the frozen sizing rule gives "
                              f"{recomputed}")
        rows_out.append({
            "signal_time": (fill_ts - bar).isoformat(),
            "fill_time": fill,
            "side": str(t["side"]),
            "lots": lots,
            "compare_lots": lots,
            "window_run_fill": round(float(t["entry_price"]), 10),
            "expected_set": EXPECTED_SET_WINDOW_RUN,
            "frozen_row_index": hit[0] if hit is not None else None,
            "frozen_basis_lots": (frozen_lots_of(hit[1])
                                  if hit is not None else None),
        })
    frozen_only: list[dict] = []
    for fill_min in sorted(set(frozen_by_fill) - used):
        idx, row = frozen_by_fill[fill_min]
        fill = (pd.Timestamp(row["signal_time"]) + bar).isoformat()
        if fill < window_start:
            reason = "before_window_start"
        elif fill >= window_end:
            reason = "at_or_after_window_end"
        else:
            reason = "scheduled_weight_only"
        frozen_only.append({
            "frozen_row_index": idx,
            "signal_time": row["signal_time"],
            "fill_time": fill,
            "side": row.get("side"),
            "entry_kind": row.get("entry_kind"),
            "frozen_basis_lots": frozen_lots_of(row),
            "reason": reason,
        })
    spread_note = ("manifest cost_config spread"
                   if spread_points is None else
                   f"spread_points {_num(spread_points)} "
                   f"({spread_source or 'caller-supplied'})")
    note = (f"expected entry set = engine re-run of {files['generator']} "
            f"(config_hash == manifest; fixture bytes == {frozen_rel}) at "
            f"the weight in force ({weight}: InpBaseGateWeight, no "
            f"allocation file staged), python trades only from "
            f"{window_start} (flat before), equity_start "
            f"{float(risk['equity_start'])}, window-run entry cost "
            f"{spread_note}, price_basis {price_basis!r}"
            + (" (S8-COST-1: bar prices are BID; buy at open+spread, sell "
               "at open; shorts close/stop on the ask; slippage 0)"
               if price_basis == "bid" else "")
            + "; self-checks: frozen trace reproduced (manifest cost, "
            "price_basis 'mid'), frozen approvals reproduced, run lots == "
            "frozen sizing rule on the run's signal-bar-close equity")
    return {"rows": rows_out, "frozen_only": frozen_only}, note


def frozen_rule_lots(spec, risk: dict, equity: float, stop_distance: float,
                     weight: float = float(TESTER_WEIGHT_COLUMN)) -> float:
    """The frozen sizing rule (owner_gate.frozen_rule_lots: one copy, shared
    with the verifier)."""
    return og.frozen_rule_lots(spec, risk, equity, stop_distance, weight)


def python_risk_context(repo: Path | str, gold: str) -> tuple[dict | None,
                                                               str]:
    """What the python SL/TP (S8-SLTP-1) and the MT5-equity sizing
    (S8-TICKPATH-1) need: the manifest broker_spec / risk / sl_atr / tp_atr,
    the engine's own ATR(14) series on the frozen fixture, and the frozen
    expected_execution stop_distance per fill minute (a guard). None with
    the reason when any input is unreadable."""
    repo = Path(repo)
    files = GOLD_FILES.get(gold, {})
    try:
        import numpy as np
        import pandas as pd

        from mql5bot.indicators import atr as atr_indicator
        from mql5bot.symbolspec import SymbolSpec

        manifest = _load(repo / files["manifest"])
        expected = _load(repo / files["expected"])
        df = pd.read_csv(repo / files["fixture"], parse_dates=["time"])
        a = np.asarray(atr_indicator(df["high"].values, df["low"].values,
                                     df["close"].values, 14), dtype=float)
        step = TF_SECONDS[str(manifest.get("timeframe"))]
        frozen_stop: dict[str, float] = {}
        for row in expected.get("entries") or []:
            if (row.get("risk") or {}).get("rejected") or \
                    not row.get("stop_distance"):
                continue
            fill = datetime.fromisoformat(str(row["signal_time"])) + \
                timedelta(seconds=step)
            frozen_stop[fill.isoformat()[:16]] = float(row["stop_distance"])
        return {"spec": SymbolSpec(**manifest["broker_spec"]),
                "risk": manifest["risk_config"],
                "sl_atr": float(manifest["engine_config"]["sl_atr"]),
                "tp_atr": float(manifest["engine_config"]["tp_atr"]),
                "digits": int(manifest["broker_spec"]["digits"]),
                "atr": a,
                "bar_of": {t.isoformat()[:16]: i
                           for i, t in enumerate(df["time"])},
                "frozen_stop": frozen_stop}, "ok"
    except Exception as exc:  # noqa: BLE001 -- any failure refuses the column
        return None, f"python risk context unavailable: {type(exc).__name__}: {exc}"


def python_stop_levels(ctx: dict | None, fill_minute: str, side: str,
                       fill_price: float) -> dict:
    """S8-SLTP-1 python SL/TP of one entry, the engine's own rule
    (engine.fresh_levels): distance = enforce_min_stop(sl_atr|tp_atr x
    ATR14[signal bar]), level = round_to_tick(fill -/+ distance), at
    broker digits. ``fill_price`` is the named fill model's price. Guard:
    the raw SL distance must equal the frozen expected_execution
    stop_distance where a frozen row fills at that minute. Returns
    {sl, tp, stop_distance} or {refused: reason}."""
    from mql5bot.symbolspec import enforce_min_stop, round_to_tick

    if ctx is None:
        return {"refused": "no python risk context"}
    bar = ctx["bar_of"].get(str(fill_minute)[:16])
    if bar is None or bar < 1:
        return {"refused": f"fill minute {fill_minute} is not a fixture bar "
                           "with a signal bar before it"}
    a = float(ctx["atr"][bar - 1])
    if not math.isfinite(a) or a <= 0.0:
        return {"refused": f"no valid ATR at the signal bar of {fill_minute}"}
    sd = ctx["sl_atr"] * a
    frozen = ctx["frozen_stop"].get(str(fill_minute)[:16])
    if frozen is not None and round(sd, 10) != round(frozen, 10):
        return {"refused": (f"ATR stop distance {sd!r} != the frozen "
                            f"stop_distance {frozen!r} at {fill_minute}")}
    s = 1 if side == "buy" else -1
    spec, dg = ctx["spec"], ctx["digits"]
    return {"sl": round(round_to_tick(
                fill_price - s * enforce_min_stop(sd, spec), spec), dg),
            "tp": round(round_to_tick(
                fill_price + s * enforce_min_stop(ctx["tp_atr"] * a, spec),
                spec), dg),
            "stop_distance": sd}


def tested_window_start(window_text: str,
                        symbol: str | None) -> tuple[str | None, str | None]:
    """The tested-window start MT5 ITSELF states for this leg's symbol
    (`start time changed to <Y.M.D H:M> to provide data at beginning`).
    (None, None) when no such line names the symbol: the start was not
    measured and no window is assumed."""
    for line in (window_text or "").splitlines():
        if not symbol or symbol not in line:
            continue
        m = _WINDOW_START_RE.search(line)
        if m:
            y, mo, d, h, mi, sec = m.groups()
            return f"{y}-{mo}-{d}T{h}:{mi}:{sec or '00'}", line.strip()
    return None, None


def fixture_minute_opens(fixture_csv: Path | str) -> dict[str, float]:
    """minute (YYYY-MM-DDTHH:MM) -> open price, from the frozen gold fixture.
    The manifest's signal_timing_contract fills a market order at the next
    bar open; the fixture open at the fill minute is the BID the expected
    fill model (expected_fill) starts from -- never compared bare."""
    out: dict[str, float] = {}
    with open(fixture_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[row["time"][:10] + "T" + row["time"][11:16]] = \
                    float(row["open"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def mt5_deal_line_facts(deal: dict, symbol: str) -> dict:
    """side/volume/price from the MT5 journal line the grader captured in
    this deal's own `lines` (`deal #N buy/sell VOL SYMBOL at PRICE`), for
    the SAME ticket and symbol. Empty when no such line exists: those
    fields stay unmeasured, never inferred."""
    for line in deal.get("lines") or []:
        m = _MT5_DEAL_LINE_RE.search(str(line))
        if m and m.group(4) == symbol and \
                str(deal.get("ticket")) == m.group(1):
            return {"side": m.group(2).lower(), "volume": float(m.group(3)),
                    "price": float(m.group(5)), "line": str(line)}
    return {}


def _pair_by_minute(py: list[dict], entries: list[dict]
                    ) -> tuple[list[tuple[dict, dict]], list[dict],
                               list[dict]]:
    """Pair python entries with MT5 entry deals on the SAME fill minute
    (python fill = signal_time + 1 bar), each deal used at most once, both
    sides walked in time order. NEVER by list position."""
    unused = list(range(len(entries)))
    pairs: list[tuple[dict, dict]] = []
    missing: list[dict] = []
    for p in sorted(py, key=lambda r: str(r["fill_time"])):
        want = str(p["fill_time"])[:16]
        hit = next((i for i in unused
                    if str(_ea_time_iso(entries[i].get("time")) or "")[:16]
                    == want), None)
        if hit is None:
            missing.append(p)
        else:
            unused.remove(hit)
            pairs.append((p, entries[hit]))
    extra = [entries[i] for i in unused]
    return pairs, missing, extra


def reconciliation_events(py: list[dict], mt5_by_model: dict[str, list[dict]],
                          symbol: str, *,
                          window_starts: dict | None = None,
                          window_end: str | None = None,
                          window_end_source: str | None = None,
                          fixture_opens: dict[str, float] | None = None,
                          fill: dict | None = None,
                          expected_sets: dict | None = None,
                          log_deals: dict[str, list[dict]] | None = None,
                          tick_paths: dict | None = None,
                          deposits: dict | None = None,
                          size_rule=None,
                          risk_ctx: dict | None = None,
                          request_levels: dict | None = None
                          ) -> tuple[list[dict], dict]:
    """Per-model events pairing python entries with MT5 entry deals BY TIME
    (same fill minute), never by list position. Returns (events, summary).

    * a python trade whose fill is before the model's measured MT5 window
      start, or at/after the tester window END (``window_end``, the
      ToDate the gate derived from the fixture; MT5 treats ToDate as
      exclusive -- gate_run28: 5 python 2024-01-04 entries had wrongly
      been MISSING_IN_MT5 while the test ended 2024.01.04 00:00), is
      OUT_OF_TESTED_WINDOW: recorded with the start line quoted (or the
      end + its source named), with NO compared fields -- never silently
      dropped, never counted as matched, and never a divergence (the
      window is a named limitation of the comparison, not its first
      divergence);
    * an unpaired python trade INSIDE the window is MISSING_IN_MT5 and an
      unpaired MT5 entry deal is EXTRA_IN_MT5 -- both ARE divergences
      (field `state`, so the closed taxonomy classifies them);
    * a paired event compares timestamp, volume, and -- when the MT5 journal
      line in the deal's `lines` states them -- entry side and entry price.
      The python entry price is the named fill model (``expected_fill``,
      needs ``fill``) applied to the fixture open at the fill minute (the
      manifest fills at next bar open) -- never a bare open; when either
      side lacks a value the field carries only what was measured, never
      an invented one;
    * the python column is the model's EXPECTED SET
      (``expected_sets[model]`` = (set_doc, note) from
      expected_set_window_run, S8-WEIGHT-1): the weight-in-force run's own
      entries/side/lots/fill. When the set is None the FROZEN column
      (``py``: expected_execution meta[TESTER_WEIGHT_COLUMN]) is compared
      and the fallback reason is stated on every event -- never silent.
      Every event records ``expected_set`` and the ``frozen_row_index``
      cross-reference (None when there is none); the volume columns
      ``python_volume_frozen_basis`` / ``python_volume_window_basis`` are
      both recorded with the compared basis stated;
    * a frozen scheduled-weight row with no weight-in-force counterpart
      is a FROZEN_ONLY_SCHEDULED_WEIGHT event: informational, NO compared
      fields, never a divergence, with a measured ``reason``
      (before_window_start / scheduled_weight_only /
      at_or_after_window_end);
    * S8-TS-1: the paired timestamp is compared at fill-BAR level (python
      fill minute vs the MT5 time floored to the minute, basis
      ``owner_gate.TS_BASIS_FILL_BAR``); the raw MT5 seconds are recorded
      as ``mt5_time_raw``. The verifier holds it valid only beside an
      exact entry_price match on the same event;
    * S8-TICKPATH-1: on a tick-generating leg whose ``tick_paths[model]``
      record names its first exit that differs from the m1_ohlc leg, a
      paired entry AFTER that deal compares volume against ``size_rule``
      (the frozen sizing rule) on MT5's own pre-entry equity (``deposits``
      + cumulative pnl of the leg's earlier ``log_deals``, book flat) with
      the python SL distance; the python-path volume stays beside it,
      recorded, uncompared. Before it, and on m1_ohlc always, the python
      path is compared;
    * S8-SLTP-1: when ``request_levels`` is given, every paired event
      carries ``sl``/``tp``: mt5 from MT5's own entry request line, python
      from python_stop_levels on the named fill model price;
    * `trade_index` numbers a model's per-trade events in time order;
    * a final event compares per-model entry counts INSIDE the window (the
      out-of-window count is beside it, uncompared).
    """
    window_starts = window_starts or {}
    expected_sets = expected_sets or {}

    def fill_model_of(p: dict) -> str | None:
        if fill is None:
            return None
        return expected_fill(0.0, _PY_SIDE_TO_MT5.get(p["side"], ""),
                             fill)[1]

    raw: list[tuple[str, str, dict]] = []
    summary: dict[str, dict] = {}
    for model in sorted(mt5_by_model):
        entries = mt5_by_model[model]
        start, start_line = window_starts.get(model, (None, None))
        sd, sd_note = expected_sets.get(
            model, (None, "no expected-set run supplied"))
        if sd is not None:
            rows = sd["rows"]
            frozen_only = sd["frozen_only"]
            set_label = EXPECTED_SET_WINDOW_RUN
            basis_note = f"WINDOW_RUN: {sd_note}"
        else:
            rows = py
            frozen_only = []
            set_label = f"{EXPECTED_SET_FROZEN} (fallback: {sd_note})"
            basis_note = ("FROZEN: expected_execution "
                          f"meta[{TESTER_WEIGHT_COLUMN!r}].final_lots "
                          f"(expected-set run unavailable: {sd_note})")
        before = [p for p in rows
                  if start is not None and str(p["fill_time"]) < start]
        after = [p for p in rows
                 if window_end is not None
                 and str(p["fill_time"]) >= window_end
                 and (start is None or str(p["fill_time"]) >= start)]
        in_window = [p for p in rows
                     if (start is None or str(p["fill_time"]) >= start)
                     and (window_end is None
                          or str(p["fill_time"]) < window_end)]
        pairs, missing, extra = _pair_by_minute(in_window, entries)
        summary[model] = {
            "paired": len(pairs), "missing_in_mt5": len(missing),
            "extra_in_mt5": len(extra),
            "out_of_tested_window": len(before) + len(after),
            "out_before_start": len(before),
            "out_at_or_after_end": len(after),
            "frozen_only_scheduled_weight": len(frozen_only),
            "expected_set": set_label,
            "mt5_window_start": start,
            "mt5_window_start_line": start_line,
            "mt5_window_end": window_end,
        }
        for p in before:
            raw.append((str(p["fill_time"]), model, {
                "model": model, "symbol": symbol,
                "pairing": OUT_OF_TESTED_WINDOW,
                "python_signal_time": p["signal_time"],
                "python_fill_time": p["fill_time"],
                "python_side_declared": p["side"],
                "python_lots": p["lots"],
                "fill_model": fill_model_of(p),
                "expected_set": set_label,
                "frozen_row_index": p.get("frozen_row_index"),
                "mt5_window_start": start,
                "mt5_window_start_line": start_line,
                "fields": {},
                "note": ("python trade before the MT5 tested window start "
                         "(line quoted above): recorded, not compared -- "
                         "the window is a named limitation, never this "
                         "comparison's divergence"),
            }))
        for p in after:
            raw.append((str(p["fill_time"]), model, {
                "model": model, "symbol": symbol,
                "pairing": OUT_OF_TESTED_WINDOW,
                "python_signal_time": p["signal_time"],
                "python_fill_time": p["fill_time"],
                "python_side_declared": p["side"],
                "python_lots": p["lots"],
                "fill_model": fill_model_of(p),
                "expected_set": set_label,
                "frozen_row_index": p.get("frozen_row_index"),
                "mt5_window_end": window_end,
                "mt5_window_end_source": window_end_source,
                "fields": {},
                "note": ("python trade at/after the tester window end "
                         "(source named above; MT5 ToDate is exclusive): "
                         "recorded, not compared -- the window is a named "
                         "limitation, never this comparison's divergence"),
            }))
        for fo in frozen_only:
            raw.append((str(fo["fill_time"]), model, {
                "model": model, "symbol": symbol,
                "pairing": FROZEN_ONLY_SCHEDULED_WEIGHT,
                "expected_set": set_label,
                "frozen_row_index": fo["frozen_row_index"],
                "python_signal_time": fo["signal_time"],
                "python_fill_time": fo["fill_time"],
                "python_side_declared": fo["side"],
                "fill_model": fill_model_of(fo),
                "entry_kind": fo.get("entry_kind"),
                "python_volume_frozen_basis": fo.get("frozen_basis_lots"),
                "reason": fo["reason"],
                "fields": {},
                "note": ("frozen scheduled-weight row with no weight-in-"
                         "force counterpart (S8-WEIGHT-1): informational, "
                         "recorded uncompared, never a divergence"),
            }))
        per_trade: list[tuple[str, dict]] = []
        deals_all = (log_deals or {}).get(model) or []
        index_of = {d.get("ticket"): k for k, d in enumerate(deals_all)}
        tp_rec = ((tick_paths or {}).get(model) or {}).get("record")
        for p, deal in pairs:
            facts = mt5_deal_line_facts(deal, symbol)
            mt5_time = _ea_time_iso(deal.get("time"))
            fields: dict = {
                "timestamp": {"python": str(p["fill_time"])[:16],
                              "mt5": mt5_time[:16] if mt5_time else None,
                              "basis": og.TS_BASIS_FILL_BAR},
            }
            py_volume = p.get("compare_lots")
            k = index_of.get(deal.get("ticket"))
            after_tick_path = (tp_rec is not None and k is not None
                               and k > tp_rec["deal_index"])
            py_open = (fixture_opens or {}).get(str(p["fill_time"])[:16])
            mt5_side = _PY_SIDE_TO_MT5.get(p["side"], "")
            fill_price = (expected_fill(py_open, mt5_side, fill)[0]
                          if py_open is not None and fill is not None
                          else None)
            stops = (python_stop_levels(risk_ctx, p["fill_time"], mt5_side,
                                        fill_price)
                     if fill_price is not None else
                     {"refused": "no fill-model price for this entry"})
            tick_facts: dict = {}
            if after_tick_path:
                tick_facts, why = _mt5_equity_sizing(
                    deals_all, k, (deposits or {}).get(model), stops,
                    size_rule)
                spec_v = {"python": tick_facts.get("python_volume"),
                          "mt5": deal.get("volume"),
                          "basis": og.VOLUME_BASIS_MT5_EQUITY}
                if why:
                    spec_v.update({"status": "DIVERGENT",
                                   "refused": why})
                fields["volume"] = spec_v
            elif py_volume is not None:
                fields["volume"] = {"python": py_volume,
                                    "mt5": deal.get("volume")}
            else:
                # the MT5 volume stays measured; the python column is
                # absent for the stated reason, never substituted
                fields["volume"] = {"mt5": deal.get("volume")}
            unmeasured = []
            if facts.get("side"):
                fields["entry_side"] = {
                    "python": _PY_SIDE_TO_MT5.get(p["side"], p["side"]),
                    "mt5": facts["side"]}
            else:
                unmeasured.append("side")
            if facts.get("price") is not None:
                spec: dict = {"mt5": facts["price"]}
                py_open = (fixture_opens or {}).get(str(p["fill_time"])[:16])
                if py_open is not None and fill is not None:
                    spec["python"] = expected_fill(
                        py_open, _PY_SIDE_TO_MT5.get(p["side"], ""), fill)[0]
                fields["entry_price"] = spec
            else:
                unmeasured.append("entry_price")
            if request_levels is not None:
                lv = (request_levels.get(model) or {}).get(deal.get("ticket"))
                for name in ("sl", "tp"):
                    spec_l: dict = {"mt5": lv[name] if lv else None}
                    if "refused" in stops:
                        spec_l.update({"python": None, "status": "DIVERGENT",
                                       "refused": stops["refused"]})
                    else:
                        spec_l["python"] = stops[name]
                    fields[name] = spec_l
            event = {
                "model": model, "symbol": symbol,
                "pairing": PAIRED_BY_TIME,
                "time": mt5_time,
                "python_signal_time": p["signal_time"],
                "python_side_declared": p["side"],
                # the volume column in force, recorded per event — and the
                # weight-free approval beside it, labelled, uncompared
                "python_volume_column": (TESTER_WEIGHT_SOURCE
                                         if sd is None else
                                         "weight-in-force window run lots "
                                         "(S8-WEIGHT-1)"),
                "python_approved_lots": p.get("lots"),
                "python_volume_frozen_basis": p.get("frozen_basis_lots"),
                "python_volume_window_basis": (p.get("compare_lots")
                                               if sd is not None else None),
                "python_volume_basis": basis_note,
                "fill_model": fill_model_of(p),
                "expected_set": set_label,
                "frozen_row_index": p.get("frozen_row_index"),
                "mt5_ticket": deal.get("ticket"),
                "fields": fields,
            }
            event["mt5_time_raw"] = mt5_time
            if after_tick_path:
                event.update({
                    "tick_path": og.TICK_PATH_DIVERGENCE,
                    "python_volume_path": py_volume,
                    "python_volume_path_note": (
                        "python-path volume after the tick-path divergence: "
                        "recorded, uncompared (S8-TICKPATH-1)"),
                    **{key: tick_facts.get(key) for key in (
                        "mt5_pre_entry_equity", "book_flat_at_entry",
                        "mt5_deposit", "mt5_deposit_source",
                        "python_stop_distance")}})
            if request_levels is not None:
                lv = (request_levels.get(model) or {}).get(deal.get("ticket"))
                if lv:
                    event["mt5_request_line"] = lv["request_line"]
            if p.get("window_run_fill") is not None:
                # the engine run's own fill (mid +/- costs), labelled,
                # NEVER the compared column (that is the named fill model)
                event["python_window_run_fill"] = p["window_run_fill"]
            if py_volume is None:
                event["python_volume_unavailable"] = p.get(
                    "compare_lots_note",
                    "no python volume for the tester weight column")
            if facts.get("line"):
                event["mt5_deal_line"] = facts["line"]
            if unmeasured:
                event["unmeasured_mt5_fields"] = unmeasured
            per_trade.append((str(p["fill_time"]), event))
        for p in missing:
            per_trade.append((str(p["fill_time"]), {
                "model": model, "symbol": symbol,
                "pairing": MISSING_IN_MT5,
                "python_signal_time": p["signal_time"],
                "python_side_declared": p["side"],
                "python_volume_frozen_basis": p.get("frozen_basis_lots"),
                "python_volume_window_basis": (p.get("compare_lots")
                                               if sd is not None else None),
                "python_volume_basis": basis_note,
                "fill_model": fill_model_of(p),
                "expected_set": set_label,
                "frozen_row_index": p.get("frozen_row_index"),
                "fields": {"state": {
                    "python": (f"entry {p['fill_time']} {p['side']} "
                               f"{p['lots']} lots"),
                    "mt5": (f"{MISSING_IN_MT5}: no entry deal at minute "
                            f"{str(p['fill_time'])[:16]} in the tested "
                            "window")}},
            }))
        for deal in extra:
            mt5_time = _ea_time_iso(deal.get("time"))
            per_trade.append((str(mt5_time), {
                "model": model, "symbol": symbol,
                "pairing": EXTRA_IN_MT5,
                "expected_set": set_label,
                "time": mt5_time,
                "mt5_ticket": deal.get("ticket"),
                "fields": {"state": {
                    "python": (f"{EXTRA_IN_MT5}: no approved python entry "
                               f"at minute {str(mt5_time)[:16]}"),
                    "mt5": (f"entry deal #{deal.get('ticket')} at "
                            f"{mt5_time}")}},
            }))
        per_trade.sort(key=lambda t: t[0])
        for k, (when, event) in enumerate(per_trade):
            event["trade_index"] = k
            raw.append((when, model, event))
    raw.sort(key=lambda t: (t[0], t[1]))
    events = []
    for i, (_, _, event) in enumerate(raw):
        events.append({"index": i, **event})
    events.append({
        "index": len(events), "symbol": symbol,
        "fields": {f"entry_count:{m}": {
            "python": summary[m]["paired"] + summary[m]["missing_in_mt5"],
            "mt5": len(mt5_by_model[m])} for m in sorted(mt5_by_model)},
        "python_out_of_tested_window": {
            m: summary[m]["out_of_tested_window"]
            for m in sorted(mt5_by_model)},
        "python_frozen_only_scheduled_weight": {
            m: summary[m]["frozen_only_scheduled_weight"]
            for m in sorted(mt5_by_model)},
        "expected_set": {m: summary[m]["expected_set"]
                         for m in sorted(mt5_by_model)},
        "note": ("per-model entry counts INSIDE the tested window, from "
                 "each model's expected set; out-of-window and frozen-only "
                 "rows are counted beside, never compared"),
    })
    return events, summary


# ---------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------

def _mt5_equity_sizing(deals: list[dict], k: int, deposit, stops: dict,
                       size_rule) -> tuple[dict, str | None]:
    """S8-TICKPATH-1: the frozen sizing rule on MT5's own pre-entry equity
    for the entry at deal index ``k``: equity = deposit + cumulative pnl of
    deals[:k]; the book must be flat (every earlier entry closed); the
    stop distance is the python one. Returns (facts, refusal-or-None)."""
    dep_value, dep_source = (deposit if isinstance(deposit, tuple)
                             else (None, "no deposit"))
    flat = 2 * len(og.log_entry_deals(deals[:k])) == k
    facts: dict = {"mt5_deposit": dep_value, "mt5_deposit_source": dep_source,
                   "book_flat_at_entry": flat,
                   "python_stop_distance": stops.get("stop_distance")}
    if dep_value is None:
        return facts, f"no deposit: {dep_source}"
    eq = round(float(dep_value) + sum(float(d.get("pnl") or 0.0)
                                      for d in deals[:k]), 2)
    facts["mt5_pre_entry_equity"] = eq
    if not flat:
        return facts, "book not flat at entry: an earlier entry is open"
    if "refused" in stops:
        return facts, f"no python SL distance: {stops['refused']}"
    if size_rule is None:
        return facts, "no sizing rule supplied"
    facts["python_volume"] = size_rule(eq, float(stops["stop_distance"]))
    return facts, None


def _git_head(repo: Path) -> str | None:
    try:
        cp = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=False)
    except OSError:
        return None
    head = cp.stdout.strip()
    return head if cp.returncode == 0 and len(head) == 40 else None


def _remove_previous_build(pkg: Path) -> list[str]:
    """Remove ONLY what the gate itself built into this package last time
    (listed in gate/package_build.json). Owner files are never touched."""
    prev = _load(pkg / GATE_BUILD_REL)
    removed = []
    if isinstance(prev, dict):
        for rel in sorted(prev.get("built") or {}):
            path = (pkg / rel).resolve()
            if pkg.resolve() in path.parents and path.is_file():
                path.unlink()
                removed.append(rel)
    return removed


def build_package(*, repo: Path | str, package: Path | str,
                  gate_evidence: Path | str, data_folder: Path | str | None,
                  golds: list[str], symbolspec_export: Path | str | None,
                  host: dict | None = None,
                  frozen_rel: str = "artifacts/owner_mt5_gate/frozen_inputs.json",
                  symbolspec_custom: dict[str, Path | str] | None = None
                  ) -> dict:
    repo, pkg, ev = Path(repo), Path(package), Path(gate_evidence)
    pkg.mkdir(parents=True, exist_ok=True)
    built: dict[str, str] = {}
    not_built: dict[str, str] = {}
    sources: dict[str, str] = {}
    removed = _remove_previous_build(pkg)

    def put_bytes(rel: str, data: bytes, source: str) -> None:
        path = pkg / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        built[rel] = _sha_bytes(data)
        sources[rel] = source

    def put_json(rel: str, doc: dict, source: str) -> None:
        _write_json(pkg / rel, doc)
        built[rel] = _sha(pkg / rel)
        sources[rel] = source

    head = _git_head(repo)

    # --- gate/stage_5.json: the stage-5 record (NOT_APPLICABLE legs) ------
    stage5_path = ev / "stage_5.json"
    stage5 = _load(stage5_path)
    if isinstance(stage5, dict):
        put_bytes(og.GATE_STAGE5_REL, stage5_path.read_bytes(),
                  f"gate stage-5 record {stage5_path.name}")
    else:
        not_built[og.GATE_STAGE5_REL] = "no readable stage_5.json in the gate evidence"
    na = {g: f for g, f in na_fixtures(stage5).items() if g in golds}

    # --- compile/ (stage 1) ----------------------------------------------
    logs = sorted(ev.glob("compile-*.log"), key=lambda p: p.stat().st_mtime)
    ident: dict = {}
    meta: dict | None = None  # written after symbolspec/ (TERMINAL_BUILD)
    if not logs:
        for key in ("compile_log", "compile_metadata", "ex5"):
            not_built[og.LAYOUT[key]] = "no stage-1 compile log copy in the gate evidence"
    else:
        log = logs[-1]
        put_bytes(og.LAYOUT["compile_log"], log.read_bytes(),
                  f"stage-1 compile log copy {log.name}")
        ident = compile_identity(gs.read_text_bom_aware(log))
        ea_hash = ident["ex5_hashes"].get("Mql5Bot.mq5")
        ex5_src = Path(data_folder) / EA_EX5_REL if data_folder else None
        if not ea_hash:
            not_built[og.LAYOUT["ex5"]] = "the compile log states no ex5 hash for Mql5Bot.mq5"
        elif ex5_src is None or not ex5_src.is_file():
            not_built[og.LAYOUT["ex5"]] = f"compiled EA not found at {ex5_src}"
        elif _sha(ex5_src) != ea_hash:
            not_built[og.LAYOUT["ex5"]] = (
                f"{ex5_src} sha256 {_sha(ex5_src)} != the stage-1 log's "
                f"ex5={ea_hash}: not the binary stage 1 compiled")
        else:
            dest = pkg / og.LAYOUT["ex5"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ex5_src, dest)  # keeps mtime for the freshness check
            built[og.LAYOUT["ex5"]] = _sha(dest)
            sources[og.LAYOUT["ex5"]] = f"{ex5_src} (sha256 == stage-1 log)"
        meta: dict = {"COMPILER_LOG_SHA256": built[og.LAYOUT["compile_log"]],
                      "SOURCE_NOTE": ("SOURCE_COMMIT is the HEAD the gate ran "
                                      "(git rev-parse), not the frozen anchor")}
        for key, val in (("SOURCE_COMMIT", head),
                         ("COMPILER_VERSION", ident.get("compiler_version")),
                         ("EX5_SHA256", ea_hash),
                         ("COMPILE_TIMESTAMP", ident.get("compile_timestamp")),
                         ("ERRORS", ident.get("errors")),
                         ("WARNINGS", ident.get("warnings"))):
            if val is not None:
                meta[key] = val

    # --- symbolspec/ ------------------------------------------------------
    # The tester trades the CUSTOM gold symbol, so the package carries this
    # run's export of THAT symbol (gate stage 4, after import) -- its
    # spread_points is the measured tester spread. The first scoped gold
    # with a custom export fills the slot; each gold's reconciliation reads
    # its OWN custom export. Without one, the stage-3 broker export is used
    # and the record says so.
    custom = {g: Path(p) for g, p in (symbolspec_custom or {}).items()
              if g in golds}
    slot_gold = next((g for g in golds if g in custom), None)
    spec_doc = None
    if slot_gold is not None:
        spec_file: Path | None = custom[slot_gold]
        spec_source: dict = {
            "basis": "custom-symbol export (this run, gate stage 4, after "
                     "import)",
            "gold": slot_gold,
            "symbol": GOLD_FILES[slot_gold]["tester_symbol"]}
    else:
        spec_file = Path(symbolspec_export) if symbolspec_export else None
        spec_source = {"basis": "stage-3 broker export (no custom-symbol "
                                "export supplied)",
                       "gold": None, "symbol": None}
    if spec_file is not None and spec_file.is_file():
        raw = spec_file.read_bytes()
        spec_source.update({"file": str(spec_file),
                            "sha256": _sha_bytes(raw)})
        put_bytes(og.LAYOUT["symbolspec"], raw,
                  f"{spec_source['basis']}: {spec_file.name}")
        try:
            spec_doc = json.loads(gs.decode_bom_aware(raw))
        except ValueError:
            spec_doc = None
        if isinstance(spec_doc, dict) and spec_source["symbol"] is None:
            sym = spec_doc.get("symbol")
            spec_source["symbol"] = (sym.get("name") if isinstance(sym, dict)
                                     else sym)
    else:
        spec_source["file"] = str(spec_file) if spec_file else None
        not_built[og.LAYOUT["symbolspec"]] = (
            f"{spec_source['basis']}: export not found: {spec_file}")
    spec_symbol = spec_doc.get("symbol") if isinstance(spec_doc, dict) else None

    # --- compile/compile_metadata.json (after symbolspec/) ---------------
    # TERMINAL_BUILD: the compile log states none, so it comes from the
    # same-run SymbolSpec export's flat terminal_build (the terminal that
    # compiled and ran this gate), source named -- as environment.json does
    if meta is not None:
        tb_export = (spec_doc.get("terminal_build")
                     if isinstance(spec_doc, dict) else None)
        if tb_export not in (None, ""):
            meta["TERMINAL_BUILD"] = tb_export
            meta["TERMINAL_BUILD_SOURCE"] = (
                f"{spec_source['basis']} flat terminal_build "
                "(TerminalInfoInteger(TERMINAL_BUILD)), "
                f"{Path(spec_source['file']).name}")
        put_json(og.LAYOUT["compile_metadata"], meta,
                 "parsed stage-1 compile log + git HEAD"
                 + (" + same-run SymbolSpec export terminal_build"
                    if "TERMINAL_BUILD" in meta else ""))

    # --- symbolspec/import_<gold>.json + tester/<gold>_<model>.ini --------
    # S8-SPEC-3 witnesses for a custom symbol's derived tick value: the
    # same-run stage-4 import record (its SYMBOL_TRADE_TICK_VALUE read-back)
    # and each leg's intended tester .ini (deposit Currency); byte copies,
    # bound by archive_manifest.json like every package file
    for gold in golds:
        sym = GOLD_FILES[gold]["tester_symbol"]
        rec = ev / f"import_{sym}.json"
        if rec.is_file():
            put_bytes(og.symbolspec_import_rel(gold), rec.read_bytes(),
                      f"gate stage-4 import record {rec.name}")
        else:
            not_built[og.symbolspec_import_rel(gold)] = (
                f"no stage-4 import record {rec.name} in the gate evidence")
        for model in LEG_MODELS:
            ini = ev / f"tester_{gold}_{model}.ini"
            if ini.is_file():
                put_bytes(og.tester_ini_rel(gold, model), ini.read_bytes(),
                          f"gate stage-5 intended tester config {ini.name}")

    # --- environment.json -------------------------------------------------
    windows = [gs.read_text_bom_aware(p) for g in golds
               for p in sorted(ev.glob(f"tester_{g}_*_window.txt"))]
    facts = window_facts(windows)
    env: dict = {"field_sources": {}, "tester_symbols": {
        g: GOLD_FILES[g]["tester_symbol"] for g in golds}}
    # terminal_build/broker from the stage-3 export's flat fields
    # (S8-SPEC-1) when the leg windows did not state them; the source
    # names which one was used
    spec_flat = spec_doc if isinstance(spec_doc, dict) else {}
    tb, tb_src = facts["terminal_build"], "leg windows: '... build N'"
    if not tb and spec_flat.get("terminal_build"):
        tb = spec_flat["terminal_build"]
        tb_src = ("stage-3 SymbolSpec export flat terminal_build "
                  "(TerminalInfoInteger(TERMINAL_BUILD))")
    for field, val, src in (
            ("server", facts["server"], "leg windows: '(<server>): ... generating'"),
            ("terminal_build", tb, tb_src),
            ("broker", spec_flat.get("broker"),
             ("stage-3 SymbolSpec export flat broker "
              "(AccountInfoString(ACCOUNT_COMPANY))")),
            ("account_mode", facts["account_mode"], "leg windows: hedging|netting"),
            ("symbol", spec_symbol, "stage-3 SymbolSpec export (the custom symbols carry its spec)"),
            ("run_timestamp", (stage5 or {}).get("utc") if isinstance(stage5, dict) else None,
             "gate stage-5 record utc"),
            ("os", (host or {}).get("os"), "gate host"),
            ("timezone", (host or {}).get("timezone"), "gate host")):
        if val:
            env[field] = val
            env["field_sources"][field] = src
    env["unmeasured"] = sorted(
        f for f in ("os", "terminal_build", "broker", "server",
                    "account_mode", "symbol", "timezone", "run_timestamp")
        if f not in env)
    put_json(og.LAYOUT["environment"], env, "measured lines only; gaps omitted")

    # --- real_tick_coverage.json -----------------------------------------
    if golds and all(g in na for g in golds):
        put_json(og.LAYOUT["real_tick_coverage"], {
            "coverage": og.REAL_TICK_COVERAGE_NONE,
            "leg_launched": False,
            "outcome": og.STAGE5_NOT_APPLICABLE,
            "requested_model": mt.MT5_MODEL_LABELS[LEG_MODELS["real_ticks"]],
            "symbol": spec_symbol,
            "golds": {g: {"fixture": na[g], "leg": "not launched",
                          "tester_symbol": GOLD_FILES[g]["tester_symbol"]}
                      for g in golds},
            "note": ("NONE (bar-only fixture): no real_ticks leg ran, so "
                     "nothing about real ticks is evidenced. Never FULL.")},
            "gate stage-5 record (NOT_APPLICABLE legs)")
    else:
        not_built[og.LAYOUT["real_tick_coverage"]] = (
            "a scoped gold's real_ticks leg was launched (or no stage-5 "
            "record): the gate builds a coverage record only for "
            "NOT_APPLICABLE legs; FULL/PARTIAL evidence is the owner's")

    # --- log_windows/<gold>_<model>.txt (S8-SLTP-1) ----------------------
    # byte copy of each log-sourced leg's window capture, ONLY when its
    # bytes are the ones the log trade list names (window_sha256): the
    # entry request lines' sl/tp are read from it, by builder and verifier
    for gold, model in sorted(og.log_sourced_legs(pkg)):
        if gold not in golds:
            continue
        rel = og.log_window_rel(gold, model)
        win = ev / f"tester_{gold}_{model}_window.txt"
        want = (_load(pkg / og.log_trades_rel(gold, model)) or {}).get(
            "window_sha256")
        if not win.is_file():
            not_built[rel] = f"no window capture {win.name} in the gate evidence"
        elif _sha(win) != want:
            not_built[rel] = (f"{win.name} sha256 != the log trade list's "
                              f"window_sha256 {want}")
        else:
            put_bytes(rel, win.read_bytes(),
                      f"gate stage-5 leg window capture {win.name}")

    # --- reconciliation/<gold>.json ----------------------------------------
    for gold in golds:
        rel = og.LAYOUT[f"reconciliation_{gold}"]
        why = _build_reconciliation(repo, pkg, gold, na, head, put_json, ev,
                                    spec_path=custom.get(gold))
        if why:
            not_built[rel] = why

    # --- safety/ (8a-8d, docs/SAFETY_8A_8D_PLAN.md) ------------------------
    # Only from a safety tester leg THIS gate ran: its window is copied to
    # safety/raw/ and graded by mql5bot.safety_legs against the same run's
    # gold m1_ohlc window (also copied). A test the tester cannot run, or
    # whose leg left no window, is never written: it stays MISSING.
    from mql5bot import safety_legs as sl

    base_gold = golds[0] if golds else None
    base_win = (ev / f"tester_{base_gold}_{sl.BASELINE_MODEL}_window.txt"
                if base_gold else None)
    for name in og.SAFETY_TESTS + ("netting", "hedging"):
        rel = og.LAYOUT.get(name, f"safety/{name}.json")
        if name in sl.DEMO_ONLY:
            not_built[rel] = f"demo-only, not a tester leg: {sl.DEMO_ONLY[name]}"
            continue
        win = ev / f"tester_{sl.leg_tag(name)}_window.txt"
        if not win.is_file():
            not_built[rel] = (f"no safety leg window {win.name} in the gate "
                              "evidence: the tester leg did not run")
            continue
        if base_win is None or not base_win.is_file():
            not_built[rel] = ("no baseline gold m1_ohlc window in the gate "
                              "evidence: the safety leg cannot be graded")
            continue
        raw_rel = f"safety/raw/{name}_window.txt"
        put_bytes(raw_rel, win.read_bytes(),
                  f"gate safety tester leg window {win.name}")
        base_rel = f"safety/raw/baseline_{base_gold}_{sl.BASELINE_MODEL}_window.txt"
        if base_rel not in built:
            put_bytes(base_rel, base_win.read_bytes(),
                      f"gate stage-5 baseline window {base_win.name}")
        doc = sl.grade(name, gs.read_text_bom_aware(win),
                       gs.read_text_bom_aware(base_win),
                       GOLD_FILES[base_gold]["tester_symbol"])
        doc["raw_evidence"] = {"path": raw_rel, "sha256": built[raw_rel]}
        doc["baseline_evidence"] = {"path": base_rel,
                                    "sha256": built[base_rel]}
        doc["source"] = ("graded by mql5bot.safety_legs from the MT5 "
                         "Strategy Tester leg window of this gate run")
        put_json(rel, doc, f"graded safety leg {win.name}")

    # --- record, then archive_manifest.json LAST (owner_evidence_bind) ----
    record = {"schema": "mql5bot.stage8_package_build/1", "golds": golds,
              "built": dict(sorted(built.items())), "sources": sources,
              "not_built": dict(sorted(not_built.items())),
              "removed_previous_build": removed,
              "symbolspec_source": spec_source,
              "not_applicable": {g: na[g] for g in sorted(na)}}
    put_json(GATE_BUILD_REL, record, "this builder")
    record["built"][GATE_BUILD_REL] = built[GATE_BUILD_REL]
    bind = repo / "tools" / "owner_evidence_bind.py"
    cp = subprocess.run([sys.executable, str(bind), "manifest", str(pkg),
                         "--frozen", str(repo / frozen_rel)],
                        capture_output=True, text=True, check=False)
    if cp.returncode == 0:
        (pkg / og.LAYOUT["archive_manifest"]).write_text(cp.stdout,
                                                         encoding="utf-8")
        record["archive_manifest_sha256"] = _sha(pkg / og.LAYOUT["archive_manifest"])
    else:
        record["not_built"][og.LAYOUT["archive_manifest"]] = (
            f"owner_evidence_bind.py exit {cp.returncode}: {cp.stderr.strip()}")
    record["ok"] = cp.returncode == 0
    record["package"] = str(pkg)
    return record


def _build_reconciliation(repo: Path, pkg: Path, gold: str, na: dict,
                          head: str | None, put_json,
                          gate_evidence: Path | None = None,
                          spec_path: Path | None = None) -> str | None:
    """Write reconciliation/<gold>.json; return the reason when it cannot be
    built honestly."""
    files = GOLD_FILES[gold]
    manifest = _load(repo / files["manifest"])
    expected = _load(repo / files["expected"])
    if not isinstance(manifest, dict) or not isinstance(expected, dict):
        return "manifest or expected_execution unreadable"
    py, py_note = python_entries(expected, manifest.get("timeframe"))
    if py is None:
        return py_note
    # this gold's own custom-symbol export when the gate supplied one (the
    # tester trades that symbol), else the package's symbolspec slot: its
    # flat MEASURED spread_points (S8-SPEC-1) feeds the expected fill
    # model and the window-run cost; manifest fallback stated otherwise
    spec_file = Path(spec_path) if spec_path else pkg / og.LAYOUT["symbolspec"]
    spec_doc = _load(spec_file)
    sym = spec_doc.get("symbol") if isinstance(spec_doc, dict) else None
    spread_source = {
        "file": str(spec_file),
        "sha256": _sha(spec_file) if spec_file.is_file() else None,
        "symbol": sym.get("name") if isinstance(sym, dict) else sym,
        "basis": ("this gold's custom-symbol export (gate stage 4)"
                  if spec_path else "package symbolspec slot")}
    fill, fill_note = fill_spec_of(
        manifest, spec_doc if isinstance(spec_doc, dict) else None)
    if fill is None:
        return fill_note
    log_models = {m for g, m in og.log_sourced_legs(pkg) if g == gold}
    na_models = {"real_ticks"} if gold in na else set()
    report_models = set(og.MODELS) - log_models - na_models
    if report_models:
        return (f"models {sorted(report_models)} are neither log-sourced nor "
                "NOT_APPLICABLE: binding a report-sourced leg is not "
                "implemented in the gate builder")
    tester_models: dict = {}
    mt5_by_model: dict[str, list[dict]] = {}
    notes: dict[str, str] = {"python": f"{files['expected']}: {py_note}"}
    log_hashes: dict[str, str] = {}
    window_starts: dict[str, tuple[str | None, str | None]] = {}
    log_deals: dict[str, list[dict]] = {}
    request_levels: dict[str, dict] = {}
    deposits: dict[str, tuple] = {}
    risk_ctx, risk_note = python_risk_context(repo, gold)
    for model in sorted(log_models):
        path = pkg / og.log_trades_rel(gold, model)
        doc = _load(path) or {}
        log_deals[model] = [d for d in doc.get("deals") or []
                            if isinstance(d, dict)]
        wcopy = pkg / og.log_window_rel(gold, model)
        request_levels[model] = (og.entry_request_levels(
            gs.read_text_bom_aware(wcopy), files["tester_symbol"])
            if wcopy.is_file() else {})
        ini = pkg / og.tester_ini_rel(gold, model)
        dep = og.ini_deposit(ini.read_bytes()) if ini.is_file() else None
        eq0 = ((manifest.get("risk_config") or {}).get("equity_start"))
        if dep is None:
            deposits[model] = (None, f"no Deposit in {og.tester_ini_rel(gold, model)}")
        elif eq0 is None or float(eq0) != dep:
            deposits[model] = (None, (f"tester ini Deposit {dep} != manifest "
                                      f"risk_config.equity_start {eq0}"))
        else:
            deposits[model] = (dep, (f"{og.tester_ini_rel(gold, model)} "
                                     "Deposit (== manifest equity_start)"))
        log_hashes[model] = _sha(path)
        tester_models[model] = {"requested": LEG_MODELS[model],
                                "log_reported": (doc.get("settings") or {}).get("model")}
        entries, note = mt5_entries(doc.get("deals") or [])
        notes[model] = note
        if entries is not None:
            mt5_by_model[model] = entries
        win = (gate_evidence / f"tester_{gold}_{model}_window.txt"
               if gate_evidence else None)
        window_starts[model] = tested_window_start(
            gs.read_text_bom_aware(win) if win and win.is_file() else "",
            files["tester_symbol"])
    if not mt5_by_model:
        return "no log-sourced model yielded a usable entry list: " + "; ".join(
            f"{k}: {v}" for k, v in notes.items())
    for model in sorted(na_models):
        tester_models[model] = {"not_applicable": True,
                                "outcome": og.STAGE5_NOT_APPLICABLE,
                                "requested": LEG_MODELS[model],
                                "fixture": na[gold]}

    def sha_of(rel: str) -> str | None:
        p = pkg / rel
        return _sha(p) if p.is_file() else None

    fixture = repo / files["fixture"]
    bindings = {
        "source_commit": head,
        "fixture_sha256": _sha(fixture),
        "config_hash": manifest.get("config_hash"),
        "dataset_hash": gs.dataset_hash_of_csv(fixture),
        "symbolspec_sha256": sha_of(og.LAYOUT["symbolspec"]),
        "ex5_sha256": sha_of(og.LAYOUT["ex5"]),
        "expected_execution_sha256": _sha(repo / files["expected"]),
        "tester_models": tester_models,
        "raw_report_hashes": {},
        "parsed_report_hashes": {},
        "log_trade_hashes": log_hashes,
    }
    # tester window END: the ToDate the gate itself derives from the frozen
    # fixture (the same mt5tester.fixture_date_range the ps1 feeds the
    # tester config); MT5 treats ToDate as EXCLUSIVE, so the tested window
    # ends at ToDate 00:00 (gate_run28: no MT5 deals on the ToDate day
    # while python fills 5 entries there).
    try:
        date_to = mt.fixture_date_range(fixture)[1]
        window_end = date_to.replace(".", "-") + "T00:00:00"
        window_end_source = (
            f"tester ToDate {date_to} derived from the fixture "
            "(mt5tester.fixture_date_range, the same derivation the gate's "
            "tester config uses); MT5 ToDate is exclusive")
    except ValueError:
        window_end, window_end_source = None, None
    # expected entry set (S8-WEIGHT-1): one guarded weight-in-force run
    # per distinct measured window start (models normally share it)
    by_start: dict = {}
    expected_sets = {}
    for model in sorted(mt5_by_model):
        start = window_starts.get(model, (None, None))[0]
        if start not in by_start:
            by_start[start] = expected_set_window_run(
                repo, gold, start, window_end,
                spread_points=float(fill["spread_points"]),
                spread_source=fill.get("spread_source", "manifest"))
        expected_sets[model] = by_start[start]
    # S8-TICKPATH-1: each tick-generating leg's first exit that differs
    # from the m1_ohlc leg (observed, named; never a divergence by itself)
    tick_paths: dict[str, dict] = {}
    for model in sorted(set(log_deals) & set(og.TICK_PATH_MODELS)):
        ref = log_deals.get(og.TICK_PATH_REFERENCE)
        rec, note = (og.tick_path_divergence(ref, log_deals[model])
                     if ref is not None else
                     (None, (f"no {og.TICK_PATH_REFERENCE} log leg: the "
                             "leg stays fully strict")))
        tick_paths[model] = {"record": rec, "note": note}

    def size_rule(equity: float, stop_distance: float) -> float:
        return frozen_rule_lots(risk_ctx["spec"], risk_ctx["risk"], equity,
                                stop_distance)

    events, pairing = reconciliation_events(
        py, mt5_by_model, files["tester_symbol"],
        window_starts=window_starts,
        window_end=window_end, window_end_source=window_end_source,
        fixture_opens=fixture_minute_opens(fixture), fill=fill,
        expected_sets=expected_sets, log_deals=log_deals,
        tick_paths=tick_paths, deposits=deposits,
        size_rule=size_rule if risk_ctx is not None else None,
        risk_ctx=risk_ctx, request_levels=request_levels)
    limitations = []
    for model in sorted(mt5_by_model):
        sd, sd_note = expected_sets[model]
        if sd is None:
            limitations.append(
                f"{model}: expected set FALLBACK to the frozen scheduled-"
                f"weight column -- the weight-in-force run was refused: "
                f"{sd_note}; the comparison is stated on every event, "
                "never silent")
        else:
            reasons: dict[str, int] = {}
            for fo in sd["frozen_only"]:
                reasons[fo["reason"]] = reasons.get(fo["reason"], 0) + 1
            if reasons:
                detail = ", ".join(f"{n} {r}" for r, n in sorted(
                    reasons.items()))
                limitations.append(
                    f"{model}: {sum(reasons.values())} frozen scheduled-"
                    "weight rows have no weight-in-force counterpart "
                    f"(FROZEN_ONLY_SCHEDULED_WEIGHT, informational, never "
                    f"a divergence): {detail}")
        n_before = pairing[model]["out_before_start"]
        n_after = pairing[model]["out_at_or_after_end"]
        start, line = window_starts.get(model, (None, None))
        if n_before:
            limitations.append(
                f"{model}: {n_before} python "
                f"entr{'y' if n_before == 1 else 'ies'} "
                f"fill before the measured MT5 tested-window start {start} "
                f"({line!r}) -- OUT_OF_TESTED_WINDOW, recorded uncompared; "
                "the window is a named limitation of this comparison, "
                "never its first divergence")
        elif start is None:
            limitations.append(
                f"{model}: no measured window-start line in this leg's "
                "window capture; every python entry is treated as inside "
                "the tested window")
        if n_after:
            limitations.append(
                f"{model}: {n_after} python "
                f"entr{'y' if n_after == 1 else 'ies'} "
                f"fill at/after the tester window end {window_end} "
                f"({window_end_source}) -- OUT_OF_TESTED_WINDOW, recorded "
                "uncompared; never this comparison's divergence")
    for model in sorted(tick_paths):
        rec = tick_paths[model]["record"]
        if rec is not None:
            limitations.append(
                f"{model}: {og.TICK_PATH_DIVERGENCE} at deal index "
                f"{rec['deal_index']} (ticket {rec['ticket']}): "
                f"{model} {rec['tick_deal']['time']} @"
                f"{rec['tick_deal']['price']} pnl {rec['tick_deal']['pnl']} "
                f"vs m1_ohlc {rec['reference_deal']['time']} @"
                f"{rec['reference_deal']['price']} pnl "
                f"{rec['reference_deal']['pnl']}; later entries compare "
                "volume against the frozen sizing rule on MT5's own "
                "pre-entry equity (S8-TICKPATH-1)")
    if risk_ctx is None:
        limitations.append(f"python SL/TP and MT5-equity sizing refused: "
                           f"{risk_note}")
    doc = {
        "schema": "mql5bot.gate_reconciliation/1",
        "gold": gold,
        "built_by": "owner gate (stage8_package), from its own measured outputs",
        "python_source": files["expected"],
        "python_vs_mt5_tester": "COMPARED_FROM_TESTER_LOG",
        "bindings": {k: v for k, v in bindings.items() if v is not None},
        "events": events,
        "pairing": pairing,
        "pairing_notes": notes,
        "fill_model": {"buy": fill_model_buy_name(fill),
                       "sell": FILL_MODEL_SELL,
                       "inputs": fill, "inputs_source": fill_note,
                       "spread_source": spread_source,
                       "slippage_applied": False, "note": FILL_MODEL_NOTE},
        "expected_set": {m: {
            "set": (EXPECTED_SET_WINDOW_RUN if expected_sets[m][0]
                    is not None else EXPECTED_SET_FROZEN + " (fallback)"),
            "note": expected_sets[m][1]} for m in sorted(expected_sets)},
        "limitations": limitations,
        "tick_path_divergence": tick_paths,
        "note": ("Events pair python entries with MT5 entry deals BY TIME "
                 "(same fill minute, signal_time + 1 bar), never by list "
                 "position. Python trades before the measured MT5 window "
                 "start, or at/after the tester ToDate window end "
                 "(exclusive), are OUT_OF_TESTED_WINDOW (quoted/sourced, "
                 "uncompared); "
                 "unpaired trades inside the window are MISSING_IN_MT5 / "
                 "EXTRA_IN_MT5 divergences. Compared fields per pair: "
                 "timestamp, volume and entry side/price when the MT5 "
                 "journal deal line states them. The python column is the "
                 "EXPECTED SET (S8-WEIGHT-1): the guarded weight-in-force "
                 "run's own entries/side/lots, else the frozen scheduled-"
                 "weight column with the fallback stated on every event. "
                 "Frozen rows with no weight-in-force counterpart are "
                 "FROZEN_ONLY_SCHEDULED_WEIGHT (informational, never a "
                 "divergence). The python entry price is the named fill "
                 "model on the fixture open at the fill minute: "
                 f"{FILL_MODEL_SELL} / {FILL_MODEL_BUY}. Bindings nothing "
                 "measured are omitted and the verifier names them."),
    }
    put_json(og.LAYOUT[f"reconciliation_{gold}"], doc,
             f"{files['expected']} (python) + log trade lists (mt5)")
    return None


def divergence_note(verify_report: dict, golds: list[str]) -> str:
    """One stage-8 reason fragment quoting each gold's first divergence (and
    first per-trade divergence) whatever the verdict. Empty when none."""
    parts = []
    for key, label in (("first_divergence", "first divergence"),
                       ("first_trade_divergence", "first per-trade divergence")):
        per = verify_report.get(key) or {}
        for gold in golds:
            div = per.get(gold)
            if not div:
                continue
            where = (f"trade {div.get('trade_index')} ({div.get('model')})"
                     if div.get("trade_index") is not None
                     else f"event {div.get('event_index')}")
            parts.append(
                f"{gold} {label}: field {div.get('first_divergent_field')!r} "
                f"python={div.get('python_value')!r} "
                f"mt5={div.get('mt5_value')!r} at {where}, time "
                f"{div.get('timestamp')} -> {div.get('classification')}"
                + ("" if div.get("binding_verified")
                   else " [observed; binding chain NOT verified]"))
    return "; ".join(parts)


__all__ = [
    "EXPECTED_SET_FROZEN",
    "EXPECTED_SET_WINDOW_RUN",
    "EXTRA_IN_MT5",
    "FILL_MODEL_BUY",
    "FILL_MODEL_SELL",
    "FROZEN_ONLY_SCHEDULED_WEIGHT",
    "GATE_BUILD_REL",
    "MISSING_IN_MT5",
    "OUT_OF_TESTED_WINDOW",
    "PAIRED_BY_TIME",
    "TESTER_WEIGHT_COLUMN",
    "TESTER_WEIGHT_SOURCE",
    "build_package",
    "compile_identity",
    "divergence_note",
    "expected_fill",
    "expected_set_window_run",
    "fill_model_buy_name",
    "fill_spec_of",
    "fixture_minute_opens",
    "mt5_deal_line_facts",
    "mt5_entries",
    "na_fixtures",
    "python_entries",
    "reconciliation_events",
    "tested_window_start",
    "window_facts",
]
