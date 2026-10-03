"""tools/preview_gold2_regen.py — the diff logic only (the full preview
runs the gold builder and is exercised manually; its output lives under
gitignored evidence/preview/ and is never evidence)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "preview_gold2_regen",
    Path(__file__).resolve().parents[1] / "tools" / "preview_gold2_regen.py")
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)


def _t(entry: str, side: str, lots: float = 1.0, reason: str = "signal_exit"):
    return {"signal_time": entry, "side": side, "lots": lots,
            "exit_reason": reason}


def test_diff_classifies_unchanged_moved_vanished_appeared():
    frozen = [
        _t("2024-01-02T08:01:00", "long"),              # unchanged
        _t("2024-01-02T09:12:00", "short", lots=0.5),   # moved +1 bar
        _t("2024-01-02T10:00:00", "long"),              # vanishes
    ]
    preview = [
        _t("2024-01-02T08:01:00", "long"),
        _t("2024-01-02T09:13:00", "short", lots=0.4, reason="stop_loss"),
        _t("2024-01-02T11:30:00", "short"),             # appears
    ]
    d = pv.diff_traces(frozen, preview)
    assert (d["frozen_trades"], d["preview_trades"]) == (3, 3)
    assert d["unchanged"] == 1
    assert d["moved_plus_one_bar"] == 1
    assert d["moved"][0]["preview_entry"] == "2024-01-02T09:13:00"
    # the moved match also reports its lots/exit_reason changes
    assert d["matched_with_lots_changed"] == 1
    assert d["matched_with_exit_reason_changed"] == 1
    assert d["moved"][0]["lots"] == {"frozen": 0.5, "preview": 0.4}
    assert [v["entry"] for v in d["vanished"]] == ["2024-01-02T10:00:00"]
    assert [a["entry"] for a in d["appeared"]] == ["2024-01-02T11:30:00"]


def test_diff_never_double_consumes_a_preview_trade():
    # two frozen entries competing for one preview trade: exact match wins,
    # the other is vanished — a preview trade is consumed at most once
    frozen = [_t("2024-01-02T08:01:00", "long"),
              _t("2024-01-02T08:00:00", "long")]
    preview = [_t("2024-01-02T08:01:00", "long")]
    d = pv.diff_traces(frozen, preview)
    assert d["unchanged"] + d["moved_plus_one_bar"] == 1
    assert len(d["vanished"]) == 1 and not d["appeared"]
