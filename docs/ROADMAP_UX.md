# Roadmap — the operator experience

This is a design document, not a task list. It explains **why** the
operator experience should change, so that whoever implements it can
follow the reasoning and disagree with evidence rather than with a
checkbox. It agrees with [OWNER_DELIVERY.md](OWNER_DELIVERY.md): nothing
in this system is proven beyond the evidence that exists for it, and no
screen may imply otherwise.

## The core problem — one system, two users

The system today serves one kind of person well: someone comfortable at
a command line, who runs the certification gate and reads JSON. But the
project actually has **two** users, and building for only one of them is
the central UX defect.

- **The OWNER.** A Persian-speaking trader, usually on a phone, not a
  developer. On any given day the owner has three questions and only
  three: *Is it alive? What did it do today? How far am I from my loss
  limit?* The command line answers none of these in a form the owner can
  use.
- **The CERTIFIER.** Technical, runs `tools\owner_gate.ps1`, reads the
  evidence directory, verifies hashes. For this user the CLI is correct
  and should not change. Adding friendly surfaces must not degrade the
  certifier's precise, greppable, exit-code-driven tools.

Conflating the two — forcing the owner through the certifier's tools, or
softening the certifier's tools to be friendlier — is what makes the
experience wrong. The phases below separate them.

## Phase 1 — Telegram as the primary interface

For this owner, Telegram beats any web page. It is already on the phone;
it pushes notifications without the owner opening anything; it needs no
URL and no password; it is reachable anywhere. The web console (Phase 2)
is for going deeper, not for daily life. So the daily relationship with
the system should live in Telegram, and the web page should be the place
you go when Telegram made you want to look closer.

**What it pushes.**

- A **daily digest** at a fixed local time: alive or not, trades today,
  realised profit or loss for the day, open positions, and the distance
  to the configured drawdown limit.
- **Per-trade open/close notifications**, toggleable — some owners want
  every fill, some want only the digest.
- The **existing watchdog alerts** (stale heartbeat, drawdown, engine
  state), which already exist and already rate-limit themselves.

**What it accepts.** Four read-or-stop commands: `status`, `positions`,
`report`, and `stop`. Each reads state; none invents it.

**The binding design principle — asymmetric friction.** Stopping must be
easy; starting must be hard.

- `stop` acts immediately, with no confirmation step. When money is at
  risk, a confirmation dialog is a way to lose money, not to prevent a
  mistake.
- **Resuming must not be possible from Telegram at all.** There is no
  resume command and no code path — not behind a confirmation, not
  behind a password — that can start or re-enable trading from a chat
  message. Resuming requires the console (Phase 2).
- The rationale is a threat model, not a preference: if someone gets
  hold of the unlocked phone, the worst they can do is *stop* the bot.
  They can never start it. A symmetric start/stop button would turn a
  lost phone into a way to put the owner into the market.

**Access.** An allow-list of permitted chat ids, read from the
environment. A message from any other chat is ignored and logged without
echoing its content. No account numbers, tokens, chat ids, or file paths
appear in any message.

## Phase 2 — one Persian RTL status page

A single phone-first, right-to-left Persian page that answers the three
questions above the fold: a **traffic light** and **one plain-Persian
sentence** — is it alive, what did it do today, how far from the loss
limit.

The formal certification vocabulary (`SOFTWARE_PASS`,
`EMPIRICAL_VALIDATION_PENDING`, `BLOCKED_OWNER_ENVIRONMENT`, `VERIFIED`)
stays available **on tap**, never in the reader's face. The owner should
never have to learn those words to use the system, but must be able to
reach the exact, un-translated term when they want it — the terms are
shown verbatim and explained alongside, never replaced by a Persian
synonym that could drift in meaning.

**Warning to whoever builds this — the equity curve.** Never show a
backtest equity curve without an "unproven" label attached to the curve
itself. People believe green lines even when the caption underneath says
"hypothetical". A rising curve manufactures confidence that the evidence
does not support. If a curve is shown at all, it appears **beside** the
drawdown limit and the kill-switch state, so the risk is always in the
same glance as the promise.

## Phase 3 — always-on deployment

The bot only trades while MetaTrader 5 is running and connected. For
unattended operation the owner needs an always-on host. Three options,
with their trade-offs:

**(a) MetaQuotes' own MT5 VPS.** One click from inside the terminal, low
latency to the broker. But it runs the *terminal only* — no Python. So
no watchdog, no Telegram, no console. The owner would be always-on but
blind.

**(b) A full Windows VPS.** Everything on one machine: MT5 and all the
Python services together. Simplest to reason about, heaviest to manage,
and the most expensive Windows host.

**(c) Split — the recommended option.** MT5 on (a) or a small Windows
host, and the Python services on a cheap Linux host.

The architecture **already supports the split.** The EA POSTs its
telemetry outward via `WebRequest` to the Python collector
(`python/mql5bot/telemetry_bridge.py`), so the Python side never needed
to sit on the same machine as MT5. And the existing **Watchdog** already
raises a Telegram alert on a stale heartbeat — so a VPS outage or a
sleeping terminal surfaces to the owner with no new code. The full
procedure is in [DEPLOYMENT.md](DEPLOYMENT.md); note there that this
split has never been deployed or drilled — it is a procedure, not a
proven configuration.

## Phase 4 — the strategy conversation

Today `POST /interpret` exists and returns a structured result, but the
owner-facing experience of it is not a conversation. For a non-developer
it should be a dialogue:

1. The owner writes a strategy in Persian.
2. The system shows a **plain-Persian restatement** of what it
   understood — derived from the scrubbed draft, not echoed from the
   owner's words.
3. The owner confirms or corrects.
4. The **DSL schema/parse check** runs — the one Python check that needs
   no market data. It proves the draft is well-formed; it is **not** a
   test of the strategy.
5. The system gives a **plain-Persian verdict** whose headline names
   exactly what ran: schema-validated (structure only), or a schema
   failure with its reason. The headline must never read as "it was
   tested and it works".

Any parameter the owner did not specify is surfaced as a **question, in
Persian, naming what is missing** — never filled in silently. "RSI is
low" does not become "RSI < 30"; it becomes "you didn't say how low —
what threshold?"

**The hard boundary — record it and make it visible.** As built today,
this flow **ends at SCHEMA VALIDATION** — a well-formedness check, nothing
more. Two things have **not** happened and must be shown as explicit,
not-yet-done steps: **(a)** the Python research validation — backtest,
robustness, out-of-sample — which needs a dataset and has not run; and
**(b)** the owner-run 11-stage MT5 certification gate. The flow must
never end at "added to MetaTrader". If the owner ever feels that one
button in this conversation tested their strategy or made it live, the
entire value of this project is gone.

## The rule that binds every screen

A friendly interface over an unproven system is **more** dangerous, not
less, because polish manufactures confidence the evidence has not earned.
A rough CLI that says "NOT VERIFIED" is safer than a beautiful dashboard
that lets the eye assume "ready". Therefore three rules bind every screen
this roadmap produces:

1. **Every status surface states what is still unproven.** Not in a
   footnote — in the same view as the status itself.
2. **The stop control is always visible, never behind a menu.**
3. **No button anywhere sends a strategy straight to a real account.**
   The path to real money runs through the certification gate and human
   approval, and every screen shows that the path is not yet complete.
