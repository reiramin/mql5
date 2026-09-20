# Telegram — alerts, digest, and the four commands

The owner's primary interface (Phase 1 of [ROADMAP_UX.md](ROADMAP_UX.md)),
built on the existing alert channel. It pushes watchdog alerts, a daily digest
and per-trade notifications to the owner's phone, and accepts four read-or-stop
commands. This single document covers the whole feature (it supersedes the
former `TELEGRAM_ALERTS.md`).

> **Built and unit-tested; never run live.** Nothing here has talked to
> Telegram's servers or a running EA. Treat it as untested until you have run
> it yourself. And nothing in this project is certified — see
> [OWNER_DELIVERY.md](OWNER_DELIVERY.md).

## Running it

```sh
# reads ALL configuration from the environment (below); refuses to start,
# naming a missing variable, if the credentials are absent
python -m mql5bot.notify.telegram_ops
```

The runner prints, on startup, what it is and the asymmetric-friction rule
(stop from Telegram, resume console-only), then long-polls Telegram for
commands. It never bundles a secret and never echoes a token value.

## Asymmetric friction — the binding rule

**Stopping is easy; starting is hard.** The `stop` command acts immediately,
with no confirmation. There is **no resume** — no command, no code path, not
behind a password — that can start or re-enable trading from Telegram.
Resuming is only possible from the console. The rationale is a threat model: a
lost, unlocked phone can only ever *stop* the bot, never start it.

## Commands

Sent as a chat message; the leading `/` is optional. Each reads state; none
invents it.

| Command | Effect |
|---|---|
| `status` | alive?, engine state, whether new trades are allowed, distance to the loss limit |
| `positions` | the open positions (symbol, side, lots) |
| `report` | the full daily digest on demand |
| `stop` | trips the kill switch immediately — no confirmation, no inverse command |

A message from a chat id that is not on the allow-list is ignored and logged
without echoing its content.

## Notifications

- **Watchdog alerts** — stale heartbeat, drawdown, engine state. The Telegram
  channel is a delivery `channel` for the existing
  `mql5bot.discovery.safety.Watchdog` (`channel: Callable[[dict], None]`); it
  adds no monitoring logic and does not touch Watchdog's per-kind rate limit.
- **Daily digest** at the configured local time: alive/not, trades today,
  realised P&L today, open positions, and the distance to the drawdown limit.
- **Per-trade open/close** notifications, toggleable — turning them off leaves
  the digest and the watchdog alerts flowing.

A message carries only the alert kind / trade fields / requested state — never
an account number, balance, token, chat id, or file path.

## Creating the bot (once)

1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts.
   BotFather returns the **bot token** — this is `MQL5BOT_TELEGRAM_BOT_TOKEN`.
2. Add the bot to the chat that should receive alerts (or start a DM with it).
3. Find the **chat id** (e.g. send a message and read
   `https://api.telegram.org/bot<TOKEN>/getUpdates`). That id is
   `MQL5BOT_TELEGRAM_CHAT_ID`; put the ids allowed to send commands in
   `MQL5BOT_TELEGRAM_ALLOWED_CHAT_IDS`.

## Environment variables

All configuration comes from the environment. **The token is never committed,
never put in a tracked `.env`, and never pasted into a chat or an issue.**

| Variable | Meaning |
|---|---|
| `MQL5BOT_TELEGRAM_BOT_TOKEN` | the bot token from @BotFather — **secret** |
| `MQL5BOT_TELEGRAM_CHAT_ID` | the chat the digest and alerts are sent to |
| `MQL5BOT_TELEGRAM_ALLOWED_CHAT_IDS` | comma-separated chat ids allowed to send commands |
| `MQL5BOT_TELEGRAM_PER_TRADE` | `1`/`true`/`on` enables per-trade notifications; anything else = digest only |
| `MQL5BOT_TELEGRAM_DIGEST_TIME` | local time of the daily digest, `HH:MM` (24h); default `22:00` |

```sh
export MQL5BOT_TELEGRAM_BOT_TOKEN='123456789:AA...'   # secret — never commit
export MQL5BOT_TELEGRAM_CHAT_ID='-1001234567890'
export MQL5BOT_TELEGRAM_ALLOWED_CHAT_IDS='-1001234567890'
```

A missing `MQL5BOT_TELEGRAM_BOT_TOKEN` or `MQL5BOT_TELEGRAM_CHAT_ID` fails
construction naming the variable, never its value. A local, untracked `.env`
(git-ignored) is the intended place to keep these on the operator's machine.

## The token is a secret — why the scrubbing matters

The token appears **inside the request URL**
(`https://api.telegram.org/bot<TOKEN>/sendMessage`), so it would otherwise leak
through every network-error string. The channel scrubs the token **by value**
(replacing it with `<redacted>`) before any exception, breadcrumb, or log line
leaves the module.

## Behaviour under failure

- Every send has a bounded timeout (default 5 s). The channel never blocks the
  Watchdog: on failure it gives up for that one alert (no retry loop, no
  backoff sleep) and raises a scrubbed exception so Watchdog records a
  breadcrumb and keeps monitoring.
- A minimum send interval (default 1 s) is enforced by **skipping** sends that
  arrive too soon — Telegram's own rate limit is respected without sleeping.

## Wiring (outline)

`mql5bot.notify.telegram.TelegramChannel` is the delivery channel (reused for
alerts, the digest, and command replies — one rate-limited, token-scrubbed
path). `mql5bot.notify.telegram_ops.TelegramOperator` adds the digest, the
per-trade notifications, and the four commands on top of it, and trips the
`KillSwitch` on `stop` (see [KILL_SWITCH.md](KILL_SWITCH.md)). Both take an
injected transport and clock, so tests never touch the network.
