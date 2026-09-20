# Telegram — alerts, digest, and the four commands

This is the owner's primary interface (Phase 1 of [ROADMAP_UX.md](ROADMAP_UX.md)),
built on the existing alert channel. It pushes a daily digest and per-trade
notifications to the owner's phone, and accepts four read-or-stop commands.

> **Built and unit-tested; never run against a live bot.** Nothing here has
> talked to Telegram's servers or a running EA. Treat it as untested until you
> have run it yourself.

## Asymmetric friction — the binding rule

**Stopping is easy; starting is hard.** The `stop` command acts immediately,
with no confirmation. There is **no resume** — no command, no code path, not
behind a password — that can start or re-enable trading from Telegram.
Resuming is only possible from the console. The rationale is a threat model: a
lost, unlocked phone can only ever *stop* the bot, never start it.

## Commands

Sent as a chat message; the leading `/` is optional.

| Command | Effect |
|---|---|
| `status` | alive?, engine state, whether new trades are allowed, distance to the loss limit |
| `positions` | the open positions (symbol, side, lots) |
| `report` | the full daily digest on demand |
| `stop` | trips the kill switch immediately — no confirmation, no inverse command |

A message from a chat id that is not on the allow-list is ignored and logged
without echoing its content.

## Notifications

- **Daily digest** at the configured local time: alive/not, trades today,
  realised P&L today, open positions, and the distance to the drawdown limit.
- **Per-trade open/close** notifications, toggleable — turning them off leaves
  the digest and the watchdog alerts flowing.
- The existing **watchdog alerts** (stale heartbeat, drawdown, engine state).

No message ever contains an account number, token, chat id, or file path.

## Environment variables

All credentials come from the environment. **The token is never committed,
never put in a tracked `.env`, and never pasted into a chat or an issue.**

| Variable | Meaning |
|---|---|
| `MQL5BOT_TELEGRAM_BOT_TOKEN` | the bot token from @BotFather — **secret** |
| `MQL5BOT_TELEGRAM_CHAT_ID` | the chat the digest and alerts are sent to |
| `MQL5BOT_TELEGRAM_ALLOWED_CHAT_IDS` | comma-separated list of chat ids allowed to send commands |
| `MQL5BOT_TELEGRAM_PER_TRADE` | `1`/`true`/`on` enables per-trade notifications; anything else = digest only |
| `MQL5BOT_TELEGRAM_DIGEST_TIME` | local time of the daily digest, `HH:MM` (24h); default `22:00` |

A missing `MQL5BOT_TELEGRAM_BOT_TOKEN` or `MQL5BOT_TELEGRAM_CHAT_ID` fails
construction naming the variable, never its value.

## Wiring (outline)

`mql5bot.notify.telegram.TelegramChannel` is the delivery channel (reused for
alerts, the digest, and command replies — one rate-limited, token-scrubbed
path). `mql5bot.notify.telegram_ops.TelegramOperator` adds the digest, the
per-trade notifications, and the four commands on top of it, and trips the
`KillSwitch` on `stop`. Both take an injected transport and clock, so tests
never touch the network.
