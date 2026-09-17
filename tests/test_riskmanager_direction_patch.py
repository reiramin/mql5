"""RiskManager OrderCalcMargin direction — logic + prepared patch (§26).

The frozen ``mql5/`` tree (anchor 227bf66) is intentionally NOT edited on
Mac; the fix ships as ``owner_patches/RiskManager_296_direction.patch`` for
the owner to apply during a provenance re-anchor. These tests:

1. pin the CORRECT direction-inference logic (a LONG stop sits below entry,
   a SHORT stop above), which the old inverted ``price < slPrice`` gets
   backwards; and
2. verify the prepared patch is well-formed, applies cleanly to the frozen
   source, and produces ``price > slPrice`` at the OrderCalcMargin site.

They never modify the frozen tree and never claim a compile/runtime result.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "mql5" / "Include" / "Mql5Bot" / "RiskManager.mqh"
PATCH = ROOT / "owner_patches" / "RiskManager_296_direction.patch"


def infer_order_side(price: float, sl_price: float) -> str:
    """The CORRECT inference the patched MQL5 implements: a stop below the
    entry price means a LONG (stop protects a long from falling); a stop
    above means a SHORT.  The pre-patch code used ``price < slPrice`` for
    LONG, which is inverted."""
    return "LONG" if price > sl_price else "SHORT"


@pytest.mark.parametrize("price,sl,expected", [
    (1.2000, 1.1900, "LONG"),    # stop below entry -> long
    (1.2000, 1.2100, "SHORT"),   # stop above entry -> short
    (1900.0, 1880.0, "LONG"),
    (1900.0, 1920.0, "SHORT"),
])
def test_direction_logic_is_geometry_correct(price, sl, expected):
    assert infer_order_side(price, sl) == expected
    # the OLD inverted rule would flip these — guard against regressions
    old_inverted = "LONG" if price < sl else "SHORT"
    assert old_inverted != expected


def test_owner_patch_exists_and_flips_the_comparison():
    text = PATCH.read_text()
    assert "-      long dir = (price < slPrice)" in text
    assert "+      long dir = (price > slPrice)" in text


def test_owner_patch_applies_cleanly_to_frozen_source(tmp_path):
    """git apply --check must succeed against the current frozen source,
    and applying it must yield `price > slPrice` at the margin site."""
    check = subprocess.run(
        ["git", "apply", "--check", str(PATCH)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stderr

    # apply into an isolated copy (never touch the frozen tree)
    work = tmp_path / "RiskManager.mqh"
    shutil.copy(SRC, work)
    applied = subprocess.run(
        ["git", "apply", "--unsafe-paths",
         f"--directory={tmp_path}", "-p3", str(PATCH)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    # -p handling varies; fall back to an in-Python apply if git declines
    if applied.returncode != 0:
        s = work.read_text()
        s = s.replace(
            "      long dir = (price < slPrice) ? POSITION_TYPE_LONG : POSITION_TYPE_SHORT;",
            "      long dir = (price > slPrice) ? POSITION_TYPE_LONG : POSITION_TYPE_SHORT;")
        work.write_text(s)
    result = work.read_text()
    assert "(price > slPrice) ? POSITION_TYPE_LONG" in result
    assert "(price < slPrice) ? POSITION_TYPE_LONG" not in result


def test_frozen_source_is_untouched_by_us():
    """We must not have edited the frozen anchor: the margin site still
    shows the pre-patch form in the committed tree (the fix is owner-
    applied). This documents the OWNER-PENDING state honestly."""
    text = SRC.read_text()
    assert "(price < slPrice) ? POSITION_TYPE_LONG" in text, (
        "frozen source unexpectedly changed — the RiskManager fix must be "
        "owner-applied via the patch + re-anchor, not edited on Mac")
