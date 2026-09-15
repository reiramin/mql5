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
EMPIRICAL_VALIDATED = "EMPIRICAL_VALIDATED"
DEMO_VALIDATED = "DEMO_VALIDATED"
VERIFIED = "VERIFIED"
POSITIVE_VERDICTS = (MT5_VALIDATED, EMPIRICAL_VALIDATED, DEMO_VALIDATED,
                     VERIFIED)

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
SEMANTICALLY_COMPATIBLE = "SEMANTICALLY_COMPATIBLE"
DECISION_CHANGING_MISMATCH = "DECISION_CHANGING_MISMATCH"
UNSUPPORTED_BROKER_DIFFERENCE = "UNSUPPORTED_BROKER_DIFFERENCE"
SYMBOLSPEC_CLASSES = (EXACT_MATCH, SEMANTICALLY_COMPATIBLE,
                      DECISION_CHANGING_MISMATCH,
                      UNSUPPORTED_BROKER_DIFFERENCE)
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

REAL_TICK_COVERAGES = ("REAL_TICK_COVERAGE_FULL",
                       "REAL_TICK_COVERAGE_PARTIAL",
                       "REAL_TICK_COVERAGE_UNKNOWN")

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
    return out


# ---------------------------------------------------------------------------
# 2. compiler evidence (§8: identity + freshness, attack-resistant)
# ---------------------------------------------------------------------------

def verify_compile(root: Path | str, frozen_source_commit: str) -> dict:
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

    # source identity: commit identity, never the branch name (§4)
    checks["source_commit"] = ("VALID"
                               if str(doc.get("SOURCE_COMMIT", "")).lower()
                               == str(frozen_source_commit).lower()
                               else MISMATCHED)
    if checks["source_commit"] != "VALID":
        report["reasons"].append("source commit does not match the frozen "
                                 "anchor")

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

def verify_symbolspec(root: Path | str,
                      frozen_expected: dict | None) -> dict:
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

    decision_changing = []
    for field, expected in frozen_expected.items():
        actual = doc.get(field)
        if actual is None:
            cls = UNSUPPORTED_BROKER_DIFFERENCE
        elif actual == expected:
            cls = EXACT_MATCH
        elif field in _DECISION_FIELDS:
            cls = DECISION_CHANGING_MISMATCH
            decision_changing.append(field)
        else:
            cls = SEMANTICALLY_COMPATIBLE
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


# ---------------------------------------------------------------------------
# 6. first-divergence engine + reconciliation (§14/§16)
# ---------------------------------------------------------------------------

def first_divergence(events: list[dict]) -> dict | None:
    """The FIRST event with any DIVERGENT field — never just the final
    metrics. Deterministic: events are walked in index order."""
    for event in sorted(events, key=lambda e: int(e.get("index", 0))):
        fields = event.get("fields") or {}
        divergent = {name: spec for name, spec in fields.items()
                     if isinstance(spec, dict)
                     and spec.get("status") == "DIVERGENT"}
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
                   "raw_report_hashes", "parsed_report_hashes")


def verify_reconciliation(root: Path | str, gold: str, frozen: dict,
                          model_identities: dict) -> dict:
    """Binding chain + field-by-field reconciliation for one gold.

    The reconciliation artifact must bind SOURCE→FIXTURE→CONFIG→
    DATASET→SYMBOLSPEC→EX5→TESTER MODEL→REPORT; any broken edge
    invalidates the leg. The python side of every event must equal the
    frozen expected execution (a reconciliation whose python column
    drifts from the frozen artifact is INVALID, never trusted).
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

    report: dict = {"state": PRESENT_UNVERIFIED, "reasons": [],
                    "gold": gold}

    # --- binding chain (§22) -------------------------------------------
    bindings = doc.get("bindings") or {}
    broken = [f for f in _BINDING_FIELDS
              if not bindings.get(f) or bindings.get(f) == "PENDING_OWNER"]
    if broken:
        report["state"] = INVALID
        report["reasons"].append(f"binding chain broken at: {broken}")
        return report
    fman = frozen.get(gold, {})
    cross = (
        ("source_commit", frozen.get("source_commit")),
        ("fixture_sha256", fman.get("fixture_sha256")),
        ("config_hash", fman.get("config_hash")),
        ("dataset_hash", fman.get("dataset_hash_from_manifest")),
    )
    mism = [name for name, expected in cross
            if expected and str(bindings.get(name)) != str(expected)]
    if mism:
        report["state"] = MISMATCHED
        report["reasons"].append(
            f"bindings disagree with the frozen record: {mism}")
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
    rrh = bindings.get("raw_report_hashes")
    if not isinstance(rrh, dict) or set(rrh) != set(MODELS):
        report["state"] = INVALID
        report["reasons"].append("raw_report_hashes must bind every "
                                 f"model: {sorted(MODELS)}")
        return report
    bad_raw = []
    for model in MODELS:
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
    prh = bindings.get("parsed_report_hashes")
    if not isinstance(prh, dict) or set(prh) != set(MODELS):
        report["state"] = INVALID
        report["reasons"].append("parsed_report_hashes must bind every "
                                 f"model: {sorted(MODELS)}")
        return report
    bad_reports = []
    for model in MODELS:
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
    for model, triad in (bindings.get("tester_models") or {}).items():
        ident = verify_model_identity(triad)
        model_identities[f"{gold}:{model}"] = ident
        if ident["state"] != VALID:
            report["state"] = MISMATCHED
            report["reasons"].extend(ident["reasons"])
    if report["state"] == MISMATCHED:
        return report

    # --- events: python column must equal the frozen expectation -------
    events = doc.get("events")
    if not isinstance(events, list) or not events:
        report["state"] = INVALID
        report["reasons"].append("reconciliation carries no events")
        return report

    div = first_divergence(events)
    report["first_divergence"] = div
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
                  "observed_result", "raw_evidence")


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


def verify_archive_manifest(root: Path | str, frozen: dict) -> dict:
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
    unbound = [rel for key, rel in LAYOUT.items()
               if key != "archive_manifest" and rel not in arts]
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

def run_gate(evidence_dir: Path | str, frozen_inputs: dict) -> dict:
    """Consume the owner directory; produce the machine-readable report
    and the explainable verdict. Never returns a positive verdict on
    missing, stale, wrong, partial or simulated evidence."""
    root = Path(evidence_dir)
    if not root.is_dir():
        return {"verdict": NOT_VERIFIED_MISSING_MT5_EVIDENCE,
                "reasons": [f"evidence directory missing: {root}"],
                "artifacts": {}, "gold": {}, "safety": {},
                "missing": sorted(LAYOUT)}

    scan = scan_package(root)
    missing = sorted(k for k, v in scan.items() if v["state"] == MISSING)
    ambiguous = sorted(k for k, v in scan.items()
                       if v["state"] == INVALID)

    frozen_source = frozen_inputs.get("source", {}).get("commit", "")
    compile_rep = verify_compile(root, frozen_source)
    spec_expected = frozen_inputs.get("symbolspec_expectations")
    spec_rep = verify_symbolspec(root, spec_expected if isinstance(
        spec_expected, dict) else None)
    cov_rep = verify_real_tick_coverage(root)

    model_identities: dict = {}
    gold_reps = {
        g: verify_reconciliation(root, g, {
            "source_commit": frozen_source,
            "gold1": frozen_inputs.get("gold_1", {}),
            "gold2": frozen_inputs.get("gold_2", {}),
        }, model_identities) for g in GOLDS}

    safety_rep = verify_safety(root)
    env_rep = verify_environment(root)
    man_rep = verify_archive_manifest(root, {
        "source_commit": frozen_source,
        "gold_1": frozen_inputs.get("gold_1", {}),
        "gold_2": frozen_inputs.get("gold_2", {}),
    })

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
    elif cov_rep["coverage"] != "REAL_TICK_COVERAGE_FULL":
        # PARTIAL keeps the limitation explicit; UNKNOWN never promotes
        verdict = NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN
    else:
        verdict = MT5_VALIDATED

    if verdict == MT5_VALIDATED:
        reasons = [("all owner evidence verified against the frozen "
                   "record — gold parity holds on the owner terminal")]

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
    }


__all__ = [
    "ARTIFACT_STATES",
    "DECISION_CHANGING_MISMATCH",
    "DEMO_VALIDATED",
    "EMPIRICAL_VALIDATED",
    "EXACT_MATCH",
    "FIELD_CLASS",
    "GOLDS",
    "INVALID",
    "LAYOUT",
    "MISMATCHED",
    "MISSING",
    "MODELS",
    "MODEL_LABELS",
    "MT5_VALIDATED",
    "NOT_VERIFIED_ARTIFACT_MISMATCH",
    "NOT_VERIFIED_MISSING_MT5_EVIDENCE",
    "NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN",
    "NOT_VERIFIED_RECONCILIATION_MISSING",
    "PENDING_OWNER",
    "POSITIVE_VERDICTS",
    "PRESENT_UNVERIFIED",
    "REAL_TICK_COVERAGES",
    "SAFETY_TESTS",
    "SEMANTICALLY_COMPATIBLE",
    "STALE",
    "SYMBOLSPEC_CLASSES",
    "SYMBOLSPEC_REQUIRED",
    "TAXONOMY",
    "UNSUPPORTED_BROKER_DIFFERENCE",
    "VALID",
    "VERIFIED",
    "classify_anchor_changes",
    "classify_field",
    "first_divergence",
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
