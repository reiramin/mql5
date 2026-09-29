"""Stage 8 accepts a PASS_FROM_LOG log trade list when no report exists.

Verifier self-tests on synthetic owner packages (see test_owner_gate.py): a
green test here is NOT MT5 evidence. They pin that:

  * a leg with no raw report but a bound ``log_trades/<gold>_<model>.json``
    (from_log: true) is accepted as that leg's trade source, and the report
    records the source as the tester agent log;
  * a log list with ZERO deals is valid input: its trade count is compared
    with the frozen Python trade count by the UNCHANGED comparison —
    0 vs 0 matches, 0 vs 56 (gold2's frozen contract) diverges;
  * tampered, mis-flagged or mis-modelled log lists, or a missing
    hash-verified Python count, fail closed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from mql5bot import owner_gate as og
from mql5bot import tester_log_grader as tlg
from test_owner_gate import FROZEN, _build_manifest, _w, build_package

REPO = Path(__file__).resolve().parents[1]
CAPTURE = REPO / "tests" / "data" / "owner_gate" / "tester_log_gate_runs_16_17.txt"
MODELS = {"m1_ohlc": 1, "every_tick": 0, "real_ticks": 3}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _real_gold2_trade_list() -> dict:
    """The log trade list the grader produces from the REAL captured gold2
    lines (gate runs 16/17): PASS_FROM_LOG with zero deals."""
    lines = [ln for ln in CAPTURE.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#") and "EURUSD.G1" not in ln]
    window = "\n".join(lines) + "\n"
    grade = tlg.grade_leg_from_log(window_text=window, symbol="EURUSD.G2",
                                   requested_model=1, leg="gold2_m1_ohlc")
    doc = tlg.log_trade_list(grade, window.encode("utf-8"))
    assert doc is not None and doc["deals"] == []
    return doc


def _log_source(root: Path, gold: str, models=tuple(MODELS), *, deals=(),
                events=None, mutate=None) -> None:
    """Turn ``models`` of ``gold`` into log-sourced legs: remove their raw +
    parsed reports, write + bind a log trade list, re-bind the manifest."""
    recon_path = root / "reconciliation" / f"{gold}.json"
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    b = recon["bindings"]
    b["log_trade_hashes"] = {}
    for model in models:
        (root / gold / f"{model}.htm").unlink()
        (root / "parsed" / f"{gold}_{model}.json").unlink()
        del b["raw_report_hashes"][model]
        del b["parsed_report_hashes"][model]
        doc = _real_gold2_trade_list() if model == "m1_ohlc" else \
            copy.deepcopy(_real_gold2_trade_list())
        doc["leg"] = f"{gold}_{model}"
        doc["settings"]["model"] = og.MODEL_LABELS[MODELS[model]]
        doc["deals"] = [dict(d) for d in deals]
        if mutate:
            mutate(model, doc)
        path = root / og.log_trades_rel(gold, model)
        _w(path, doc)
        b["log_trade_hashes"][model] = _sha(path)
        triad = b["tester_models"][model]
        del triad["report_reported"]
        triad["log_reported"] = og.MODEL_LABELS[MODELS[model]]
    if events is not None:
        recon["events"] = events
    _w(recon_path, recon)
    _w(root / "archive_manifest.json", _build_manifest(root))


def _frozen(py_count):
    fz = copy.deepcopy(FROZEN)
    if py_count is not None:
        fz["gold_2"]["python_trade_count"] = py_count
    return fz


def test_all_legs_log_sourced_zero_deals_vs_zero_python_trades_matches(tmp_path):
    root = build_package(tmp_path)
    _log_source(root, "gold2", events=[])
    rep = og.run_gate(root, _frozen(0))
    g2 = rep["gold"]["gold2"]
    assert g2["result"] == "MATCH", g2["reasons"]
    assert g2["trade_sources"] == {m: "tester agent log" for m in MODELS}
    assert g2["log_trade_counts"] == {m: 0 for m in MODELS}
    assert rep["log_sourced_legs"] == [f"gold2:{m}" for m in sorted(MODELS)]
    assert rep["trade_sources"]["gold1"] == {m: "report" for m in MODELS}
    # the source is named in the verdict reasons, not only in the details
    assert any("tester agent log" in r for r in rep["reasons"])
    # a log-sourced leg's report slots are LOG_SOURCED, never "missing"
    assert rep["artifacts"]["raw_gold2_m1_ohlc"]["state"] == og.LOG_SOURCED
    assert rep["missing"] == []


def test_zero_deals_vs_the_frozen_56_python_trades_diverges_not_rejected(tmp_path):
    root = build_package(tmp_path)
    _log_source(root, "gold2", events=[])
    rep = og.run_gate(root, _frozen(56))
    g2 = rep["gold"]["gold2"]
    assert g2["state"] == og.MISMATCHED
    assert g2["result"] == "DIVERGENT"
    div = g2["first_divergence"]
    assert div["first_divergent_field"] == "trade_count:every_tick"
    assert (div["python_value"], div["mt5_value"]) == (56, 0)
    assert rep["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_log_deal_count_is_what_gets_compared(tmp_path):
    root = build_package(tmp_path)
    deal = {"ticket": 2, "time": "2024.01.02 10:00:00", "symbol": "EURUSD.G2",
            "side": None, "entry": None, "volume": 0.1, "price": 1.1001,
            "pnl": 0.0, "lines": []}
    _log_source(root, "gold2", deals=[deal], events=[])
    rep = og.run_gate(root, _frozen(1))
    assert rep["gold"]["gold2"]["result"] == "MATCH"
    assert rep["gold"]["gold2"]["log_trade_counts"]["m1_ohlc"] == 1


def test_one_log_sourced_leg_beside_two_report_legs(tmp_path):
    root = build_package(tmp_path)
    _log_source(root, "gold2", models=("m1_ohlc",))
    rep = og.run_gate(root, _frozen(0))
    g2 = rep["gold"]["gold2"]
    assert g2["result"] == "MATCH", g2["reasons"]
    assert g2["trade_sources"] == {"m1_ohlc": "tester agent log",
                                   "every_tick": "report",
                                   "real_ticks": "report"}
    assert rep["log_sourced_legs"] == ["gold2:m1_ohlc"]


def test_empty_events_are_still_rejected_while_any_leg_has_a_report(tmp_path):
    root = build_package(tmp_path)
    _log_source(root, "gold2", models=("m1_ohlc",), events=[])
    g2 = og.run_gate(root, _frozen(0))["gold"]["gold2"]
    assert g2["state"] == og.INVALID
    assert "no events" in " ".join(g2["reasons"])


def test_no_hash_verified_python_count_fails_closed(tmp_path):
    root = build_package(tmp_path)
    _log_source(root, "gold2", events=[])
    g2 = og.run_gate(root, _frozen(None))["gold"]["gold2"]
    assert g2["state"] == og.INVALID
    assert "Python trade count" in " ".join(g2["reasons"])


def test_tampered_log_trade_list_fails(tmp_path):
    root = build_package(tmp_path)
    _log_source(root, "gold2", events=[])
    path = root / og.log_trades_rel("gold2", "every_tick")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["deals"] = []
    doc["final_balance"] = 12345.0
    _w(path, doc)
    g2 = og.run_gate(root, _frozen(0))["gold"]["gold2"]
    assert g2["state"] == og.MISMATCHED
    assert "every_tick: log trade list bytes changed" in " ".join(g2["reasons"])


@pytest.mark.parametrize("field,value", [("from_log", False),
                                         ("report_present", True),
                                         ("evidence_class",
                                          "BLOCKED_OWNER_ENVIRONMENT"),
                                         ("deals", None)])
def test_a_list_that_is_not_pass_from_log_is_refused(tmp_path, field, value):
    root = build_package(tmp_path)

    def mutate(model, doc):
        if model == "real_ticks":
            doc[field] = value

    _log_source(root, "gold2", events=[], mutate=mutate)
    g2 = og.run_gate(root, _frozen(0))["gold"]["gold2"]
    assert g2["state"] == og.MISMATCHED
    assert "real_ticks: not a PASS_FROM_LOG log trade list" in \
        " ".join(g2["reasons"])


def test_log_reported_model_must_equal_the_list(tmp_path):
    root = build_package(tmp_path)

    def mutate(model, doc):
        if model == "m1_ohlc":
            doc["settings"]["model"] = "Every tick"

    _log_source(root, "gold2", events=[], mutate=mutate)
    g2 = og.run_gate(root, _frozen(0))["gold"]["gold2"]
    assert g2["state"] == og.MISMATCHED
    assert "m1_ohlc: log_reported" in " ".join(g2["reasons"])


def test_a_raw_report_wins_over_a_log_list(tmp_path):
    root = build_package(tmp_path)
    _w(root / og.log_trades_rel("gold2", "m1_ohlc"), _real_gold2_trade_list())
    assert og.log_sourced_legs(root) == set()


def test_archive_manifest_must_bind_the_log_list(tmp_path):
    root = build_package(tmp_path)
    _log_source(root, "gold2", events=[])
    man = json.loads((root / "archive_manifest.json").read_text("utf-8"))
    del man["artifacts"][og.log_trades_rel("gold2", "m1_ohlc")]
    _w(root / "archive_manifest.json", man)
    rep = og.run_gate(root, _frozen(0))
    assert rep["archive_manifest"]["state"] == og.INVALID
    assert "log_trades/gold2_m1_ohlc.json" in \
        " ".join(rep["archive_manifest"]["reasons"])


# ---------------------------------------------------------------------------
# the verifier tool supplies the Python count only from hash-pinned bytes
# ---------------------------------------------------------------------------

def _tool():
    sys.path.insert(0, str(REPO / "tools"))
    import verify_owner_mt5_gate as tool
    return tool


def test_python_trade_count_comes_from_the_hash_pinned_reconciliation():
    frozen = json.loads((REPO / "artifacts" / "owner_mt5_gate"
                         / "frozen_inputs.json").read_text(encoding="utf-8"))
    _tool()._bind_python_trade_counts(REPO, frozen)
    # gold2: the frozen record pins reconciliation.json; 56 is its contract
    assert frozen["gold_2"]["python_trade_count"] == 56
    # gold1: no hash chain in the frozen record -> no count (fail-closed)
    assert "python_trade_count" not in frozen["gold_1"]


def test_python_trade_count_absent_when_the_pinned_hash_disagrees():
    frozen = json.loads((REPO / "artifacts" / "owner_mt5_gate"
                         / "frozen_inputs.json").read_text(encoding="utf-8"))
    frozen["gold_2"]["artifact_hash_chain"]["reconciliation.json"] = "0" * 64
    _tool()._bind_python_trade_counts(REPO, frozen)
    assert "python_trade_count" not in frozen["gold_2"]
