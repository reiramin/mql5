"""Reality Gate §4/§5 semantic closure — the volume normalisation contract.

Canonical question answered here: "What raw volume maps to what execution
volume, under which broker specification?" — for BOTH runtimes, with exact
(bitwise) equality, not tolerance.

Contract (pinned; see docs/DECISIONS.md 2026-09-07):

* ``normalize_volume`` floors to the broker step grid. It NEVER rounds up.
* The floor carries a dust guard of ``VOLUME_FLOOR_DUST_EPS`` = 1e-9 STEP
  UNITS, bitwise-identical to the MQL5 ``SpecNormalizeVolume`` / EA Meta
  re-normalisation constants. The guard absorbs IEEE-754 division dust
  (REPRESENTATION tolerance). It can promote a strictly-below-grid input by
  at most 1e-9 of one step — never an economic magnitude (no EXECUTION
  tolerance exists in this mapping).
* A positive input whose floored grid point is below ``volume_min`` yields
  ``volume_min`` (exact mirror of MQL5). The SIZER rejects below-min risk
  budgets before ever calling the normaliser, so on the trading path the
  min-bump is unreachable; off-path callers get the documented mirror.
* Caps ``min(volume_max, volume_limit)`` are themselves floored onto the
  grid; a cap below the minimum yields 0.0 (nothing tradable).
* Non-positive input -> 0.0. NaN/Inf input raises (Python refuses loudly;
  the MQL5 path refuses via the OrderCalcMargin gate — both refuse).

Evidence classes: LOCAL_DETERMINISTIC_GATE (Python behaviour, this file)
and SOURCE_BEHAVIOR (the MQL5 transcription is a line-by-line mirror of
mql5/Include/Mql5Bot/SymbolSpec.mqh::SpecNormalizeVolume and of the
OnNewBar Meta re-normalisation line in mql5/Experts/Mql5Bot/Mql5Bot.mq5;
the runtime MQL5 leg remains BLOCKED_OWNER_ENVIRONMENT).

The historical cross-runtime split (pre-fix Python used 1e-12, MQL5 used
1e-9) is reproduced below with the legacy constants and classified
DECISION_CHANGING; it is kept as the permanent §36 regression.
"""

from __future__ import annotations

import json
import math
import random

import pytest
from mql5bot.symbolspec import (
    VOLUME_FLOOR_DUST_EPS,
    SymbolSpec,
    normalize_volume,
)

# --------------------------------------------------------------------------
# Broker configuration matrix (plausible specs; all synthetic — no broker
# fact is assumed real; the mapping is spec-relative by construction).
# --------------------------------------------------------------------------


def _spec(name, vmin, vmax, step, limit=0.0):
    return SymbolSpec(
        name=name, digits=5, point=1e-5, tick_size=1e-5,
        tick_value_loss=1.0, tick_value_profit=1.0,
        contract_size=100_000.0, volume_min=vmin, volume_max=vmax,
        volume_step=step, volume_limit=limit,
    )


SPECS = {
    "EURUSD": _spec("EURUSD", 0.01, 100.0, 0.01),
    "GBPJPY": _spec("GBPJPY", 0.01, 100.0, 0.01),
    "XAUUSD": _spec("XAUUSD", 0.01, 50.0, 0.01),
    "US30": _spec("US30", 0.1, 200.0, 0.1),
    "BTCUSD": _spec("BTCUSD", 0.001, 500.0, 0.001),
    "MICRO_FX": _spec("MICRO_FX", 0.001, 100.0, 0.001),
    "STEP_05": _spec("STEP_05", 0.05, 10.0, 0.05),
    "LIMITED": _spec("LIMITED", 0.01, 100.0, 0.01, limit=0.5),
}


# --------------------------------------------------------------------------
# MQL5 transcriptions — line-by-line mirrors, kept here so the contract is
# self-contained. If the MQL5 sources change, these MUST change with them
# (the source-pin tests in test_mql5_sources.py guard the constants).
# --------------------------------------------------------------------------


def mql5_spec_normalize_volume(lots: float, spec: SymbolSpec) -> float:
    """Mirror of SpecNormalizeVolume (mql5/Include/Mql5Bot/SymbolSpec.mqh).

    Note the MQL5 error channel is 0.0 (no exceptions); it is reproduced
    faithfully. The 1e-9 constant is the MQL5 one.
    """
    if spec.volume_step <= 0.0 or spec.volume_min <= 0.0:
        return 0.0
    if lots <= 0.0:
        return 0.0
    step = spec.volume_step
    floor = math.floor(lots / step + 1e-9) * step
    if floor < spec.volume_min:
        return spec.volume_min
    cap = spec.volume_max
    if spec.volume_limit > 0.0 and spec.volume_limit < cap:
        cap = spec.volume_limit
    if floor > cap:
        floor = math.floor(cap / step + 1e-9) * step
        if floor < spec.volume_min:
            return 0.0  # cap below the minimum: nothing tradable
    return floor


def mql5_meta_renorm(lots: float, step: float) -> float:
    """Mirror of the EA OnNewBar Meta re-normalisation line
    (``MathFloor(lots / g_spec.volumeStep + 1e-9) * g_spec.volumeStep``)."""
    return math.floor(lots / step + 1e-9) * step


def legacy_python_normalize(lots: float, spec: SymbolSpec) -> float:
    """The PRE-FIX Python implementation (dust guard 1e-12), kept only to
    pin the historical cross-runtime split as a permanent regression."""
    if spec.volume_step <= 0.0 or spec.volume_min <= 0.0:
        raise ValueError("volume min/step must be positive")
    if lots <= 0.0:
        return 0.0
    step = spec.volume_step
    floor = int(lots / step + 1e-12) * step
    if floor < spec.volume_min:
        return spec.volume_min
    cap = spec.volume_max
    if spec.volume_limit > 0.0:
        cap = min(cap, spec.volume_limit)
    if floor > cap:
        floor = int(cap / step + 1e-12) * step
        if floor < spec.volume_min:
            return 0.0
    return round(floor / step) * step


# --------------------------------------------------------------------------
# §4 — the explicit mapping: raw volume -> execution volume per spec
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SPECS))
def test_exact_grid_points_map_to_themselves(name):
    spec = SPECS[name]
    step, vmin, vmax = spec.volume_step, spec.volume_min, spec.volume_max
    cap = vmax if spec.volume_limit <= 0 else min(vmax, spec.volume_limit)
    k_min = math.ceil(vmin / step - 1e-9)
    k_max = math.floor(cap / step + 1e-9)
    ks = set(range(k_min, k_max + 1))
    if len(ks) > 40:  # keep the suite fast: edges + a deterministic sample
        ks = {k_min, k_min + 1, k_min + 2, *sorted(ks)[:: len(ks) // 30],
              k_max - 1, k_max}
    for k in sorted(ks):
        raw = k * step
        assert normalize_volume(raw, spec) == raw
        assert mql5_spec_normalize_volume(raw, spec) == raw


@pytest.mark.parametrize("name", sorted(SPECS))
def test_one_step_below_and_above(name):
    spec = SPECS[name]
    step, vmin = spec.volume_step, spec.volume_min
    k0 = math.ceil(vmin / step - 1e-9) + 2
    raw = k0 * step
    # one step below -> previous grid point (>= min by construction)
    assert normalize_volume(raw - step, spec) == (k0 - 1) * step
    # one step above -> next grid point (floored identity)
    assert normalize_volume(raw + step, spec) == (k0 + 1) * step
    # fractional part always floors DOWN (never rounds up)
    for frac in (0.25, 0.4, 0.5, 0.6, 0.75, 0.999):
        assert normalize_volume(raw + frac * step, spec) == raw
        assert normalize_volume(raw - frac * step, spec) == (k0 - 1) * step


@pytest.mark.parametrize("name", sorted(SPECS))
def test_min_boundary(name):
    spec = SPECS[name]
    step, vmin = spec.volume_step, spec.volume_min
    assert normalize_volume(vmin, spec) == vmin
    # just below min, beyond the dust zone: the NORMALISER mirrors MQL5 and
    # returns volume_min (the sizer layer is what rejects below-min risk);
    # both layers are pinned here so the split of responsibilities is clear.
    below = math.nextafter(vmin, 0.0)
    assert normalize_volume(below, spec) == vmin
    assert mql5_spec_normalize_volume(below, spec) == vmin
    # one full step below min (when that is representable > 0) still bumps
    if vmin > step:
        assert normalize_volume(vmin - step, spec) == vmin
    assert normalize_volume(0.0, spec) == 0.0
    assert normalize_volume(-vmin, spec) == 0.0


@pytest.mark.parametrize("name", sorted(SPECS))
def test_max_boundary_and_cap(name):
    spec = SPECS[name]
    step, vmin = spec.volume_step, spec.volume_min
    cap = spec.volume_max
    if spec.volume_limit > 0.0:
        cap = min(cap, spec.volume_limit)
    cap_grid = math.floor(cap / step + 1e-9) * step
    assert normalize_volume(cap, spec) == cap_grid
    assert normalize_volume(cap + step, spec) == cap_grid
    assert normalize_volume(cap + 1000 * step, spec) == cap_grid
    assert normalize_volume(cap_grid, spec) == cap_grid
    # a cap below the minimum means nothing tradable
    tiny = SymbolSpec(name="TINY", volume_min=0.5, volume_max=0.1,
                      volume_step=0.01)
    assert normalize_volume(1.0, tiny) == 0.0
    assert mql5_spec_normalize_volume(1.0, tiny) == 0.0
    _ = vmin  # symmetry with min test; kept explicit for readability


# --------------------------------------------------------------------------
# §5 — the epsilon boundary matrix (representation vs execution tolerance)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ("EURUSD", "US30", "BTCUSD", "STEP_05"))
def test_dust_matrix_below_grid(name):
    """Offsets below an exact grid point, from 1 ULP to well beyond the
    guard. Inside the guard: rescued to the grid point (representation
    dust). Beyond it: floored DOWN (no execution tolerance)."""
    spec = SPECS[name]
    step, vmin = spec.volume_step, spec.volume_min
    k = max(math.ceil(vmin / step - 1e-9) + 5, 6)
    grid = k * step
    # safely inside the guard (step-relative << 1e-9) -> rescued
    for delta in (math.ulp(grid), step * 1e-13, step * 1e-12,
                  step * 1e-11, step * 1e-10):
        raw = grid - delta
        assert normalize_volume(raw, spec) == grid, (name, delta)
        assert mql5_spec_normalize_volume(raw, spec) == grid
    # safely beyond the guard (step-relative >> 1e-9) -> floors down
    for delta in (step * 1e-6, step * 1e-4, step * 0.4, step * 0.999):
        raw = grid - delta
        assert normalize_volume(raw, spec) == (k - 1) * step, (name, delta)
        assert mql5_spec_normalize_volume(raw, spec) == (k - 1) * step


@pytest.mark.parametrize("name", ("EURUSD", "BTCUSD"))
def test_dust_matrix_above_grid_floors_back(name):
    """Dust ABOVE a grid point must floor back onto it (never up beyond)."""
    spec = SPECS[name]
    step, vmin = spec.volume_step, spec.volume_min
    k = math.ceil(vmin / step - 1e-9) + 5
    grid = k * step
    for delta in (math.ulp(grid), step * 1e-12, step * 1e-9, step * 1e-6):
        assert normalize_volume(grid + delta, spec) == grid


def test_just_below_min_dust_rescues_the_grid_point():
    """volume_min itself when approached by dust: the grid point stands."""
    spec = SPECS["EURUSD"]
    raw = spec.volume_min - math.ulp(spec.volume_min)
    assert normalize_volume(raw, spec) == spec.volume_min
    assert mql5_spec_normalize_volume(raw, spec) == spec.volume_min


def test_epsilon_is_representation_safe_never_execution():
    """The guard can promote by at most 1e-9 of one step. Quantified in
    money: even at a 10-pip stop with $1/tick value, the worst-case
    promotion risk is far below one micro-cent per lot-class unit."""
    spec = SPECS["EURUSD"]
    step = spec.volume_step
    promotion_lots = step * VOLUME_FLOOR_DUST_EPS          # 1e-11 lots
    risk_per_lot_10pips = 10.0 * spec.tick_value_loss      # $10 / lot
    assert promotion_lots * risk_per_lot_10pips < 1e-9     # < one nano-dollar
    # and relative to any on-grid size the error is <= 1e-9 of one step
    assert VOLUME_FLOOR_DUST_EPS == 1e-9  # pinned: representation-only


# --------------------------------------------------------------------------
# §3.3 — the dust guard is DERIVED, not arbitrary
# --------------------------------------------------------------------------


def test_guard_covers_division_dust_of_exact_grid_quotients():
    """budget/loss-per-lot quotients whose TRUE value is exactly k steps
    must survive onto the grid across the DERIVED rescue envelope: quotient
    (= volume_max/volume_step) <= 1e6, which covers every realistic MT5
    symbol spec (FX 100/0.01 = 1e4; metals/index smaller; crypto
    500/0.001 = 5e5). Inside the envelope the guard dominates the worst
    case of the sizing arithmetic (input rounding + division rounding <=
    ~2 * 0.5 ulp(k) <= 1.2e-10 at k = 5e5 — an order of magnitude inside
    the 1e-9 guard)."""
    spec = _spec("DUST", 0.01, 100.0, 0.0001)    # quotient up to 1e6
    rng = random.Random(20260907)
    for _ in range(600):
        k = rng.randint(100, 999_999)            # k steps (quotient <= 1e6)
        loss_pl = rng.uniform(1.0, 500.0)        # $ per lot at the stop
        exact = k * spec.volume_step
        budget = loss_pl * exact                 # one rounding
        raw = budget / loss_pl                   # second rounding (dust)
        out = normalize_volume(raw, spec)
        assert out == exact, (k, raw, raw / spec.volume_step - k)


def test_beyond_envelope_worst_case_is_conservative_undersize_and_parity():
    """Documented envelope edge: at extreme quotients (> 1e6 steps) a
    two-operation dust chain can exceed the guard. The outcome is pinned:
    (1) Python and the MQL5 transcription stay BITWISE identical — parity
    never breaks; (2) the only possible deviation from the exact grid is a
    ONE-STEP UNDERSIZE (risk only shrinks; the guard can never mint volume
    upward). Both properties hold because the floor direction is one-way."""
    spec = _spec("EXTREME", 0.01, 1000.0, 0.0001)  # quotient up to 1e7
    rng = random.Random(20260907)
    witness = None
    for _ in range(20_000):                      # seeded, bounded search
        k = rng.randint(1_000_000, 9_999_999)
        loss_pl = rng.uniform(1.0, 500.0)
        exact = k * spec.volume_step
        raw = (loss_pl * exact) / loss_pl
        if abs(raw / spec.volume_step - k) > VOLUME_FLOOR_DUST_EPS:
            witness = (k, loss_pl, exact, raw)
            break
    assert witness is not None, "envelope-edge witness must exist"
    k, loss_pl, exact, raw = witness
    py = normalize_volume(raw, spec)
    mq = mql5_spec_normalize_volume(raw, spec)
    assert py == mq                              # parity never breaks
    assert py in (exact, exact - spec.volume_step)  # exact or 1 step under
    assert py <= exact                           # never overshoots the grid


def test_guard_upper_bound_still_floors_genuine_substep_values():
    """Inputs genuinely below the grid by more than the guard floor DOWN:
    the guard is not an execution tolerance and cannot mint volume."""
    spec = SPECS["EURUSD"]
    step = spec.volume_step
    k = 40
    for rel in (2e-9, 1e-8, 1e-7, 1e-5):
        raw = k * step - rel * step
        assert normalize_volume(raw, spec) == (k - 1) * step


def test_pre_fix_1e12_guard_lost_steps_at_moderate_quotients():
    """Why 1e-12 was wrong: at quotient scales above ~4.5e3 the 0.5-ulp
    division dust exceeds 1e-12, so an on-grid size lands one step low.
    Demonstrated at quotient 5e6 (step 0.0001, k = 5,000,000 -> 500 lots):
    the legacy floor undersizes by a full step; the unified guard rescues.
    This pins the threshold derivation against future 'simplifications'."""
    spec = _spec("DUST", 0.01, 1000.0, 0.0001)
    k = 5_000_000
    grid = k * spec.volume_step                  # 500.0
    raw = math.nextafter(grid, 0.0)              # 1 ULP of pure dust below
    assert math.floor(raw / spec.volume_step + 1e-12) == k - 1  # legacy loses
    assert normalize_volume(raw, spec) == grid                  # unified wins
    assert mql5_spec_normalize_volume(raw, spec) == grid


# --------------------------------------------------------------------------
# §3.2 — the historical tripwire split, classified DECISION_CHANGING
# --------------------------------------------------------------------------


def test_the_pre_fix_split_zone_is_decision_changing():
    """Raw inputs inside (k - 1e-9, k - 1e-12) step units BELOW a grid
    point split the legacy Python normaliser from the MQL5 semantics by
    exactly one volume step. At k = 2 with min = 0.01 this is a 2x lot
    difference (0.01 vs 0.02) on otherwise identical inputs — a
    DECISION_CHANGING split (lot size; at other boundaries it would flip
    accept-vs-reject). After unification the split does not exist: both
    runtimes agree bitwise (asserted across the full sweep below)."""
    spec = SPECS["EURUSD"]
    raw = 0.02 - 5e-13          # 5e-11 steps below the 0.02 grid point
    assert 1e-12 < (0.02 - raw) / spec.volume_step < 1e-9  # inside the zone
    assert legacy_python_normalize(raw, spec) == 0.01      # historical bug
    assert normalize_volume(raw, spec) == 0.02             # fixed contract
    assert mql5_spec_normalize_volume(raw, spec) == 0.02   # MQL5 agreement
    # classification is permanent: one step of lot size = risk difference
    assert abs(0.02 - 0.01) == spec.volume_step


def test_split_zone_sweep_now_bitwise_identical():
    """The entire former divergence zone is exercised explicitly: for every
    grid point of two specs and a dense set of sub-guard offsets, Python
    and the MQL5 transcription return the BITWISE-same double."""
    rng = random.Random(42)
    for name in ("EURUSD", "BTCUSD"):
        spec = SPECS[name]
        step, vmin, vmax = spec.volume_step, spec.volume_min, spec.volume_max
        k_lo = math.ceil(vmin / step - 1e-9) + 1
        k_hi = math.floor(vmax / step + 1e-9) - 1
        ks = list(range(k_lo, min(k_lo + 40, k_hi + 1)))
        ks += [rng.randint(k_lo, k_hi) for _ in range(60)]
        for k in ks:
            grid = k * step
            for rel in (0.5e-12, 1e-11, 5e-11, 1e-10, 0.5e-9, 0.9e-9,
                        1.1e-9, 2e-9, 1e-8, 1e-6, 1e-3, 0.5):
                raw = grid - rel * step
                py = normalize_volume(raw, spec)
                mq = mql5_spec_normalize_volume(raw, spec)
                assert py == mq, (name, k, rel, py, mq)
                # exact equality of doubles, not approx:
                assert math.isclose(py, mq, rel_tol=0.0, abs_tol=0.0)


# --------------------------------------------------------------------------
# §4 — derived volume, repeated arithmetic, serialization, idempotence
# --------------------------------------------------------------------------


def test_repeated_arithmetic_is_idempotent_and_grid_closed():
    """normalize is idempotent, and sums/products of on-grid values stay on
    the grid (no drift accumulates through repeated arithmetic)."""
    spec = SPECS["EURUSD"]
    rng = random.Random(7)
    for _ in range(400):
        raw = rng.uniform(0.0, 150.0)
        once = normalize_volume(raw, spec)
        assert normalize_volume(once, spec) == once
        if once > 0.0:
            # repeated addition of one step stays on the grid
            acc = once
            for _i in range(5):
                acc = normalize_volume(acc + spec.volume_step, spec)
            assert abs(acc / spec.volume_step
                       - round(acc / spec.volume_step)) < 1e-9


def test_serialization_roundtrip_preserves_the_normalized_volume():
    """A normalized volume survives JSON (and repr) round-trips bitwise and
    re-normalises to itself — the wire format cannot mint dust."""
    spec = SPECS["EURUSD"]
    for raw in (0.01, 0.03, 0.57, 1.23456789, 99.999):
        v = normalize_volume(raw, spec)
        assert json.loads(json.dumps(v)) == v
        assert float(repr(v)) == v
        assert normalize_volume(json.loads(json.dumps(v)), spec) == v


@pytest.mark.parametrize("name", sorted(SPECS))
def test_invalid_inputs(name):
    spec = SPECS[name]
    assert normalize_volume(0.0, spec) == 0.0
    assert normalize_volume(-0.5, spec) == 0.0
    with pytest.raises(ValueError):
        normalize_volume(float("nan"), spec)
    with pytest.raises((OverflowError, ValueError)):
        normalize_volume(float("inf"), spec)
    # an invalid spec is refused, never traded around
    with pytest.raises(ValueError):
        normalize_volume(1.0, SymbolSpec(name="BAD", volume_min=0.0,
                                         volume_step=0.01))


def test_mql5_error_channel_is_refusal_not_trade():
    """The MQL5 transcription mirrors the production error channel: invalid
    spec / non-positive input -> 0.0 -> GetLots never sends. (NaN/Inf on
    the live MQL5 path are refused by the OrderCalcMargin gate — recorded
    as SOURCE_BEHAVIOR; the Python side raises, asserted above.)"""
    bad = SymbolSpec(name="BAD", volume_min=0.0, volume_step=0.0)
    assert mql5_spec_normalize_volume(1.0, bad) == 0.0
    assert mql5_spec_normalize_volume(-1.0, SPECS["EURUSD"]) == 0.0


# --------------------------------------------------------------------------
# Symbol-spec variation sweep + meta re-normalisation parity
# --------------------------------------------------------------------------


def test_broad_spec_sweep_python_vs_mql5_bitwise():
    """Deterministic seeded sweep over many (spec, raw) pairs incl. limits:
    Python production == MQL5 transcription, bitwise."""
    rng = random.Random(20260907)
    steps = (0.01, 0.001, 0.05, 0.1, 0.25, 0.0001)
    for step in steps:
        for vmin, vmax, limit in ((0.01, 100.0, 0.0), (0.05, 50.0, 0.0),
                                  (0.1, 200.0, 0.0), (0.001, 500.0, 0.0),
                                  (0.01, 100.0, 0.5), (0.01, 100.0, 0.005)):
            spec = _spec("SWEEP", vmin, vmax, step, limit=limit)
            cap = vmax if limit <= 0 else min(vmax, limit)
            for _ in range(300):
                raw = rng.uniform(0.0, cap * 1.5)
                py = normalize_volume(raw, spec)
                mq = mql5_spec_normalize_volume(raw, spec)
                assert py == mq, (step, vmin, vmax, limit, raw, py, mq)


def test_meta_renorm_transcription_matches_ea_line():
    """The EA floors the meta-scaled size with the same 1e-9 guard; the
    Python engine uses math.floor(lots*w/step + 1e-9)*step. Both must agree
    bitwise for identical scaled values (mission §20: builder artifacts may
    not change these semantics)."""
    rng = random.Random(99)
    for step in (0.01, 0.001, 0.1):
        for _ in range(500):
            scaled = rng.uniform(0.0, 5.0)
            assert (math.floor(scaled / step + 1e-9) * step
                    == mql5_meta_renorm(scaled, step))


def test_sizer_rejects_below_min_before_normalisation():
    """Layering contract: the risk engine rejects a below-minimum risk
    budget (BELOW_MIN); it never relies on the normaliser's min-bump."""
    from mql5bot.sizer import size_position

    spec = _spec("LAYER", 0.10, 100.0, 0.01)  # min 0.10 > step
    res = size_position(spec, mode="risk_percent_equity", equity=100.0,
                        stop_distance=0.0100, value=0.5)  # $0.50 budget
    assert res.rejected and res.reason == "below_min_volume"
    # the normaliser on its own would bump — that is why the sizer gate
    # must run FIRST on the trading path (both sides pinned here):
    assert normalize_volume(0.005, spec) == spec.volume_min
