# Telegram alert channel — operator guide

`mql5bot.notify.telegram.TelegramChannel` delivers `Watchdog` alerts to a
Telegram chat. It is a **channel** for the existing
`mql5bot.discovery.safety.Watchdog` (`channel: Callable[[dict], None]`), not a
second alerting system — it adds no monitoring logic and does not touch
Watchdog's per-kind rate limiting.

```python
from mql5bot.discovery.safety import Watchdog
from mql5bot.notify.telegram import TelegramChannel

wd = Watchdog(channel=TelegramChannel())   # reads the two env vars below
```

## The two environment variables (the ONLY way to supply credentials)

| Variable | What it is |
| --- | --- |
| `MQL5BOT_TELEGRAM_BOT_TOKEN` | the bot token from BotFather |
| `MQL5BOT_TELEGRAM_CHAT_ID`   | the chat/channel id to send alerts to |

Both are read **from the environment only**. There is no CLI flag, no config
file, no default, and no literal in the code. If either is missing,
construction fails with a message that names the variable and never prints its
value.

```sh
export MQL5BOT_TELEGRAM_BOT_TOKEN='123456789:AA...'
export MQL5BOT_TELEGRAM_CHAT_ID='-1001234567890'
```

## Creating the bot (once)

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts.
   BotFather returns the **bot token** — this is `MQL5BOT_TELEGRAM_BOT_TOKEN`.
2. Add the bot to the group/channel that should receive alerts (or start a DM
   with it).
3. Find the **chat id** (e.g. send a message and read
   `https://api.telegram.org/bot<TOKEN>/getUpdates`, or use a chat-id helper
   bot). That id is `MQL5BOT_TELEGRAM_CHAT_ID`.

## The token is a secret — never commit it

- **Never** commit the token, **never** put it in a tracked `.env`, and
  **never** paste it into a chat, an issue, or a log. Anyone with the token
  controls the bot.
- The token appears **inside the request URL**
  (`https://api.telegram.org/bot<TOKEN>/sendMessage`), so it would otherwise
  leak through every network error string. The channel scrubs the token by
  value (replacing it with `<redacted>`) before any exception, breadcrumb, or
  log line leaves the module.
- A local, untracked `.env` (git-ignored — see `.gitignore`) is the intended
  place to keep the two variables on the operator's own machine. `.env` and
  `.env.*` are in `.gitignore`; a fresh clone never carries secrets.

## Behaviour under failure

- Every send has a bounded timeout (default 5 s). The channel never blocks the
  Watchdog: on failure it gives up for that one alert (no retry loop, no
  backoff sleep) and raises a scrubbed exception so Watchdog records a
  breadcrumb and keeps monitoring.
- A minimum send interval (default 1 s) is enforced by **skipping** sends that
  arrive too soon — Telegram's own rate limit is respected without sleeping.

## What an alert message contains

Only the alert kind, equity, open-position count and timestamp. It never
contains account numbers, balances, tokens, chat ids, or file paths.
