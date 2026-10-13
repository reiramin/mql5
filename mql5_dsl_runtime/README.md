# Generic MQL5 DSL Runtime — integrated owner-pending surface

The runtime sources are integrated under `mql5/Include/Mql5Bot/` and the
parity script is under `mql5/Scripts/Mql5Bot/`. The EA can load an executable
bundle through `InpDslBundleFile` and produces `SBotSignal` before the existing
RiskManager, Meta allocation, and TradeManager path.

Status: the owner gate exercises it on every run. Stage 2 (`dsl_parity`)
requires 14/14 fixtures EXACT with the tampered bundle refused, and the gold
tester legs run the gold strategy through this runtime; gate_run59 certified
those legs (MT5 execution-parity and safety certificate, bar models, no
real-tick claim, no profitability claim). Indicator kinds beyond the six it
implements (EMA, RSI, ATR, DONCHIAN, HIGHEST, LOWEST) remain owner-pending
and are refused.

Execution chain:

```
DSL bundle -> generic DSL runtime -> SBotSignal -> RiskManager veto
           -> Meta allocation -> TradeManager order authority -> MT5
```

The generic runtime is fail-closed for unsupported bundle structure and
indicator kinds. The owner must complete and verify any remaining TODOs,
then run every fixture in `artifacts/dsl_parity/` against byte-identical
offline OHLC data. No parity or certification result is implied by this
source integration.
