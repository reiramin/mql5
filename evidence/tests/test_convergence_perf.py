"""Convergence §67: decision-latency measurement (bench marker;
measurement only — no absolute-speed assertions, no optimization)."""

from __future__ import annotations

import time

import pytest
from mql5bot.discovery import AllocationGovernor, GovernorBounds
from mql5bot.discovery.entry_chain import ChainContext, EntryRequest, govern_entry
from mql5bot.discovery.governor import EligibilityRecord


@pytest.mark.bench
def test_entry_chain_and_governor_latency_measurement():
    req = EntryRequest(origin="strategy", strategy_id="lat_strat",
                       symbol="EURUSD", side="long",
                       requested_risk=0.005)
    ctx = ChainContext()
    gov = AllocationGovernor(GovernorBounds(max_strategy_delta=10))
    entries = [EligibilityRecord(strategy_id=f"s{i}",
                                 lifecycle_state="LIVE",
                                 human_approved=True, gates_pass=True,
                                 kill_switch_ok=True, evidence_ok=True)
               for i in range(5)]
    scores = {f"s{i}": 0.5 + i * 0.05 for i in range(5)}

    t0 = time.perf_counter()
    n = 2000
    for _ in range(n):
        govern_entry(req, ctx)
        gov.recommend(entries, scores)
    dt = time.perf_counter() - t0
    per_call_us = dt / n * 1e6
    # recorded, not asserted against a production-SLA number (§67:
    # correctness first; the number documents the current cost)
    print(f"\nentry-chain+governor combined latency: "
          f"{per_call_us:.1f} µs/call ({n} iters)")
    assert per_call_us < 50_000        # sanity only: not pathological
