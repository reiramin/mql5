# Rules for any agent working in this repository

- NEVER modify mql5/, artifacts/, evidence/, logs_owner/, frozen_inputs.json,
  certification_manifest.json, or any manifest. These are the compile-of-record and
  frozen evidence. Any change there invalidates the owner certification gate.
- No new third-party dependency. Standard library first; fastapi/jinja2/httpx are the
  existing set (see requirements.txt).
- Never state or imply a profit claim, anywhere, in any file.
- The certification gate result is truth: stage 5 is FAIL, BLOCKED is not a pass,
  stages 6-10 have never run. Never describe them otherwise.
- Anything built but never run against a live system is written as
  "built, unit-tested, never run live" — never "done", never "working".
- Every "done" must be checkable against a file, a test, or a hash. Never invent a
  hash, a test count, or a result you did not see in output.
- A verdict may only be justified by evidence scoped to the thing being judged. Never
  let one unit's result justify another's.
- Work on a branch. Never commit to master directly. Never amend or force-push.
- Before committing: ruff on python/ tests/ tools/ factory/ must exit 0, and the full
  pytest suite must exit 0. Read exit codes, do not poll for summary lines.
- Secrets come from environment variables only; never in code, docs, commits or logs.
- End every session by appending a dated entry to AUTONOMOUS_LOG.md: branch, commits,
  test exit code, what was done, what was NOT done and why.
