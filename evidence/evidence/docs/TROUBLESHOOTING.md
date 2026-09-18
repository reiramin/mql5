# Troubleshooting

For every class: symptom → likely cause → inspection → safe
resolution → when to STOP instead of bypassing a gate. Never invent a
fix that weakens a safety or certification boundary.

## Python environment

| Symptom | Likely cause | Inspection | Resolution |
|---|---|---|---|
| `ModuleNotFoundError: mql5bot` | not installed / wrong interpreter | `which python`, `pip show mql5bot` | activate the venv; `pip install -e ".[dev]"` |
| `externally-managed-environment` | system pip (PEP 668) | distro Python without venv | create a venv first |
| API tests fail on `TestClient` import | httpx missing | `pip list | grep httpx` | install the `dev` extra |
| optuna import errors in optimization tools | optional extra absent | `pip list | grep optuna` | `pip install -e ".[optimize]"` |
| `MetaTrader5` import fails on Linux | Windows-only package | platform check | expected on Linux — data bridge is Windows-only |

## Repository / paths

| Symptom | Likely cause | Inspection | Resolution |
|---|---|---|---|
| scripts reference missing paths | run from wrong cwd | most tools expect the repo root | `cd` to the repo root |
| stale `.ex5` used by the terminal | old binary in data folder | compare EX5 hash vs `compile_metadata.json` | recompile with the strict script; delete stale binaries |
| install script can't find MT5 folder | non-standard install | `install_mql5.py` output | pass `--folder "<MT5 Data Folder>"` |

## MetaEditor compile (owner environment)

| Symptom | Class | Action |
|---|---|---|
| compile errors in log | `COMPILE_ERROR` | record file/line/column + compiler build; STOP; classify before touching source |
| warnings under `-Strict` | `COMPILE_WARNING` | same — the strict gate is 0/0 by contract |
| MetaEditor not found / path errors | `TOOLCHAIN_ERROR` / `PATH_ERROR` | verify terminal+MetaEditor install; do not hand-compile outside the script |
| script fails before invoking MetaEditor | `ENVIRONMENT_ERROR` | PowerShell version/permissions; rerun with `-ExecutionPolicy Bypass` |

## Strategy Tester / evidence

| Symptom | Likely cause | Action |
|---|---|---|
| report Model ≠ requested model | silent model fallback / misconfig | `MODEL_IDENTITY_MISMATCH` — stop normal certification; fix the leg, don't relabel |
| real-tick leg slow/partial | missing broker tick history | official semantics: silent per-bar fallback ⇒ coverage PARTIAL/UNKNOWN; never claim FULL |
| reconciliation divergence | genuine semantic difference | FIRST divergent event → classify → authoritative side → one-sided fix → rerun both golds (`CERTIFICATION_GUIDE.md`) |
| SymbolSpec `DECISION_CHANGING_MISMATCH` | broker differs from frozen expectations | STOP; never rewrite gold fixtures to fit the broker |
| verifier: hash mismatch on any artifact | artifact edited/copied after binding | rebind with `tools/owner_evidence_bind.py`; if source truly changed, STOP and re-freeze deliberately |
| verifier: path escape / outside root | evidence file not inside the package | move the artifact into the evidence directory and rebind |
| verifier: `NOT_VERIFIED_MISSING_MT5_EVIDENCE` | incomplete package | return exactly what exists; missing is a truthful state, not a defect to hide |
| verifier exits 2 | usage/config error (e.g. missing frozen inputs) | check `--frozen` / `--repo` paths; do not "fix" by editing evidence |

## Runtime / broker

| Symptom | Likely cause | Safe resolution |
|---|---|---|
| order rejected: invalid stops | stop inside broker stops level | widen stops per SymbolSpec; never bypass the check |
| volume rejected | outside min/max/step/limit | normalize per SymbolSpec contract (sizer already does; investigate if it recurs) |
| insufficient margin | sizing vs margin mode | Risk reduces/rejects by contract; do not raise leverage to compensate |
| WebRequest telemetry fails | URL not whitelisted | Tools → Options → Expert Advisors → allow the URL; telemetry failure never blocks trading logic |
| position lost after restart | adoption failed | verify magic mapping; restart matrix in `MT5_ROUNDTRIP.md`; never re-enter to "fix" exposure |
| not enough history for indicators | warmup window | expected: no signal during warmup; extend history, don't shorten warmup semantics |

## Environment availability

| Symptom | Meaning |
|---|---|
| sandbox/CI cannot compile MQL5 or run the tester | expected — `OWNER_ENVIRONMENT_UNAVAILABLE`; the handoff procedure in `artifacts/owner_mt5_gate/README.md` applies |

## When to STOP

Any time the tempting next step is: edit a gold artifact, relabel a
model, claim FULL coverage without proof, convert BLOCKED into PASS,
dual-patch a divergence, or run live capital to "confirm". Those are
gate bypasses, not fixes.
