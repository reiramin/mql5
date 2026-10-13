# Release / Operations Checklist

The exact final pre-release sequence. Every item is mechanically
checkable; none may be skipped or softened.

## Sandbox-side release gate

```text
 1. Clean git tree                       git status --short  (empty)
 2. Main branch canonical                main == canonical implementation;
                                          remote verified via ls-remote
 3. Python dependencies coherent         pyproject extras == real imports;
                                          no drift with requirements.txt
 4. Tests pass                           python -m pytest  (0 failed / 0 errors)
 5. Static checks pass                   ruff check python/ tests/ tools/ factory/
                                          (clean, canonical scope);
                                          authority/order-sending scans clean
 6. Docs consistency checks pass         tests/test_docs_contract.py green
 7. Gold fixtures intact                 Gold #1 regen byte-identical;
                                          Gold #2 hash chain green;
                                          freeze-pin (anchor ancestry) green
 8. Certification tooling intact         owner_gate_decide / gate_certificate /
                                          verify_owner_mt5_gate / broker_symbol_parity
                                          imports green
 9. Owner gate fails closed              verifier on the template package is
                                          NOT positive; PENDING_OWNER intact
10. No fake evidence                     zero fabricated EX5/log/report/spec
                                          hashes anywhere in the tree
11. No stale docs                        command examples map to real entry
                                          points; status labels match evidence
12. No secrets                           no tokens/credentials/keys committed
13. README matches reality               pinned scope statements present;
                                          statuses not collapsed
14. Main pushed                          origin main == local main
15. Final commit recorded                CHANGELOG entry names the release
```

## Before any real money — the pre-live checklist

This checklist aligns with, and does not replace, the ordered pre-live
checklist in [OWNER_DELIVERY.md](OWNER_DELIVERY.md) §5 (historical, the
2026-09-20 run). gate_run59 certified the EA (MT5 execution-parity and safety certificate, bar models, no real-tick claim, no profitability claim):
the gold #1 rebuild, the log-graded stage 5, stage 8 reconciliation and
stages 9–10 are done. Still open, in order: the BTC denomination verdict;
≥4 weeks demo / ≥30 trades; a VPS deployment and an uptime/recovery drill
(see [DEPLOYMENT.md](DEPLOYMENT.md) — never done).

## Owner-side MT5 release gate

No item below can be satisfied by the sandbox, by simulation, or by
wording. State as of gate_run59 (`[x]` = satisfied by that run's evidence):

```text
[x] strict compile: 0 errors / 0 warnings, fresh EX5 (stage 1; the provenance fields are as the gate records them)
[x] broker SymbolSpec exported and compared (no DECISION_CHANGING_MISMATCH)
[x] Gold #1 legs: M1 OHLC / Every Tick (Real Ticks NOT_APPLICABLE: bar-only fixture)
[x] Gold #2 legs: same two models (Real Ticks NOT_APPLICABLE)
[x] real-tick coverage recorded honestly: NONE (bar-only fixture)
[x] reconciliation bound + verified for both golds (18/18, 37/37)
[x] safety runtime exercises with bound raw evidence (8/8 VALID)
[x] netting / hedging recorded independently (demo accounts, stage 7)
[x] archive manifest binds every artifact
[x] tools/verify_owner_mt5_gate.py exits 0 (MT5_VALIDATED_BAR_MODELS)
[ ] a real-tick leg (needs a fixture with a tick dataset)
```

The state moved only as far as the evidence supports:
`MT5_VALIDATED_BAR_MODELS` (no real-tick claim). `MT5_VALIDATED` needs a
real-tick leg; empirical / demo / live are later, separate gates.

## After a successful owner gate

Empirical lane per `AEGIS_EMPIRICAL_LANE_PACKAGE.md` (still owner
environment), then demo per `CERTIFICATION_GUIDE.md`, then live — each
with its own human approvals. `PRODUCTION = NOT_READY` until every one
of them is independently satisfied.
