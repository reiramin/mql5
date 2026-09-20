# The operator console / کنسول مالک

The owner's web console: six pages over the data that already exists in the
system — the factory store, the safety chain, the telemetry bridge, and the
gate evidence. **Built, unit-tested, never run live.** Nothing in this project
is certified — see [OWNER_DELIVERY.md](OWNER_DELIVERY.md).

کنسول وبِ مالک: شش صفحه روی داده‌هایی که همین حالا در سیستم وجود دارد. ساخته
و تست‌شده؛ هرگز در محیط زنده اجرا نشده است. هیچ چیزِ این پروژه گواهی نشده است.

## Starting it / راه‌اندازی

```sh
pip install uvicorn                # the only extra needed to serve it
python -m mql5bot.api              # binds 127.0.0.1:8000
python -m mql5bot.api --host 0.0.0.0 --port 8000   # requires the auth token
```

The default database lives in a per-user data directory **outside the
repository** (printed at startup) so starting the console never dirties the
working tree; `--db` overrides. English is the default; every page also ships
Persian — add `?lang=fa`.

## Authentication / ورود

Set `MQL5BOT_CONSOLE_TOKEN` to a secret of your choosing. With it set, every
page requires login: `/login` exchanges the token for a signed session cookie
(HMAC, constant-time compare); `/logout` clears it. **Without the token the
runner refuses to bind any non-loopback host** — an unauthenticated console
that anyone on the network can reach could stop the bot or reset the kill
switch. The token is never logged and never rendered.

توکن را در `MQL5BOT_CONSOLE_TOKEN` بگذارید. بدون آن، کنسول فقط روی
loopback بالا می‌آید و از راه دور در دسترس نیست.

## The three hard rules / سه قانون سخت

1. **Every status surface states what is still unproven** — the banner on
   every page comes from the real status model, never hardcoded prose.
   (هر صفحه می‌گوید چه چیزی هنوز اثبات نشده است.)
2. **The stop control is always visible, never behind a menu.**
   (کلید توقف همیشه دیده می‌شود.)
3. **No button anywhere sends a strategy toward a real account.** No route
   can move a strategy into SHADOW / DEMO / LIVE_SMALL / LIVE — pinned by a
   test that walks every route.
   (هیچ دکمه‌ای استراتژی را به حساب واقعی نمی‌فرستد.)

## The pages / صفحه‌ها

### Home — `/` (`?lang=fa` for the Persian status page)
The traffic light and the three answers: alive?, today's activity, distance
to the loss limit. The kill switch is on the page. A source that is not
connected says **وصل نیست / not connected** — never a zero that looks like
data.

### Strategies — `/strategies`
Every strategy on the pipeline rail
`DRAFT → PARSED → VALIDATED → BACKTESTED → ROBUSTNESS_PASS → OOS_SURVIVOR →
SHADOW → DEMO → LIVE_SMALL → LIVE`, the current state highlighted, and **why
it is there** — the last lifecycle event's evidence or refusal from the store.

### Strategy detail — `/strategy/<id>`
The owner's original text, the accepted restatement (recomputed from the
stored spec), the lifecycle timeline with evidence per transition, recorded
runs, and only the actions the lifecycle permits from that state — pause /
retire (with confirmation) / resume. Refusals are shown verbatim. On a DRAFT,
"Run Python validation" runs the existing backtest **only if a dataset is
configured** (`MQL5BOT_CONSOLE_DATASET`) and records the result — it never
advances the state by itself; without a dataset it says exactly what is
missing and runs nothing.

### New strategy — `/new`
A conversation, not a form: write in Persian → the restatement appears as a
reply → each unanswered question is its own prompt → the explicit
**«بله، منظورم همین بود»** accept button (bound to that exact restatement — a
changed draft invalidates it) → the schema verdict worded exactly as the
backend words it (**SCHEMA-VALIDATED — structure only; the strategy has NOT
been tested**) → the two remaining steps shown as not-done → «ثبت به‌عنوان
پیش‌نویس» registers it as a DRAFT. Nothing beyond DRAFT is reachable here.

### Trades — `/trades`
Open positions (P&L always beside the distance to the loss limit), today's
closed trades, and a paged history read from the telemetry JSONL
(`MQL5BOT_TELEMETRY_LOG`). Live via one SSE subscription per page through the
console's same-origin proxy (`MQL5BOT_TELEMETRY_URL`); when the bridge is
unreachable the page shows not-connected and the last-seen time.

### Certification — `/certification`
**Read-only.** The 11-stage gate as a rail, read from the evidence directory
the owner points the console at (`MQL5BOT_EVIDENCE_DIR`): per stage
PASS / FAIL / BLOCKED / NOT RUN with the gate's own reason strings and
artifact hashes; the stage-5 legs individually with their verdict class and
the quoted tester-log lines. Certification terms appear verbatim with the
Persian explanation beside them. This page is where the owner learns why the
gate stopped without opening a JSON file. It runs and changes nothing.

### Settings & health — `/settings`
A checklist a non-developer can read top to bottom: which environment
variables are SET (names only — never values), Telegram configured or not,
telemetry reachable or not, evidence dir configured or not, console language,
and when MT5 was last seen (from the latest heartbeat).

## What it cannot do / چه کاری نمی‌کند

- It cannot promote a strategy toward execution or a live account.
- It cannot fabricate a number: unconnected sources say not-connected.
- It cannot resume trading from Telegram (stop is Telegram-easy,
  resume is console-only — [TELEGRAM.md](TELEGRAM.md)).
- It does not prove anything: the gate result on the certification page is
  the gate's own file, and today it reads `GATE_RESULT=tester_legs` — stage 5
  FAIL, stages 6–10 never run, nothing VERIFIED.

## Environment variables (names only)

| Variable | Purpose |
|---|---|
| `MQL5BOT_CONSOLE_TOKEN` | owner login token — **secret**, required for non-loopback binds |
| `MQL5BOT_TELEMETRY_URL` | the telemetry bridge base URL (SSE + latest proxy) |
| `MQL5BOT_TELEMETRY_LOG` | the bridge's JSONL file for the trades history |
| `MQL5BOT_EVIDENCE_DIR` | an owner-gate evidence directory for the certification page |
| `MQL5BOT_CONSOLE_DATASET` | a CSV of OHLC bars enabling "Run Python validation" |
