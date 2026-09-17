# Generic MQL5 DSL Runtime (staging) — OWNER-PENDING / UNCOMPILED

Status: **SOURCE-ONLY. NOT COMPILED. NOT RUNTIME-VERIFIED.**
This tree is written on Mac, where MetaEditor/MT5 do not exist, so it has
**never been compiled or run**. It is the Mac-side realization of the
generic-runtime design (mission §8–§14) for the owner to compile, complete
and verify. No compile/tester/broker/EX5 evidence is claimed.

## Why this lives OUTSIDE `mql5/`

`mql5/` is byte-frozen at anchor `227bf66` (see
`docs/WINDOWS_OWNER_HANDOFF.md`): the owner's compile-of-record maps to
that exact source hash, and `git diff 227bf66 HEAD -- mql5/` must stay
empty. Adding a generic runtime there would break that invariant and
invalidate existing owner evidence. So this staging tree is separate; the
owner integrates it and **re-anchors** provenance (new `source.commit` +
manifest + explanation, mission §26/§32) as an explicit, deliberate step.

## What problem it solves (§8/§35)

Today `mql5/Include/Mql5Bot/SignalEngine.mqh` dispatches a fixed
`switch(strategy)` over five enum families (EMA_CROSSOVER, RSI_REVERSAL,
DONCHIAN_BREAKOUT, BOLLINGER_REVERSAL, MACD_MOMENTUM). The Python DSL
runtime (`python/mql5bot/dsl/runtime.py`) is, by contrast, a *generic*
interpreter of a recursive spec. This runtime closes that gap: it consumes
the SAME canonical **executable bundle** (`python/mql5bot/dsl/bundle.py`)
and evaluates arbitrary supported strategies as DATA — so a new strategy
reaches execution without becoming one of the five enums.

## Authority model — UNCHANGED (§1/§21)

This runtime only produces a **desired signal** (direction + exit
geometry). It feeds the EXISTING `RiskManager` (final veto) and
`TradeManager` (only order authority). It never sizes, never places
orders, never widens allocation, never bypasses the SL protection. It is a
drop-in peer of `CSignalEngine`, not a replacement for Risk/Trade.

```
DslBundle (JSON, hash-bound)
   -> CDslBundleLoader   fail-closed load (mirrors Python load_bundle)
   -> CDslRuntime        indicators + recursive condition eval -> {-1,0,+1}
   -> SBotSignal         direction + SL/TP/trail geometry (same struct)
   -> RiskManager        final financial-risk veto (UNCHANGED)
   -> TradeManager       order operations (UNCHANGED)
   -> MT5
```

## Files

| File | Role |
|------|------|
| `Include/DslJson.mqh`    | Minimal bounded JSON reader (no eval, depth/size caps) |
| `Include/DslBundle.mqh`  | Bundle loader + fail-closed checks (mirror of Python §10) |
| `Include/DslRuntime.mqh` | Indicators + recursive condition/exit evaluator (mirror of runtime.py) |
| `Scripts/DslParityRunner.mq5` | Loads a bundle + offline OHLC, emits the per-bar position vector for parity |

## Fail-closed refusals (must match Python `load_bundle`, §10)

Malformed envelope · unsupported `bundle_format_version` ·
unsupported `runtime_contract_version` · missing identity ·
`bundle_hash` mismatch · unresolved ambiguity · spec-hash/identity
mismatch · indicator-contract drift · unsupported indicator / condition /
exit. On ANY of these the loader refuses and NO signal is produced.

## Scope of this reference

Implements the BASELINE indicator kinds (EMA, SMA, RSI, ATR, BBANDS,
MACD, DONCHIAN, HIGHEST, LOWEST) and the FULL condition/exit/filter
grammar — which covers the canonical example and every fixture in
`artifacts/dsl_parity/`. The 62 extended registry kinds are explicit
owner-extension points: a bundle referencing an unimplemented kind is
**refused**, never approximated.

## Owner procedure (see also `docs/WINDOWS_OWNER_HANDOFF.md`)

1. Review + integrate this tree (decide in-place vs peer module).
2. Compile in MetaEditor (`-Strict`); fix any platform-specific issues.
3. Re-anchor `artifacts/owner_mt5_gate/frozen_inputs.json` `source.commit`
   to the new snapshot; write a new manifest + provenance + explanation.
4. Run `Scripts/DslParityRunner.mq5` over each `artifacts/dsl_parity/<f>/`
   fixture; compare the exported position vector to `expected_trace.json`
   (EXACT match on positions — logical values carry no tolerance).
5. Record results; only then may any parity claim be made.

## Hard rule

Never fabricate a compile result, tester report, or parity verdict for
this tree. Until the owner compiles and runs it, its status is exactly
what this file says: **OWNER-PENDING / UNCOMPILED**.
