"""RiskManager OrderCalcMargin direction — logic + APPLIED fix (§26).

The integration wave applied the direction fix directly to ``mql5/``
(the old anchor 227bf66 predates it — see
docs/WINDOWS_OWNER_HANDOFF.md §8a, "APPLIED"). The
``owner_patches/RiskManager_296_direction.patch`` is kept as the
historical record of the flip. These tests:

1. pin the CORRECT direction-inference logic (a LONG stop sits below
   entry, a SHORT stop above), which the old inverted ``price < slPrice``
   gets backwards; and
2. verify the fix is now IN the committed tree (``price > slPrice`` at the
   OrderCalcMargin site) and the inverted form is gone.

They never claim a compile/runtime result; the re-anchor that promotes
this to compile-of-record is owner work.
"""

from __future__ import annotations

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
    """The historical patch documents the exact flip that is now applied
    in-tree."""
    text = PATCH.read_text()
    assert "-      long dir = (price < slPrice)" in text
    assert "+      long dir = (price > slPrice)" in text


def test_fix_is_applied_in_tree():
    """The direction fix is now in the committed RiskManager source: the
    margin site infers the side from `price > slPrice` and the inverted
    form is gone. Promotion to compile-of-record is the owner re-anchor
    (docs/WINDOWS_OWNER_HANDOFF.md §8a)."""
    text = SRC.read_text()
    assert "(price > slPrice) ? POSITION_TYPE_LONG" in text, (
        "the RiskManager direction fix is missing from the integrated tree")
    assert "(price < slPrice) ? POSITION_TYPE_LONG" not in text, (
        "the inverted pre-fix form must not remain in the tree")
