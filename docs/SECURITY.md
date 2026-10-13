# Security — secrets at rest, encrypted outputs, account hardening

REPO-SECURITY-1 (owner decision D4, Phase 1). This changes nothing about
the EA, the gate, the verifier or any frozen artifact. Every tool here is
built, unit-tested, never run live: no key has been created, and nothing has
been encrypted with a real key.

**Rules.**
- No credential, key or token is ever committed: not in code, docs, commits
  or logs.
- Secrets come from environment variables, or from files outside the
  repository (for example the demo accounts file).
- Private keys stay on the owner's machine.

## 1. Strategy secrets: git-crypt on `strategies/private/`

**What is secret.** Strategy DSL bundles and parameter sets that are **not**
part of the certified gold fixtures.

**What is not secret.** Everything the gate, the tests or the verifier read
stays plaintext and frozen, because it is evidence:
- `artifacts/**` (gold1, gold2, the DSL parity fixtures,
  `artifacts/owner_mt5_gate/`);
- `examples/strategies/*.json` (the gold strategies, and the example and
  negative-test specs read by `owner_gate.py`, `gold_leg_inputs.py`,
  `gold2_reference.py` and the tests);
- every source file.

**No existing file moves.** Every strategy-shaped file in the tree today is
a gate, test or verifier input. `strategies/private/` starts empty.

**The rule** (in `.gitattributes`):

```
strategies/private/** filter=git-crypt diff=git-crypt
```

**The guard.**
- What it checks: `tools/git_crypt_guard.py` (run by pytest as
  `tests/test_git_crypt_guard.py`, and by the pre-commit hook) reads the
  bytes git stores. Every file under `strategies/private/` must start with
  the git-crypt header `\x00GITCRYPT\x00`.
- Why it is needed: without git-crypt installed and the repository
  unlocked, git silently commits such a file in plaintext. The guard turns
  that into a failing test.
- The other direction: the guard also fails if any gate, test or verifier
  input is ever routed through git-crypt.

### Owner setup (once, on the owner's own machine)

No key is generated or committed by any agent or tool in this repository.

```
# install git-crypt (macOS: brew install git-crypt; Debian/Ubuntu:
# apt install git-crypt; Windows: a release binary from the git-crypt
# project, or run these steps in WSL)
cd <clone of reiramin/mql5>
git-crypt init                         # creates the symmetric key in .git/git-crypt/ (never committed)
git-crypt export-key ~/mql5bot-git-crypt.key
#   -> store this file OFFLINE (password manager / encrypted backup).
#      Anyone with it can read strategies/private/. Losing it loses the data.
mkdir -p strategies/private
cp <your private bundle>.json strategies/private/
git add strategies/private/
git-crypt status -e                    # every file listed must be "encrypted"
python tools/git_crypt_guard.py        # must print OK
git commit -m "Add private strategy bundle"
```

### Unlock on the Windows MT5 runner (only if a job there needs the files)

Nothing the gate runs today reads `strategies/private/`, so the runner does
not need the key. If a future job does:

```
# copy ~/mql5bot-git-crypt.key to the runner over a secure channel
# (never e-mail, chat or a repository)
git-crypt unlock C:\Users\<user>\.mql5bot\mql5bot-git-crypt.key
#   keep the key file under the runner user's profile (NTFS ACL: that user only)
```

**Limits.**
- git-crypt encrypts file contents, not file names or sizes.
- It cannot rotate a key: old ciphertext stays readable in history with the
  old key. If the key leaks, treat everything ever committed under the path
  as disclosed.

## 2. Encrypted outputs: `tools/encrypt_outputs.py`

The tool encrypts a directory of research outputs to the owner's age public
key **before** it leaves a runner (for example before an
`actions/upload-artifact` step).
- The directory is packed into a deterministic tar in memory, so no
  plaintext archive is written to disk.
- The output is a standard age v1 file.
- Engines: the `age` binary if it is installed. Otherwise a built-in age-v1
  X25519 encryptor that uses the optional `cryptography` package, which is
  not a declared dependency.
- The tests prove interop with throwaway keys: the built-in output decrypts
  with the `age` binary, and the reverse.

### Owner setup

```
age-keygen -o ~/.age/mql5bot-owner.txt   # private identity: stays on your machine
#   prints "Public key: age1..."
```

Paste the `age1...` line into `security/age_recipients.txt`. Public keys
are safe to commit. Until a key is there, the tool refuses to run.

### In a workflow (example step; no such workflow exists yet)

```yaml
- name: Encrypt outputs before upload
  run: python tools/encrypt_outputs.py results/ --out results.tar.age
- uses: actions/upload-artifact@v4
  with:
    name: results-encrypted
    path: results.tar.age        # never upload results/ itself
```

### Decrypt (owner)

```
age -d -i ~/.age/mql5bot-owner.txt results.tar.age | tar -x
```

## 3. Secret hygiene

**`tools/secret_scan.py`** scans the tracked tree, or the files it is given.
- **What it catches:**
  - private key blocks and age secret keys;
  - GitHub, AWS, `sk-` style, Slack, Google and Telegram bot tokens;
  - MT5 credentials: an ini `Login=<5+ digits>` with a real `Password=`, or a
    JSON `"login"` of 5+ digits with a real `"password"`;
  - the demo-accounts file shape: `"hedging"` / `"netting"` with a real
    password.
- **Placeholders** (`...`, `<password>`, `${VAR}`, `%VAR%`) never match.
- **Output:** a hit prints `path:line: <pattern>` and never the value.
- **Where it runs:** `tests/test_secret_scan.py`, so every CI run and every
  local full pytest.
- **Whitelist:** only the two test files whose *fake* demo accounts (logins
  1111/2222, passwords `s3cret-*`) prove that credentials never reach the
  evidence, plus the scanner's own tests. A test fails if a whitelist entry
  stops being needed, or names a non-test file.
- **Pre-commit (optional):** `pip install pre-commit && pre-commit install`
  runs the scan, the git-crypt guard and ruff before each commit
  (`.pre-commit-config.yaml`). Skipping the hook never skips the check: CI
  runs the same tests.
- **The runner's leak check is unaffected.** Before publishing
  `reports/gate_run<N>/`, the Windows runner scans every published file for
  the real demo logins and passwords (gate_run59: 34 files, 0 hits). That
  check is the runner's procedure, not repo code. This change does not touch
  what the gate writes. It was not re-run here, because it needs the
  runner's local accounts file.

## 4. Account hardening checklist (owner, in GitHub settings)

Recommended; nothing here is force-enabled by the repository.

- [ ] **Two-factor authentication** on the GitHub account (Settings →
  Password and authentication), with an authenticator app or a security
  key. Save the recovery codes offline.
- [ ] **SSH key with a passphrase** for git (`ssh-keygen -t ed25519 -C
  "<label>"`, then Settings → SSH and GPG keys). Use no passwordless keys
  on shared machines.
- [ ] **Signed commits** (optional). An SSH signing key works:

  ```
  git config --global gpg.format ssh
  git config --global user.signingkey ~/.ssh/id_ed25519.pub
  git config --global commit.gpgsign true
  ```

  Then add the same key as a *signing* key on GitHub. The repository does
  not require signatures: agent commits are unsigned, and requiring them
  would block the developer agent.
- [ ] **Branch protection on `master`** (Settings → Branches → rule for
  `master`):
  - require a pull request before merging;
  - require the `test (3.10)`, `test (3.11)` and `test (3.12)` status checks;
  - block force pushes and deletion.
- [ ] **Secret scanning and push protection** (Settings → Code security).
  On a private repository this may need GitHub Advanced Security / Secret
  Protection.
- [ ] **Dependabot alerts** (Settings → Code security → Dependabot alerts).
- [ ] **No collaborators** beyond the owner (Settings → Collaborators).
  Review installed GitHub Apps and their repository access.
- [ ] **Private repository** (Settings → General → Danger zone → Change
  visibility), unless publishing the showcase is intended. The certificate
  and reports carry no credentials either way.

## 5. GitHub Actions secrets the future CI gate will need (names only)

None exists today. CI runs only the Python suite and needs no secret. If a
gate job is ever wired into Actions, these are the names it would use. The
values are set only in Settings → Secrets and variables → Actions, never in
the repository.

| Name | Kind | Used for |
|---|---|---|
| `GIT_CRYPT_KEY_B64` | secret | base64 of the exported git-crypt key, only if a job must read `strategies/private/` |
| `MQL5BOT_DEMO_ACCOUNTS_JSON` | secret | the demo accounts file contents, only if the demo harness ever runs on a hosted runner (today it runs on the owner's Windows runner with a local file, `MQL5BOT_DEMO_ACCOUNTS`) |
| `MQL5BOT_TELEGRAM_BOT_TOKEN`, `MQL5BOT_TELEGRAM_CHAT_ID` | secret | posting a gate result to Telegram |
| `AGE_RECIPIENTS` | variable (public) | an alternative to `security/age_recipients.txt` for `encrypt_outputs.py` |

## What this does not do

- It does not encrypt the gate evidence, the reports on `gate-reports`, or
  any frozen artifact. Those stay plaintext by design.
- It does not protect a strategy once someone with the git-crypt key, or the
  runner, has decrypted it.
- It does not replace the account hardening above: an attacker with the
  owner's GitHub session can read everything the owner can.
