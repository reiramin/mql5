# OWNER MT5 EXECUTION — YES/NO CHECKLIST (§31)

Answer every row YES or NO (or `BLOCKED_OWNER_ENVIRONMENT` where
marked). An unanswered row keeps the status `REALITY_GATE_BLOCKED`.
Every YES requires the raw artifact named in `README.md` — a YES
without its artifact is a NO.

## Pre-flight

- [ ] The frozen-input hashes in `frozen_inputs.json` reproduced exactly
      on the owner machine? (any mismatch = STOP)

## Compile gate

- [ ] Did the EXACT pinned source compile? (`compile.ps1 -Strict`,
      exit 0, zero errors AND zero warnings counted from the log)
- [ ] Does the EX5 hash match the recorded fresh binary? (stale/cached
      `.ex5` rejected)

## SymbolSpec gate

- [ ] Did the ACTUAL SymbolSpec export succeed? (terminal/broker
      export, hashed, never the synthetic parity spec)
- [ ] Was every field comparison classified (EXACT_MATCH /
      SEMANTICALLY_COMPATIBLE / DECISION_CHANGING_MISMATCH /
      UNSUPPORTED_BROKER_DIFFERENCE), with no DECISION_CHANGING_MISMATCH
      left unresolved?

## Gold runs

- [ ] Did Gold #1 run in ALL THREE modes (M1 OHLC / Every Tick /
      Every Tick based on real ticks)?
- [ ] Did Gold #2 run in ALL THREE modes?
- [ ] Is real-tick coverage KNOWN for each real-tick leg
      (FULL/PARTIAL/UNKNOWN recorded with evidence — never assumed)?
- [ ] Did every leg's report prove the model ACTUALLY used (report
      Model line + journal, not just the command line)?

## Reconciliation

- [ ] Did Python↔MT5 reconciliation succeed for Gold #1?
- [ ] Did Python↔MT5 reconciliation succeed for Gold #2?
- [ ] Were ALL mismatches classified with exactly one class from the
      closed taxonomy (no CLOSE_ENOUGH)?
- [ ] Was the FIRST divergent bar/tick identified for every failed
      reconciliation (before any patch)?

## Safety runtime (owner demo environment)

- [ ] Did the Kill Switch runtime test pass (zero new orders while
      latched)?
- [ ] Did the SL verification runtime test pass (verify → modify →
      re-verify)?
- [ ] Did the restart/recovery test pass (pending / retry / open
      position / allocation polling)?
- [ ] Did netting pass (weighted aggregation, attribution, magic)?
- [ ] Did hedging pass — or receive an explicit
      `BLOCKED_OWNER_ENVIRONMENT` (never a fabricated pass)?

## Discipline

- [ ] Was NO live capital used (tester + controlled demo only)?
- [ ] Is every returned artifact RAW (no screenshots as primary
      evidence)?
- [ ] Was `certify_strategy.py` run with `--reconciliation` pointing
      at the recorded reconciliation artifact?
