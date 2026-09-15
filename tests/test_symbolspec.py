"""Tests for the canonical broker-symbol specification and normalisers
(SPEC §3.3/§3.10, DoD #9/#10) and the FNV-1a magic identity (SPEC §3.9)."""

import json

import pytest
from mql5bot.symbolspec import (
    FNV1A_MASK32,
    MAGIC_BASE,
    MAGIC_MAX,
    MAGIC_SPAN,
    MagicRegistry,
    SymbolSpec,
    derive_magic,
    enforce_min_stop,
    fnv1a32,
    normalize_volume,
    round_to_tick,
    ticks_of,
)

# ---------------------------------------------------------------------------
# Synthetic broker specs required by SPEC DoD #9 — single source of truth
# is mql5bot.specs (canonical fixtures shared by Sizer / backtester / risk
# tests, AEGIS Phase 2.5).  The five original + GBPUSD live there.
# ---------------------------------------------------------------------------


def make_specs() -> dict[str, SymbolSpec]:
    from mql5bot.specs import SYNTHETIC_SPECS

    return {name: spec for name, spec in SYNTHETIC_SPECS.items()}


@pytest.fixture(scope="module")
def specs() -> dict[str, SymbolSpec]:
    return make_specs()


def test_specs_are_sane(specs):
    assert set(specs) == {"EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30", "BTCUSD"}
    for s in specs.values():
        assert s.tick_size > 0 and s.point > 0 and s.contract_size > 0
        assert 0 < s.volume_min <= s.volume_max
        assert s.volume_step > 0


# ---------------------------------------------------------------------------
# FNV-1a + magic registry (SPEC §3.9)
# ---------------------------------------------------------------------------


def test_fnv1a_classic_vectors():
    assert fnv1a32("") == 0x811C9DC5
    assert fnv1a32("a") == 0xE40C292C
    assert 0 <= fnv1a32("a") <= FNV1A_MASK32


def test_derive_magic_range_and_determinism():
    m1 = derive_magic("ema_crossover")
    m2 = derive_magic("ema_crossover")
    assert m1 == m2
    assert MAGIC_BASE <= m1 <= MAGIC_MAX
    assert MAGIC_SPAN > 1000


def test_derive_magic_unique_on_sample():
    ids = [f"strat_{i}" for i in range(200)]
    magics = [derive_magic(i) for i in ids]
    assert len(set(magics)) == len(magics)


def test_derive_magic_probes_collisions_deterministically():
    # tiny span forces a collision between two ids with the same primary slot
    base, span = 1000, 8
    seen: dict[int, str] = {}
    colliders: list[str] = []
    for i in range(500):
        id_ = f"cand_{i}"
        slot = fnv1a32(id_) % span
        # require the successor slot to be reachable without wrapping
        if slot in seen and slot < span - 1:
            colliders = [seen[slot], id_]
            break
        seen[slot] = id_
    assert colliders, "test data did not produce a usable collision"
    first = derive_magic(colliders[0], base=base, span=span)
    second = derive_magic(colliders[1], [first], base=base, span=span)
    # second probes to the first free slot after its (occupied) primary slot
    assert second == first + 1
    assert second < base + span


def test_magic_registry_stability_across_removal_and_reload():
    reg = MagicRegistry()
    a = reg.allocate("alpha")
    b = reg.allocate("beta")
    c = reg.allocate("gamma")
    assert len({a, b, c}) == 3
    assert reg.get("beta") == b

    # removal + re-add must return the SAME magic (no reallocation churn)
    reg2 = MagicRegistry({k: v for k, v in reg._map.items() if k != "beta"})
    assert reg2.allocate("beta") == b
    # a fresh process "reload" from JSON keeps everything stable
    reg3 = MagicRegistry.from_json(reg.to_json())
    for i in range(300):
        reg3.allocate(f"extra_{i}")
    for k, v in reg._map.items():
        assert reg3.get(k) == v, f"reload changed magic of {k}"


def test_magic_registry_json_roundtrip_and_corruption():
    reg = MagicRegistry()
    for i in range(50):
        reg.allocate(f"s{i}")
    payload = reg.to_json()
    again = MagicRegistry.from_json(payload)
    assert again._map == reg._map
    assert json.loads(payload)["s0"] == reg.get("s0")
    with pytest.raises(ValueError):
        MagicRegistry.from_json('{"a": "not-an-int"}')
    with pytest.raises(ValueError):
        MagicRegistry.from_json("[1,2,3]")


# ---------------------------------------------------------------------------
# Volume / price normalisers
# ---------------------------------------------------------------------------


def test_normalize_volume_floors_to_step(specs):
    eurusd = specs["EURUSD"]
    assert normalize_volume(0.153, eurusd) == pytest.approx(0.15)
    assert normalize_volume(0.159999, eurusd) == pytest.approx(0.15)
    assert normalize_volume(0.2, eurusd) == pytest.approx(0.2)


def test_normalize_volume_min_max_and_limit(specs):
    eurusd = specs["EURUSD"]
    assert normalize_volume(0.0001, eurusd) == pytest.approx(0.01)  # -> min
    assert normalize_volume(0.0, eurusd) == 0.0
    assert normalize_volume(-1.0, eurusd) == 0.0
    assert normalize_volume(1e9, eurusd) == pytest.approx(100.0)  # -> max
    btc = specs["BTCUSD"]
    # volume_limit (50) is tighter than volume_max (100)
    assert normalize_volume(80.0, btc) == pytest.approx(50.0)
    # step alignment when clamping: cap is on the grid here
    assert normalize_volume(1234.0, specs["US30"]) == pytest.approx(200.0)


def test_normalize_volume_index_step_grid(specs):
    us30 = specs["US30"]
    assert normalize_volume(2.7, us30) == pytest.approx(2.0)  # floor to 1.0
    assert normalize_volume(0.4, us30) == pytest.approx(1.0)  # -> min


def test_round_to_tick_uses_tick_not_digits(specs):
    eurusd = specs["EURUSD"]
    assert round_to_tick(1.234561, eurusd) == pytest.approx(1.23456)
    us30 = specs["US30"]
    # tick is 0.25 while point is 0.01 — digit rounding would be wrong
    assert round_to_tick(35001.13, us30) == pytest.approx(35001.25)
    assert round_to_tick(35001.99, us30) == pytest.approx(35002.0)


def test_ticks_of_and_min_stop_enforcement(specs):
    eurusd = specs["EURUSD"]
    assert ticks_of(0.0, eurusd) == 0
    assert ticks_of(0.0023, eurusd) == 230
    us30 = specs["US30"]
    assert ticks_of(0.6, us30) == 2  # 0.6 / 0.25 -> 2 ticks
    assert ticks_of(1.3, us30) == 5  # 5.2 -> 5 ticks
    # min stop never shrinks a valid distance, and grows invalid ones
    assert enforce_min_stop(0.5, eurusd) == pytest.approx(0.5)
    assert enforce_min_stop(0.00005, eurusd) == pytest.approx(0.0001)
    # ...aligned onto the tick grid afterwards
    assert enforce_min_stop(0.1, us30) == pytest.approx(0.25)


def test_freeze_zone(specs):
    eurusd = SymbolSpec(
        name="EURUSD", freeze_level_points=20.0,
    )
    assert eurusd.freezes_before_price(1.10001, 1.10000) is True
    assert eurusd.freezes_before_price(1.10050, 1.10000) is False
