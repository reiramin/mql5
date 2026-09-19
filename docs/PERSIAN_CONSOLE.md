# خروجی فارسی کنسول — Persian / RTL console output

An opt-in Persian, right-to-left PRESENTATION layer over the CLI's
human-facing console output. Presentation only: no computed value, stored
status string, JSON field, artifact (HTML reports, manifests, parity or
evidence files) or exit code changes — the default stays English and
byte-identical, proven by tests (`tests/test_i18n_fa.py`).

## Opting in

```sh
mql5bot --lang fa backtest --data data/EURUSD_H1.csv --strategy ema_crossover
# or, for a whole shell session:
export MQL5BOT_LANG=fa
```

The `--lang` flag (accepted before or after the subcommand) wins over the
environment variable. An unknown `--lang` value fails cleanly; an unknown
`MQL5BOT_LANG` value falls back to English.

## What Persian mode does — and deliberately does not — change

- Labels and sentences are translated (the single table lives in
  `python/mql5bot/i18n.py` — `MESSAGES_FA`; a missing key falls back to
  English, never raises).
- Numbers presented for a human get Persian digits (۰–۹). Latin identifiers,
  symbol names, hashes, JSON, URLs and file paths are **never** translated,
  reordered, or digit-substituted — they are wrapped in Unicode directional
  isolates (LRI…PDI) so RTL layout cannot scramble them and they stay
  copyable.
- Column alignment uses a display width that ignores the zero-width bidi
  control characters, so mixed-direction tables stay aligned.

## Protected certification vocabulary

`SOFTWARE_PASS`, `EMPIRICAL_VALIDATION_PENDING`, `VERIFIED`, `NOT VERIFIED`,
`GOLD_SEMANTIC_PASS`, `MT5-VALIDATED`, `BLOCKED_OWNER_ENVIRONMENT` are never
translated: these words carry precise evidential meaning and a Persian
synonym would misrepresent what was proven. `i18n.explain_status(term, "fa")`
shows the Persian explanation ALONGSIDE the verbatim original term, never
instead of it.
