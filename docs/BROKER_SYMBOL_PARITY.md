# BROKER SYMBOL PARITY — Mission 3 / AEGIS Phase 3

Parity of broker/symbol reality against the owner's live-account exports.
**Owner-gated**: the sandbox cannot reach a broker, so every owner-side
number is PENDING until the owner commits `data/broker_exports/*.json`
(produced by `mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5`). No broker
parameter is ever invented here.

## Mandated field map (pinned by `tests/test_broker_symbol_parity.py`)

| Owner export field (MT5 source) | Python `SymbolSpec` | MQL5 `SSymbolSpec` | Consumers | Tolerance |
|---|---|---|---|---|
| digits (SYMBOL_DIGITS) | `digits` | `digits` | rounding | exact |
| point (SYMBOL_POINT) | `point` | `point` | stops/freeze conversion | rel 1e-12 |
| tick_size (SYMBOL_TRADE_TICK_SIZE) | `tick_size` | `tickSize` | round_to_tick/ticks_of/min-stop | rel 1e-12 |
| tick_value_profit (SYMBOL_TRADE_TICK_VALUE_PROFIT) | `tick_value_profit` | `tickValueProfit` | gain valuation | rel 1e-9 |
| tick_value_loss (SYMBOL_TRADE_TICK_VALUE_LOSS) | `tick_value_loss` | `tickValueLoss` | **loss_per_lot → SL sizing** | rel 1e-9 |
| contract_size (SYMBOL_TRADE_CONTRACT_SIZE) | `contract_size` | `contractSize` | engine P/L | rel 1e-9 |
| volume_min / volume_max / volume_step / volume_limit | `volume_*` | `volume*` | volume grid & caps | exact |
| stops_level_points (SYMBOL_TRADE_STOPS_LEVEL) | `stops_level_points` | `stopsLevelPoints` | sizer, SlGuard, pending offset | exact |
| freeze_level_points (SYMBOL_TRADE_FREEZE_LEVEL) | `freeze_level_points` | `freezeLevelPoints` | freeze guard | exact |
| currency_profit (SYMBOL_CURRENCY_PROFIT) | `currency_profit` | `currencyProfit` | profit→deposit conversion | exact |
| trade_mode (SYMBOL_TRADE_MODE) | — (runtime) | `tradeMode` | OnNewBar entry gates | exact |
| filling_mode_mask (SYMBOL_FILLING_MODE) | — (runtime) | `fillingMode` | filling ladder FOK→IOC→RETURN | exact |
| order_mode / expiration_mode_mask | — (runtime) | `orderMode`/`expirationMode` | pending policy | exact |
| margin_initial / margin_maintenance (SYMBOL_MARGIN_*) + OrderCalcMargin probe | — (runtime `OrderCalcMargin` is authority) | — (runtime) | margin sanity cross-check | rel 1e-9 |

Asset classes required: **FX, METAL, INDEX CFD, CRYPTO** (one symbol each the
broker actually offers).

## Tick-value denomination probe (Stage A)

The old derived FX identity was not independently attestable: deriving
`fx(profit→deposit)` from `tick_value / (contract_size × tick_size)` is circular
and is forbidden. The owner export may optionally contain
`symbol.denomination_probe`; it is intentionally outside `FIELD_MAP`, so old
four-field exports remain valid input.

The exporter measures one symbol at a time with an independent
`OrderCalcProfit` witness at 1.0 lot over `N` ticks (default `N = 100`): BUY
`ask → ask - N*tick` must be a loss and SELL `bid → bid - N*tick` must be a
gain. The exporter sets `ok=true` only when both calls succeed, all required
numeric inputs and outputs are valid, and both signs are correct. The tick
values are re-read at that same probe moment. The harness returns
`ACCOUNT_CURRENCY` only when both exported tick values agree with the
account-currency witness. It returns `PROFIT_CURRENCY` only when the
structural `contract_size × tick_size` hypothesis agrees and is sufficiently
separated from the account witness; otherwise it returns `UNVERIFIED` with a
`PENDING` status. Missing, failed, inverted-sign, or ambiguous evidence never
becomes a numeric default or a conversion.

The sizer parity replay uses the independent witness only for an
`ACCOUNT_CURRENCY` verdict and uses the export's actual `account_currency`.
For `PROFIT_CURRENCY` or `UNVERIFIED`, no conversion is manufactured and the
row remains PENDING. This is observability only: no runtime risk semantics
changed, and no Python sizer or runtime risk file is modified.

The previous PENDING-forever result was a harness defect, not proof that the
broker was safe. Stage A repairs the measurement path, but broker parity is
**STILL NOT VERIFIED**. BTC remains an owner-side open measurement: no BTC
verdict is claimed until a real owner export supplies an accepted witness.

The sizer primitives (`round_to_tick`, `normalize_volume` floor semantics,
`loss_per_lot`) are replayed against the OWNER's exported grid so parity is
behavioural, not just field-by-field.

## Status

| Item | Status |
|---|---|
| Export script (`Mql5BotExportSymbolSpec.mq5`) | WRITTEN (compile owner-gated) |
| Harness (`tools/broker_symbol_parity.py`) | COMPLETE, tested |
| Schema validation + strict fail-fast | COMPLETE, tested |
| Owner exports (FX/METAL/INDEX/CRYPTO) | **PENDING — owner only** |
| Parity verdict | **NOT VERIFIED** |
