"""Indicator mql5_status truthfulness (mission §7.8/§33).

The registry defines ``mql5_status`` with two values (registry.py):
  * "canonical-defined" — Python pinned by tests; MQL5 port PENDING owner
    compile; NEVER reported as parity-proven.
  * "parity-tested"     — RESERVED for a kind with OWNER-VERIFIED MQL5↔
    Python runtime parity (real MetaEditor compile + Strategy-Tester
    evidence).

The repo state is REALITY_GATE_BLOCKED: there is no owner MT5 compile, and
65+ of the 71 kinds have no MQL5 implementation at all. So NO kind may
claim "parity-tested". A prior default labelled every kind "parity-tested"
— an over-claim of parity that never existed; this test fails under that
old default and pins the truthful state.
"""

from __future__ import annotations

from mql5bot import indicator_universe as iu


def test_no_kind_claims_mql5_parity_without_owner_evidence():
    offenders = sorted(k for k in iu.ALL_KINDS
                       if iu.contract(k).mql5_status == "parity-tested")
    assert offenders == [], (
        "these kinds claim MQL5 'parity-tested' but no owner MT5 compile / "
        "Strategy-Tester evidence exists (REALITY_GATE_BLOCKED): "
        f"{offenders}")


def test_every_kind_is_canonical_defined_pending_owner_compile():
    for k in iu.ALL_KINDS:
        assert iu.contract(k).mql5_status == "canonical-defined", k
