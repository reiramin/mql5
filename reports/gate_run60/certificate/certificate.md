# AEGIS owner-gate certificate

- **Verdict:** MT5_VALIDATED_BAR_MODELS
- **Certificate scope:** bar models -- no real-tick claim; m1_ohlc + every_tick only
- **Source commit:** 50cdb71c149c24689a89dba2dfac97b1afd9dd1c
- **Issued (UTC):** 2026-10-13T11:18:14.073977+00:00
- **reconciliation_verify.json sha256:** 72a325ae57ec51da65a2a733680642d446119a113e24014c4abd5f863261eff1
- **archive_manifest.json sha256:** bd624aa1285fe2c202c9df1bc2a5b12ad49e6c601c420f942e18cef7d121e11e

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
