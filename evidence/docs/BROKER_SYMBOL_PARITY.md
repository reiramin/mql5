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

## Owner-evidence provenance — captured ≠ committed ≠ verified

Three states are kept strictly apart so the repository never over- or
under-claims:

- **CAPTURED (owner environment).** As of 2026-09-16 the owner has run the
  exporter on the live Windows account and obtained a successful
  `denomination_probe` (`ok=true`, `source=OrderCalcProfit`) for EURUSD,
  XAUEUR, US30 and BTC. The measurement was **performed** — this is not a
  gap.
- **NOT COMMITTED / NOT REPRODUCIBLE (this repo).** `data/` is
  `.gitignore`d, so those raw owner exports are not in Git and cannot be
  re-derived on Mac. On this host `tools/broker_symbol_parity.py` sees
  `n_exports:0` and reports every asset class PENDING. "Absent from the
  repo" means *not committed*, **not** *not performed*.
- **NOT VERIFIED (verdict).** `denomination_probe.ok=true` is a
  *precondition*, not a verdict. The ACCOUNT_CURRENCY vs PROFIT_CURRENCY
  decision — and hence the parity PASS — is rendered ONLY when the harness
  runs on the committed export. No verdict is claimed here; the tick-value
  denomination decision stays owner-gated (see `docs/DECISIONS.md`
  2026-09-16 Wave-1 entry).

To move from CAPTURED to VERIFIED the owner commits the exports under
`data/broker_exports/` on the certification host and re-runs the harness;
the frozen input contract for that evidence lives in
`artifacts/owner_mt5_gate/`. No raw owner export is committed merely to turn
a dashboard green, and none is fabricated.

## Status

| Item | Status |
|---|---|
| Export script (`Mql5BotExportSymbolSpec.mq5`) | WRITTEN (compile owner-gated) |
| Harness (`tools/broker_symbol_parity.py`) | COMPLETE, tested |
| Schema validation + strict fail-fast | COMPLETE, tested |
| Owner probe capture (EURUSD/XAUEUR/US30/BTC) | CAPTURED on Windows (`denomination_probe.ok=true`) — see provenance section |
| Owner exports committed to this repo | **NOT COMMITTED** (`data/` gitignored; not repo-reproducible) |
| Parity verdict (in this repository) | **NOT VERIFIED** — rendered only when exports are committed and the harness runs |
