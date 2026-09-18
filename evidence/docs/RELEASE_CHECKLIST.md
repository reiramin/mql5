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
 5. Static checks pass                   ruff check python tests (clean);
                                          authority/order-sending scans clean
 6. Docs consistency checks pass         tests/test_docs_contract.py green
 7. Gold fixtures intact                 Gold #1 regen byte-identical;
                                          Gold #2 hash chain green;
                                          freeze-pin (anchor ancestry) green
 8. Certification tooling intact         certify_strategy / run_mt5_backtest /
                                          broker_symbol_parity imports green
 9. Owner gate correctly blocked         verifier on the template package is
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

## Owner-side MT5 release gate

**Remains BLOCKED until actual Windows/MT5 evidence exists.** No item
below can be satisfied by the sandbox, by simulation, or by wording:

```text
[ ] strict compile: 0 errors / 0 warnings, fresh EX5, six provenance fields
[ ] broker SymbolSpec exported and compared (no DECISION_CHANGING_MISMATCH)
[ ] Gold #1 legs: M1 OHLC / Every Tick / Real Ticks, model triads agree
[ ] Gold #2 legs (56-trade fixture): same three models
[ ] real-tick coverage recorded honestly (FULL only with positive proof)
[ ] reconciliation bound + verified for both golds
[ ] safety runtime exercises with bound raw evidence
[ ] netting / hedging recorded independently (hedging may be
    BLOCKED_OWNER_ENVIRONMENT, never a fabricated pass)
[ ] archive manifest binds every artifact
[ ] tools/verify_owner_mt5_gate.py exits 0 on the returned directory
```

Only then may `REALITY_GATE_BLOCKED` move — and only to the state the
evidence supports (`MT5_VALIDATED` at most from this gate; empirical /
demo / live are later, separate gates).

## After a successful owner gate

Empirical lane per `AEGIS_EMPIRICAL_LANE_PACKAGE.md` (still owner
environment), then demo per `CERTIFICATION_GUIDE.md`, then live — each
with its own human approvals. `PRODUCTION = NOT_READY` until every one
of them is independently satisfied.
