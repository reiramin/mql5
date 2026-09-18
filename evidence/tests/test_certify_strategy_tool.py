"""Fail-closed check for the certify_strategy step-8 reconciliation gate.

`_reconciliation_ok` decides whether a recorded Python↔MT5 reconciliation
is COMPLETE enough to let a would-be VERIFIED verdict stand. It must reject
an owner-work-in-progress artifact whose MT5 side is still PENDING_OWNER —
otherwise pointing --reconciliation at either frozen gold reconciliation
(which carries python↔DSL/source lanes but `python_vs_mt5_tester ==
"PENDING_OWNER"` and every `mt5 == None`) would wrongly satisfy the gate.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_tool():
    path = REPO / "tools" / "certify_strategy.py"
    spec = importlib.util.spec_from_file_location("certify_strategy_tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TOOL = _load_tool()


@pytest.mark.parametrize("rel", ["artifacts/gold/reconciliation.json",
                                 "artifacts/gold_2/reconciliation.json"])
def test_pending_owner_reconciliation_is_not_step8_evidence(rel):
    # both frozen gold reconciliations are python_vs_mt5_tester=PENDING_OWNER
    # with every mt5 == None: NOT a completed step-8 comparison
    assert TOOL._reconciliation_ok(str(REPO / rel)) is False


def test_completed_reconciliation_is_accepted(tmp_path):
    doc = {"python_vs_mt5_tester": "MATCHED",
           "trades": [{"python": 1.05, "mt5": 1.05, "mt5_status": "MATCH"}]}
    p = tmp_path / "recon.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert TOOL._reconciliation_ok(str(p)) is True


def test_marker_complete_but_no_real_mt5_value_is_rejected(tmp_path):
    # a non-pending marker is not enough: at least one real mt5 obs required
    doc = {"python_vs_mt5_tester": "MATCHED",
           "trades": [{"python": 1.05, "mt5": None, "mt5_status": "PENDING"}]}
    p = tmp_path / "recon.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert TOOL._reconciliation_ok(str(p)) is False


def test_missing_or_unparsable_artifact_is_rejected(tmp_path):
    assert TOOL._reconciliation_ok(str(tmp_path / "nope.json")) is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert TOOL._reconciliation_ok(str(bad)) is False
