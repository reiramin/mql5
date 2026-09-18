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
# tools/owner_gate.ps1 -- stage 4 attaches the diagnostic on pass OR fail
# ---------------------------------------------------------------------------

def test_ps1_stage4_delegates_import_diagnostic_and_attaches_on_pass_or_fail():
    src = _ps1()
    # the diagnostic classification is delegated to committed Python
    assert "import-diagnostic" in src
    # the importer result is attached to stage_4 before the pass/fail branch
    assert "$stage4art.Add((New-Artifact $resCopy))" in src
    # a missing output JSON is now RECORDED, never a silent break
    assert "importer produced no output JSON" in src
    # a PASS whose diagnostic is not populated fails closed (regression guard)
    assert "import diagnostic not populated" in src
