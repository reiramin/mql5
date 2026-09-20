# Deployment — running the system always-on

This is Phase 3 of [ROADMAP_UX.md](ROADMAP_UX.md), written so the owner can
follow it. It describes three ways to keep the system running unattended and
recommends the split one.

> **This procedure has never been deployed or drilled.** It is a plan, not a
> proven configuration. No uptime test, recovery drill, or live run has been
> performed (see [OWNER_DELIVERY.md](OWNER_DELIVERY.md)). Treat every step as
> untested until you have run it yourself.

Nothing here contains a secret. Every credential is referenced by the name of
its environment variable only; never write a token into a tracked file.

## Why always-on at all

The bot only trades **while MetaTrader 5 is running and connected**. Close the
terminal, or let the PC sleep, and it stops. For unattended operation you need
a host that is always on. The Python services (watchdog, Telegram, console) are
a separate concern from the terminal, and — importantly — they do **not** have
to live on the same machine.

## The three options

### (a) MetaQuotes' own MT5 VPS

One click from inside the terminal (Tools → *Virtual Hosting*). Lowest latency
to the broker.

- **Runs the terminal only.** No Python. So no watchdog, no Telegram, no
  console. You would be always-on but blind — no daily digest, no stale-
  heartbeat alert, no stop command.
- Use it as the *terminal half* of the split below, not on its own.

### (b) A full Windows VPS

MT5 and every Python service on one Windows machine.

- Simplest to reason about — one host, one clock, one place to log in.
- Heaviest to manage and the most expensive option (a Windows VPS costs more
  than a small Linux box).

### (c) Split — recommended

**MT5 on (a) or a small Windows host; the Python services on a cheap Linux
host.** The architecture already supports this:

- The EA POSTs its telemetry outward via `WebRequest` to the Python collector
  (`python/mql5bot/telemetry_bridge.py`), so the Python side never needed to be
  on the same machine as MT5.
- The existing **Watchdog** already raises a Telegram alert on a stale
  heartbeat, so a VPS outage or a sleeping terminal surfaces to your phone with
  no new code.

What runs where:

| Component | Host | Notes |
|---|---|---|
| MetaTrader 5 terminal + the EA | Windows / MT5 VPS | the only piece with order authority |
| Telemetry collector (`telemetry_bridge.py`) | Linux | receives heartbeat/trade/alert POSTs from the EA |
| Watchdog + Telegram (`discovery/safety.py`, `notify/`) | Linux | daily digest, alerts, the four commands |
| Operator console (FastAPI, `api/`) | Linux | going deeper; also the ONLY place to resume after a stop |

## Configuration template for the split

Set these on the **Linux** host (environment variables — never a tracked
`.env`, never pasted into a chat or an issue):

```sh
# --- Telegram (owner's phone) ---------------------------------------------
export MQL5BOT_TELEGRAM_BOT_TOKEN="<from @BotFather>"     # SECRET — never commit
export MQL5BOT_TELEGRAM_CHAT_ID="<owner chat id>"         # where the digest goes
export MQL5BOT_TELEGRAM_ALLOWED_CHAT_IDS="<owner chat id>"  # who may send commands
export MQL5BOT_TELEGRAM_PER_TRADE="1"                     # 1=per-trade msgs, 0=digest only
export MQL5BOT_TELEGRAM_DIGEST_TIME="22:00"               # local HH:MM for the daily digest

# --- telemetry collector ---------------------------------------------------
# Bind the collector so the Windows terminal can reach it. Default is loopback
# (127.0.0.1); for the split, bind an interface the EA host can reach and put a
# firewall / private network in front of it.
#   python -m mql5bot.telemetry_bridge --host 0.0.0.0 --port 8080
```

On the **Windows / MT5** host, tell the EA where to POST telemetry (the EA
input `InpTelemetryUrl`, e.g. `http://<linux-host>:8080/telemetry`) and — this
is required by MetaTrader — **add that exact URL to the terminal's allowed
`WebRequest` list**: Tools → Options → Expert Advisors → *Allow WebRequest for
listed URL* → add `http://<linux-host>:8080`. Without it MT5 silently blocks
the POST and the watchdog will (correctly) report a stale heartbeat.

## Restart-on-boot

**Windows / MT5 host.** Enable MetaTrader's auto-start of the EA on the chart
(the EA re-adopts its persisted state on `OnInit`), and set the terminal to
launch at login (Task Scheduler → *At log on*, or the MT5 VPS's own always-on
hosting which needs no boot script). Confirm the chart+EA reload after a reboot.

**Linux host.** Run each Python service under a supervisor that restarts it on
exit and on boot. A minimal systemd unit per service:

```ini
# /etc/systemd/system/mql5bot-telemetry.service
[Unit]
Description=mql5bot telemetry collector
After=network-online.target

[Service]
# secrets come from an environment file readable only by this service's user
EnvironmentFile=/etc/mql5bot/telemetry.env
ExecStart=/opt/mql5bot/.venv/bin/python -m mql5bot.telemetry_bridge --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then `systemctl enable --now mql5bot-telemetry`. Add sibling units for the
watchdog/Telegram runner and the console the same way. Keep the `EnvironmentFile`
mode `600` and out of the repo.

## After deployment — drill it before real money

Because none of this is proven, run these checks yourself before connecting a
real account, and treat any failure as blocking:

1. Reboot the Windows host — confirm the terminal + EA come back and telemetry
   resumes (the digest/heartbeat should recover).
2. Restart the Linux host — confirm every service comes back via systemd.
3. Kill the terminal deliberately — confirm the Watchdog raises a stale-
   heartbeat Telegram alert within the configured window.
4. Send `stop` from the owner's phone — confirm it halts immediately, and
   confirm you can only resume from the console, never from Telegram.
