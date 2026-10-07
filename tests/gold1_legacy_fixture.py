"""The PRE-REGENERATION gold1 fixture (120 H1 bars, 2024-01-01 00:00 ..
2024-01-05 23:00), rebuilt from its original deterministic recipe.

S8-GOLD1-REGEN (2026-10-07) replaced artifacts/gold/gold_fixture.csv with
a longer fixture whose warmup is CONSTANT, so the Python and platform EMA
seeds agree exactly there. The EMA seed-transient analysis
(tests/test_ema_seed_parity.py) studies a NON-constant warmup, so it keeps
running on this original series. ``LEGACY_SHA256`` is the frozen
fixture_sha256 the old record pinned; a test checks the rebuild against it.
"""

from __future__ import annotations

import pandas as pd

LEGACY_SHA256 = ("2b1730cbb43e959291a115c53db8a0c8620ea80ccf00b2251bf01dd236"
                 "ebd764")


def _mk(closes, spike_bars=None):
    n = len(closes)
    o = [closes[0]] + closes[:-1]
    h = [max(a, b) + 0.00025 for a, b in zip(o, closes)]
    lo = [min(a, b) - 0.00025 for a, b in zip(o, closes)]
    if spike_bars:
        for i, up, dn in spike_bars:
            h[i] = o[i] + up
            lo[i] = o[i] - dn
    idx = pd.date_range("2024-01-01 00:00:00", periods=n, freq="h")
    df = pd.DataFrame({"open": o, "high": h, "low": lo, "close": closes,
                       "volume": [1000.0 + 10 * i for i in range(n)]},
                      index=idx)
    df.index.name = "time"
    return df


def legacy_gold1_fixture() -> pd.DataFrame:
    flat = [1.1000 + 0.00005 * (i % 3) for i in range(30)]
    up = [1.1000 + 0.0011 * i for i in range(1, 26)]
    drop = [1.1275 - 0.005 * i for i in range(1, 5)]
    dn = [1.1075 - 0.0013 * i for i in range(1, 19)]
    spikes = [dn[-1], dn[-1]]
    up2 = [dn[-1] + 0.0014 * i for i in range(1, 19)]
    hold = [up2[-1] + 0.00002 * (i % 2) for i in range(23)]
    closes = flat + up + drop + dn + spikes + up2 + hold
    k = len(flat) + len(up) + len(drop) + len(dn)
    return _mk(closes, spike_bars=[(k, 0.006, 0.008),
                                   (k + 1, 0.009, 0.012)])


def legacy_gold1_csv() -> str:
    return legacy_gold1_fixture().to_csv(float_format="%.10f")
