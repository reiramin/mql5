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

Built, unit-tested, never run live.
"""

from __future__ import annotations

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


def reconciliation_events(py: list[dict], mt5_by_model: dict[str, list[dict]],
                          symbol: str) -> list[dict]:
    """One event per (trade index, model), python vs mt5 on the fields BOTH
    sides measured: fill timestamp and volume. Side and price are not stated
    by the EA's DEAL line, so they are listed as unmeasured, never compared.
    A final event compares the entry counts."""
    models = sorted(mt5_by_model)
    events: list[dict] = []
    for pos, model in enumerate(models):
        entries = mt5_by_model[model]
        for k in range(min(len(py), len(entries))):
            deal = entries[k]
            events.append({
                "index": k * len(models) + pos,
                "trade_index": k,
                "model": model,
                "symbol": symbol,
                "time": _ea_time_iso(deal.get("time")),
                "python_signal_time": py[k]["signal_time"],
                "mt5_ticket": deal.get("ticket"),
                "fields": {
                    "timestamp": {"python": py[k]["fill_time"],
                                  "mt5": _ea_time_iso(deal.get("time"))},
                    "volume": {"python": py[k]["lots"],
                               "mt5": deal.get("volume")},
                },
                "unmeasured_mt5_fields": ["side", "entry_price"],
            })
    tail = max([e["index"] for e in events], default=-1) + 1
    events.append({
        "index": tail, "symbol": symbol,
        "fields": {f"entry_count:{m}": {"python": len(py),
                                        "mt5": len(mt5_by_model[m])}
                   for m in models}})
    return sorted(events, key=lambda e: e["index"])


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
        why = _build_reconciliation(repo, pkg, gold, na, head, put_json)
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
                          head: str | None, put_json) -> str | None:
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
    doc = {
        "schema": "mql5bot.gate_reconciliation/1",
        "gold": gold,
        "built_by": "owner gate (stage8_package), from its own measured outputs",
        "python_source": files["expected"],
        "python_vs_mt5_tester": "COMPARED_FROM_TESTER_LOG",
        "bindings": {k: v for k, v in bindings.items() if v is not None},
        "events": reconciliation_events(py, mt5_by_model,
                                        files["tester_symbol"]),
        "pairing_notes": notes,
        "note": ("Events pair python entry k with MT5 entry k per model, in "
                 "order. Only fields both sides measured are compared "
                 "(timestamp, volume). Bindings nothing measured are omitted "
                 "and the verifier names them."),
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
    "GATE_BUILD_REL",
    "build_package",
    "compile_identity",
    "divergence_note",
    "mt5_entries",
    "na_fixtures",
    "python_entries",
    "reconciliation_events",
    "window_facts",
]
