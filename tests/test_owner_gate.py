"""Owner-evidence intake red team (FINAL REALITY GATE §24/§25).

These tests exercise the evidence CONSUMER with synthetic packages.
A green test here proves the verifier fails closed — it is NOT MT5
evidence and never a certification claim.

Every attack must fail closed with an explainable state/verdict:
missing, stale, wrong, partial or simulated evidence can never become
a positive verdict.
"""

from __future__ import annotations

import json
import os

import pytest
from mql5bot import owner_gate as og

FROZEN_COMMIT = "a" * 40
FROZEN = {
    "source": {"commit": FROZEN_COMMIT},
    "gold_1": {"fixture_sha256": "f1" * 32, "config_hash": "c1" * 32,
               "dataset_hash_from_manifest": "d1" * 32},
    "gold_2": {"fixture_sha256": "f2" * 32, "config_hash": "c2" * 32,
               "dataset_hash_from_manifest": "d2" * 32,
               "provenance_label": "GOLD_2_RECONSTRUCTED_NEW_PROVENANCE"},
    "symbolspec_expectations": {"point": 1e-05, "volume_min": 0.01,
                                "contract_size": 100000},
}


def _w(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        content = json.dumps(content, indent=2)
    path.write_text(content, encoding="utf-8")


def _build_manifest(root):
    """Bind EVERY file in the evidence root by SHA-256 (the manifest
    itself excluded — it cannot bind its own bytes)."""
    import hashlib as _h
    arts = {}
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.name != "archive_manifest.json":
            arts[str(f.relative_to(root)).replace("\\", "/")] = \
                _h.sha256(f.read_bytes()).hexdigest()
    return {"artifacts": arts,
            "identity": {
                "source_commit": FROZEN_COMMIT,
                "gold1_fixture_sha256":
                    FROZEN["gold_1"]["fixture_sha256"],
                "gold2_fixture_sha256":
                    FROZEN["gold_2"]["fixture_sha256"]}}


def build_package(root, *, diverge_gold2=None, coverage="FULL",
                  skip=(), source_commit=FROZEN_COMMIT,
                  ex5_stale=False, log_stale=False, model_wrong=False):
    """Build a synthetic owner package. Divergence/wrongness hooks let
    each attack mutate exactly one thing."""
    root = root if hasattr(root, "mkdir") else __import__("pathlib").Path(root)
    ex5_bytes = b"\x00EX5-FRESH-BINARY" if not ex5_stale else b"OLD-BINARY"
    # the FRESH log is what the metadata binds; a stale attack swaps the
    # bytes on disk so the recorded hash no longer matches
    _fresh_log = ("Mql5Bot.mq5 - 0 error(s), 0 warning(s)\n"
                  "compile ok\n")
    ex5 = root / "compile" / "Mql5Bot.ex5"
    log = root / "compile" / "compile.log"
    if "compile" not in skip:
        ex5.parent.mkdir(parents=True, exist_ok=True)
        ex5.write_bytes(ex5_bytes)
        if log_stale:
            log.write_text("STALE LOG FROM AN ATTEMPT LONG AGO\n",
                           encoding="utf-8")
        else:
            log.write_text(_fresh_log, encoding="utf-8")
        import hashlib
        from datetime import datetime, timezone
        _w(root / "compile" / "compile_metadata.json", {
            "SOURCE_COMMIT": source_commit,
            "COMPILER_VERSION": "MetaEditor 5 build 9999",
            "TERMINAL_BUILD": "MT5 build 9999",
            "EX5_SHA256": hashlib.sha256(
                b"\x00EX5-FRESH-BINARY").hexdigest(),
            "COMPILE_TIMESTAMP": datetime.now(timezone.utc).isoformat(),
            "COMPILER_LOG_SHA256": hashlib.sha256(
                _fresh_log.encode()).hexdigest(),
            "ERRORS": 0, "WARNINGS": 0,
        })
    if ex5_stale:
        # keep the EX5 file but predate it vs the compile timestamp
        ex5.parent.mkdir(parents=True, exist_ok=True)
        ex5.write_bytes(b"OLD-BINARY")
        os.utime(ex5, (1000000000, 1000000000))

    import hashlib as _hl
    spec_text = None
    if "symbolspec" not in skip:
        spec = {
            "broker": "DemoBroker", "server": "Demo-Live", "symbol":
            "EURUSD", "point": 1e-05, "tick_size": 1e-05,
            "tick_value_profit": 10.0, "contract_size": 100000,
            "volume_min": 0.01, "volume_max": 100.0,
            "volume_step": 0.01, "volume_limit": 0.0,
            "stops_level_points": 10, "freeze_level_points": 0,
            "trade_mode": 4, "filling_mode_mask": 3,
            "expiration_mode_mask": 15, "currency_profit": "USD",
            "timestamp": "2026-09-08T12:05:00+00:00",
            "terminal_build": "9999",
        }
        spec_text = json.dumps(spec, indent=2)
        _w(root / "symbolspec" / "symbolspec.json", spec_text)

    models = {"m1_ohlc": 1, "every_tick": 0, "real_ticks": 3}
    ex5_hash = _hl.sha256(b"\x00EX5-FRESH-BINARY").hexdigest()
    spec_hash = (_hl.sha256(spec_text.encode()).hexdigest()
                 if spec_text else "00" * 32)
    for gold in ("gold1", "gold2"):
        # write raw + parsed reports FIRST so reconciliation can bind
        # their real hashes — no downstream record may conceal tampering
        parsed_hashes = {}
        raw_hashes = {}
        for m, mid in models.items():
            if f"raw_{gold}_{m}" not in skip:
                raw_text = ("<table><tr><td>Symbol</td>"
                            "<td>EURUSD</td></tr></table>")
                _w(root / gold / f"{m}.htm", raw_text)
                raw_hashes[m] = _hl.sha256(raw_text.encode()).hexdigest()
                parsed_text = json.dumps(
                    {"settings": {"symbol": "EURUSD",
                                  "model": og.MODEL_LABELS[mid]}},
                    indent=2)
                _w(root / "parsed" / f"{gold}_{m}.json", parsed_text)
                parsed_hashes[m] = _hl.sha256(
                    parsed_text.encode()).hexdigest()
        bindings = {
            "source_commit": FROZEN_COMMIT,
            "fixture_sha256": FROZEN[f"gold_{gold[-1]}"]["fixture_sha256"],
            "config_hash": FROZEN[f"gold_{gold[-1]}"]["config_hash"],
            "dataset_hash": FROZEN[f"gold_{gold[-1]}"]
            ["dataset_hash_from_manifest"],
            "symbolspec_sha256": spec_hash,
            "ex5_sha256": ex5_hash,
            "raw_report_hashes": raw_hashes,
            "parsed_report_hashes": parsed_hashes,
            "tester_models": {
                m: {"requested": mid,
                    "report_reported": og.MODEL_LABELS[mid],
                    "journal": og.MODEL_LABELS[mid]}
                for m, mid in models.items()},
        }
        if model_wrong and gold == "gold2":
            bindings["tester_models"]["real_ticks"]["report_reported"] = \
                "Every tick"  # terminal actually ran a different model
        events = [
            {"index": i, "bar": 10 + i, "time": f"2026-01-01 08:{i:02d}",
             "symbol": "EURUSD",
             "fields": {
                 "signal": {"python": 1, "mt5": 1, "status": "MATCH"},
                 "volume": {"python": 0.1, "mt5": 0.1, "status": "MATCH"},
                 "sl": {"python": 1.05, "mt5": 1.05, "status": "MATCH"},
             }} for i in range(56)]
        if diverge_gold2 and gold == "gold2":
            field, py_v, mt5_v = diverge_gold2
            events[3]["fields"][field] = {"python": py_v, "mt5": mt5_v,
                                          "status": "DIVERGENT"}
        if f"reconciliation_{gold}" not in skip and "reconciliation" \
                not in skip:
            _w(root / "reconciliation" / f"{gold}.json",
               {"gold": gold, "bindings": bindings, "events": events})

    # ---- real-tick evidence: a REAL journal file, bound by path+sha256
    journal_rel = "real_ticks_journal.log"
    interval = "2026-01-01..2026-01-04"
    journal_text = (
        "tester: model = Every tick based on real ticks\n"
        "symbol EURUSD real ticks loaded from broker history\n"
        "2026-01-01 .. 2026-01-04 interval fully covered by real ticks\n"
        "no generated-tick fallback recorded\n")
    _w(root / journal_rel, journal_text)
    cov = {
        "leg": "gold2:real_ticks",
        "requested_model": "Every tick based on real ticks",
        "actual_model_from_report": "Every tick based on real ticks",
        "terminal_model_identifier": "model 3",
        "requested_interval": interval,
        "actual_interval": interval,
        "broker": "DemoBroker", "symbol": "EURUSD",
        "real_tick_availability_evidence": {
            "path": journal_rel,
            "sha256": _hl.sha256(journal_text.encode()).hexdigest(),
        },
        "coverage": ("REAL_TICK_COVERAGE_FULL" if coverage == "FULL"
                     else f"REAL_TICK_COVERAGE_{coverage}"),
        "fallback_intervals": [],
        "tester_build": "9999", "terminal_build": "9999",
        "notes": "synthetic self-test record",
    }
    if coverage != "FULL":
        cov["real_tick_availability_evidence"] = {"path": "", "sha256": ""}
    if "real_tick_coverage" not in skip:
        _w(root / "real_tick_coverage.json", cov)

    # ---- safety evidence: one REAL artifact per test, bound by hash
    for name in og.SAFETY_TESTS + ("netting", "hedging"):
        if name in skip or "safety" in skip:
            continue
        ev_rel = f"safety/evidence_{name}.log"
        ev_text = (f"{name} runtime exercise on DemoBroker Demo-Live\n"
                   "journal excerpt + state transition captured\n")
        _w(root / ev_rel, ev_text)
        _w(root / "safety" / f"{name}.json", {
            "action": f"{name} procedure executed on demo",
            "initial_state": "documented",
            "resulting_state": "documented",
            "observed_result": "pass per procedure",
            "raw_evidence": {
                "path": ev_rel,
                "sha256": _hl.sha256(ev_text.encode()).hexdigest(),
            },
        })

    if "environment" not in skip:
        _w(root / "environment.json", {
            "os": "Windows 11", "terminal_build": "9999",
            "broker": "DemoBroker", "server": "Demo-Live",
            "account_mode": "hedging", "symbol": "EURUSD",
            "timezone": "UTC", "run_timestamp":
                "2026-09-08T12:30:00+00:00"})
    if "archive_manifest" not in skip:
        _w(root / "archive_manifest.json", _build_manifest(root))
    return root
    return root


def gate(root):
    return og.run_gate(root, FROZEN)


# ---------------------------------------------------------------------------
# happy path: a complete, consistent package reaches the ceiling verdict
# ---------------------------------------------------------------------------


def test_complete_valid_package_reaches_mt5_validated(tmp_path):
    report = gate(build_package(tmp_path))
    assert report["verdict"] == og.MT5_VALIDATED
    assert report["gold"]["gold1"]["result"] == "MATCH"
    assert report["gold"]["gold2"]["result"] == "MATCH"
    assert report["first_divergence"] == {"gold1": None, "gold2": None}


# ---------------------------------------------------------------------------
# §24 stale-artifact attack battery — all fail closed
# ---------------------------------------------------------------------------


def test_stale_ex5_fails_closed(tmp_path):
    report = gate(build_package(tmp_path, ex5_stale=True))
    assert report["compile"]["state"] in (og.MISMATCHED, og.STALE)
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_stale_compile_log_fails_closed(tmp_path):
    report = gate(build_package(tmp_path, log_stale=True))
    assert report["compile"]["checks"]["log_hash"] == og.MISMATCHED
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_wrong_source_commit_fails_closed(tmp_path):
    report = gate(build_package(tmp_path, source_commit="b" * 40))
    assert report["compile"]["checks"]["source_commit"] == og.MISMATCHED
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_model_identity_mismatch_fails_closed(tmp_path):
    report = gate(build_package(tmp_path, model_wrong=True))
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH
    assert any("MODEL_IDENTITY_MISMATCH" in r
               for r in report["reasons"])


def test_reconciliation_binding_mismatch_fails_closed(tmp_path):
    root = build_package(tmp_path)
    doc = json.loads((root / "reconciliation" / "gold2.json").read_text())
    doc["bindings"]["fixture_sha256"] = "99" * 32  # wrong fixture identity
    (root / "reconciliation" / "gold2.json").write_text(json.dumps(doc))
    report = gate(root)
    assert report["gold"]["gold2"]["state"] == og.MISMATCHED
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_symbolspec_missing_field_fails_closed(tmp_path):
    root = build_package(tmp_path)
    doc = json.loads((root / "symbolspec" / "symbolspec.json").read_text())
    del doc["volume_step"]
    (root / "symbolspec" / "symbolspec.json").write_text(json.dumps(doc))
    report = gate(root)
    assert report["symbolspec"]["state"] == og.INVALID
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_symbolspec_decision_changing_mismatch_stops(tmp_path):
    root = build_package(tmp_path)
    doc = json.loads((root / "symbolspec" / "symbolspec.json").read_text())
    doc["point"] = 1e-04  # decision-changing vs frozen 1e-05
    (root / "symbolspec" / "symbolspec.json").write_text(json.dumps(doc))
    report = gate(root)
    assert report["symbolspec"]["state"] == og.MISMATCHED
    assert any("DECISION_CHANGING_MISMATCH" in r
               for r in report["symbolspec"]["reasons"])
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_edited_report_parse_garbage_is_not_evidence(tmp_path):
    root = build_package(tmp_path)
    _w(root / "parsed" / "gold1_m1_ohlc.json", "{not json")
    # a broken parsed report does not silently pass: the artifact scan
    # keeps it PRESENT_UNVERIFIED and reconciliation identity (report
    # binding) is the proof path — gate stays non-positive without the
    # full chain
    report = gate(root)
    assert report["verdict"] != og.VERIFIED


# ---------------------------------------------------------------------------
# §25 partial packages — never VERIFIED, precise missing reasons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skip", [
    ("hedging",),             # every single missing slot counts
    ("symbolspec",),
    ("reconciliation",),
    ("safety",),
    ("real_tick_coverage",),
    ("netting",),
    ("environment",),
])
def test_partial_packages_never_verify(tmp_path_factory, skip):
    root = tmp_path_factory.mktemp("pkg")
    report = gate(build_package(root, skip=skip))
    assert report["verdict"] not in og.POSITIVE_VERDICTS
    assert report["reasons"], "verdict must carry exact reasons"


def test_compile_only_package_reports_missing(tmp_path):
    root = build_package(tmp_path, skip=(
        "symbolspec", "reconciliation", "safety", "real_tick_coverage",
        "netting", "hedging", "environment", "archive_manifest"))
    report = gate(root)
    assert report["verdict"] in (og.NOT_VERIFIED_RECONCILIATION_MISSING,
                                 og.NOT_VERIFIED_MISSING_MT5_EVIDENCE)
    assert any("missing artifacts" in r for r in report["reasons"])


# ---------------------------------------------------------------------------
# §11 real-tick coverage — selection is not proof, UNKNOWN never promotes
# ---------------------------------------------------------------------------


def test_unknown_coverage_constrains_the_verdict(tmp_path):
    report = gate(build_package(tmp_path, coverage="UNKNOWN"))
    assert report["verdict"] == og.NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN


def test_partial_coverage_stays_limited(tmp_path):
    report = gate(build_package(tmp_path, coverage="PARTIAL"))
    assert report["verdict"] == og.NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN
    assert report["real_tick_coverage"]["coverage"] == \
        "REAL_TICK_COVERAGE_PARTIAL"


def test_full_coverage_without_evidence_is_rejected(tmp_path):
    root = build_package(tmp_path)
    doc = json.loads((root / "real_tick_coverage.json").read_text())
    doc["real_tick_availability_evidence"] = ""  # claim FULL, no proof
    (root / "real_tick_coverage.json").write_text(json.dumps(doc))
    report = gate(root)
    assert report["real_tick_coverage"]["state"] == og.INVALID
    assert report["verdict"] != og.MT5_VALIDATED


# ---------------------------------------------------------------------------
# §14/§15 first divergence + deterministic classification
# ---------------------------------------------------------------------------


def test_first_divergence_is_found_and_classified(tmp_path):
    report = gate(build_package(tmp_path,
                                diverge_gold2=("sl", 1.05, 1.06)))
    div = report["gold"]["gold2"]["first_divergence"]
    assert div is not None
    assert div["event_index"] == 3
    assert div["first_divergent_field"] == "sl"
    assert div["classification"] == og.ROUNDING_MISMATCH
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_first_divergence_earliest_event_wins(tmp_path):
    root = build_package(tmp_path)
    doc = json.loads((root / "reconciliation" / "gold2.json").read_text())
    doc["events"][9]["fields"]["signal"] = {"python": 1, "mt5": 0,
                                            "status": "DIVERGENT"}
    doc["events"][2]["fields"]["volume"] = {"python": 0.1, "mt5": 0.2,
                                            "status": "DIVERGENT"}
    (root / "reconciliation" / "gold2.json").write_text(json.dumps(doc))
    div = og.run_gate(root, FROZEN)["gold"]["gold2"]["first_divergence"]
    assert div["event_index"] == 2
    assert div["classification"] == og.SIZING_MISMATCH


def test_classification_is_deterministic_and_closed():
    assert og.classify_field("signal") == og.SIGNAL_MISMATCH
    assert og.classify_field("indicator_rsi") == og.INDICATOR_MISMATCH
    assert og.classify_field("session_state") == og.SESSION_MISMATCH
    assert og.classify_field("meta_weight") == og.META_MISMATCH
    assert og.classify_field("risk_veto") == og.RISK_MISMATCH
    assert og.classify_field("exit_reason") == og.EXECUTION_MISMATCH
    assert og.classify_field("timestamp") == og.TIMESTAMP_MISMATCH
    assert og.classify_field("position_identifier") == og.STATE_MISMATCH
    assert og.classify_field("broker_point") == og.BROKER_SPEC_MISMATCH
    assert og.classify_field("close") == og.DATA_MISMATCH
    assert og.classify_field("something_unmapped") == og.UNKNOWN
    assert og.UNKNOWN in og.TAXONOMY and len(og.TAXONOMY) == 14


# ---------------------------------------------------------------------------
# §20 safety evidence discipline
# ---------------------------------------------------------------------------


def test_screenshot_only_safety_evidence_is_invalid(tmp_path):
    root = build_package(tmp_path)
    _w(root / "safety" / "kill_switch.json", {
        "action": "latched", "initial_state": "flat",
        "resulting_state": "latched", "observed_result": "pass",
        "raw_evidence": "screenshot.png"})
    report = gate(root)
    assert report["safety"]["kill_switch"]["state"] == og.INVALID
    assert report["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_hedging_may_be_blocked_but_nothing_else(tmp_path):
    root = build_package(tmp_path)
    _w(root / "safety" / "hedging.json",
       {"blocked_owner_environment": True,
        "reason": "netting-only account"})
    report = gate(root)
    assert report["safety"]["hedging"]["result"] == \
        "BLOCKED_OWNER_ENVIRONMENT"
    _w(root / "safety" / "kill_switch.json",
       {"blocked_owner_environment": True})
    report = gate(root)
    assert report["safety"]["kill_switch"]["state"] == og.INVALID


# ---------------------------------------------------------------------------
# §5 freeze-anchor change classification + §7 states + no-gold-upgrade
# ---------------------------------------------------------------------------


def test_anchor_change_classification():
    cls = og.classify_anchor_changes(
        ["docs/NOTE.md", "python/mql5bot/engine.py", "README.md"])
    assert cls["execution_relevant"] == ["python/mql5bot/engine.py"]
    assert cls["golds_still_frozen"] is False
    cls = og.classify_anchor_changes(["docs/NOTE.md", "HANDOFF.md"])
    assert cls["execution_relevant"] == []
    assert cls["golds_still_frozen"] is True


def test_validity_states_are_never_booleans():
    assert len(og.ARTIFACT_STATES) == 7
    assert og.PENDING_OWNER in og.ARTIFACT_STATES
    assert og.STALE in og.ARTIFACT_STATES


def test_gold_semantic_pass_never_upgrades_here():
    # a package with NO mt5 artifacts at all can never be positive —
    # gold fixtures alone are not runtime evidence
    report = og.run_gate("/nonexistent-dir", FROZEN)
    assert report["verdict"] == og.NOT_VERIFIED_MISSING_MT5_EVIDENCE
    assert report["verdict"] not in og.POSITIVE_VERDICTS


def test_scan_flags_ambiguous_directory_artifact(tmp_path):
    root = build_package(tmp_path)
    (root / "symbolspec" / "symbolspec.json").unlink()
    (root / "symbolspec" / "symbolspec.json").mkdir()  # dir, not file
    scan = og.scan_package(root)
    assert scan["symbolspec"]["state"] == og.INVALID


# ---------------------------------------------------------------------------
# §7 leave-one-out completeness — EVERY mandatory artifact, one at a time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(og.LAYOUT))
def test_leave_one_out_never_verifies(tmp_path_factory, key):
    root = tmp_path_factory.mktemp("loo")
    build_package(root)
    target = root / og.LAYOUT[key]
    if target.is_file():
        target.unlink()
    report = gate(root)
    assert report["verdict"] not in og.POSITIVE_VERDICTS, key
    assert any(key in r or og.LAYOUT[key] in r
               for r in report["reasons"]), \
        f"{key}: reasons must name the missing artifact"


def test_multiple_missing_all_reasons_visible(tmp_path):
    root = build_package(tmp_path)
    for key in ("ex5", "symbolspec", "netting", "environment"):
        (root / og.LAYOUT[key]).unlink()
    report = gate(root)
    joined = " ".join(report["reasons"])
    for key in ("ex5", "symbolspec", "netting", "environment"):
        assert key in joined, f"{key} missing-reason lost"


# ---------------------------------------------------------------------------
# §9 hash-chain attacks — ONE BYTE of tampering breaks the leg
# ---------------------------------------------------------------------------


def _flip(path):
    b = bytearray(path.read_bytes())
    b[-1] ^= 0x01
    path.write_bytes(bytes(b))


@pytest.mark.parametrize("rel", [
    og.LAYOUT["ex5"],
    og.LAYOUT["symbolspec"],
    og.LAYOUT["parsed_gold1_m1_ohlc"],
    og.LAYOUT["parsed_gold2_real_ticks"],
])
def test_one_byte_tamper_breaks_identity_chain(tmp_path_factory, rel):
    root = tmp_path_factory.mktemp("tamper")
    build_package(root)
    _flip(root / rel)
    report = gate(root)
    assert report["verdict"] not in og.POSITIVE_VERDICTS, rel


# ---------------------------------------------------------------------------
# §10 time / freshness attacks
# ---------------------------------------------------------------------------


def test_future_compile_timestamp_is_impossible(tmp_path):
    from datetime import datetime, timedelta, timezone
    root = build_package(tmp_path)
    meta = root / og.LAYOUT["compile_metadata"]
    doc = json.loads(meta.read_text())
    doc["COMPILE_TIMESTAMP"] = (datetime.now(timezone.utc)
                                + timedelta(days=10)).isoformat()
    meta.write_text(json.dumps(doc))
    report = gate(root)
    assert report["compile"]["checks"]["freshness"] == og.INVALID
    assert report["verdict"] not in og.POSITIVE_VERDICTS


def test_timezone_offset_same_instant_is_accepted(tmp_path):
    from datetime import datetime, timedelta, timezone
    root = build_package(tmp_path)
    meta = root / og.LAYOUT["compile_metadata"]
    doc = json.loads(meta.read_text())
    utc_now = datetime.now(timezone.utc)
    tehran = timezone(timedelta(hours=3, minutes=30))
    doc["COMPILE_TIMESTAMP"] = utc_now.astimezone(tehran).isoformat()
    meta.write_text(json.dumps(doc))
    # metadata bytes changed, so re-bind the archive manifest to keep the
    # (otherwise valid) package internally consistent
    _w(root / "archive_manifest.json", _build_manifest(root))
    report = gate(root)
    assert report["compile"]["checks"]["freshness"] == "VALID"
    assert report["verdict"] == og.MT5_VALIDATED


def test_stale_mtime_cannot_hide_behind_correct_hash(tmp_path):
    # copied artifact with preserved (old) timestamps: the hash is right
    # but the filesystem time predates the compile — freshness is a
    # separate, filesystem-based guarantee and must still fail closed
    root = build_package(tmp_path)
    ex5 = root / og.LAYOUT["ex5"]
    os.utime(ex5, (1000000000, 1000000000))
    report = gate(root)
    assert report["compile"]["checks"]["freshness"] == og.STALE
    assert report["verdict"] not in og.POSITIVE_VERDICTS


# ---------------------------------------------------------------------------
# §11 tester-model triad — attack each pair independently
# ---------------------------------------------------------------------------


def _triad(requested=3, reported=None, journal=None):
    reported = "Every tick based on real ticks" if reported is None \
        else reported
    triad = {"requested": requested, "report_reported": reported}
    if journal is not None:
        triad["journal"] = journal
    return triad


def test_model_triad_requested_vs_reported():
    assert og.verify_model_identity(
        _triad(reported="Every tick"))["state"] == og.MISMATCHED


def test_model_triad_requested_vs_journal():
    assert og.verify_model_identity(_triad(
        journal="1 minute OHLC"))["state"] == og.MISMATCHED


def test_model_triad_reported_and_journal_both_wrong():
    assert og.verify_model_identity(_triad(
        reported="Every tick", journal="Open prices only"))["state"] == \
        og.MISMATCHED


def test_model_cli_selection_alone_never_trusted():
    # requested present but no report-confirmed model: identity unproven
    assert og.verify_model_identity(
        {"requested": 3})["state"] == og.INVALID


# ---------------------------------------------------------------------------
# §12 real-tick coverage attacks
# ---------------------------------------------------------------------------


def _mutate_cov(root, **kw):
    path = root / og.LAYOUT["real_tick_coverage"]
    doc = json.loads(path.read_text())
    doc.update(kw)
    path.write_text(json.dumps(doc))
    return root


def test_coverage_wrong_symbol(tmp_path):
    root = _mutate_cov(build_package(tmp_path), symbol="XAUUSD")
    assert gate(root)["real_tick_coverage"]["state"] == og.MISMATCHED


def test_coverage_wrong_broker(tmp_path):
    root = _mutate_cov(build_package(tmp_path), broker="OtherBroker")
    assert gate(root)["real_tick_coverage"]["state"] == og.MISMATCHED


def test_coverage_actual_model_differs_from_requested(tmp_path):
    root = _mutate_cov(build_package(tmp_path),
                       actual_model_from_report="Every tick")
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.MISMATCHED
    assert "silent fallback" in rep["reasons"][0]


def test_coverage_full_with_prose_evidence(tmp_path):
    root = _mutate_cov(build_package(tmp_path),
                       real_tick_availability_evidence="looks complete")
    assert gate(root)["real_tick_coverage"]["state"] == og.INVALID


def test_coverage_full_with_interval_mismatch(tmp_path):
    root = _mutate_cov(build_package(tmp_path),
                       actual_interval="2026-01-02..2026-01-04")
    assert gate(root)["real_tick_coverage"]["state"] == og.INVALID


def test_mode_selection_alone_never_full(tmp_path):
    root = build_package(tmp_path)
    path = root / og.LAYOUT["real_tick_coverage"]
    doc = json.loads(path.read_text())
    doc["real_tick_availability_evidence"] = ""
    doc["coverage"] = "REAL_TICK_COVERAGE_FULL"
    path.write_text(json.dumps(doc))
    assert gate(root)["verdict"] != og.MT5_VALIDATED


# ---------------------------------------------------------------------------
# §14/§15 taxonomy — one known discrepancy per class, owner overrides
# ---------------------------------------------------------------------------

_CLASS_FIELDS = [
    ("signal", og.SIGNAL_MISMATCH),
    ("indicator_rsi", og.INDICATOR_MISMATCH),
    ("warmup", og.WARMUP_MISMATCH),
    ("session", og.SESSION_MISMATCH),
    ("volume", og.SIZING_MISMATCH),
    ("sl", og.ROUNDING_MISMATCH),
    ("meta_weight", og.META_MISMATCH),
    ("risk_veto", og.RISK_MISMATCH),
    ("exit_reason", og.EXECUTION_MISMATCH),
    ("close", og.DATA_MISMATCH),
    ("timestamp", og.TIMESTAMP_MISMATCH),
    ("state", og.STATE_MISMATCH),
    ("broker_point", og.BROKER_SPEC_MISMATCH),
    ("completely_unmapped", og.UNKNOWN),
]


@pytest.mark.parametrize("field,cls", _CLASS_FIELDS)
def test_each_class_deterministically(tmp_path_factory, field, cls):
    root = tmp_path_factory.mktemp("tax")
    report = gate(build_package(root, diverge_gold2=(field, 1, 2)))
    div = report["gold"]["gold2"]["first_divergence"]
    assert div["classification"] == cls, field
    assert div["classification"] in og.TAXONOMY


def test_owner_declared_class_cannot_override_machine(tmp_path):
    root = build_package(tmp_path)
    doc = json.loads((root / "reconciliation" / "gold2.json").read_text())
    doc["events"][4]["fields"]["sl"] = {
        "python": 1.05, "mt5": 1.06, "status": "DIVERGENT",
        "class": "SIGNAL_MISMATCH",  # owner tries to steer the class
    }
    (root / "reconciliation" / "gold2.json").write_text(json.dumps(doc))
    div = og.run_gate(root, FROZEN)["gold"]["gold2"]["first_divergence"]
    assert div["classification"] == og.ROUNDING_MISMATCH


# ---------------------------------------------------------------------------
# §19 safety prose-only evidence
# ---------------------------------------------------------------------------


def test_prose_only_safety_evidence_fails(tmp_path):
    root = build_package(tmp_path)
    _w(root / "safety" / "risk_veto.json", {
        "action": "exercised", "initial_state": "flat",
        "resulting_state": "vetoed", "observed_result": "passed",
        "raw_evidence": "seems to work fine"})
    report = gate(root)
    assert report["safety"]["risk_veto"]["state"] == og.INVALID
    assert report["verdict"] not in og.POSITIVE_VERDICTS


# ---------------------------------------------------------------------------
# §27 CLI contract — exit 0 positive / 1 negative / 2 configuration
# ---------------------------------------------------------------------------


def _cli(*args):
    import subprocess
    import sys as _sys
    return subprocess.run(
        [_sys.executable, "tools/verify_owner_mt5_gate.py", *args],
        capture_output=True, text=True, check=False, cwd=".")


def test_cli_exit_codes(tmp_path):
    ok = build_package(tmp_path / "ok")
    frozen_file = tmp_path / "frozen.json"
    frozen_file.write_text(json.dumps(FROZEN))
    r = _cli(str(ok), "--frozen", str(frozen_file),
             "--out", str(tmp_path / "rep.json"))
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "rep.json").read_text())["verdict"] == \
        og.MT5_VALIDATED
    r = _cli(str(tmp_path / "does-not-exist"), "--frozen", str(frozen_file))
    assert r.returncode == 1
    r = _cli(str(ok), "--frozen", str(tmp_path / "no-such-frozen.json"))
    assert r.returncode == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _cli(str(empty), "--frozen", str(frozen_file))
    assert r.returncode == 1


def test_cli_template_package_is_not_positive():
    # the shipped owner template carries PENDING_OWNER placeholders —
    # consuming it as-is must never produce a positive verdict
    r = _cli("artifacts/owner_mt5_gate")
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# §5/§6 REAL-TICK EVIDENCE MUST BE FILE-BOUND — attack matrix A..L
# ---------------------------------------------------------------------------


def _cov_doc(root):
    return json.loads((root / og.LAYOUT["real_tick_coverage"]).read_text())


def _set_cov(root, **kw):
    doc = _cov_doc(root)
    doc.update(kw)
    _w(root / og.LAYOUT["real_tick_coverage"], doc)


def _bind(path, digest):
    return {"path": str(path), "sha256": digest}


def test_real_tick_A_valid_journal_matching_hash_accepted(tmp_path):
    report = gate(build_package(tmp_path))
    assert report["real_tick_coverage"]["state"] == og.VALID
    assert report["verdict"] == og.MT5_VALIDATED


def test_real_tick_B_filename_right_bytes_changed(tmp_path):
    root = build_package(tmp_path)
    doc = _cov_doc(root)
    ev = dict(doc["real_tick_availability_evidence"])
    j = root / ev["path"]
    j.write_text(j.read_text() + "\nextra line not in hash\n")
    report = gate(root)
    assert report["real_tick_coverage"]["state"] == og.MISMATCHED
    assert report["verdict"] not in og.POSITIVE_VERDICTS


def test_real_tick_C_hash_right_different_file(tmp_path):
    root = build_package(tmp_path)
    doc = _cov_doc(root)
    ev = dict(doc["real_tick_availability_evidence"])
    # decoy file with DIFFERENT content, but the binding keeps the hash
    # of the real journal — hash of the bound path must not match
    (root / "decoy_journal.log").write_text(
        "EURUSD 2026-03-01 .. 2026-03-04 some other run\n")
    _set_cov(root, real_tick_availability_evidence=_bind(
        "decoy_journal.log", ev["sha256"]))
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.MISMATCHED


def test_real_tick_D_path_escapes_evidence_root(tmp_path):
    root = build_package(tmp_path)
    outside = root.parent / "outside.log"
    outside.write_text("EURUSD 2026-01-01 .. 2026-01-04\n")
    import hashlib as _h
    _set_cov(root, real_tick_availability_evidence=_bind(
        "../outside.log", _h.sha256(outside.read_bytes()).hexdigest()))
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.INVALID and "escapes" in rep["reasons"][0]


def test_real_tick_E_bound_file_missing(tmp_path):
    root = build_package(tmp_path)
    doc = _cov_doc(root)
    ev = dict(doc["real_tick_availability_evidence"])
    (root / ev["path"]).unlink()
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.INVALID and "does not exist" in rep["reasons"][0]


def test_real_tick_F_journal_from_other_symbol(tmp_path):
    root = build_package(tmp_path)
    import hashlib as _h
    doc = _cov_doc(root)
    ev = dict(doc["real_tick_availability_evidence"])
    j = root / ev["path"]
    # a REAL journal from another symbol, honestly re-hashed: the hash
    # layer passes, the symbol cross-check must catch it
    j.write_text(j.read_text().replace("EURUSD", "GBPUSD"))
    _set_cov(root, real_tick_availability_evidence=_bind(
        ev["path"], _h.sha256(j.read_bytes()).hexdigest()))
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.MISMATCHED and "symbol" in rep["reasons"][0]


def test_real_tick_G_journal_from_other_interval(tmp_path):
    root = build_package(tmp_path)
    import hashlib as _h
    doc = _cov_doc(root)
    ev = dict(doc["real_tick_availability_evidence"])
    j = root / ev["path"]
    # a REAL journal covering another interval, honestly re-hashed
    j.write_text(j.read_text().replace("2026-01-04", "2026-02-28"))
    _set_cov(root, real_tick_availability_evidence=_bind(
        ev["path"], _h.sha256(j.read_bytes()).hexdigest()))
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.MISMATCHED and "interval" in rep["reasons"][0]


def test_real_tick_H_full_with_prose_only(tmp_path):
    root = build_package(tmp_path)
    _set_cov(root, real_tick_availability_evidence="trust me, real ticks")
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.INVALID
    assert "not evidence" in rep["reasons"][0]


def test_real_tick_I_full_without_hash(tmp_path):
    root = build_package(tmp_path)
    _set_cov(root, real_tick_availability_evidence={
        "path": "real_ticks_journal.log"})
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.INVALID and "SHA-256" in rep["reasons"][0]


def test_real_tick_J_requested_real_report_every_tick(tmp_path):
    root = build_package(tmp_path)
    _set_cov(root, actual_model_from_report="Every tick")
    rep = gate(root)["real_tick_coverage"]
    assert rep["state"] == og.MISMATCHED
    assert "silent fallback" in rep["reasons"][0]


def test_real_tick_K_partial_constrained(tmp_path):
    report = gate(build_package(tmp_path, coverage="PARTIAL"))
    assert report["verdict"] == og.NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN


def test_real_tick_L_unknown_constrained(tmp_path):
    report = gate(build_package(tmp_path, coverage="UNKNOWN"))
    assert report["verdict"] == og.NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN


# ---------------------------------------------------------------------------
# §7/§8 SAFETY RAW EVIDENCE MUST BE FILE-BOUND — attack matrix
# ---------------------------------------------------------------------------


def _safety_doc(root, name):
    return json.loads((root / "safety" / f"{name}.json").read_text())


def _set_safety(root, name, **kw):
    doc = _safety_doc(root, name)
    doc.update(kw)
    _w(root / "safety" / f"{name}.json", doc)


@pytest.mark.parametrize("name", list(og.SAFETY_TESTS) + ["netting",
                                                          "hedging"])
def test_safety_valid_evidence_accepted(tmp_path_factory, name):
    root = tmp_path_factory.mktemp("sok")
    report = gate(build_package(root))
    if name == "hedging":
        assert report["safety"][name]["state"] == og.VALID
    else:
        assert report["safety"][name]["state"] == og.VALID


@pytest.mark.parametrize("name", list(og.SAFETY_TESTS) + ["netting"])
def test_safety_altered_evidence_rejected(tmp_path_factory, name):
    root = tmp_path_factory.mktemp("salt")
    build_package(root)
    ev = _safety_doc(root, name)["raw_evidence"]
    (root / ev["path"]).write_text("tampered evidence content\n")
    report = gate(root)
    assert report["safety"][name]["state"] == og.MISMATCHED
    assert report["verdict"] not in og.POSITIVE_VERDICTS


@pytest.mark.parametrize("name", list(og.SAFETY_TESTS) + ["netting"])
def test_safety_missing_evidence_rejected(tmp_path_factory, name):
    root = tmp_path_factory.mktemp("smiss")
    build_package(root)
    ev = _safety_doc(root, name)["raw_evidence"]
    (root / ev["path"]).unlink()
    report = gate(root)
    assert report["safety"][name]["state"] == og.INVALID
    assert report["verdict"] not in og.POSITIVE_VERDICTS


def test_safety_screenshot_only_rejected(tmp_path):
    root = build_package(tmp_path)
    png = root / "safety" / "shot.png"
    png.write_bytes(b"\x89PNG fake")
    import hashlib as _h
    _set_safety(root, "kill_switch", raw_evidence={
        "path": "safety/shot.png",
        "sha256": _h.sha256(png.read_bytes()).hexdigest()})
    rep = gate(root)["safety"]["kill_switch"]
    assert rep["state"] == og.INVALID and "screenshot" in rep["reasons"][0]


def test_safety_prose_claim_rejected(tmp_path):
    root = build_package(tmp_path)
    _set_safety(root, "risk_veto", raw_evidence="passed")
    rep = gate(root)["safety"]["risk_veto"]
    assert rep["state"] == og.INVALID and "not evidence" in rep["reasons"][0]


def test_safety_journal_ref_unbound_rejected(tmp_path):
    root = build_package(tmp_path)
    _set_safety(root, "restart", raw_evidence="journal:foo.log")
    rep = gate(root)["safety"]["restart"]
    assert rep["state"] == og.INVALID


def test_safety_wrong_hash_rejected(tmp_path):
    root = build_package(tmp_path)
    ev = _safety_doc(root, "meta_reduce")["raw_evidence"]
    _set_safety(root, "meta_reduce", raw_evidence={
        "path": ev["path"], "sha256": "0" * 64})
    rep = gate(root)["safety"]["meta_reduce"]
    assert rep["state"] == og.MISMATCHED


def test_safety_path_escape_rejected(tmp_path):
    root = build_package(tmp_path)
    outside = root.parent / "escape.log"
    outside.write_text("x")
    import hashlib as _h
    _set_safety(root, "sl_verify", raw_evidence={
        "path": "../escape.log",
        "sha256": _h.sha256(outside.read_bytes()).hexdigest()})
    rep = gate(root)["safety"]["sl_verify"]
    assert rep["state"] == og.INVALID and "escapes" in rep["reasons"][0]


def test_safety_wrong_environment_rejected(tmp_path):
    # evidence that describes a DIFFERENT broker/run is not this run's
    root = build_package(tmp_path)
    ev = _safety_doc(root, "lost_response")["raw_evidence"]
    p = root / ev["path"]
    p.write_text("lost_response exercise on OtherBroker Other-Server\n")
    import hashlib as _h
    _set_safety(root, "lost_response", raw_evidence={
        "path": ev["path"],
        "sha256": _h.sha256(p.read_bytes()).hexdigest()})
    # the file binds + parses, but the environment contradicts SymbolSpec
    _w(root / "environment.json", {
        "os": "Windows 11", "terminal_build": "9999",
        "broker": "OtherBroker", "server": "Other-Server",
        "account_mode": "netting", "symbol": "EURUSD",
        "timezone": "UTC", "run_timestamp": "2026-09-08T12:30:00+00:00"})
    _w(root / "archive_manifest.json", _build_manifest(root))
    report = gate(root)
    assert report["environment"]["state"] == og.MISMATCHED
    assert report["verdict"] not in og.POSITIVE_VERDICTS


# ---------------------------------------------------------------------------
# §9 environment binding
# ---------------------------------------------------------------------------


def test_environment_contradiction_detected(tmp_path):
    root = build_package(tmp_path)
    _w(root / "environment.json", {
        "os": "Windows 11", "terminal_build": "9999",
        "broker": "DemoBroker", "server": "Demo-Live",
        "account_mode": "hedging", "symbol": "XAUUSD",
        "timezone": "UTC", "run_timestamp": "2026-09-08T12:30:00+00:00"})
    report = gate(root)
    assert report["environment"]["state"] == og.MISMATCHED
    assert report["verdict"] not in og.POSITIVE_VERDICTS


def test_environment_missing_fields_rejected(tmp_path):
    root = build_package(tmp_path)
    _w(root / "environment.json", {"os": "Windows 11"})
    report = gate(root)
    assert report["environment"]["state"] == og.INVALID


# ---------------------------------------------------------------------------
# §10 archive manifest binding + one-byte mutation
# ---------------------------------------------------------------------------


def test_manifest_mere_filenames_rejected(tmp_path):
    root = build_package(tmp_path)
    _w(root / "archive_manifest.json",
       {"artifacts": {og.LAYOUT["ex5"]: "Mql5Bot.ex5"}})
    report = gate(root)
    assert report["archive_manifest"]["state"] in (og.INVALID, og.MISMATCHED)
    assert report["verdict"] not in og.POSITIVE_VERDICTS


def test_manifest_unbound_artifact_rejected(tmp_path):
    root = build_package(tmp_path)
    man = json.loads((root / og.LAYOUT["archive_manifest"]).read_text())
    man["artifacts"].pop(og.LAYOUT["symbolspec"])
    _w(root / "archive_manifest.json", man)
    report = gate(root)
    assert report["archive_manifest"]["state"] == og.INVALID


def test_manifest_wrong_identity_rejected(tmp_path):
    root = build_package(tmp_path)
    man = json.loads((root / og.LAYOUT["archive_manifest"]).read_text())
    man["identity"]["source_commit"] = "b" * 40
    _w(root / "archive_manifest.json", man)
    report = gate(root)
    assert report["archive_manifest"]["state"] == og.MISMATCHED


@pytest.mark.parametrize("rel", [og.LAYOUT["ex5"],
                                 og.LAYOUT["symbolspec"],
                                 og.LAYOUT["parsed_gold1_m1_ohlc"]])
def test_manifest_catches_one_byte_mutation(tmp_path_factory, rel):
    root = tmp_path_factory.mktemp("man")
    build_package(root)
    _flip(root / rel)
    report = gate(root)
    assert report["archive_manifest"]["state"] == og.MISMATCHED
    assert report["verdict"] not in og.POSITIVE_VERDICTS


# ---------------------------------------------------------------------------
# §11 raw report binding (raw -> parsed -> reconciliation)
# ---------------------------------------------------------------------------


def test_raw_report_missing_breaks_chain(tmp_path):
    root = build_package(tmp_path)
    (root / og.LAYOUT["raw_gold2_every_tick"]).unlink()
    report = gate(root)
    assert report["gold"]["gold2"]["state"] in (og.MISMATCHED, og.INVALID)
    assert report["verdict"] not in og.POSITIVE_VERDICTS


def test_raw_report_altered_breaks_chain(tmp_path):
    root = build_package(tmp_path)
    _flip(root / og.LAYOUT["raw_gold1_real_ticks"])
    report = gate(root)
    assert report["gold"]["gold1"]["state"] == og.MISMATCHED
    assert "raw report" in " ".join(report["gold"]["gold1"]["reasons"])
