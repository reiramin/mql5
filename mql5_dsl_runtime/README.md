# Generic MQL5 DSL Runtime — integrated owner-pending surface

The runtime sources are integrated under `mql5/Include/Mql5Bot/` and the
parity script is under `mql5/Scripts/Mql5Bot/`. The EA can load an executable
bundle through `InpDslBundleFile` and produces `SBotSignal` before the existing
RiskManager, Meta allocation, and TradeManager path.

Status remains **OWNER-PENDING** until the owner verifies canonical bundle
hashing, exact offline-fixture parity, broker SymbolSpec bindings, and the
MT5 round-trip protocol. The source compiles in MetaEditor, but compilation
alone is not runtime, tester, broker, or certification evidence.

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
