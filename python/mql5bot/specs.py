"""mql5bot.specs — canonical synthetic broker fixtures (research foundation).

Single source of cross-asset :class:`~mql5bot.symbolspec.SymbolSpec`
fixtures shared by the Sizer, the backtest engine and every risk test
(AEGIS Phase 2.5, Phase 1).  The six fixtures cover the asset classes the
research engine must behave correctly on:

* FX majors (EURUSD, GBPUSD — 5-digit, tick == point)
* JPY FX (USDJPY — profit currency differs from deposit currency)
* metals (XAUUSD — tick 0.01, 100 oz contract)
* index CFD (US30 — tick 0.25 is a MULTIPLE of the printed 0.01 point)
* crypto CFD (BTCUSD — 1 coin/lot, tiny volume step, tick value is NOT
  ``tick_size * contract_size``; broker markup)

Values are synthetic and pinned for deterministic unit tests, not live
broker facts.  ``FIXTURE_PROFIT_TO_DEPOSIT`` pins the profit-currency ->
deposit-currency conversion used by the fixtures; live research must
inject the runtime conversion instead of importing these numbers.

Everything mirrors broker facts the MQL5 EA queries at runtime
(SPEC §3.3/§3.10) and the MQL5 port ``mql5/Include/Mql5Bot/SymbolSpec.mqh``.
"""

from __future__ import annotations

from .symbolspec import SymbolSpec

#: Canonical synthetic specs, keyed by symbol name.
SYNTHETIC_SPECS: dict[str, SymbolSpec] = {
    # classic 5-digit FX: tick 0.00001 == point, $1 per tick per 1.0 lot
    "EURUSD": SymbolSpec(
        name="EURUSD", digits=5, point=1e-5, tick_size=1e-5,
        tick_value_loss=1.0, contract_size=100_000.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=10.0,  # 0.0001 min stop distance
        currency_profit="USD", currency_deposit="USD",
    ),
    "GBPUSD": SymbolSpec(
        name="GBPUSD", digits=5, point=1e-5, tick_size=1e-5,
        tick_value_loss=1.0, contract_size=100_000.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=10.0,
        currency_profit="USD", currency_deposit="USD",
    ),
    # 3-digit JPY pair: tick value expressed in JPY (profit currency)
    "USDJPY": SymbolSpec(
        name="USDJPY", digits=3, point=0.001, tick_size=0.001,
        tick_value_loss=100.0, contract_size=100_000.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=10.0,  # 0.010 JPY min stop distance
        currency_profit="JPY", currency_deposit="USD",
    ),
    # metals: 2 digits, tick 0.01, 100 oz contract -> $1/tick/lot
    "XAUUSD": SymbolSpec(
        name="XAUUSD", digits=2, point=0.01, tick_size=0.01,
        tick_value_loss=1.0, contract_size=100.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=20.0,  # 0.20 min stop distance
        currency_profit="USD", currency_deposit="USD",
    ),
    # index CFD with a tick that is a MULTIPLE of the printed point,
    # integer volume grid, contract 10 -> $2.5 per tick per 1.0 lot
    "US30": SymbolSpec(
        name="US30", digits=2, point=0.01, tick_size=0.25,
        tick_value_loss=2.5, contract_size=10.0,
        volume_min=1.0, volume_max=200.0, volume_step=1.0,
        stops_level_points=25.0,  # 0.25 price units
        currency_profit="USD", currency_deposit="USD",
    ),
    # crypto CFD: 1 coin per lot, tiny volume step, tick value per tick is
    # NOT tick_size * contract_size (broker-specific markup)
    "BTCUSD": SymbolSpec(
        name="BTCUSD", digits=2, point=0.01, tick_size=0.01,
        tick_value_loss=0.0105, contract_size=1.0,
        volume_min=0.001, volume_max=100.0, volume_step=0.001,
        stops_level_points=0.0, volume_limit=50.0,
        currency_profit="USD", currency_deposit="USD",
    ),
}

#: Pinned conversion rates (profit currency -> deposit currency) used by the
#: fixtures when a test exercises multi-currency profit.  Live research must
#: inject the runtime quote conversion; never import these for live use.
FIXTURE_PROFIT_TO_DEPOSIT: dict[str, float] = {
    "EURUSD": 1.0,
    "GBPUSD": 1.27,
    "USDJPY": 1.0 / 150.0,
    "XAUUSD": 1.0,
    "US30": 1.0,
    "BTCUSD": 1.0,
}


def synthetic_spec(symbol: str) -> SymbolSpec:
    """Return the canonical synthetic spec for ``symbol`` (copy semantics:
    the dataclass is frozen/immutable, safe to share)."""
    if symbol not in SYNTHETIC_SPECS:
        raise KeyError(f"no synthetic spec for {symbol!r}; have {sorted(SYNTHETIC_SPECS)}")
    return SYNTHETIC_SPECS[symbol]


def synthetic_profit_to_deposit(symbol: str) -> float:
    """Fixture conversion for ``symbol`` (raises for unknown symbols)."""
    if symbol not in FIXTURE_PROFIT_TO_DEPOSIT:
        raise KeyError(
            f"no fixture conversion for {symbol!r}; have {sorted(FIXTURE_PROFIT_TO_DEPOSIT)}")
    return FIXTURE_PROFIT_TO_DEPOSIT[symbol]


__all__ = [
    "FIXTURE_PROFIT_TO_DEPOSIT",
    "SYNTHETIC_SPECS",
    "synthetic_profit_to_deposit",
    "synthetic_spec",
]
