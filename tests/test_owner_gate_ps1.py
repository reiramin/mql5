"""owner_gate.ps1 decision-engine red team (stage A + stages 1-3 parse).

owner_gate.ps1 cannot run on this host (no PowerShell), so every DECISION
it makes lives in committed Python (mql5bot.gate_selfcheck) and is tested
here against real git repos and the real calibration artifacts. A green
test proves the gate FAILS CLOSED: a dirty tree, wrong HEAD, tampered
fixture hash or hand-written frozen_inputs can never pass self-protection,
and a non-clean compile / broken parity / broker MISMATCH can never pass a
stage. These are VERIFIER self-tests, never MT5/tester/gold claims.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from mql5bot import gate_selfcheck as gs

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers: a throwaway git repo carrying the real frozen artifacts
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


def _init_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    return repo


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def _stage_artifacts(repo: Path) -> None:
    """Copy the real gold + dsl_parity + frozen files so every hash matches."""
    for rel in (
        "artifacts/owner_mt5_gate/frozen_inputs.json",
        "artifacts/gold/gold_fixture.csv",
        "artifacts/gold/manifest.json",
        "artifacts/gold/expected_execution.json",
        "artifacts/gold_2/gold2_fixture.csv",
        "artifacts/gold_2/manifest.json",
        "artifacts/gold_2/expected_execution.json",
        "artifacts/gold_2/dsl_trace.json",
        "artifacts/gold_2/python_trace.json",
        "artifacts/gold_2/reconciliation.json",
    ):
        _copy(REPO / rel, repo / rel)
    dsl = REPO / "artifacts" / "dsl_parity"
    for p in dsl.rglob("*"):
        if p.is_file():
            _copy(p, repo / "artifacts" / "dsl_parity" / p.relative_to(dsl))


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = _init_repo(tmp_path)
    _stage_artifacts(r)
    # mirror the real repo: the gate's own output root is gitignored, so a run
    # that creates evidence/owner_gate/<UTC>/ never dirties the tree it checks.
    (r / ".gitignore").write_text("/evidence/\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "artifacts")
    return r


def _frozen(repo: Path) -> dict:
    return json.loads((repo / gs.FROZEN_REL).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# stage A -- self-protection, one failing attack per required scenario
# ---------------------------------------------------------------------------

def test_self_protection_fails_on_dirty_tree(repo: Path):
    # dirty a file that is NOT frozen_inputs, so the dirty-tree reason wins
    (repo / "artifacts" / "gold" / "manifest.json").write_text(
        (repo / "artifacts" / "gold" / "manifest.json").read_text() + "\n")
    # frozen_hashes would also trip, but clean_tree is checked first and is
    # the honest reason for an uncommitted edit
    res = gs.verify_clean_tree(repo)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_DIRTY_TREE
    assert "manifest.json" in res["detail"]


def test_self_protection_fails_on_wrong_head(repo: Path):
    frozen = _frozen(repo)
    frozen["source"]["commit"] = "0" * 40  # not the tmp repo HEAD
    res = gs.verify_head_matches_frozen(repo, frozen)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_HEAD_MISMATCH
    assert "0000000000000000000000000000000000000000" in res["detail"]


def test_self_protection_passes_head_when_it_matches(repo: Path):
    head = _git(repo, "rev-parse", "HEAD").strip()
    frozen = {"source": {"commit": head}}
    res = gs.verify_head_matches_frozen(repo, frozen)
    assert res["ok"] and res["reason"] == gs.SELF_PROTECT_OK


def test_self_protection_fails_on_tampered_fixture_hash(repo: Path):
    # flip one byte of the gold fixture -> its sha256 no longer matches the
    # frozen pin. Re-commit so the tree is clean (isolating the hash check).
    fx = repo / "artifacts" / "gold" / "gold_fixture.csv"
    data = bytearray(fx.read_bytes())
    data[-2] ^= 0x01
    fx.write_bytes(bytes(data))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tamper")
    res = gs.verify_frozen_hashes(repo, _frozen(repo))
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_FROZEN_HASH_MISMATCH
    assert "gold_fixture.csv" in res["detail"]


def test_self_protection_fails_on_handwritten_frozen_inputs(repo: Path):
    # a frozen_inputs.json that differs from its committed HEAD blob is a
    # hand-written record -> refused, and the gate never trusts it
    wt = repo / gs.FROZEN_REL
    doc = json.loads(wt.read_text())
    doc["gold_1"]["fixture_sha256"] = "f" * 64  # relax a pin by hand
    wt.write_text(json.dumps(doc, indent=2))
    res = gs.verify_frozen_inputs_untampered(repo)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_FROZEN_INPUTS_TAMPERED


def test_self_protection_untampered_frozen_passes(repo: Path):
    res = gs.verify_frozen_inputs_untampered(repo)
    assert res["ok"] and res["reason"] == gs.SELF_PROTECT_OK


def test_self_protection_fails_on_autocrlf_true(repo: Path):
    _git(repo, "config", "core.autocrlf", "true")
    res = gs.verify_autocrlf_false(repo)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_AUTOCRLF_NOT_FALSE


def test_self_protection_fails_on_dsl_binding_corruption(repo: Path):
    ok = gs.verify_dsl_parity_binding(repo)
    assert ok["ok"], ok  # baseline: 42 bound files verify
    assert "42" in ok["detail"]
    # corrupt one bound file
    victim = repo / "artifacts" / "dsl_parity" / "ema_gt" / "ohlc.csv"
    victim.write_bytes(victim.read_bytes() + b"x")
    bad = gs.verify_dsl_parity_binding(repo)
    assert not bad["ok"]
    assert bad["reason"] == gs.SELF_PROTECT_DSL_PARITY_BINDING


def test_run_self_protection_reports_first_named_failure(repo: Path):
    # wrong HEAD (frozen names a foreign commit) -> the run aborts with the
    # head-mismatch reason, having first cleared the untamper check
    res = gs.run_self_protection(repo)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_HEAD_MISMATCH
    names = [c["name"] for c in res["checks"]]
    assert names[0] == "frozen_inputs_untampered"
    assert res["checks"][0]["ok"] is True  # untampered passed first


def test_live_repo_head_relates_to_anchor_not_a_hard_abort():
    """After the 2026-09-18 re-anchor the frozen anchor (a85cba3) is a real
    commit on master, and HEAD is that commit or a descendant of it. The
    head-relation check must therefore PASS (exact or ahead-of-anchor) --
    the stale-anchor hard abort is gone. It never silently accepts an older
    or diverged HEAD; that is covered by the ancestry tests below."""
    frozen = json.loads((REPO / gs.FROZEN_REL).read_text(encoding="utf-8"))
    res = gs.verify_head_matches_frozen(REPO, frozen)
    assert res["ok"], res
    assert res["reason"] in (gs.SELF_PROTECT_OK,
                             gs.SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR)


# ---------------------------------------------------------------------------
# stage A -- HEAD/anchor ANCESTRY semantics (re-anchor fix): a newer clean
# commit passes; an older, diverged or unknown-anchor HEAD fails.
# ---------------------------------------------------------------------------

def test_head_newer_than_anchor_passes_with_note(repo: Path):
    # anchor = the current commit; add a NEWER descendant commit as HEAD
    anchor = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "note.txt").write_text("newer\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "newer clean commit")
    frozen = {"source": {"commit": anchor}}
    res = gs.verify_head_matches_frozen(repo, frozen)
    assert res["ok"], res
    assert res["reason"] == gs.SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR
    assert res["anchor"] == anchor and res["head"] != anchor


def test_head_older_than_anchor_fails(repo: Path):
    older = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "note.txt").write_text("newer\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "newer")
    newer = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", older)  # HEAD now OLDER than the anchor
    frozen = {"source": {"commit": newer}}
    res = gs.verify_head_matches_frozen(repo, frozen)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_HEAD_MISMATCH
    assert "OLDER" in res["detail"]


def test_head_diverged_from_anchor_fails(repo: Path):
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", "-b", "anchor_branch")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a")
    anchor = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-q", base)
    _git(repo, "checkout", "-q", "-b", "head_branch")
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "b")
    frozen = {"source": {"commit": anchor}}  # no ancestry to HEAD
    res = gs.verify_head_matches_frozen(repo, frozen)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_HEAD_MISMATCH
    assert "diverged" in res["detail"]


def test_head_unknown_anchor_fails(repo: Path):
    frozen = {"source": {"commit": "0" * 40}}  # anchor absent from this clone
    res = gs.verify_head_matches_frozen(repo, frozen)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_HEAD_MISMATCH
    assert "not present in this clone" in res["detail"]


def test_run_self_protection_passes_when_head_descends_from_anchor(repo: Path):
    """Full stage-A run: re-anchor the committed frozen_inputs to the current
    commit, then land a newer clean commit. HEAD descends from the anchor and
    every frozen artifact is byte-identical -> the WHOLE self-protection
    PASSES with a NOTE. Proves a legitimate newer commit is not a hard abort
    (the exact stage-0 bug this replaces)."""
    anchor = _git(repo, "rev-parse", "HEAD").strip()
    fp = repo / gs.FROZEN_REL
    doc = json.loads(fp.read_text())
    doc["source"]["commit"] = anchor  # anchor = the PARENT of the next commit
    fp.write_text(json.dumps(doc, indent=2) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "re-anchor to self, add newer commit")
    res = gs.run_self_protection(repo)
    assert res["ok"], res
    assert res["reason"] == gs.SELF_PROTECT_OK
    assert any("newer than" in n for n in res["notes"]), res["notes"]


def test_run_self_protection_still_aborts_on_dirty_tree(repo: Path):
    # even at the exact anchor, an uncommitted edit fails closed (unchanged)
    anchor = _git(repo, "rev-parse", "HEAD").strip()
    fp = repo / gs.FROZEN_REL
    doc = json.loads(fp.read_text())
    doc["source"]["commit"] = anchor
    fp.write_text(json.dumps(doc, indent=2) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "re-anchor")
    (repo / "artifacts" / "gold" / "manifest.json").write_text(
        (repo / "artifacts" / "gold" / "manifest.json").read_text() + "\n")
    res = gs.run_self_protection(repo)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_DIRTY_TREE


def test_clean_checkout_with_evidence_dir_passes_stage0(repo: Path):
    """The stage-0 self-block regression: the gate creates
    evidence/owner_gate/<UTC>/ on every run, then its own clean-tree check used
    to see `?? evidence/` and abort SELF_PROTECT_DIRTY_TREE. With evidence/
    gitignored, a clean checkout that already carries gate output still passes
    stage 0."""
    anchor = _git(repo, "rev-parse", "HEAD").strip()
    fp = repo / gs.FROZEN_REL
    doc = json.loads(fp.read_text())
    doc["source"]["commit"] = anchor
    fp.write_text(json.dumps(doc, indent=2) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "re-anchor to self")
    # simulate a prior (and the current) gate run's append-only output
    run_dir = repo / "evidence" / "owner_gate" / "20260919-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "stage_0.json").write_text('{"stage": 0}\n')
    (run_dir / "gate_summary.json").write_text('{"gate_result": "certified"}\n')
    # the gate output is invisible to the clean-tree check...
    assert gs.verify_clean_tree(repo)["ok"], "evidence/ must not dirty the tree"
    # ...and the whole stage-0 self-protection passes
    res = gs.run_self_protection(repo)
    assert res["ok"], res
    assert res["reason"] == gs.SELF_PROTECT_OK


def test_modified_tracked_file_still_fails_stage0_with_evidence_present(
        repo: Path):
    """The gitignore exclusion must not blunt the real check: a genuinely
    dirty TRACKED file still fails closed, even with an (ignored) evidence dir
    sitting alongside it."""
    (repo / "evidence" / "owner_gate" / "20260919-000000").mkdir(parents=True)
    (repo / "artifacts" / "gold" / "manifest.json").write_text(
        (repo / "artifacts" / "gold" / "manifest.json").read_text() + "\n")
    res = gs.verify_clean_tree(repo)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_DIRTY_TREE
    assert "manifest.json" in res["detail"]
    assert "evidence/" not in res["detail"]  # the ignored dir never appears


def test_run_self_protection_still_aborts_on_tampered_frozen_artifact(repo: Path):
    # a changed frozen artifact fails closed even when HEAD descends cleanly
    anchor = _git(repo, "rev-parse", "HEAD").strip()
    fx = repo / "artifacts" / "gold" / "gold_fixture.csv"
    data = bytearray(fx.read_bytes())
    data[-2] ^= 0x01
    fx.write_bytes(bytes(data))
    fp = repo / gs.FROZEN_REL
    doc = json.loads(fp.read_text())
    doc["source"]["commit"] = anchor
    fp.write_text(json.dumps(doc, indent=2) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "re-anchor + tamper fixture")
    res = gs.run_self_protection(repo)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_FROZEN_HASH_MISMATCH


# ---------------------------------------------------------------------------
# stage A -- fresh-clone target preflight (the real-world snag: the intended
# clone directory already exists -> name it and exit, never move it by hand)
# ---------------------------------------------------------------------------

def test_clone_target_missing_is_safe(tmp_path: Path):
    res = gs.clone_target_status(tmp_path / "fresh")
    assert res["ok"] and res["reason"] == gs.SELF_PROTECT_OK


def test_clone_target_empty_dir_is_safe(tmp_path: Path):
    d = tmp_path / "empty"
    d.mkdir()
    res = gs.clone_target_status(d)
    assert res["ok"]


def test_clone_target_nonempty_dir_refused_by_name(tmp_path: Path):
    d = tmp_path / "mql5bot"
    d.mkdir()
    (d / ".git").mkdir()  # a stale prior clone
    res = gs.clone_target_status(d)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_CLONE_TARGET_EXISTS
    assert "mql5bot" in res["detail"]  # named, not a bare "already exists"
    assert str(d) == res["path"]


def test_clone_target_existing_file_refused(tmp_path: Path):
    f = tmp_path / "mql5bot"
    f.write_text("x")
    res = gs.clone_target_status(f)
    assert not res["ok"]
    assert res["reason"] == gs.SELF_PROTECT_CLONE_TARGET_EXISTS


# ---------------------------------------------------------------------------
# stage 1 -- strict compile log parse (BOM-aware; from the LOG)
# ---------------------------------------------------------------------------
_TARGETS = ["Mql5Bot.mq5", "DslParityRunner.mq5", "Mql5BotDownloadData.mq5",
            "Mql5BotExportSymbolSpec.mq5"]


def _clean_log() -> str:
    lines = ["# AEGIS compile run"]
    for t in _TARGETS:
        lines.append(f"[compile] {t} : PASS (exit 1, ex5 fresh=True)")
        lines.append("Result: 0 errors, 0 warnings, 500 ms elapsed, cpu='X64'")
    lines.append(f"[compile] RESULT: PASS -- {len(_TARGETS)} file(s) compiled clean")
    return "\n".join(lines) + "\n"


def test_compile_clean_log_passes():
    r = gs.parse_compile_log(_clean_log(), _TARGETS)
    assert r["ok"], r["reasons"]
    assert r["clean_summaries"] == len(_TARGETS)


def test_compile_utf16_bom_decodes_and_passes():
    raw = _clean_log().encode("utf-16")  # BOM'd UTF-16, like some owner logs
    r = gs.parse_compile_log(gs.decode_bom_aware(raw), _TARGETS)
    assert r["ok"], r["reasons"]


def test_compile_utf8_bom_decodes():
    raw = _clean_log().encode("utf-8-sig")
    assert "RESULT: PASS" in gs.decode_bom_aware(raw)


def test_compile_fails_on_warning_summary():
    log = _clean_log().replace("0 warnings", "1 warnings", 1)
    r = gs.parse_compile_log(log, _TARGETS)
    assert not r["ok"]
    assert any("non-zero" in x for x in r["reasons"])


def test_compile_fails_on_missing_target():
    r = gs.parse_compile_log(_clean_log(), _TARGETS + ["Mql5BotImportFixture.mq5"])
    assert not r["ok"]
    assert any("Mql5BotImportFixture.mq5" in x for x in r["reasons"])


def test_compile_fails_on_empty_log():
    r = gs.parse_compile_log("", _TARGETS)
    assert not r["ok"]


def test_compile_accepts_real_metaeditor_error_paren_form():
    # MetaEditor's real summary is "N errors, M warnings"; the fixture form
    # "N error(s), M warning(s)" must also parse as dirty when non-zero
    log = ("[compile] Mql5Bot.mq5 : FAIL (exit 2)\n"
           "Mql5Bot.mq5 - 1 error(s), 0 warning(s)\n"
           "[compile] RESULT: FAIL -- errors in: Mql5Bot.mq5\n")
    r = gs.parse_compile_log(log, ["Mql5Bot.mq5"])
    assert not r["ok"]


# ---------------------------------------------------------------------------
# stage 2 -- dsl parity compare report
# ---------------------------------------------------------------------------

def test_dsl_full_parity_passes():
    text = ("EXACT arithmetic\n" * 1) + "14/14 fixtures EXACT\n" \
        + "EXACT tampered_bundle (refused: bundle_hash mismatch)\n"
    r = gs.parse_dsl_compare_report(text)
    assert r["ok"], r["reasons"]
    assert r["exact"] == 14 and r["total"] == 14


def test_dsl_fails_when_not_all_exact():
    text = "13/14 fixtures EXACT -- PARITY NOT PROVEN\n" \
        + "EXACT tampered_bundle (refused: bundle_hash mismatch)\n"
    r = gs.parse_dsl_compare_report(text)
    assert not r["ok"]


def test_dsl_fails_when_tamper_not_refused():
    text = "14/14 fixtures EXACT\n"  # no tampered-refused line
    r = gs.parse_dsl_compare_report(text)
    assert not r["ok"]
    assert any("tampered" in x for x in r["reasons"])


def test_dsl_parses_real_calibration_report():
    # the committed calibration report is UTF-16; decode + parse it
    path = REPO / "tests" / "data" / "owner_gate" / "compare_report_utf16.txt"
    if not path.is_file():
        pytest.skip("calibration compare report fixture not present")
    r = gs.parse_dsl_compare_report(gs.read_text_bom_aware(path))
    assert r["ok"] and r["exact"] == 14


# ---------------------------------------------------------------------------
# stage 3 -- broker parity scope rule
# ---------------------------------------------------------------------------

def test_broker_mismatch_aborts():
    report = {"rows": [{"symbol": "EURUSD", "field": "point",
                        "status": "MISMATCH"}]}
    r = gs.broker_parity_scope(report)
    assert not r["ok"]
    assert r["mismatch"]


def test_broker_crypto_pending_excluded_not_a_pass_blocker():
    report = {"rows": [
        {"symbol": "EURUSD", "field": "point", "status": "MATCH"},
        {"symbol": "BTC", "field": "sizer.behaviour", "status": "PENDING"},
        {"symbol": "BTC", "field": "tick_value_denomination", "status": "PENDING"},
    ]}
    r = gs.broker_parity_scope(report)
    assert r["ok"], r["reasons"]
    assert ["BTC", "sizer.behaviour"] in [list(x) for x in r["pending_excluded_crypto"]]
    assert not r["pending_in_scope"]


def test_broker_in_scope_pending_blocks():
    report = {"rows": [
        {"symbol": "EURUSD", "field": "point", "status": "MATCH"},
        {"symbol": "XAUEUR", "field": "tick_value_denomination", "status": "PENDING"},
    ]}
    r = gs.broker_parity_scope(report)
    assert not r["ok"]
    assert ["XAUEUR", "tick_value_denomination"] in [list(x) for x in r["pending_in_scope"]]


def test_broker_no_matches_is_not_a_pass():
    r = gs.broker_parity_scope({"rows": []})
    assert not r["ok"]


def test_broker_parses_real_calibration_report():
    path = REPO / "tests" / "data" / "owner_gate" / "parity_report.json"
    if not path.is_file():
        pytest.skip("calibration parity report fixture not present")
    report = json.loads(path.read_text(encoding="utf-8"))
    r = gs.broker_parity_scope(report)
    assert r["ok"], r["reasons"]
    assert r["match_count"] >= 1
    assert not r["mismatch"]


# ---------------------------------------------------------------------------
# stage 4 -- dataset hash derivation matches the frozen pins
# ---------------------------------------------------------------------------

def test_dataset_hash_matches_frozen_pins():
    frozen = json.loads(
        (REPO / gs.FROZEN_REL).read_text(encoding="utf-8"))
    assert gs.dataset_hash_of_csv(REPO / "artifacts/gold/gold_fixture.csv") \
        == frozen["gold_1"]["dataset_hash_from_manifest"]
    assert gs.dataset_hash_of_csv(REPO / "artifacts/gold_2/gold2_fixture.csv") \
        == frozen["gold_2"]["dataset_hash_from_manifest"]


# ---------------------------------------------------------------------------
# mismatch classification (task G: sizing/risk divergence is EXPECTED)
# ---------------------------------------------------------------------------

def test_sizing_and_risk_fields_classify_as_expected_classes():
    assert gs.classify_field("volume") == "SIZING_MISMATCH"
    assert gs.classify_field("requested_lots") == "SIZING_MISMATCH"
    assert gs.classify_field("risk_approved") == "RISK_MISMATCH"


def test_real_calibration_compile_log_parses_clean_bom_aware():
    # the committed calibration log is stored UTF-16 (the encoding the task
    # warns compile.ps1/MetaEditor emit); the BOM-aware decoder must handle
    # it and read the 4 clean targets from the LOG
    path = REPO / "tests" / "data" / "owner_gate" / "compile-calibration.log"
    if not path.is_file():
        pytest.skip("calibration compile log fixture not present")
    text = gs.read_text_bom_aware(path)
    targets = ["Mql5Bot.mq5", "DslParityRunner.mq5",
               "Mql5BotDownloadData.mq5", "Mql5BotExportSymbolSpec.mq5"]
    r = gs.parse_compile_log(text, targets)
    assert r["ok"], r["reasons"]
    assert r["clean_summaries"] == 4


def test_expected_compile_targets_tracks_the_source_tree():
    # the calibration compiled 4; adding the fixture importer makes it 5 -
    # the gate must expect exactly what the repo ships, never a magic number
    targets = gs.expected_compile_targets(REPO)
    assert "Mql5Bot.mq5" in targets
    assert "Mql5BotImportFixture.mq5" in targets
    assert len(targets) == 5


# ---------------------------------------------------------------------------
# tools/owner_gate.ps1 -- static contract (cannot execute here; no PowerShell)
# ---------------------------------------------------------------------------
def _ps1() -> str:
    return (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")


def test_ps1_is_pure_ascii():
    raw = (REPO / "tools" / "owner_gate.ps1").read_bytes()
    assert not [b for b in raw if b > 0x7F], "owner_gate.ps1 must stay ASCII"


def test_ps1_delegates_every_decision_to_committed_python():
    src = _ps1()
    for cmd in ("self-protection", "parse-compile", "parse-dsl",
                "broker-scope"):
        assert cmd in src, f"ps1 must delegate {cmd!r} to owner_gate_decide"
    assert "owner_gate_decide" in src


def test_ps1_emits_machine_readable_gate_result_and_stage_files():
    src = _ps1()
    assert "GATE_RESULT=" in src
    assert "stage_{0}.json" in src
    assert "gate_summary.json" in src
    assert "first_blocking" in src


def test_ps1_honours_the_hard_rules():
    src = _ps1()
    # never WRITES frozen_inputs: it only ever reads it as an argument path
    assert "Out-File" in src  # it does write evidence...
    # ...but frozen_inputs appears only as a --frozen input, never a write
    for line in src.splitlines():
        if "frozen_inputs.json" in line:
            assert ("Out-File" not in line and "WriteAllText" not in line
                    and "Set-Content" not in line), \
                f"ps1 must never write frozen_inputs.json: {line.strip()}"
    # never amends / force-pushes / commits
    for banned in ("commit --amend", "push --force", "push -f", "git commit"):
        assert banned not in src, f"ps1 must not run: {banned}"


def test_ps1_records_expected_sizing_divergence_without_patching():
    src = _ps1()
    assert "DIVERGENCE_EXPECTED" in src
    assert "SIZING_MISMATCH" in src and "RISK_MISMATCH" in src
    assert "NEVER revert" in src or "never revert" in src.lower()


def test_ps1_stage3_applies_the_btc_pending_scope_rule():
    src = _ps1()
    assert "broker-scope" in src
    assert "pending_excluded_crypto" in src


def test_ps1_guards_an_existing_clone_target():
    src = _ps1()
    # the fresh-clone preflight is delegated to committed Python and is opt-in
    assert "-CloneInto" in src or "CloneInto" in src
    assert "clone-preflight" in src


def test_ps1_surfaces_the_head_ahead_of_anchor_note():
    src = _ps1()
    # a newer descendant HEAD is a PASS-with-NOTE, not an abort: the .ps1 must
    # read the decision's notes and print them, and must no longer hard-assert
    # "HEAD==frozen" as its only pass reason
    assert "notes" in src
    assert "NOTE" in src
    assert "HEAD==frozen, tree clean" not in src


# ---------------------------------------------------------------------------
# Mql5BotImportFixture.mq5 -- static contract (source-only; owner compiles)
# ---------------------------------------------------------------------------
def _importer() -> str:
    return (REPO / "mql5" / "Scripts" / "Mql5Bot"
            / "Mql5BotImportFixture.mq5").read_text(encoding="utf-8")


def test_importer_is_ascii_and_lf():
    raw = (REPO / "mql5" / "Scripts" / "Mql5Bot"
           / "Mql5BotImportFixture.mq5").read_bytes()
    assert not [b for b in raw if b > 0x7F], "importer must stay ASCII"
    assert b"\r\n" not in raw, "importer must be LF-only"


def test_importer_uses_custom_symbol_api_the_repo_previously_lacked():
    src = _importer()
    for api in ("CustomSymbolCreate", "CustomRatesUpdate",
                "CustomSymbolSetDouble", "CustomSymbolSetString"):
        assert api in src, f"importer must call {api}"


def test_importer_refuses_and_creates_nothing_on_hash_or_property_gaps():
    src = _importer()
    # fixture bytes must equal the manifest dataset_hash before anything
    assert "fixture csv sha256" in src
    # round-trip hash must re-derive the manifest dataset_hash
    assert "roundtrip dataset hash" in src
    # a missing property refuses rather than inventing a value
    assert "missing property" in src
    assert "inventing" in src
    # on any post-create refusal it deletes the symbol (never half-lands)
    assert "CustomSymbolDelete" in src


def test_importer_reads_properties_from_manifest_and_symbolspec_only():
    src = _importer()
    assert "broker_spec" in src           # manifest source of properties
    assert "currency_base" in src and "currency_margin" in src
    assert "SymbolSpec export" in src     # base/margin ccy from stage 3


def test_importer_does_not_pull_live_history():
    src = _importer()
    # the only CopyRates is the post-write readback of the custom symbol;
    # there must be no chart / iBars / SymbolInfo live-history pull
    assert src.count("CopyRates(") == 1
    assert "iClose" not in src and "iOpen" not in src


# ---------------------------------------------------------------------------
# Mql5BotImportFixture.mq5 -- STAGE 4 FIX contract (err=5306 family)
# ---------------------------------------------------------------------------

def test_importer_is_chart_independent():
    # it must take symbol/timeframe ONLY from inputs + manifest, never read
    # the attached chart implicitly (the gate runs it from a BTC,H1 chart)
    src = _importer()
    for implicit in ("_Symbol", "_Period", "ChartSymbol(", "ChartPeriod(",
                     "Symbol()", "Period()"):
        assert implicit not in src, f"importer must not read {implicit!r}"
    assert "InpSymbolName" in src            # symbol from the input
    assert "TimeframeFromString" in src      # timeframe from the manifest


def test_importer_validates_the_custom_symbol_name():
    src = _importer()
    assert "ValidCustomSymbolName" in src
    # the exact MT5 rule set: Latin letters/digits and only . _ & #
    assert "c=='.' || c=='_' || c=='&' || c=='#'" in src
    assert "name_check" in src               # a bad name refuses with a stage


def test_importer_handles_5306_symbol_state_before_mutating():
    src = _importer()
    # a selected symbol cannot be deleted (5306) or have properties changed:
    # deselect before any delete/set, select ONLY after bars are written
    assert "SymbolSelect(sym, false)" in src
    assert "SymbolSelect(sym, true)" in src
    # a stale prior custom symbol is detected and recreated deterministically
    assert "SymbolExist(sym, isCustom)" in src
    # a broker (non-custom) symbol of the same name is never shadowed
    assert "refusing to shadow a broker symbol" in src
    # the select-after-import comes AFTER CustomRatesUpdate in source order
    assert src.index("CustomRatesUpdate(sym") < src.index("SymbolSelect(sym, true)")


def test_importer_sets_each_property_one_at_a_time_with_named_diagnostic():
    src = _importer()
    # per-property setters that check each return and record enum/value/source
    for setter in ("bool SetI(", "bool SetD(", "bool SetS("):
        assert setter in src
    # the running per-property diagnostic and its keys
    for key in ('\\"enum\\":', '\\"value\\":', '\\"source\\":',
                '\\"ok\\":', '\\"last_error\\":'):
        assert key in src, f"property record must carry {key}"
    # a value is sourced by name from the manifest / SymbolSpec export
    assert "manifest.broker_spec.volume_min" in src
    assert "symbol.currency_base" in src


def test_importer_refusal_record_is_populated_not_vacuous():
    src = _importer()
    # the refusal writer names the failing call/property/value/source + error
    for key in ('\\"failed_call\\":', '\\"failed_property\\":',
                '\\"failed_source\\":', '\\"failed_value\\":',
                '\\"last_error\\":', '\\"stage\\":', '\\"properties\\":'):
        assert key in src, f"refusal record must carry {key}"
    # the old vacuous refusal writer is gone (RefuseAt replaces WriteRefusal)
    assert "RefuseAt(" in src
    assert "void WriteRefusal(" not in src


def test_importer_writes_to_the_explicit_gate_path_not_a_guess():
    src = _importer()
    # the output path comes from InpOutFile (the EXACT path the gate passes),
    # only falling back to the guessed default for a manual run
    assert "input string InpOutFile" in src
    assert "StringLen(InpOutFile) > 0" in src
    assert "? InpOutFile" in src


def test_importer_removes_stale_symbol_idempotently_and_fails_closed():
    src = _importer()
    # a stale custom symbol is deleted AND verified gone before create; a
    # failed delete REFUSES at symbol_state rather than 5304-colliding
    assert "DropCustomSymbolChecked" in src
    assert "SymbolExist(still present after delete)" in src
    assert "ERR_CUSTOM_SYMBOL_EXIST (5304)" in src
    # the create refusal explains 5304 explicitly
    assert "5304 = ERR_CUSTOM_SYMBOL_EXIST" in src
    # the delete-verify helper deselects (5306-safe) then deletes then checks
    di = src.index("bool DropCustomSymbolChecked")
    assert src.index("SymbolSelect(sym, false)", di) < src.index("CustomSymbolDelete(sym)", di)
    assert src.index("CustomSymbolDelete(sym)", di) < src.index("SymbolExist(sym, isCustom)", di)


def test_importer_documents_twice_in_a_row_determinism():
    src = _importer()
    # the idempotency requirement is stated in the script's own docs
    assert "TWICE IN A ROW MUST PRODUCE IDENTICAL RESULTS" in src


def test_importer_enforces_the_name_path_pair_rule():
    src = _importer()
    # the last element of the group must not equal the name (MT5 would treat
    # it as the symbol, not a folder); the rule is documented and enforced
    assert "GroupPathOkForName" in src
    assert "last element of group" in src
    assert "unique across the ENTIRE symbol hierarchy" in src


def test_r7_symbol_names_are_forex_xxxyyy_form_for_currency_inference():
    """R7 (gate_run9): a Forex-mode custom symbol derives base/profit currency
    from the first/second three-char chunks of the NAME, and
    CustomSymbolSetString reports success without taking effect for them. The
    fix is to NAME each gold in XXXYYY+suffix Forex form so MT5's own inference
    yields EUR/USD. Lock that the gate configures such names and that the old
    GOLD*_EURUSD names (which derived base 'GOL'/profit 'D1_') are gone."""
    ps1 = _ps1()
    # both golds and the reconciliation map use EURUSD.G1 / EURUSD.G2
    for name in ("EURUSD.G1", "EURUSD.G2"):
        assert name in ps1, f"gate must configure {name}"
        # first six characters are the currency pair -> base EUR, profit USD
        assert name[:6] == "EURUSD"
    # the broken pre-R7 names must not survive as configured VALUES (they may
    # still be named in comments that explain the fix)
    assert '= "GOLD1_EURUSD"' not in ps1 and '= "GOLD2_EURUSD"' not in ps1
    assert 'name = "GOLD' not in ps1
    # the importer default and docs reflect the same Forex-inference reasoning
    src = _importer()
    assert 'InpSymbolName  = "EURUSD.G1"' in src
    assert "cannot be set" in src and "taking effect" in src
    assert "first/second three-char chunks" in src


# ---------------------------------------------------------------------------
# stage 4 -- import diagnostic classifier (the err=5306 blind-spot mirror).
# The importer cannot run on Mac (no MT5); its refusal-record contract is
# tested here by simulating the JSON a failing property WRITES and asserting
# the gate reads a populated, property-named diagnostic from it.
# ---------------------------------------------------------------------------

def _property_refusal_doc() -> dict:
    """The record Mql5BotImportFixture writes when a CustomSymbolSet* call
    fails on an out-of-range value (err=5308 in the 5306 family)."""
    return {
        "error": "CustomSymbolSetDouble(SYMBOL_VOLUME_MIN=0.0100000000 from "
                 "manifest.broker_spec.volume_min) failed",
        "failed_call": "CustomSymbolSetDouble",
        "failed_property": "SYMBOL_VOLUME_MIN",
        "failed_source": "manifest.broker_spec.volume_min",
        "failed_value": "0.0100000000",
        "last_error": 5308,
        "properties": [
            {"enum": "SYMBOL_DIGITS", "value": "5",
             "source": "manifest.broker_spec.digits", "ok": True,
             "last_error": 0},
            {"enum": "SYMBOL_VOLUME_MIN", "value": "0.0100000000",
             "source": "manifest.broker_spec.volume_min", "ok": False,
             "last_error": 5308},
        ],
        "refused": True,
        "stage": "set_properties",
        "symbol": "GOLD_EURUSD",
    }


def test_import_refusal_writes_populated_json_with_property_name(tmp_path: Path):
    # simulate the importer refusing on a failing property: the JSON it writes
    # must appear on disk and name the offending property
    out = tmp_path / "GOLD_EURUSD.json"
    out.write_text(json.dumps(_property_refusal_doc()), encoding="utf-8")
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    verdict = gs.import_diagnostic_populated(doc)
    assert verdict["populated"], verdict
    assert verdict["refused"] is True
    assert verdict["failed_property"] == "SYMBOL_VOLUME_MIN"
    # the property name is visibly present in the file the gate attaches
    assert "SYMBOL_VOLUME_MIN" in out.read_text(encoding="utf-8")
    assert "5308" in verdict["reason"]


def test_import_old_vacuous_refusal_is_flagged_not_populated():
    # the pre-fix record: err=5306 and nothing else -> the stage-4 blind spot
    doc = {"error": "CustomSymbolSet* failed, err=5306",
           "refused": True, "symbol": "GOLD_EURUSD"}
    verdict = gs.import_diagnostic_populated(doc)
    assert not verdict["populated"]
    assert "last_error" in verdict["reason"]


def test_import_property_refusal_without_name_is_flagged():
    # a property-stage refusal that fails to name the failing property is a
    # regression and must not count as populated
    doc = _property_refusal_doc()
    doc["failed_property"] = ""
    verdict = gs.import_diagnostic_populated(doc)
    assert not verdict["populated"]
    assert "failed_property" in verdict["reason"]


def test_import_success_record_is_populated():
    doc = {"fixture_file_sha256": "a" * 64, "last_error": 0,
           "manifest_dataset_hash": "b" * 64, "n_bars": 500,
           "properties": [], "refused": False,
           "roundtrip_sha256": "b" * 64, "stage": "complete",
           "symbol": "GOLD_EURUSD", "timeframe": "H1"}
    verdict = gs.import_diagnostic_populated(doc)
    assert verdict["populated"] and not verdict["refused"]


def test_import_diagnostic_decide_cli_roundtrips(tmp_path: Path):
    # the .ps1 shells to owner_gate_decide.py import-diagnostic; a populated
    # refusal exits 1 (usable) with the reason, a vacuous one also exits 1 but
    # flags populated=false so the gate can fail closed on regression
    import subprocess as sp
    import sys
    result = tmp_path / "GOLD_EURUSD.json"
    result.write_text(json.dumps(_property_refusal_doc()), encoding="utf-8")
    decide = REPO / "tools" / "owner_gate_decide.py"
    cp = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                 "import-diagnostic", str(result)],
                capture_output=True, text=True, check=False)
    payload = json.loads(cp.stdout)
    assert payload["populated"] is True
    assert payload["failed_property"] == "SYMBOL_VOLUME_MIN"


# ---------------------------------------------------------------------------
# stage 4 -- the MISREPORT fix: three-way outcome classifier. A gate that
# blames "terminal did not run" when the importer actually ran and refused is
# worse than one that fails; these tests pin the three cases apart.
# ---------------------------------------------------------------------------

def _early_create_refusal_doc() -> dict:
    """What the importer writes on the reported failure: it created the symbol
    on a prior run, that run died, and this run hit ERR_CUSTOM_SYMBOL_EXIST at
    create. The record is written FIRST thing on that early exit path."""
    return {
        "error": "CustomSymbolCreate failed for group Mql5Bot\\gold "
                 "(last_error 5304 = ERR_CUSTOM_SYMBOL_EXIST means a prior "
                 "symbol survived deletion)",
        "failed_call": "", "failed_property": "", "failed_source": "",
        "failed_value": "", "last_error": 5304, "properties": [],
        "refused": True, "stage": "create_symbol", "symbol": "GOLD1_EURUSD",
    }


def test_stage4_early_refusal_is_case3_populated_not_case1(tmp_path: Path):
    """The exact ground-truth mismatch this round fixes: the importer refused
    early (create_symbol / 5304) and WROTE a populated JSON; the gate must
    report case 3 (refused, reason verbatim), NOT case 1 (never launched) and
    NOT case 2 (no JSON). Non-vacuous: the file is on disk, is populated, and
    the classifier surfaces the 5304 reason."""
    out = tmp_path / "GOLD1_EURUSD.json"
    out.write_text(json.dumps(_early_create_refusal_doc()), encoding="utf-8")
    doc = json.loads(out.read_text(encoding="utf-8"))
    # the JSON the importer wrote is attached + populated (usable observability)
    assert out.is_file() and out.stat().st_size > 0
    assert gs.import_diagnostic_populated(doc)["populated"] is True
    # the gate's decision, given "launched + json present":
    v = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                   manifest_hash="b" * 64, symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_REFUSED
    assert v["case"] != gs.STAGE4_CASE_NOT_LAUNCHED
    assert not v["ok"]
    # the refusal reason is surfaced VERBATIM (the 5304 fact, the stage)
    assert "5304" in v["message"]
    assert "create_symbol" in v["message"]
    assert "ERR_CUSTOM_SYMBOL_EXIST" in v["message"]


def test_stage4_case1_terminal_never_launched():
    v = gs.classify_stage4_outcome(launched=False, json_present=False,
                                   doc=None, manifest_hash="b" * 64,
                                   symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_NOT_LAUNCHED
    assert not v["ok"]
    assert "never launched" in v["message"]


def test_stage4_case2_ran_but_no_json_notes_log_backstop():
    # ran, no JSON, and a log excerpt WAS saved -> case 2, points at the log
    v = gs.classify_stage4_outcome(launched=True, json_present=False,
                                   doc=None, manifest_hash="b" * 64,
                                   symbol="GOLD1_EURUSD",
                                   log_excerpt_present=True)
    assert v["case"] == gs.STAGE4_CASE_NO_JSON
    assert not v["ok"]
    assert "terminal-log excerpt" in v["message"]
    # ran, no JSON, and NOT even a log line found -> still case 2, says so
    v2 = gs.classify_stage4_outcome(launched=True, json_present=False,
                                    doc=None, manifest_hash="b" * 64,
                                    symbol="GOLD1_EURUSD",
                                    log_excerpt_present=False)
    assert v2["case"] == gs.STAGE4_CASE_NO_JSON
    assert "no Mql5BotImportFixture lines" in v2["message"]


def test_stage4_faithful_import_is_the_only_pass():
    # R5: a PASS additionally requires the read-back proof (see the
    # properties_unverified tests below); this doc carries it clean
    v = gs.classify_stage4_outcome(launched=True, json_present=True,
                                   doc=_verified_success_doc(),
                                   manifest_hash="b" * 64, symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_PASS and v["ok"]


def test_stage4_success_with_wrong_hash_fails_closed():
    doc = {"last_error": 0, "n_bars": 5, "properties": [], "refused": False,
           "roundtrip_sha256": "d" * 64, "stage": "complete",
           "symbol": "GOLD1_EURUSD"}
    v = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                   manifest_hash="b" * 64, symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_HASH_MISMATCH and not v["ok"]


def test_stage4_outcome_decide_cli_reports_case3_for_early_refusal(tmp_path: Path):
    """End-to-end through the CLI the .ps1 shells to: an on-disk early-refusal
    JSON with launched=true is classified case 3 (refused), exit 1, message
    carrying the verbatim 5304 reason -- never 'terminal never launched'."""
    import subprocess as sp
    import sys
    result = tmp_path / "GOLD1_EURUSD.json"
    result.write_text(json.dumps(_early_create_refusal_doc()), encoding="utf-8")
    decide = REPO / "tools" / "owner_gate_decide.py"
    cp = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                 "stage4-outcome", "--symbol", "GOLD1_EURUSD",
                 "--launched", "true", "--result", str(result),
                 "--manifest-hash", "b" * 64],
                capture_output=True, text=True, check=False)
    payload = json.loads(cp.stdout)
    assert payload["case"] == gs.STAGE4_CASE_REFUSED
    assert payload["ok"] is False and cp.returncode == 1
    assert "5304" in payload["message"]
    assert "never launched" not in payload["message"]


def test_stage4_outcome_decide_cli_case1_when_missing_result(tmp_path: Path):
    # launched=false and no result file -> case 1 (never launched)
    import subprocess as sp
    import sys
    decide = REPO / "tools" / "owner_gate_decide.py"
    cp = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                 "stage4-outcome", "--symbol", "GOLD1_EURUSD",
                 "--launched", "false",
                 "--result", str(tmp_path / "absent.json"),
                 "--manifest-hash", "b" * 64],
                capture_output=True, text=True, check=False)
    payload = json.loads(cp.stdout)
    assert payload["case"] == gs.STAGE4_CASE_NOT_LAUNCHED
    assert cp.returncode == 1


def test_stage4_outcome_decide_cli_case2_launched_but_result_absent(tmp_path: Path):
    # launched=true but the result path is absent -> case 2 (ran, no JSON)
    import subprocess as sp
    import sys
    decide = REPO / "tools" / "owner_gate_decide.py"
    cp = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                 "stage4-outcome", "--symbol", "GOLD1_EURUSD",
                 "--launched", "true",
                 "--result", str(tmp_path / "absent.json"),
                 "--manifest-hash", "b" * 64],
                capture_output=True, text=True, check=False)
    payload = json.loads(cp.stdout)
    assert payload["case"] == gs.STAGE4_CASE_NO_JSON
    assert cp.returncode == 1


# ---------------------------------------------------------------------------
# tools/owner_gate.ps1 -- stage 4 attaches the diagnostic on pass OR fail
# ---------------------------------------------------------------------------

def test_ps1_stage4_delegates_outcome_and_attaches_on_pass_or_fail():
    src = _ps1()
    # the three-way outcome decision is delegated to committed Python
    assert "stage4-outcome" in src
    # the importer result is attached to stage_4 before the pass/fail branch
    assert "$stage4art.Add((New-Artifact $resCopy))" in src
    # the result is only attached when it actually exists (no crash on absence)
    assert "if (Test-Path -LiteralPath $resultJson)" in src


def test_ps1_stage4_passes_symbol_and_explicit_output_path_via_preset():
    src = _ps1()
    # the gate must tell the importer WHICH gold and EXACTLY where to write --
    # never the script's compiled-in GOLD_EURUSD default. It does this with a
    # *.set preset referenced by ScriptParameters in the startup ini.
    assert "ScriptParameters=" in src
    assert "MQL5\\Presets" in src
    assert "InpSymbolName=" in src
    assert "InpOutFile=" in src
    # the path the gate reads back is the SAME $outRel it passed to the importer
    assert "$outRel" in src
    assert "$resultJson = Join-Path $DataFolder" in src


def test_ps1_stage4_greps_terminal_log_when_no_json():
    src = _ps1()
    # backstop: no JSON -> grep the MT5 log for the importer's own lines and
    # attach them, so the cause lands in the evidence dir either way
    assert "Save-ImporterLog" in src
    assert "Mql5BotImportFixture" in src
    assert "--log-excerpt" in src
    # the old misreport ("terminal did not run the script") on a mere
    # name/path mismatch is GONE -- the decision is the Python three-case one
    assert "terminal did not run the script" not in src


def test_ps1_stage4_distinguishes_launch_from_ran_no_output():
    src = _ps1()
    # the launcher reports launch status so the gate can tell case 1 from case 2
    assert ".launched" in src
    assert "Invoke-TerminalScript" in src


# ---------------------------------------------------------------------------
# STAGE 4 ROUND 3 -- terminal_ran_no_json root causes closed on our side:
# (A) MQL5\Files sandbox pattern + sha-audited evidence copy, (B) preset
# delivery per the MT5 startup docs, (C) proof-Prints before any I/O,
# (D) the excerpt head surfaced in the gate's own console/reason.
# ---------------------------------------------------------------------------

def test_importer_first_action_is_the_startup_print_banner():
    # C) the FIRST action of OnStart is a Print() naming the fixture, EVERY
    # resolved input, and the relative+absolute output path -- so the
    # terminal-log backstop names the cause even when no JSON is written
    src = _importer()
    body = src[src.index("void OnStart()"):]
    assert body.index("[import] STARTUP") < body.index("ReadFileBytes(")
    for named in ("fixture_csv=", " manifest=", " symbol_spec=", " symbol=",
                  " group=", " out_dir=", " out_file=", " out_rel=",
                  " out_abs="):
        assert named in body, f"startup banner must name {named!r}"
    # the absolute output path is derived from the terminal's own data path
    assert "TERMINAL_DATA_PATH" in body


def test_importer_guards_the_files_sandbox_against_absolute_paths():
    # A) an MQL5 script can only write RELATIVE paths under MQL5\Files; an
    # absolute out path is detected up front, Printed loudly, and replaced by
    # the relative fallback so a diagnostic still lands where FileOpen allows
    src = _importer()
    assert "bool LooksAbsolutePath(" in src
    assert "LooksAbsolutePath(outPath)" in src
    assert "falling back to" in src
    # the guard runs BEFORE the resolved-path banner line
    body = src[src.index("void OnStart()"):]
    assert body.index("LooksAbsolutePath(outPath)") < body.index("out_rel=")


def test_importer_prints_path_and_last_error_on_fileopen_failure():
    # A) a refused FileOpen must name the path and _LastError in the terminal
    # log (read AND write side), so the backstop excerpt shows the cause
    src = _importer()
    assert "FileOpen(READ) FAILED path=" in src
    assert "FileOpen(WRITE) FAILED path=" in src
    assert src.count('" last_error=", GetLastError())') >= 2


def test_ps1_stages_the_preset_where_startup_reads_it_and_in_utf16():
    # B) verified against the MT5 "Configuration at Startup" help:
    # ScriptParameters is a bare file name resolved in MQL5\Presets of the
    # data directory -- and the terminal's own .set encoding is UTF-16LE
    src = _ps1()
    assert "Configuration at Startup" in src
    assert "MQL5\\presets" in src or "MQL5\\Presets" in src
    preset_writes = [l for l in src.splitlines()
                     if "Join-Path $presetsDir $setName" in l
                     and "WriteAllText" in l]
    assert preset_writes, "the gate must stage the .set into MQL5\\Presets"
    for line in preset_writes:
        assert "[Text.Encoding]::Unicode" in line, \
            "the staged .set must be UTF-16LE (the terminal's own encoding)"


def test_ps1_records_sha256_before_and_after_the_evidence_copy():
    # A) the gate copies the importer's JSON out of MQL5\Files into evidence\
    # recording sha256 before AND after, attaching both records
    src = _ps1()
    assert "$shaBefore = Get-Sha256 $resultJson" in src
    assert "$shaAfter = Get-Sha256 $resCopy" in src
    assert "path = $resultJson; sha256 = $shaBefore" in src
    assert "$stage4art.Add((New-Artifact $resCopy))" in src


def test_ps1_surfaces_the_excerpt_head_inline_and_spots_stray_outputs():
    src = _ps1()
    # D) the first ~10 excerpt lines go to the gate's own console
    assert "-TotalCount 10" in src
    assert "log excerpt head" in src
    # B) a defaults run writes to the importer's DEFAULT path: any stray JSON
    # in the import-out dir is copied to evidence and named in the excerpt
    assert "stray import-out JSON" in src
    assert "Save-ImporterLog $g.name $extra" in src


def test_stage4_no_json_message_carries_the_excerpt_head():
    head = ("20250918.log: Mql5BotImportFixture (BTCUSD,H1) [import] STARTUP "
            "symbol=GOLD_EURUSD group=Mql5Bot\\gold out_file=\n"
            "20250918.log: [import] FileOpen(WRITE) FAILED path=x "
            "last_error=5002")
    v = gs.classify_stage4_outcome(launched=True, json_present=False, doc=None,
                                   manifest_hash="b" * 64,
                                   symbol="GOLD1_EURUSD",
                                   log_excerpt_present=True,
                                   log_excerpt_head=head)
    assert v["case"] == gs.STAGE4_CASE_NO_JSON
    assert "excerpt begins:" in v["message"]
    assert "symbol=GOLD_EURUSD" in v["message"]
    assert "last_error=5002" in v["message"]
    # without a head the old message shape is preserved
    v2 = gs.classify_stage4_outcome(launched=True, json_present=False,
                                    doc=None, manifest_hash="b" * 64,
                                    symbol="GOLD1_EURUSD",
                                    log_excerpt_present=True)
    assert "excerpt begins:" not in v2["message"]
    assert "terminal-log excerpt" in v2["message"]


def test_stage4_outcome_decide_cli_folds_excerpt_head_into_message(tmp_path: Path):
    # end-to-end through the CLI the .ps1 shells to: the excerpt's first ~10
    # lines land in the decision message (and so in the stage reason), making
    # the failure diagnosable from the gate console alone
    import subprocess as sp
    import sys
    excerpt = tmp_path / "import_GOLD1_EURUSD_terminal_log.txt"
    lines = (["log: [import] STARTUP symbol=GOLD_EURUSD out_file="]
             + [f"log: filler line {i}" for i in range(2, 15)])
    excerpt.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    decide = REPO / "tools" / "owner_gate_decide.py"
    cp = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                 "stage4-outcome", "--symbol", "GOLD1_EURUSD",
                 "--launched", "true",
                 "--result", str(tmp_path / "absent.json"),
                 "--manifest-hash", "b" * 64,
                 "--log-excerpt", str(excerpt)],
                capture_output=True, text=True, check=False)
    payload = json.loads(cp.stdout)
    assert payload["case"] == gs.STAGE4_CASE_NO_JSON
    assert cp.returncode == 1
    assert "excerpt begins:" in payload["message"]
    assert "symbol=GOLD_EURUSD" in payload["message"]
    # only the first ~10 lines are folded in
    assert "filler line 12" not in payload["message"]


# ---------------------------------------------------------------------------
# STAGE 4 ROUND 4 -- the STARTUP banner caught it: the .set reached MT5 with
# InpSymbolName= and InpOutFile= EMPTY (their values on the FOLLOWING line).
# Root cause: inside a PowerShell @() literal the COMMA operator binds
# TIGHTER than '+', so `"Key=" + $expr,` contributes TWO array elements.
# The fix is (1) single interpolated strings in $setLines and (2) fail-closed
# validation of the STAGED preset BEFORE the terminal is ever launched.
# ---------------------------------------------------------------------------

def _intended_preset(name: str = "EURUSD.G1") -> dict:
    """The exact key=value pairs the gate intends to deliver for a gold."""
    return {
        "InpFixtureCsv": "Mql5Bot\\gold_import\\gold_fixture.csv",
        "InpManifest": "Mql5Bot\\gold_import\\manifest.json",
        "InpSymbolSpec": "Mql5Bot\\broker_exports\\EURUSD.json",
        "InpSymbolName": name,
        "InpSymbolGroup": "Mql5Bot\\gold",
        "InpOutDir": "Mql5Bot\\gold_import_out",
        "InpOutFile": "Mql5Bot\\gold_import_out\\" + name + ".json",
    }


def _build_preset_lines_from_ps1(name: str) -> list[str]:
    """Build the preset lines the gate's own $setLines literal produces for a
    fixture, under PowerShell's ACTUAL precedence rules.

    In PowerShell the comma operator binds TIGHTER than '+', so an element
    written `"Key=" + $expr` inside @() contributes TWO array elements
    ("Key=" and the expression's value) -- the gate_run6 bug. A single
    (interpolated) double-quoted string contributes ONE line. This mirror
    lets the Mac tests reconstruct the exact lines MT5 would read without a
    PowerShell host.
    """
    src = _ps1()
    start = src.index("$setLines = @(")
    end = src.index("\n    )", start)
    out_rel = "Mql5Bot\\gold_import_out\\" + name + ".json"

    def resolve(text: str) -> str:
        return (text.replace("$($g.name)", name)
                    .replace("$g.name", name)
                    .replace("$outRel", out_rel))

    lines: list[str] = []
    for raw in src[start:end].splitlines()[1:]:
        el = raw.strip().rstrip(",").strip()
        if not el or el.startswith("#"):
            continue
        whole = re.fullmatch(r'"([^"]*)"', el)
        if whole:
            lines.append(resolve(whole.group(1)))
            continue
        # a top-level '+' inside @(): comma precedence splits the element
        for part in (p.strip() for p in el.split("+")):
            quoted = re.fullmatch(r'"([^"]*)"', part)
            lines.append(resolve(quoted.group(1)) if quoted else resolve(part))
    return lines


def test_preset_lines_built_for_gold1_are_nonempty_and_single_line():
    """R4 non-vacuous regression: the lines the gate's $setLines literal
    actually produces for GOLD1_EURUSD must every one be Key=Value with a
    non-empty single-line value. FAILED against the pre-R4 construction
    (`"InpSymbolName=" + $g.name,`): InpSymbolName= and InpOutFile= arrived
    EMPTY with their values on the following lines."""
    lines = _build_preset_lines_from_ps1("EURUSD.G1")
    v = gs.validate_preset("\r\n".join(lines) + "\r\n", _intended_preset())
    assert v["ok"], v["reasons"]


def test_ps1_preset_elements_are_single_strings_no_comma_precedence():
    # no $setLines element may use bare '+' concatenation inside the @()
    # literal -- the comma operator would split it into two elements
    src = _ps1()
    start = src.index("$setLines = @(")
    end = src.index("\n    )", start)
    for raw in src[start:end].splitlines()[1:]:
        el = raw.strip().rstrip(",").strip()
        if not el or el.startswith("#"):
            continue
        assert re.fullmatch(r'"[^"]*"', el), \
            f"$setLines element must be ONE interpolated string: {el}"


def test_validate_preset_accepts_the_intended_lines():
    expected = _intended_preset()
    text = "\r\n".join(f"{k}={v}" for k, v in expected.items()) + "\r\n"
    v = gs.validate_preset(text, expected)
    assert v["ok"], v["reasons"]
    assert v["found_count"] == v["expected_count"] == 7


def test_validate_preset_rejects_the_gate_run6_broken_preset():
    # the EXACT decoded shape gate_run6 observed: the two fixture-derived
    # entries split into "Key=" with the value on the FOLLOWING line
    text = ("InpFixtureCsv=Mql5Bot\\gold_import\\gold_fixture.csv\r\n"
            "InpManifest=Mql5Bot\\gold_import\\manifest.json\r\n"
            "InpSymbolSpec=Mql5Bot\\broker_exports\\EURUSD.json\r\n"
            "InpSymbolName=\r\n"
            "GOLD1_EURUSD\r\n"
            "InpSymbolGroup=Mql5Bot\\gold\r\n"
            "InpOutDir=Mql5Bot\\gold_import_out\r\n"
            "InpOutFile=\r\n"
            "Mql5Bot\\gold_import_out\\GOLD1_EURUSD.json\r\n")
    v = gs.validate_preset(text, _intended_preset())
    assert not v["ok"]
    joined = "; ".join(v["reasons"])
    # the offending keys are NAMED, and the broken-across-lines values are
    # called out as stray key-less lines
    assert "InpSymbolName" in joined and "EMPTY" in joined
    assert "InpOutFile" in joined
    assert "stray key-less line" in joined
    assert "GOLD1_EURUSD" in joined


def test_validate_preset_names_every_violation_class():
    expected = _intended_preset()
    # missing + unexpected + duplicate + mismatched value + count
    text = ("InpFixtureCsv=Mql5Bot\\gold_import\\gold_fixture.csv\r\n"
            "InpFixtureCsv=twice\r\n"
            "InpBogus=x\r\n"
            "InpSymbolName=GOLD2_EURUSD\r\n")
    v = gs.validate_preset(text, expected)
    joined = "; ".join(v["reasons"])
    assert not v["ok"]
    assert "duplicate key: InpFixtureCsv" in joined
    assert "unexpected key: InpBogus" in joined
    assert "missing key: InpOutFile" in joined
    assert "!= intended" in joined          # GOLD2 vs GOLD1 named
    assert "key count" in joined
    # an INTENDED value that is empty or multi-line is a gate bug, named too
    bad = dict(expected, InpSymbolName="")
    v2 = gs.validate_preset("x=y\r\n", bad)
    assert any("intended value is EMPTY" in r for r in v2["reasons"])
    bad2 = dict(expected, InpOutFile="a\nb")
    v3 = gs.validate_preset("x=y\r\n", bad2)
    assert any("intended value contains CR/LF" in r for r in v3["reasons"])


def test_validate_preset_decide_cli_roundtrips_utf16(tmp_path: Path):
    # the CLI decodes the STAGED UTF-16LE .set (BOM-aware) and fails closed
    # naming the offending key -- exit 1 before any terminal launch
    import subprocess as sp
    import sys
    decide = REPO / "tools" / "owner_gate_decide.py"
    expected = _intended_preset()
    expect_args: list[str] = []
    for k, v in expected.items():
        expect_args += ["--expect", f"{k}={v}"]

    broken = tmp_path / "broken.set"
    broken.write_bytes(
        ("InpFixtureCsv=Mql5Bot\\gold_import\\gold_fixture.csv\r\n"
         "InpManifest=Mql5Bot\\gold_import\\manifest.json\r\n"
         "InpSymbolSpec=Mql5Bot\\broker_exports\\EURUSD.json\r\n"
         "InpSymbolName=\r\nGOLD1_EURUSD\r\n"
         "InpSymbolGroup=Mql5Bot\\gold\r\n"
         "InpOutDir=Mql5Bot\\gold_import_out\r\n"
         "InpOutFile=\r\n"
         "Mql5Bot\\gold_import_out\\GOLD1_EURUSD.json\r\n").encode("utf-16"))
    cp = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                 "validate-preset", str(broken)] + expect_args,
                capture_output=True, text=True, check=False)
    payload = json.loads(cp.stdout)
    assert cp.returncode == 1 and payload["ok"] is False
    assert any("InpSymbolName" in r for r in payload["reasons"])

    good = tmp_path / "good.set"
    good.write_bytes(
        ("\r\n".join(f"{k}={v}" for k, v in expected.items()) + "\r\n")
        .encode("utf-16"))
    cp2 = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                  "validate-preset", str(good)] + expect_args,
                 capture_output=True, text=True, check=False)
    payload2 = json.loads(cp2.stdout)
    assert cp2.returncode == 0 and payload2["ok"] is True


def test_ps1_validates_the_staged_preset_before_launch():
    src = _ps1()
    # the fail-closed validation runs BEFORE the terminal is launched, and the
    # DECODED preset text (UTF-16LE -> readable) is attached to the evidence
    assert "validate-preset" in src
    s4 = src.index("STAGE 4")
    assert src.index("validate-preset", s4) < src.index(
        'Invoke-TerminalScript "Mql5Bot\\Mql5BotImportFixture"', s4)
    assert "_preset_decoded.txt" in src
    assert "preset_invalid" in src


# ---------------------------------------------------------------------------
# STAGE 4 ROUND 5 (A) -- tick-value economics. MT5 docs (looked up, cited in
# docs/DECISIONS.md 2026-09-19): 5307 = ERR_CUSTOM_SYMBOL_PROPERTY_WRONG "An
# invalid custom symbol property"; SYMBOL_TRADE_TICK_VALUE_PROFIT/_LOSS are
# "Calculated tick price for a profitable/losing position" and are NOT
# settable on a custom symbol (the MQL5 book: "When trying to set a read-only
# property, we get the error CUSTOM_SYMBOL_PROPERTY_WRONG (5307)"). The
# importer therefore never calls Set on them; it proves faithfulness by
# READ-BACK: every SET property re-read equal, and the terminal-DERIVED
# _PROFIT/_LOSS equal to the manifest broker values -- refusing on any
# divergence, and the committed classifier fails an unverified success CLOSED.
# ---------------------------------------------------------------------------

def _verified_success_doc() -> dict:
    """A success record carrying the full R5 read-back proof."""
    return {
        "derived_tick_values": {
            "limitation": ("SYMBOL_TRADE_TICK_VALUE_PROFIT/"
                           "SYMBOL_TRADE_TICK_VALUE_LOSS are calculated by "
                           "MT5 and rejected by CustomSymbolSetDouble (5307 "
                           "ERR_CUSTOM_SYMBOL_PROPERTY_WRONG); faithfulness "
                           "is proven by readback equality against the "
                           "manifest broker values, never by setting"),
            "properties": [
                {"enum": "SYMBOL_TRADE_TICK_VALUE_PROFIT",
                 "manifest_value": "1.0000000000", "ok": True,
                 "readback": "1.0000000000", "settable": False,
                 "source": "manifest.broker_spec.tick_value_profit"},
                {"enum": "SYMBOL_TRADE_TICK_VALUE_LOSS",
                 "manifest_value": "1.0000000000", "ok": True,
                 "readback": "1.0000000000", "settable": False,
                 "source": "manifest.broker_spec.tick_value_loss"},
            ],
            "trade_calc_mode": "0",
        },
        "fixture_file_sha256": "a" * 64, "last_error": 0,
        "manifest_dataset_hash": "b" * 64, "n_bars": 500,
        "properties": [], "refused": False, "roundtrip_sha256": "b" * 64,
        "stage": "complete", "symbol": "GOLD1_EURUSD", "timeframe": "H1",
        "verified_properties": [
            {"enum": "SYMBOL_DIGITS", "expected": "5", "ok": True,
             "readback": "5"},
            {"enum": "SYMBOL_TRADE_TICK_VALUE",
             "expected": "1.0000000000", "ok": True,
             "readback": "1.0000000000"},
        ],
    }


def test_stage4_success_without_readback_proof_fails_closed():
    """The R5 pin: a success JSON WITHOUT the read-back proof (the pre-R5
    shape) can never pass -- a skipped property must not pass silently as if
    it were set."""
    doc = _verified_success_doc()
    del doc["verified_properties"]
    del doc["derived_tick_values"]
    v = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                   manifest_hash="b" * 64,
                                   symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_UNVERIFIED
    assert not v["ok"]
    assert "verified_properties" in v["message"]


def test_stage4_diverged_readback_fails_and_names_the_property():
    doc = _verified_success_doc()
    doc["verified_properties"][1]["ok"] = False
    doc["verified_properties"][1]["readback"] = "0.9000000000"
    v = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                   manifest_hash="b" * 64,
                                   symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_UNVERIFIED and not v["ok"]
    assert "SYMBOL_TRADE_TICK_VALUE" in v["message"]


def test_stage4_missing_derived_tick_value_fails_and_names_it():
    doc = _verified_success_doc()
    doc["derived_tick_values"]["properties"] = \
        doc["derived_tick_values"]["properties"][:1]  # drop _LOSS
    v = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                   manifest_hash="b" * 64,
                                   symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_UNVERIFIED
    assert "SYMBOL_TRADE_TICK_VALUE_LOSS" in v["message"]
    assert "5307" in v["message"]


def test_stage4_derived_tick_value_divergence_passes_with_named_limitation():
    """R8 scope decision: a CALCULATED (5307) tick value that does not read
    back equal is a NAMED, SCOPED limitation, NOT a failure — stage 4 PASSES
    (economics are certified by stage-3 broker parity + the OrderCalcProfit
    witness). Never a silent pass: the limitation is named in the message."""
    doc = _verified_success_doc()
    rec = doc["derived_tick_values"]["properties"][1]
    rec["ok"] = False
    rec["available"] = True
    rec["readback"] = "0.8700000000"
    v = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                   manifest_hash="b" * 64,
                                   symbol="GOLD1_EURUSD")
    assert v["case"] == gs.STAGE4_CASE_PASS and v["ok"] is True
    assert v["limited"] is True
    assert "SYMBOL_TRADE_TICK_VALUE_LOSS" in v["message"]
    assert "NAMED, SCOPED limitation" in v["message"]
    assert "stage-3" in v["message"]


def test_stage4_derived_tick_value_zero_readback_passes_gate_run10():
    """gate_run10: the SETTABLE SYMBOL_TRADE_TICK_VALUE read back 1.0, but the
    CALCULATED _PROFIT read back 0.0 (nothing to derive from on a bars-only
    Forex custom symbol). Stage 4 PASSES with the limitation, never blocks."""
    doc = _verified_success_doc()
    prof = doc["derived_tick_values"]["properties"][0]
    prof["ok"] = False
    prof["available"] = False
    prof["readback"] = "0.0000000000"
    doc["derived_tick_values"]["properties"][1]["ok"] = False
    doc["derived_tick_values"]["properties"][1]["available"] = False
    doc["derived_tick_values"]["properties"][1]["readback"] = "0.0000000000"
    v = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                   manifest_hash="b" * 64, symbol="EURUSD.G1")
    assert v["case"] == gs.STAGE4_CASE_PASS and v["ok"] is True
    assert v["limited"] is True
    # the settable properties are still strictly required — flip one and it
    # fails closed even though the derived values are only a limitation
    doc["verified_properties"][1]["ok"] = False
    v2 = gs.classify_stage4_outcome(launched=True, json_present=True, doc=doc,
                                    manifest_hash="b" * 64, symbol="EURUSD.G1")
    assert v2["case"] == gs.STAGE4_CASE_UNVERIFIED and not v2["ok"]


def test_verify_properties_refusal_must_name_the_property():
    # a verify_properties-stage refusal without failed_property is vacuous
    doc = {"error": "read-back diverged", "refused": True, "last_error": 0,
           "stage": "verify_properties", "symbol": "GOLD1_EURUSD"}
    verdict = gs.import_diagnostic_populated(doc)
    assert not verdict["populated"]
    assert "failed_property" in verdict["reason"]
    doc["failed_property"] = "SYMBOL_TRADE_TICK_VALUE_LOSS"
    verdict2 = gs.import_diagnostic_populated(doc)
    assert verdict2["populated"] and verdict2["refused"]


def test_stage4_outcome_decide_cli_fails_unverified_success(tmp_path: Path):
    # end-to-end through the CLI the .ps1 shells to
    import subprocess as sp
    import sys
    doc = _verified_success_doc()
    del doc["verified_properties"]
    result = tmp_path / "GOLD1_EURUSD.json"
    result.write_text(json.dumps(doc), encoding="utf-8")
    decide = REPO / "tools" / "owner_gate_decide.py"
    cp = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                 "stage4-outcome", "--symbol", "GOLD1_EURUSD",
                 "--launched", "true", "--result", str(result),
                 "--manifest-hash", "b" * 64],
                capture_output=True, text=True, check=False)
    payload = json.loads(cp.stdout)
    assert cp.returncode == 1
    assert payload["case"] == gs.STAGE4_CASE_UNVERIFIED

    ok_doc = tmp_path / "OK.json"
    ok_doc.write_text(json.dumps(_verified_success_doc()), encoding="utf-8")
    cp2 = sp.run([sys.executable, str(decide), "--repo", str(REPO),
                  "stage4-outcome", "--symbol", "GOLD1_EURUSD",
                  "--launched", "true", "--result", str(ok_doc),
                  "--manifest-hash", "b" * 64],
                 capture_output=True, text=True, check=False)
    payload2 = json.loads(cp2.stdout)
    assert cp2.returncode == 0
    assert payload2["case"] == gs.STAGE4_CASE_PASS


def test_importer_never_sets_the_calculated_tick_values():
    src = _importer()
    # the two 5307-refused calls are GONE (a call documented to fail must
    # not be issued)...
    assert "SetD(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT" not in src
    assert "SetD(sym, SYMBOL_TRADE_TICK_VALUE_LOSS" not in src
    # ...while the documented-settable SYMBOL_TRADE_TICK_VALUE is still set
    assert 'SetD(sym, SYMBOL_TRADE_TICK_VALUE, "SYMBOL_TRADE_TICK_VALUE"' in src
    # the decision and its doc citations live in the source itself
    assert "ERR_CUSTOM_SYMBOL_PROPERTY_WRONG" in src
    assert "CUSTOM_SYMBOL_PROPERTY_WRONG (5307)" in src


def test_importer_reads_back_every_property_and_refuses_on_divergence():
    src = _importer()
    for helper in ("bool VerI(", "bool VerD(", "bool VerS(",
                   "bool VerDerivedD("):
        assert helper in src, f"importer must define {helper}"
    assert '"verify_properties"' in src
    # read-back runs AFTER the bars are written + symbol selected, and
    # BEFORE the round-trip CopyRates
    assert src.index("SymbolSelect(sym, true)") \
        < src.index("VerI(sym, SYMBOL_DIGITS")
    assert src.index("VerDerivedD(sym, SYMBOL_TRADE_TICK_VALUE_LOSS") \
        < src.index("CopyRates(")
    # the JSON carries the proof the classifier requires
    assert '\\"verified_properties\\":[' in src or \
        '"verified_properties\\":[' in src
    assert "derived_tick_values" in src
    assert "trade_calc_mode" in src
    assert '\\"settable\\":false' in src
    # the derivation basis is recorded, never assumed
    assert "SYMBOL_TRADE_CALC_MODE" in src


def test_importer_derived_verification_covers_both_tick_values():
    src = _importer()
    assert "VerDerivedD(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT" in src
    assert "VerDerivedD(sym, SYMBOL_TRADE_TICK_VALUE_LOSS" in src


def test_importer_derived_tick_values_are_scoped_not_a_refusal_r8():
    """R8: the CALCULATED tick values are recorded (available/ok per property)
    with a bounded, Sleep-free retry AFTER selection + bars, but NEVER refuse
    stage 4 — a bars-only Forex custom symbol reads them back 0 legitimately,
    and economics are certified by stage 3."""
    src = _importer()
    # the retry nudges a lazy recompute without Sleep
    assert "SymbolInfoTick(sym, tick)" in src
    assert "attempt<32" in src
    # the derived read-back records availability + the scope, and does NOT feed
    # the refusal path (no MarkVerifyFail in the derived helper)
    assert '\\"available\\":' in src
    assert "authoritative" in src
    assert "NAMED, SCOPED limitation" in src
    # the old economics refusal is gone
    assert "would NOT reproduce broker" not in src
    # Sleep is still never used anywhere in the importer
    assert "Sleep(" not in src


# ---------------------------------------------------------------------------
# STAGE 4 ROUND 5 (B) -- the gate crashed VERDICTLESS: Start-Process at
# Invoke-Decide refused an -ArgumentList carrying the EMPTY $logExcerptPath
# ("Cannot validate argument on parameter 'ArgumentList'"), exit 1 with no
# stage_4.json, no gate_summary.json, no GATE_RESULT= line. Fixes pinned
# here: (1) --log-excerpt only appended when non-empty, (2) Invoke-Decide
# passes empty elements as literal quoted strings, (3) a STRUCTURAL
# always-a-verdict contract: Enter-Stage tracking + a script-scope trap that
# records the in-progress stage as FAIL, writes the summary and prints
# GATE_RESULT= on ANY unhandled error. The trap contract is exercised for
# real (fault injection) when a PowerShell host is available.
# ---------------------------------------------------------------------------

def _pwsh() -> str | None:
    import shutil
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if exe:
        return exe
    cand = Path.home() / ".dotnet" / "tools" / "pwsh"
    return str(cand) if cand.is_file() else None


def test_ps1_stage4_outcome_never_passes_an_empty_log_excerpt():
    src = _ps1()
    assert 'if ($logExcerptPath) { $ocArgs += @("--log-excerpt", $logExcerptPath) }' in src
    # the old unconditional form (the R5 crash) is gone
    assert '"--log-excerpt", $logExcerptPath)\n' not in src


def test_ps1_invoke_decide_sanitizes_empty_argumentlist_elements():
    src = _ps1()
    fn = src[src.index("function Invoke-Decide"):]
    fn = fn[:fn.index("\n}")]
    assert "'\"\"'" in fn, \
        "Invoke-Decide must pass empty elements as a literal quoted string"
    assert "Cannot validate argument" in fn  # names the root cause it closes


def test_ps1_structural_verdict_contract_is_present():
    src = _ps1()
    assert "\ntrap {" in src
    # every stage boundary updates the tracker the trap reports
    for num, name in [(0, "self_protection"), (1, "strict_compile"),
                      (2, "dsl_parity"), (3, "broker_parity"),
                      (4, "fixture_import"), (5, "tester_legs"),
                      (8, "reconciliation"), (9, "archive_manifest"),
                      (10, "certify")]:
        assert f'Enter-Stage {num} "{name}"' in src, \
            f"stage {num} must Enter-Stage before its work"
    t = src.index("\ntrap {")
    body = src[t:src.index("\n}", t)]
    # the trap records the in-progress stage, finishes the gate, and still
    # prints the verdict line even if the evidence dir itself is broken
    assert "Record-Stage" in body and "Finish-Gate" in body
    assert "UNHANDLED_ERROR" in body
    assert "GATE_RESULT=" in body
    assert "MQL5BOT_GATE_FAULT" in src  # the injection hook the test uses


def test_gate_crash_mid_stage_still_emits_stage_summary_and_verdict(
        tmp_path: Path):
    """NON-VACUOUS (executes owner_gate.ps1): inject an unhandled throw at a
    stage boundary and assert the gate STILL writes the stage record, the
    summary, and prints GATE_RESULT= -- the exact contract gate_run7 broke."""
    import os
    import subprocess as sp
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "owner_gate.ps1").write_bytes(
        (REPO / "tools" / "owner_gate.ps1").read_bytes())
    env = dict(os.environ, MQL5BOT_GATE_FAULT="self_protection")
    cp = sp.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(tools / "owner_gate.ps1")],
                capture_output=True, text=True, env=env,
                cwd=str(tmp_path), check=False)
    assert cp.returncode == 1, cp.stderr
    assert "GATE_RESULT=self_protection" in cp.stdout
    stage0 = list(tmp_path.rglob("stage_0.json"))
    assert stage0, "the in-progress stage record must still be written"
    rec = json.loads(stage0[0].read_text(encoding="ascii"))
    assert rec["status"] == "FAIL"
    assert "FAULT_INJECTION" in rec["reason"]
    assert "UNHANDLED_ERROR" in rec["reason"]
    summaries = list(tmp_path.rglob("gate_summary.json"))
    assert summaries, "gate_summary.json must still be written"
    summary = json.loads(summaries[0].read_text(encoding="ascii"))
    assert summary["gate_result"] == "self_protection"
    assert summary["first_blocking"] == "self_protection"


def test_invoke_decide_survives_an_empty_argument(tmp_path: Path):
    """NON-VACUOUS (executes the .ps1's own Invoke-Decide): the exact R5
    crash input -- an ArgumentList element that is "" -- must reach the child
    process instead of killing Start-Process."""
    import subprocess as sp
    import sys
    pwsh = _pwsh()
    if not pwsh:
        pytest.skip("no PowerShell host on this machine")
    src = _ps1()
    start = src.index("function Invoke-Decide")
    fn = src[start:src.index("\n}", start) + 2]
    stub = tmp_path / "argecho.py"
    stub.write_text("import json, sys\n"
                    "print(json.dumps({'argv': sys.argv[1:]}))\n",
                    encoding="ascii")
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        '$ErrorActionPreference = "Stop"\n'
        "$Evidence = '" + str(tmp_path) + "'\n"
        "$Python = '" + sys.executable + "'\n"
        "$Decide = '" + str(stub) + "'\n"
        "$RepoRoot = '" + str(tmp_path) + "'\n"
        + fn + "\n"
        '$r = Invoke-Decide @("stage4-outcome", "--log-excerpt", "")\n'
        'if (-not $r.data) { Write-Host "NO_DATA"; exit 3 }\n'
        'Write-Host ("ARGC=" + $r.data.argv.Count)\n'
        "exit 0\n", encoding="ascii")
    cp = sp.run([pwsh, "-NoProfile", "-File", str(driver)],
                capture_output=True, text=True, check=False)
    # pre-R5 this died inside Start-Process with "Cannot validate argument"
    assert cp.returncode == 0, cp.stderr
    # --repo <root> stage4-outcome --log-excerpt <empty> = 5 arguments
    assert "ARGC=5" in cp.stdout
