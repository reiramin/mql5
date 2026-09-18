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
SELF_PROTECT_DIRTY_TREE = "SELF_PROTECT_DIRTY_TREE"
SELF_PROTECT_AUTOCRLF_NOT_FALSE = "SELF_PROTECT_AUTOCRLF_NOT_FALSE"
SELF_PROTECT_FROZEN_HASH_MISMATCH = "SELF_PROTECT_FROZEN_HASH_MISMATCH"
SELF_PROTECT_DSL_PARITY_BINDING = "SELF_PROTECT_DSL_PARITY_BINDING"
SELF_PROTECT_FROZEN_INPUTS_UNREADABLE = "SELF_PROTECT_FROZEN_INPUTS_UNREADABLE"

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
    repo = Path(repo)
    head = _git(repo, ["rev-parse", "HEAD"], runner).stdout.strip()
    want = str(frozen.get("source", {}).get("commit", "")).strip()
    if not want:
        return {"ok": False, "reason": SELF_PROTECT_HEAD_MISMATCH,
                "detail": "frozen_inputs has no source.commit"}
    if head.lower() != want.lower():
        return {"ok": False, "reason": SELF_PROTECT_HEAD_MISMATCH,
                "detail": f"HEAD {head} != frozen source.commit {want} "
                          "(check out the frozen commit, or the owner must "
                          "re-anchor frozen_inputs.json first)"}
    return {"ok": True, "reason": SELF_PROTECT_OK, "detail": head}


def verify_clean_tree(repo: Path | str, runner=None) -> dict:
    repo = Path(repo)
    porcelain = _git(repo, ["status", "--porcelain"], runner).stdout
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
    return {
        "ok": first_fail is None,
        "reason": SELF_PROTECT_OK if first_fail is None
        else first_fail["reason"],
        "failed_check": None if first_fail is None else first_fail["name"],
        "detail": "" if first_fail is None else first_fail.get("detail", ""),
        "checks": checks,
    }


__all__ = [
    "SELF_PROTECT_AUTOCRLF_NOT_FALSE",
    "SELF_PROTECT_DIRTY_TREE",
    "SELF_PROTECT_DSL_PARITY_BINDING",
    "SELF_PROTECT_FROZEN_HASH_MISMATCH",
    "SELF_PROTECT_FROZEN_INPUTS_TAMPERED",
    "SELF_PROTECT_FROZEN_INPUTS_UNREADABLE",
    "SELF_PROTECT_HEAD_MISMATCH",
    "SELF_PROTECT_OK",
    "broker_parity_scope",
    "classify_field",
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
