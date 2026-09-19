"""mql5bot.gate_selfcheck - decision engine for tools/owner_gate.ps1.

The owner gate is ONE PowerShell command the Windows owner runs; every
DECISION it makes lives here, in committed, Mac-testable Python, not in a
prompt and not scattered through the .ps1.  The .ps1 does the Windows-only
work (locate terminal64.exe / metaeditor64.exe, run compile.ps1, launch the
tester) and calls this module for every yes/no:

  * self-protection (stage A): HEAD == frozen source.commit, clean tree,
    core.autocrlf false, frozen_inputs.json untampered vs its committed
    blob, every frozen hash matches the committed bytes, the dsl_parity
    manifest + all 42 bound files verify.  Each failure has a NAMED reason.
  * stage 1: parse the strict-compile LOG (BOM-aware: real owner logs are
    UTF-16 or UTF-8-BOM), assert "0 errors, 0 warnings" and that EVERY
    compiled target the repo ships is clean.
  * stage 2: parse the dsl-parity compare report (14/14 EXACT + the
    tampered bundle refused).
  * stage 3: apply the broker-parity scope rule (a real MISMATCH aborts; a
    PENDING crypto/BTC class is excluded from certification scope, never a
    silent pass).
  * dataset-hash derivation (raw bytes of the fixture CSV) and mismatch
    classification (delegated to owner_gate.classify_field).

This module NEVER writes frozen_inputs.json or the certification manifest,
never edits gold artifacts, never substitutes live data for a fixture, and
never fabricates MT5 / tester / broker evidence: it only reads and decides,
fail-closed.  A green self-test here is a VERIFIER self-test, not an MT5
claim.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

try:  # reuse the closed taxonomy; avoid duplicating it
    from mql5bot.owner_gate import classify_field
except ImportError:  # pragma: no cover - owner_gate always importable in-repo
    def classify_field(field: str) -> str:  # type: ignore
        return "UNKNOWN"

# ---------------------------------------------------------------------------
# named self-protection reasons (stage A) - the .ps1 aborts with one of these
# ---------------------------------------------------------------------------
SELF_PROTECT_OK = "SELF_PROTECT_OK"
SELF_PROTECT_FROZEN_INPUTS_TAMPERED = "SELF_PROTECT_FROZEN_INPUTS_TAMPERED"
SELF_PROTECT_HEAD_MISMATCH = "SELF_PROTECT_HEAD_MISMATCH"
# HEAD is a legitimate NEWER commit that descends from the frozen anchor and
# every frozen artifact still matches: a PASS with a recorded NOTE, never an
# abort. (Re-anchor semantics: what is certified is the frozen ARTIFACTS being
# byte-unchanged and the tree clean, not that HEAD equals one historical SHA.)
SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR = "SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR"
SELF_PROTECT_DIRTY_TREE = "SELF_PROTECT_DIRTY_TREE"
SELF_PROTECT_AUTOCRLF_NOT_FALSE = "SELF_PROTECT_AUTOCRLF_NOT_FALSE"
SELF_PROTECT_FROZEN_HASH_MISMATCH = "SELF_PROTECT_FROZEN_HASH_MISMATCH"
SELF_PROTECT_DSL_PARITY_BINDING = "SELF_PROTECT_DSL_PARITY_BINDING"
SELF_PROTECT_FROZEN_INPUTS_UNREADABLE = "SELF_PROTECT_FROZEN_INPUTS_UNREADABLE"
SELF_PROTECT_CLONE_TARGET_EXISTS = "SELF_PROTECT_CLONE_TARGET_EXISTS"

FROZEN_REL = "artifacts/owner_mt5_gate/frozen_inputs.json"
DSL_MANIFEST_REL = "artifacts/dsl_parity/manifest.json"
DSL_BOUND_FILES = ("bundle.json", "expected_trace.json", "ohlc.csv")
DSL_EXPECTED_BOUND_COUNT = 42  # 14 fixtures x 3 files, pinned by the manifest

# compile targets are enumerated from the committed source tree, NOT
# hardcoded: the calibration run compiled 4, adding the fixture importer
# makes it 5 - the gate must expect exactly what the repo ships.
COMPILE_SOURCE_DIRS = ("mql5/Experts/Mql5Bot", "mql5/Scripts/Mql5Bot")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_bom_aware(data: bytes) -> str:
    """Decode owner logs regardless of encoding.

    compile.ps1 writes UTF-8; MetaEditor's own per-file logs and some owner
    terminals emit UTF-16 (LE/BE), and a BOM'd UTF-8 is common on Windows.
    A wrong assumption silently blanks the log and every ``0 errors`` scan
    would vacuously pass - so decode by BOM, never by guess.
    """
    if data[:2] == b"\xff\xfe" or data[:2] == b"\xfe\xff":
        return data.decode("utf-16")
    if data[:3] == b"\xef\xbb\xbf":
        return data.decode("utf-8-sig")
    # UTF-16 without a BOM leaves interleaved NULs; detect and decode LE/BE.
    if b"\x00" in data[: min(len(data), 4096)]:
        head = data[:64]
        even_nul = sum(1 for b in head[1::2] if b == 0)
        odd_nul = sum(1 for b in head[0::2] if b == 0)
        try:
            return data.decode("utf-16-le" if even_nul >= odd_nul
                               else "utf-16-be")
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def read_text_bom_aware(path: Path | str) -> str:
    return decode_bom_aware(Path(path).read_bytes())


# ---------------------------------------------------------------------------
# stage 1: strict-compile log parse
# ---------------------------------------------------------------------------
# Two literal summary shapes seen in the wild:
#   real MetaEditor : "Result: 0 errors, 0 warnings, 3859 ms elapsed, ..."
#   test fixture    : "Mql5Bot.mq5 - 0 error(s), 0 warning(s)"
_RESULT_SUMMARY = re.compile(
    r"(\d+)\s+error(?:\(s\))?s?\s*,\s*(\d+)\s+warning(?:\(s\))?s?",
    re.IGNORECASE)
# script-authored per-target verdict, deterministic ASCII
_TARGET_PASS = re.compile(
    r"\[compile\]\s+(?P<name>\S+?\.mq5)\s*:\s*PASS\b", re.IGNORECASE)
_TARGET_FAIL = re.compile(
    r"\[compile\]\s+(?P<name>\S+?\.mq5)\s*:\s*(?:FAIL|PASS\(WARNINGS)",
    re.IGNORECASE)
_RESULT_PASS = re.compile(r"\[compile\]\s+RESULT:\s+PASS\b", re.IGNORECASE)
_RESULT_FAIL = re.compile(r"\[compile\]\s+RESULT:\s+FAIL\b", re.IGNORECASE)


def expected_compile_targets(repo: Path | str) -> list[str]:
    """The .mq5 basenames the strict compile must report clean.

    Derived from the committed sources so the count tracks the tree (4 at
    the calibration commit, 5 once the fixture importer lands) - never a
    magic number.
    """
    repo = Path(repo)
    names: set[str] = set()
    for rel in COMPILE_SOURCE_DIRS:
        d = repo / rel
        if d.is_dir():
            names.update(p.name for p in d.glob("*.mq5"))
    return sorted(names)


def parse_compile_log(text: str, expected_targets: list[str]) -> dict:
    """Decide the strict compile from the LOG, not from an exit code.

    PASS requires: a RESULT: PASS line, no RESULT: FAIL / per-target FAIL /
    PASS(WARNINGS), every expected target present with a PASS verdict, and
    every numeric summary reporting exactly 0 errors and 0 warnings.
    """
    reasons: list[str] = []
    passed = {m.group("name") for m in _TARGET_PASS.finditer(text)}
    failed = {m.group("name") for m in _TARGET_FAIL.finditer(text)}
    summaries = _RESULT_SUMMARY.findall(text)
    dirty = [(e, w) for (e, w) in summaries if int(e) != 0 or int(w) != 0]

    if not _RESULT_PASS.search(text):
        reasons.append("no '[compile] RESULT: PASS' line in the log")
    if _RESULT_FAIL.search(text):
        reasons.append("log contains a '[compile] RESULT: FAIL' line")
    if failed:
        reasons.append(f"targets not clean-PASS: {sorted(failed)}")
    missing = [t for t in expected_targets if t not in passed]
    if missing:
        reasons.append(f"expected targets missing a PASS verdict: {missing}")
    if not summaries:
        reasons.append("no '<N> errors, <M> warnings' summary found "
                       "(log empty or wrong encoding?)")
    if dirty:
        reasons.append(f"non-zero error/warning summaries: {dirty}")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "targets_passed": sorted(passed),
        "targets_failed": sorted(failed),
        "expected_targets": sorted(expected_targets),
        "clean_summaries": len(summaries) - len(dirty),
        "total_summaries": len(summaries),
    }


# ---------------------------------------------------------------------------
# stage 2: dsl-parity compare report parse
# ---------------------------------------------------------------------------
_DSL_SUMMARY = re.compile(r"(\d+)\s*/\s*(\d+)\s+fixtures\s+EXACT",
                          re.IGNORECASE)
_DSL_TAMPER_OK = re.compile(
    r"EXACT\s+tampered_bundle\s*\(refused:\s*bundle_hash\s+mismatch\)",
    re.IGNORECASE)
_DSL_NOT_PROVEN = re.compile(r"PARITY\s+NOT\s+PROVEN", re.IGNORECASE)


def parse_dsl_compare_report(text: str) -> dict:
    """Require N/N fixtures EXACT AND the tampered bundle refused."""
    reasons: list[str] = []
    m = _DSL_SUMMARY.search(text)
    exact = total = None
    if not m:
        reasons.append("no '<n>/<n> fixtures EXACT' summary line")
    else:
        exact, total = int(m.group(1)), int(m.group(2))
        if exact != total:
            reasons.append(f"parity incomplete: {exact}/{total} EXACT")
        if total != 14:
            reasons.append(f"expected 14 fixtures, report says {total}")
    if _DSL_NOT_PROVEN.search(text):
        reasons.append("report says PARITY NOT PROVEN")
    if not _DSL_TAMPER_OK.search(text):
        reasons.append("tampered_bundle was not refused for a "
                       "bundle_hash mismatch")
    return {"ok": not reasons, "reasons": reasons,
            "exact": exact, "total": total}


# ---------------------------------------------------------------------------
# stage 3: broker-parity scope rule
# ---------------------------------------------------------------------------
# BTC/crypto stays an owner-side open measurement: a PENDING crypto row is
# excluded from certification scope (never a pass, never an abort). A real
# MISMATCH on any in-scope field aborts.
_CRYPTO_MARKERS = ("btc", "eth", "crypto")


def _is_crypto(symbol: str) -> bool:
    s = str(symbol).lower()
    return any(mark in s for mark in _CRYPTO_MARKERS)


def broker_parity_scope(report: dict) -> dict:
    """Classify a parity_report.json into gate PASS / FAIL / excluded.

    FAIL: any row with status MISMATCH (regardless of symbol).
    excluded: PENDING rows on a crypto/BTC symbol (documented open item).
    blocking-PENDING: a PENDING row on an IN-SCOPE (non-crypto) symbol -
      not verified, so not a pass.
    """
    rows = report.get("rows") or []
    mism = [(r.get("symbol"), r.get("field")) for r in rows
            if r.get("status") == "MISMATCH"]
    pending = [r for r in rows if r.get("status") == "PENDING"]
    pending_crypto = [(r.get("symbol"), r.get("field")) for r in pending
                      if _is_crypto(r.get("symbol"))]
    pending_inscope = [(r.get("symbol"), r.get("field")) for r in pending
                       if not _is_crypto(r.get("symbol"))]
    matched = [r for r in rows if r.get("status") == "MATCH"]

    reasons: list[str] = []
    if mism:
        reasons.append(f"MISMATCH rows (abort): {mism}")
    if pending_inscope:
        reasons.append("in-scope PENDING rows (not verified, not a pass): "
                       f"{pending_inscope}")
    if not matched and not mism:
        reasons.append("no MATCH rows - nothing was positively verified")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "mismatch": mism,
        "pending_excluded_crypto": pending_crypto,
        "pending_in_scope": pending_inscope,
        "match_count": len(matched),
        "coverage": report.get("coverage", {}),
    }


# ---------------------------------------------------------------------------
# dataset-hash derivation (stage 4 round-trip)
# ---------------------------------------------------------------------------

def dataset_hash_of_csv(path: Path | str) -> str:
    """The dataset hash is the sha256 of the fixture CSV's raw bytes -
    exactly how the gold builders derived the manifest value. The MQL5
    importer re-derives it after the CustomRatesUpdate round-trip and this
    is the reference to compare against."""
    return sha256_file(path)


# ---------------------------------------------------------------------------
# stage 4: importer diagnostic must be non-vacuous (the err=5306 blind spot)
# ---------------------------------------------------------------------------
# The defect the fix closes: Mql5BotImportFixture.mq5 refused
# ("CustomSymbolSet* failed, err=5306") and wrote a record with no property
# name, no _LastError, no stage -- the gate had exactly one useless line to go
# on. Every importer outcome must now write a POPULATED JSON: a refusal names
# the stage + last_error, and a property-stage refusal additionally names the
# failing property. This mirror lets the Mac-tested gate CLASSIFY an importer
# result and fail closed if it ever regresses to a vacuous refusal.

def import_diagnostic_populated(doc: dict) -> dict:
    """Classify an Mql5BotImportFixture result JSON.

    Returns {"populated": bool, "refused": bool,
             "failed_property": str|None, "reason": str}.

    A result is *populated* (usable observability) when:
      - it carries a ``last_error`` field (present on every new outcome), and
      - a refusal carries a non-empty ``error`` message, and
      - a refusal at the ``set_properties`` stage additionally names the
        ``failed_property`` (which CustomSymbolSet* call failed), and
      - a success carries the round-trip hash it claims to have proven.

    The old vacuous refusal ({"error","refused","symbol"}) has no
    ``last_error`` and is therefore flagged NOT populated -- the exact blind
    spot this fix removes.
    """
    if not isinstance(doc, dict):
        return {"populated": False, "refused": False, "failed_property": None,
                "reason": "importer result is not a JSON object"}
    refused = bool(doc.get("refused", False))
    if "last_error" not in doc:
        return {"populated": False, "refused": refused, "failed_property": None,
                "reason": "importer result carries no last_error field "
                          "(vacuous refusal -- the stage-4 blind spot)"}
    stage = doc.get("stage", "") or ""
    if refused:
        err_msg = doc.get("error", "") or ""
        if not err_msg:
            return {"populated": False, "refused": True,
                    "failed_property": None,
                    "reason": "refusal carries no error message"}
        failed = doc.get("failed_property") or None
        if stage in ("set_properties", "verify_properties") and not failed:
            return {"populated": False, "refused": True,
                    "failed_property": None,
                    "reason": "property-stage refusal names no failed_property"}
        return {"populated": True, "refused": True, "failed_property": failed,
                "reason": f"refused at {stage or '?'}: {err_msg} "
                          f"(last_error={doc.get('last_error')})"}
    # success path
    if not doc.get("roundtrip_sha256"):
        return {"populated": False, "refused": False, "failed_property": None,
                "reason": "success result lacks roundtrip_sha256"}
    n_bars = int(doc.get("n_bars", 0) or 0)
    return {"populated": True, "refused": False, "failed_property": None,
            "reason": f"import succeeded; round-trip hash present "
                      f"({n_bars} bars)"}


# ---------------------------------------------------------------------------
# stage 4: staged-preset validation (the R4 empty-value fix)
# ---------------------------------------------------------------------------
# gate_run6 ground truth: the terminal received "InpSymbolName=" (EMPTY) with
# GOLD1_EURUSD on the FOLLOWING line -- the gate's PowerShell built exactly the
# two fixture-derived preset entries with `"Key=" + $expr` inside an @()
# literal, where the COMMA operator binds tighter than '+', splitting each
# into two array elements. This validator makes that entire bug class
# pre-launch fatal: the gate re-reads the STAGED .set from MQL5\Presets,
# decodes it, and this function asserts it carries EXACTLY the intended
# key=value pairs before the terminal is ever started.

def validate_preset(text: str, expected: dict[str, str]) -> dict:
    """Fail-closed check of a staged MT5 .set preset against the intended
    key=value pairs.

    Returns {"ok": bool, "reasons": [str], "keys": [str],
             "expected_count": int, "found_count": int}. ``ok`` only when:
      - the decoded text carries EXACTLY the expected key set (no missing,
        extra, or duplicate keys; count matches what MT5 will report),
      - EVERY value is non-empty and equals the intended value,
      - no stray key-less line exists (a value that broke across lines --
        the gate_run6 symptom -- shows up as one), and
      - no INTENDED value is empty or multi-line either (a gate-construction
        bug is named at the source, not discovered by the terminal).
    Every violation names the offending key or line.
    """
    reasons: list[str] = []
    for k, v in expected.items():
        if not v:
            reasons.append(f"{k}: intended value is EMPTY "
                           f"(gate preset construction bug)")
        elif "\r" in v or "\n" in v:
            reasons.append(f"{k}: intended value contains CR/LF "
                           f"(gate preset construction bug)")
    seen: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            reasons.append(f"stray key-less line (a value broke across "
                           f"lines): {line!r}")
            continue
        key, _, val = line.partition("=")
        if key in seen:
            reasons.append(f"duplicate key: {key}")
            continue
        seen[key] = val
    for k in expected:
        if k not in seen:
            reasons.append(f"missing key: {k}")
    for k in seen:
        if k not in expected:
            reasons.append(f"unexpected key: {k}")
    for k, v in seen.items():
        if k not in expected:
            continue
        if v == "":
            reasons.append(f"{k}: staged value is EMPTY (the terminal would "
                           f"run with a blank input)")
        elif v != expected[k]:
            reasons.append(f"{k}: staged value {v!r} != intended "
                           f"{expected[k]!r}")
    if len(seen) != len(expected):
        reasons.append(f"key count {len(seen)} != intended {len(expected)} "
                       f"(MT5 would report a different parameter set)")
    return {"ok": not reasons, "reasons": reasons, "keys": sorted(seen),
            "expected_count": len(expected), "found_count": len(seen)}


# ---------------------------------------------------------------------------
# stage 4: three-way import-outcome classifier (the MISREPORT fix)
# ---------------------------------------------------------------------------
# The gate must never again claim "terminal did not run" when the importer
# actually ran and refused. These three cases carry DISTINCT messages so the
# operator can tell them apart at a glance, and the decision lives here (not
# in the .ps1). The .ps1 does the I/O (launch, look for the JSON, grep the
# terminal log) and passes the observed facts in; this function decides.
STAGE4_CASE_NOT_LAUNCHED = "terminal_never_launched"
STAGE4_CASE_NO_JSON = "terminal_ran_no_json"
STAGE4_CASE_REFUSED = "json_refused"
STAGE4_CASE_HASH_MISMATCH = "roundtrip_hash_mismatch"
STAGE4_CASE_NOT_POPULATED = "diagnostic_not_populated"
STAGE4_CASE_UNVERIFIED = "properties_unverified"
STAGE4_CASE_PASS = "import_ok"

# the two properties MT5 will not let CustomSymbolSetDouble carry (5307
# ERR_CUSTOM_SYMBOL_PROPERTY_WRONG, "An invalid custom symbol property";
# ENUM_SYMBOL_INFO_DOUBLE documents both as CALCULATED). The importer must
# prove the terminal-DERIVED values equal the manifest broker values; a
# success record without that proof fails CLOSED here (never a silent skip).
DERIVED_TICK_VALUE_ENUMS = ("SYMBOL_TRADE_TICK_VALUE_PROFIT",
                            "SYMBOL_TRADE_TICK_VALUE_LOSS")


def properties_verified(doc: dict) -> dict:
    """R5 read-back contract: a SUCCESS import record must carry

      - ``verified_properties``: a non-empty list of read-backs of every
        property that was SET, each with ``ok`` true, and
      - ``derived_tick_values.properties``: read-backs of BOTH calculated
        tick-value properties (not settable, 5307), each with ``ok`` true --
        the terminal-DERIVED value equalled the manifest broker value.

    Returns {"ok": bool, "reason": str}. Anything missing or diverged is a
    named fail-closed reason: a skipped or unverified property must never
    pass as if it were set.
    """
    vp = doc.get("verified_properties")
    if not isinstance(vp, list) or not vp:
        return {"ok": False,
                "reason": "success record carries no verified_properties "
                          "read-back (properties were never proven set)"}
    bad = [str(p.get("enum") or "?") for p in vp
           if not (isinstance(p, dict) and p.get("ok") is True)]
    if bad:
        return {"ok": False,
                "reason": "read-back diverged from the value set for: "
                          + ", ".join(bad)}
    dv = doc.get("derived_tick_values")
    props = dv.get("properties") if isinstance(dv, dict) else None
    if not isinstance(props, list):
        return {"ok": False,
                "reason": "success record carries no derived_tick_values "
                          "read-back (the 5307-calculated tick values were "
                          "never proven to equal the manifest)"}
    by_enum = {p.get("enum"): p for p in props if isinstance(p, dict)}
    for need in DERIVED_TICK_VALUE_ENUMS:
        rec = by_enum.get(need)
        if rec is None:
            return {"ok": False,
                    "reason": f"derived_tick_values misses {need} (not "
                              f"settable per 5307; must be verified by "
                              f"read-back, never skipped)"}
        if rec.get("ok") is not True:
            return {"ok": False,
                    "reason": f"terminal-DERIVED {need} "
                              f"({rec.get('readback')!r}) != manifest value "
                              f"({rec.get('manifest_value')!r}); the custom "
                              f"symbol does not carry the broker tick-value "
                              f"economics"}
    return {"ok": True, "reason": "every set property read back equal; both "
                                  "derived tick values equal the manifest"}


def classify_stage4_outcome(*, launched: bool, json_present: bool,
                            doc: dict | None, manifest_hash: str | None,
                            symbol: str,
                            log_excerpt_present: bool = False,
                            log_excerpt_head: str | None = None) -> dict:
    """Decide the stage-4 outcome from what the .ps1 observed.

    Returns {"case": <STAGE4_CASE_*>, "ok": bool, "message": str, ...}. ``ok``
    is True only for a faithful import; every other case is a fail-closed FAIL
    with a message that names WHICH of the three cases occurred:

      (1) terminal never launched  -> STAGE4_CASE_NOT_LAUNCHED
      (2) terminal ran, no JSON     -> STAGE4_CASE_NO_JSON (log excerpt noted;
                                        when ``log_excerpt_head`` carries the
                                        excerpt's first lines they are folded
                                        into the message, so the cause is
                                        readable from the gate console alone)
      (3) JSON present + REFUSED     -> STAGE4_CASE_REFUSED, refusal reason
                                        surfaced VERBATIM from the record

    A JSON that is present and NOT refused is validated against the manifest
    hash and the populated-diagnostic guard, mirroring the .ps1's old inline
    branch so the whole pass/fail decision is testable off-terminal.
    """
    if not launched:
        return {"case": STAGE4_CASE_NOT_LAUNCHED, "ok": False,
                "message": f"{symbol}: terminal never launched (the MT5 "
                           f"terminal process could not be started)"}
    if not json_present:
        tail = ("see the attached terminal-log excerpt"
                if log_excerpt_present
                else "no Mql5BotImportFixture lines were found in the MT5 logs "
                     "either")
        if log_excerpt_present and log_excerpt_head:
            head = " / ".join(
                ln.strip() for ln in log_excerpt_head.splitlines()[:10]
                if ln.strip())
            if head:
                tail += f"; excerpt begins: {head}"
        return {"case": STAGE4_CASE_NO_JSON, "ok": False,
                "message": f"{symbol}: terminal ran but produced no output "
                           f"JSON at the path the gate passed; {tail}"}
    # JSON is present: classify its content.
    doc = doc if isinstance(doc, dict) else {}
    verdict = import_diagnostic_populated(doc)
    if verdict["refused"]:
        err = doc.get("error", "") or "(refusal record carries no error text)"
        stage = doc.get("stage", "?") or "?"
        last_error = doc.get("last_error")
        return {"case": STAGE4_CASE_REFUSED, "ok": False,
                "populated": verdict["populated"],
                "failed_property": verdict.get("failed_property"),
                "reason": verdict["reason"],
                "message": f"{symbol}: importer REFUSED at stage '{stage}' "
                           f"(last_error={last_error}): {err}"}
    # a success record must be populated AND round-trip to the manifest hash
    if not verdict["populated"]:
        return {"case": STAGE4_CASE_NOT_POPULATED, "ok": False,
                "message": f"{symbol}: import diagnostic not populated "
                           f"({verdict['reason']})"}
    rt = doc.get("roundtrip_sha256")
    if manifest_hash and rt != manifest_hash:
        return {"case": STAGE4_CASE_HASH_MISMATCH, "ok": False,
                "message": f"{symbol}: round-trip dataset hash {rt} != "
                           f"manifest dataset_hash {manifest_hash}"}
    # R5: a success record must PROVE its properties -- every set property
    # read back equal, and both 5307-calculated tick values derived equal to
    # the manifest. Without that proof the import fails CLOSED: a skipped
    # property must never pass silently as if it were set.
    verified = properties_verified(doc)
    if not verified["ok"]:
        return {"case": STAGE4_CASE_UNVERIFIED, "ok": False,
                "message": f"{symbol}: import not property-verified: "
                           f"{verified['reason']}"}
    return {"case": STAGE4_CASE_PASS, "ok": True,
            "message": f"{symbol}: imported; round-trip dataset hash == "
                       f"manifest; {verified['reason']}"}


# ---------------------------------------------------------------------------
# stage A: self-protection
# ---------------------------------------------------------------------------

def _git(repo: Path, args: list[str], runner=None) -> subprocess.CompletedProcess:
    if runner is not None:
        return runner(args)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=False)


def _git_show_bytes(repo: Path, ref_path: str, runner=None) -> bytes | None:
    if runner is not None:
        cp = runner(["show", ref_path])
        if cp.returncode != 0:
            return None
        out = cp.stdout
        return out.encode() if isinstance(out, str) else out
    cp = subprocess.run(["git", "-C", str(repo), "show", ref_path],
                        capture_output=True, check=False)
    return cp.stdout if cp.returncode == 0 else None


def verify_frozen_inputs_untampered(repo: Path | str, runner=None) -> dict:
    """The working-tree frozen_inputs.json must be byte-identical to its
    committed blob at HEAD. A hand-written or edited frozen_inputs is the
    canonical attack (relax a hash, re-point source.commit) and is refused
    here - the gate never trusts an uncommitted frozen record, and never
    writes one itself."""
    repo = Path(repo)
    wt = repo / FROZEN_REL
    if not wt.is_file():
        return {"ok": False, "reason": SELF_PROTECT_FROZEN_INPUTS_UNREADABLE,
                "detail": f"{FROZEN_REL} missing in the working tree"}
    committed = _git_show_bytes(repo, f"HEAD:{FROZEN_REL}", runner)
    if committed is None:
        return {"ok": False, "reason": SELF_PROTECT_FROZEN_INPUTS_TAMPERED,
                "detail": f"{FROZEN_REL} is not committed at HEAD "
                          "(no authoritative blob to compare against)"}
    if wt.read_bytes() != committed:
        return {"ok": False, "reason": SELF_PROTECT_FROZEN_INPUTS_TAMPERED,
                "detail": f"{FROZEN_REL} differs from its committed HEAD "
                          "blob (hand-written/edited frozen inputs)"}
    return {"ok": True, "reason": SELF_PROTECT_OK, "detail": ""}


def verify_head_matches_frozen(repo: Path | str, frozen: dict,
                               runner=None) -> dict:
    """Relate HEAD to the frozen anchor by ANCESTRY, not string equality.

    What certification actually rests on is that the frozen ARTIFACTS are
    byte-unchanged (``verify_frozen_hashes``) and the tree is clean, not that
    HEAD equals one historical SHA. So:

      * HEAD == anchor .................... PASS (exact, strongest case)
      * anchor is an ancestor of HEAD ..... PASS with a NOTE (HEAD is a
        legitimate NEWER commit; the frozen artifacts are what is verified)
      * HEAD is an ancestor of the anchor . FAIL (HEAD is OLDER than the
        anchor -- the anchor names a newer commit)
      * neither is an ancestor of the other FAIL (diverged history)
      * anchor absent from this clone ..... FAIL (cannot prove descent)
      * no source.commit .................. FAIL

    A newer clean commit is therefore NOT a hard abort (the stage-0 bug this
    replaces): only a genuinely wrong tree -- older, diverged, or unknown
    anchor -- fails.
    """
    repo = Path(repo)
    head = _git(repo, ["rev-parse", "HEAD"], runner).stdout.strip()
    want = str(frozen.get("source", {}).get("commit", "")).strip()
    if not want:
        return {"ok": False, "reason": SELF_PROTECT_HEAD_MISMATCH,
                "detail": "frozen_inputs has no source.commit",
                "head": head, "anchor": ""}
    if head.lower() == want.lower():
        return {"ok": True, "reason": SELF_PROTECT_OK, "detail": head,
                "head": head, "anchor": head}
    # The anchor must be a real commit IN THIS clone or ancestry is unknowable
    # (a squashed/foreign SHA can never be trusted to relate to HEAD).
    verify = _git(repo, ["rev-parse", "--verify", "--quiet",
                         want + "^{commit}"], runner)
    anchor_full = verify.stdout.strip()
    if verify.returncode != 0 or not anchor_full:
        return {"ok": False, "reason": SELF_PROTECT_HEAD_MISMATCH,
                "detail": f"HEAD {head} != frozen source.commit {want}, and "
                          f"the anchor {want} is not present in this clone "
                          "(cannot prove HEAD descends from it; re-clone the "
                          "anchored history or re-anchor frozen_inputs.json)",
                "head": head, "anchor": want}
    if _git(repo, ["merge-base", "--is-ancestor", want, "HEAD"],
            runner).returncode == 0:
        # anchor is reachable from HEAD -> HEAD is a legitimate newer commit
        return {"ok": True, "reason": SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR,
                "detail": f"HEAD {head} is newer than and descends from the "
                          f"frozen anchor {anchor_full}; the frozen artifacts "
                          "(verified separately) are what is certified, not "
                          "the SHA",
                "head": head, "anchor": anchor_full}
    if _git(repo, ["merge-base", "--is-ancestor", "HEAD", want],
            runner).returncode == 0:
        return {"ok": False, "reason": SELF_PROTECT_HEAD_MISMATCH,
                "detail": f"HEAD {head} is OLDER than the frozen anchor "
                          f"{anchor_full} (the anchor names a newer commit; "
                          "check out the anchor or a descendant of it)",
                "head": head, "anchor": anchor_full}
    return {"ok": False, "reason": SELF_PROTECT_HEAD_MISMATCH,
            "detail": f"HEAD {head} and the frozen anchor {anchor_full} have "
                      "diverged (no ancestor/descendant relation; wrong branch "
                      "or rewritten history)",
            "head": head, "anchor": anchor_full}


def verify_clean_tree(repo: Path | str, runner=None) -> dict:
    repo = Path(repo)
    # --untracked-files=normal is passed explicitly so a global
    # status.showUntrackedFiles=no config can never silently weaken this check
    # into passing on a genuinely dirty tree. The gate's own append-only output
    # (evidence/owner_gate/<UTC>/) is excluded durably via the committed
    # .gitignore, NOT special-cased here: this checker stays a plain, honest
    # "is the tree clean?" and the exclusion travels with the repo. Ignored
    # files are never shown in this mode, so the gate no longer blocks itself.
    porcelain = _git(repo, ["status", "--porcelain",
                            "--untracked-files=normal"], runner).stdout
    if porcelain.strip():
        return {"ok": False, "reason": SELF_PROTECT_DIRTY_TREE,
                "detail": "working tree not clean:\n" + porcelain.strip()}
    return {"ok": True, "reason": SELF_PROTECT_OK, "detail": ""}


def verify_autocrlf_false(repo: Path | str, runner=None) -> dict:
    repo = Path(repo)
    val = _git(repo, ["config", "--get", "core.autocrlf"], runner
               ).stdout.strip().lower()
    # unset defaults to false on the byte-exact-artifact contract; only a
    # true/input setting mangles the pinned CRLF and breaks every sha256
    if val in ("true", "input"):
        return {"ok": False, "reason": SELF_PROTECT_AUTOCRLF_NOT_FALSE,
                "detail": f"core.autocrlf={val!r} will mangle pinned bytes; "
                          "set it to false and re-clone"}
    return {"ok": True, "reason": SELF_PROTECT_OK, "detail": val or "(unset)"}


def verify_frozen_hashes(repo: Path | str, frozen: dict) -> dict:
    """Every committed artifact the frozen record pins must match its bytes:
    both golds' fixture / manifest / expected_execution, plus gold_2's full
    artifact_hash_chain. A tampered fixture (bytes changed after freezing)
    is caught here."""
    repo = Path(repo)
    bad: list[str] = []

    def check(rel: str, want: str, label: str) -> None:
        if not want:
            return
        p = repo / rel
        if not p.is_file():
            bad.append(f"{label}: missing {rel}")
        elif sha256_file(p) != want:
            bad.append(f"{label}: {rel} sha256 != frozen pin")

    g1 = frozen.get("gold_1", {})
    check("artifacts/gold/gold_fixture.csv", g1.get("fixture_sha256", ""),
          "gold_1 fixture")
    check("artifacts/gold/manifest.json", g1.get("manifest_sha256", ""),
          "gold_1 manifest")
    check("artifacts/gold/expected_execution.json",
          g1.get("expected_execution_sha256", ""), "gold_1 expected")
    g2 = frozen.get("gold_2", {})
    check("artifacts/gold_2/gold2_fixture.csv", g2.get("fixture_sha256", ""),
          "gold_2 fixture")
    check("artifacts/gold_2/manifest.json", g2.get("manifest_sha256", ""),
          "gold_2 manifest")
    check("artifacts/gold_2/expected_execution.json",
          g2.get("expected_execution_sha256", ""), "gold_2 expected")
    for fn, want in (g2.get("artifact_hash_chain") or {}).items():
        check(f"artifacts/gold_2/{fn}", want, f"gold_2 chain {fn}")

    if bad:
        return {"ok": False, "reason": SELF_PROTECT_FROZEN_HASH_MISMATCH,
                "detail": "; ".join(bad)}
    return {"ok": True, "reason": SELF_PROTECT_OK, "detail": ""}


def verify_dsl_parity_binding(repo: Path | str) -> dict:
    """The dsl_parity manifest must exist and bind exactly 42 files, and
    every bound file's bytes must match its pin."""
    repo = Path(repo)
    man_path = repo / DSL_MANIFEST_REL
    if not man_path.is_file():
        return {"ok": False, "reason": SELF_PROTECT_DSL_PARITY_BINDING,
                "detail": f"{DSL_MANIFEST_REL} missing"}
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return {"ok": False, "reason": SELF_PROTECT_DSL_PARITY_BINDING,
                "detail": f"manifest unparsable: {exc}"}
    fixtures = man.get("fixtures")
    if not isinstance(fixtures, dict):
        return {"ok": False, "reason": SELF_PROTECT_DSL_PARITY_BINDING,
                "detail": "manifest has no fixtures map"}
    bad: list[str] = []
    bound = 0
    base = repo / "artifacts" / "dsl_parity"
    for name, spec in sorted(fixtures.items()):
        files = (spec or {}).get("files") or {}
        for fn in DSL_BOUND_FILES:
            want = files.get(fn)
            if not want:
                bad.append(f"{name}/{fn}: no pin in manifest")
                continue
            bound += 1
            p = base / name / fn
            if not p.is_file():
                bad.append(f"{name}/{fn}: file missing")
            elif sha256_file(p) != want:
                bad.append(f"{name}/{fn}: bytes != pin")
    if bound != DSL_EXPECTED_BOUND_COUNT:
        bad.append(f"expected {DSL_EXPECTED_BOUND_COUNT} bound files, "
                   f"manifest pins {bound}")
    if bad:
        return {"ok": False, "reason": SELF_PROTECT_DSL_PARITY_BINDING,
                "detail": "; ".join(bad[:8])
                + (f" (+{len(bad) - 8} more)" if len(bad) > 8 else "")}
    return {"ok": True, "reason": SELF_PROTECT_OK,
            "detail": f"{bound} bound files verified"}


def clone_target_status(path: Path | str) -> dict:
    """Decide whether ``path`` is safe to be a fresh clone target.

    The owner's real-world snag: the gate is meant to run from a clean-room
    checkout, but if the intended clone directory already exists ``git clone``
    fails deep in its own machinery ("destination path already exists and is
    not an empty directory"), leaving the owner to move directories by hand.
    This names the offending path up front so the .ps1 can refuse cleanly.

    ok  -> the path is absent, or an empty directory (git clone would succeed)
    not -> the path already exists with content (a file, or a non-empty dir)
    """
    p = Path(path)
    full = str(p if p.is_absolute() else p.resolve())
    if not p.exists():
        return {"ok": True, "reason": SELF_PROTECT_OK,
                "detail": f"clone target {full} does not exist (safe to clone)",
                "path": full}
    if p.is_dir():
        try:
            empty = not any(p.iterdir())
        except OSError as exc:
            return {"ok": False, "reason": SELF_PROTECT_CLONE_TARGET_EXISTS,
                    "detail": f"clone target {full} is unreadable: {exc}",
                    "path": full}
        if empty:
            return {"ok": True, "reason": SELF_PROTECT_OK,
                    "detail": f"clone target {full} is an empty directory "
                              "(safe to clone)",
                    "path": full}
        return {"ok": False, "reason": SELF_PROTECT_CLONE_TARGET_EXISTS,
                "detail": f"clone target {full} already exists and is not "
                          "empty; remove it or choose another target directory "
                          "(the gate will not move or overwrite it for you)",
                "path": full}
    return {"ok": False, "reason": SELF_PROTECT_CLONE_TARGET_EXISTS,
            "detail": f"clone target {full} already exists as a file; remove "
                      "it or choose another target directory",
            "path": full}


def run_self_protection(repo: Path | str, runner=None) -> dict:
    """Run every stage-A check in order and stop reporting at the first
    failure's named reason. Checks are computed append-only (all recorded)
    but the gate ABORTS on the first failure."""
    repo = Path(repo)
    checks: list[dict] = []

    tamper = verify_frozen_inputs_untampered(repo, runner)
    checks.append({"name": "frozen_inputs_untampered", **tamper})
    frozen: dict = {}
    if tamper["ok"]:
        try:
            frozen = json.loads((repo / FROZEN_REL).read_text(
                encoding="utf-8"))
        except ValueError as exc:
            checks.append({"name": "frozen_inputs_parse", "ok": False,
                           "reason": SELF_PROTECT_FROZEN_INPUTS_UNREADABLE,
                           "detail": f"frozen_inputs unparsable: {exc}"})

    if frozen:
        for name, fn in (
            ("head_matches_frozen",
             lambda: verify_head_matches_frozen(repo, frozen, runner)),
            ("clean_tree", lambda: verify_clean_tree(repo, runner)),
            ("autocrlf_false", lambda: verify_autocrlf_false(repo, runner)),
            ("frozen_hashes", lambda: verify_frozen_hashes(repo, frozen)),
            ("dsl_parity_binding",
             lambda: verify_dsl_parity_binding(repo)),
        ):
            checks.append({"name": name, **fn()})

    first_fail = next((c for c in checks if not c["ok"]), None)
    # non-fatal notes: an OK check whose reason is not plain SELF_PROTECT_OK is
    # a PASS the operator should still SEE (e.g. HEAD ahead of the anchor after
    # a re-anchor). The gate does not abort on these; it records + prints them.
    notes = [c["detail"] for c in checks
             if c["ok"] and c.get("reason") not in (SELF_PROTECT_OK, None)]
    return {
        "ok": first_fail is None,
        "reason": SELF_PROTECT_OK if first_fail is None
        else first_fail["reason"],
        "failed_check": None if first_fail is None else first_fail["name"],
        "detail": "" if first_fail is None else first_fail.get("detail", ""),
        "notes": notes,
        "checks": checks,
    }


__all__ = [
    "SELF_PROTECT_AUTOCRLF_NOT_FALSE",
    "SELF_PROTECT_CLONE_TARGET_EXISTS",
    "SELF_PROTECT_DIRTY_TREE",
    "SELF_PROTECT_DSL_PARITY_BINDING",
    "SELF_PROTECT_FROZEN_HASH_MISMATCH",
    "SELF_PROTECT_FROZEN_INPUTS_TAMPERED",
    "SELF_PROTECT_FROZEN_INPUTS_UNREADABLE",
    "SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR",
    "SELF_PROTECT_HEAD_MISMATCH",
    "SELF_PROTECT_OK",
    "broker_parity_scope",
    "classify_field",
    "clone_target_status",
    "dataset_hash_of_csv",
    "decode_bom_aware",
    "expected_compile_targets",
    "parse_compile_log",
    "parse_dsl_compare_report",
    "read_text_bom_aware",
    "run_self_protection",
    "sha256_bytes",
    "sha256_file",
    "verify_autocrlf_false",
    "verify_clean_tree",
    "verify_dsl_parity_binding",
    "verify_frozen_hashes",
    "verify_frozen_inputs_untampered",
    "verify_head_matches_frozen",
]
