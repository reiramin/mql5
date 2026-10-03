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

Built, unit-tested, never run live.
"""

from __future__ import annotations

import csv
import hashlib
import json
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
              "tester_symbol": "EURUSD.G1"},
    "gold2": {"manifest": "artifacts/gold_2/manifest.json",
              "fixture": "artifacts/gold_2/gold2_fixture.csv",
              "expected": "artifacts/gold_2/expected_execution.json",
              "tester_symbol": "EURUSD.G2"},
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
PAIRED_BY_TIME = "PAIRED_BY_TIME"
OUT_OF_TESTED_WINDOW = "OUT_OF_TESTED_WINDOW"
MISSING_IN_MT5 = "MISSING_IN_MT5"
EXTRA_IN_MT5 = "EXTRA_IN_MT5"
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


def python_entries(expected: dict, timeframe: str) -> tuple[list[dict] | None,
                                                            str]:
    """The approved entries of expected_execution.json, in signal order. The
    fill time is signal_time + one bar (manifest signal_timing_contract:
    action at the next bar open)."""
    rows = expected.get("entries") if isinstance(expected, dict) else None
    step = TF_SECONDS.get(str(timeframe))
    if not isinstance(rows, list):
        return None, "expected_execution has no 'entries' list (schema not supported)"
    if step is None:
        return None, f"timeframe {timeframe!r} has no bar length"
    out = []
    for row in sorted(rows, key=lambda r: str(r.get("signal_time"))):
        risk = row.get("risk") or {}
        if risk.get("rejected"):
            continue
        sig = datetime.fromisoformat(str(row["signal_time"]))
        out.append({"signal_time": row["signal_time"],
                    "fill_time": (sig + timedelta(seconds=step)).isoformat(),
                    "side": row.get("side"),
                    "lots": risk.get("approved_lots")})
    return out, f"{len(out)} approved entries"


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
    bar open, so the fixture open at the fill minute IS the python-side
    expected entry price (bid basis; the fixture carries no spread)."""
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
                          fixture_opens: dict[str, float] | None = None
                          ) -> tuple[list[dict], dict]:
    """Per-model events pairing python entries with MT5 entry deals BY TIME
    (same fill minute), never by list position. Returns (events, summary).

    * a python trade whose fill is before the model's measured MT5 window
      start is OUT_OF_TESTED_WINDOW: recorded with the measured start line
      quoted, with NO compared fields -- never silently dropped, never
      counted as matched, and never a divergence (the window is a named
      limitation of the comparison, not its first divergence);
    * an unpaired python trade INSIDE the window is MISSING_IN_MT5 and an
      unpaired MT5 entry deal is EXTRA_IN_MT5 -- both ARE divergences
      (field `state`, so the closed taxonomy classifies them);
    * a paired event compares timestamp, volume, and -- when the MT5 journal
      line in the deal's `lines` states them -- entry side and entry price.
      The python entry price is the fixture open at the fill minute (the
      manifest fills at next bar open); when either side lacks a value the
      field carries only what was measured, never an invented one;
    * `trade_index` numbers a model's per-trade events in time order;
    * a final event compares per-model entry counts INSIDE the window (the
      out-of-window count is beside it, uncompared).
    """
    window_starts = window_starts or {}
    raw: list[tuple[str, str, dict]] = []
    summary: dict[str, dict] = {}
    for model in sorted(mt5_by_model):
        entries = mt5_by_model[model]
        start, start_line = window_starts.get(model, (None, None))
        before = [p for p in py
                  if start is not None and str(p["fill_time"]) < start]
        in_window = [p for p in py
                     if start is None or str(p["fill_time"]) >= start]
        pairs, missing, extra = _pair_by_minute(in_window, entries)
        summary[model] = {
            "paired": len(pairs), "missing_in_mt5": len(missing),
            "extra_in_mt5": len(extra),
            "out_of_tested_window": len(before),
            "mt5_window_start": start,
            "mt5_window_start_line": start_line,
        }
        for p in before:
            raw.append((str(p["fill_time"]), model, {
                "model": model, "symbol": symbol,
                "pairing": OUT_OF_TESTED_WINDOW,
                "python_signal_time": p["signal_time"],
                "python_fill_time": p["fill_time"],
                "python_side_declared": p["side"],
                "python_lots": p["lots"],
                "mt5_window_start": start,
                "mt5_window_start_line": start_line,
                "fields": {},
                "note": ("python trade before the MT5 tested window start "
                         "(line quoted above): recorded, not compared -- "
                         "the window is a named limitation, never this "
                         "comparison's divergence"),
            }))
        per_trade: list[tuple[str, dict]] = []
        for p, deal in pairs:
            facts = mt5_deal_line_facts(deal, symbol)
            mt5_time = _ea_time_iso(deal.get("time"))
            fields: dict = {
                "timestamp": {"python": p["fill_time"], "mt5": mt5_time},
                "volume": {"python": p["lots"], "mt5": deal.get("volume")},
            }
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
                if py_open is not None:
                    spec["python"] = py_open
                fields["entry_price"] = spec
            else:
                unmeasured.append("entry_price")
            event = {
                "model": model, "symbol": symbol,
                "pairing": PAIRED_BY_TIME,
                "time": mt5_time,
                "python_signal_time": p["signal_time"],
                "python_side_declared": p["side"],
                "mt5_ticket": deal.get("ticket"),
                "fields": fields,
            }
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
        "note": ("per-model entry counts INSIDE the tested window; python "
                 "trades before the measured MT5 window start are counted "
                 "beside, never compared"),
    })
    return events, summary


# ---------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------

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
                  frozen_rel: str = "artifacts/owner_mt5_gate/frozen_inputs.json"
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
        put_json(og.LAYOUT["compile_metadata"], meta,
                 "parsed stage-1 compile log + git HEAD")

    # --- symbolspec/ (stage 3) -------------------------------------------
    spec_doc = None
    if symbolspec_export and Path(symbolspec_export).is_file():
        raw = Path(symbolspec_export).read_bytes()
        put_bytes(og.LAYOUT["symbolspec"], raw,
                  f"stage-3 SymbolSpec export {Path(symbolspec_export).name}")
        try:
            spec_doc = json.loads(gs.decode_bom_aware(raw))
        except ValueError:
            spec_doc = None
    else:
        not_built[og.LAYOUT["symbolspec"]] = f"stage-3 export not found: {symbolspec_export}"
    spec_symbol = spec_doc.get("symbol") if isinstance(spec_doc, dict) else None

    # --- environment.json -------------------------------------------------
    windows = [gs.read_text_bom_aware(p) for g in golds
               for p in sorted(ev.glob(f"tester_{g}_*_window.txt"))]
    facts = window_facts(windows)
    env: dict = {"field_sources": {}, "tester_symbols": {
        g: GOLD_FILES[g]["tester_symbol"] for g in golds}}
    for field, val, src in (
            ("server", facts["server"], "leg windows: '(<server>): ... generating'"),
            ("terminal_build", facts["terminal_build"], "leg windows: '... build N'"),
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

    # --- reconciliation/<gold>.json ----------------------------------------
    for gold in golds:
        rel = og.LAYOUT[f"reconciliation_{gold}"]
        why = _build_reconciliation(repo, pkg, gold, na, head, put_json, ev)
        if why:
            not_built[rel] = why

    for name in og.SAFETY_TESTS + ("netting", "hedging"):
        not_built[og.LAYOUT.get(name, f"safety/{name}.json")] = (
            "never built by the gate: 8a-8d have not run on MT5")

    # --- record, then archive_manifest.json LAST (owner_evidence_bind) ----
    record = {"schema": "mql5bot.stage8_package_build/1", "golds": golds,
              "built": dict(sorted(built.items())), "sources": sources,
              "not_built": dict(sorted(not_built.items())),
              "removed_previous_build": removed,
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
                          gate_evidence: Path | None = None) -> str | None:
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
    for model in sorted(log_models):
        path = pkg / og.log_trades_rel(gold, model)
        doc = _load(path) or {}
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
    events, pairing = reconciliation_events(
        py, mt5_by_model, files["tester_symbol"],
        window_starts=window_starts,
        fixture_opens=fixture_minute_opens(fixture))
    limitations = []
    for model in sorted(mt5_by_model):
        n_out = pairing[model]["out_of_tested_window"]
        start, line = window_starts.get(model, (None, None))
        if n_out:
            limitations.append(
                f"{model}: {n_out} python entr{'y' if n_out == 1 else 'ies'} "
                f"fill before the measured MT5 tested-window start {start} "
                f"({line!r}) -- OUT_OF_TESTED_WINDOW, recorded uncompared; "
                "the window is a named limitation of this comparison, "
                "never its first divergence")
        elif start is None:
            limitations.append(
                f"{model}: no measured window-start line in this leg's "
                "window capture; every python entry is treated as inside "
                "the tested window")
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
        "limitations": limitations,
        "note": ("Events pair python entries with MT5 entry deals BY TIME "
                 "(same fill minute, signal_time + 1 bar), never by list "
                 "position. Python trades before the measured MT5 window "
                 "start are OUT_OF_TESTED_WINDOW (quoted, uncompared); "
                 "unpaired trades inside the window are MISSING_IN_MT5 / "
                 "EXTRA_IN_MT5 divergences. Compared fields per pair: "
                 "timestamp, volume, and entry side/price when the MT5 "
                 "journal deal line states them (python entry price = "
                 "fixture open at the fill minute, the manifest's "
                 "next-bar-open fill). Bindings nothing measured are "
                 "omitted and the verifier names them."),
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
    "EXTRA_IN_MT5",
    "GATE_BUILD_REL",
    "MISSING_IN_MT5",
    "OUT_OF_TESTED_WINDOW",
    "PAIRED_BY_TIME",
    "build_package",
    "compile_identity",
    "divergence_note",
    "fixture_minute_opens",
    "mt5_deal_line_facts",
    "mt5_entries",
    "na_fixtures",
    "python_entries",
    "reconciliation_events",
    "tested_window_start",
    "window_facts",
]
