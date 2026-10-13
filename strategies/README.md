# strategies/

`strategies/private/` holds strategy DSL bundles and parameter sets that are
**not** part of the certified gold fixtures. It is encrypted at rest with
git-crypt (`.gitattributes`); without the key a clone sees only ciphertext.
Setup, unlock on the Windows runner, and the rules are in
[docs/SECURITY.md](../docs/SECURITY.md).

Nothing the gate, the tests or the verifier read lives here. The gold
strategies (`artifacts/gold*/`, `examples/strategies/`) stay plaintext and
frozen: they are evidence. `tools/git_crypt_guard.py` (run by pytest and the
pre-commit hook) fails if a file under `strategies/private/` is ever
committed unencrypted.

This README sits outside `strategies/private/` on purpose, so it stays
readable.
