# AEGIS owner-gate certificate

- **Verdict:** MT5_VALIDATED_BAR_MODELS
- **Certificate scope:** bar models -- no real-tick claim; m1_ohlc + every_tick only
- **Source commit:** ab312d55eefd7458ddc2bc92b6fcd770acf2f955
- **Issued (UTC):** 2026-10-13T09:37:00.729266+00:00
- **reconciliation_verify.json sha256:** 2507ef5f0ca9b5427181af5dc7505f697762a5ab2eeebdfd3dc44f0904af6a25
- **archive_manifest.json sha256:** 1db44f20b2edf73471b9dc95d662e8aa7374579a4dd99a6d1530827b0c699583

## Gold reconciliation

- gold1: MATCH (VALID)
- gold2: MATCH (VALID)

## Safety results

- hedging: INDEPENDENT_POSITIONS_ISOLATED_BY_MAGIC
- kill_switch: ZERO_NEW_ORDERS_WHILE_LATCHED
- lost_response: LOST_RESPONSE_ADOPTED_NO_DUPLICATE
- meta_reduce: ALL_SIZES_LE_RISK_APPROVED
- netting: NET_ONE_POSITION_PER_SYMBOL
- restart: RESTART_RECOVERED_NO_DUPLICATE
- risk_veto: ENTRIES_VETOED_FOR_THE_DAY
- sl_verify: SL_STRIPPED_AND_RESTORED

## Real-tick coverage

- gold1: NONE (bar-only fixture)
- gold2: NONE (bar-only fixture)

## Trade source

- graded from the tester agent log: gold1:every_tick, gold1:m1_ohlc, gold2:every_tick, gold2:m1_ohlc

## Limits

- bar models -- no real-tick claim; m1_ohlc + every_tick only
- No profitability claim. This certifies execution parity of the EA with the frozen Python expectation on the frozen gold fixtures, and the safety behaviours listed; it says nothing about future returns.
