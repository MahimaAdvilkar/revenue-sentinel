# Demo script — 5 to 7 minutes

Spoken narration, with the command to run underneath each beat. It is a walkthrough of an
argument, not a tour of a terminal: every beat exists to make one claim, and the commands
are there to make the claim checkable rather than to be read aloud.

**Before you start:** `make quickstart` (clean clone → golden scenario, offline, spends
nothing). For the screens, `make api` in one terminal and `make web` in another.

Total spend for everything below: **$0.000000**. No live model call, no external system.

---

## 0 · Setup — 15 seconds

> "This runs entirely offline. No API key, no network calls to a model provider, no
> external system connected. Every figure you'll see is computed, and every integration is
> simulated and labelled as such. It has never made a live model call — not once."

```bash
make quickstart
```

---

## 1 · The problem — 30 seconds

> "A deal worth $180,000 is sitting in Proposal. The rep hasn't spoken to the account in
> fourteen days. Meanwhile the buyer's product usage is *climbing* — feature events up from
> 1,250 to 1,750 week over week, active users from 12 to 19.
>
> That contradiction is the interesting part. Silence usually means a deal is dying. Rising
> usage usually means it's alive. Someone has to look, and nobody has time to look at every
> deal every week. That's what this does."

---

## 2 · Detection — 30 seconds

> "The detector is ordinary code with unit tests — not a model. It scores 15 opportunities,
> finds one signal, and opens `INC-001` at HIGH severity. Severity is a banded function of
> weighted pipeline value, so the same inputs always produce the same band."

```bash
make ingest
```

---

## 3 · Investigation and evidence — 60 seconds

> "Now the agent works. It plans an investigation, then gathers evidence — and every piece
> of evidence arrives through an **MCP tool call**, not a database read the agent made up.
> Six evidence items across four source systems.
>
> Two things to notice. Each tool is narrow: `crm_get_opportunity`, not `run_sql`. And every
> result is stamped `SIMULATED` by the adapter that served it, so the badge on the screen is
> derived from the code that answered the request."

```bash
make investigate INCIDENT=INC-001
```

> "It produces two hypotheses, each citing specific evidence. The citations are foreign
> keys — a hypothesis that cited invented evidence would fail to persist at all. That's not
> a prompt asking nicely for citations; it's the schema refusing the alternative."

---

## 4 · The money — 45 seconds *(the beat that matters most)*

> "Pipeline $180,000. Weighted $108,000. At risk **$32,130**.
>
> **The model did not calculate any of that.** Stall risk and usage offset are banded lookup
> tables in `analytics/`, unit tested, versioned. The LLM classifies, extracts, and explains;
> it never does arithmetic the business depends on.
>
> If I let a model multiply those numbers, I'd have a system whose headline figure changes
> between runs and can't be audited. The interesting engineering here is the boundary, not
> the prompt."

---

## 5 · Strategy, and three different answers — 60 seconds

> "Three interventions, ranked by a deterministic scorer — the model drafted more, and the
> scorer decided the order. Each one hits the policy layer and gets a *different* answer:
>
> - **Tier 1** — a CRM task. Allowed, executed automatically.
> - **Tier 2** — an email to the champion. Requires a human.
> - **Tier 3** — a discount. Denied outright.
>
> The policy engine is a pure function over a versioned rule set. Same inputs, same decision,
> every time, with the matched rules recorded next to it."

---

## 6 · Approval, and what is *not* possible — 60 seconds

```bash
make approvals
uv run rs approve APR-001 --as usr:your-name
uv run rs resume INC-001
```

> "Approval is a recorded event with an actor and an expiry, not a flag someone flipped.
>
> Two things I want to point out because they're deliberate absences. The dashboard shows
> this queue but has **no approve button** — there's no authentication in this system, so a
> button would imply an accountable user who doesn't exist. And the email is created as an
> **unsent draft**: there is no `send_email` tool and no send method on the messaging port.
> Tier 3 isn't blocked, it's *absent from the interface*."

---

## 7 · Running it twice — 45 seconds

```bash
make demo    # runs the whole scenario again
```

> "Same scenario, second time. Zero duplicate effects.
>
> Every effect has an idempotency key derived from business values — the incident, the action
> type, the target, the payload — and deliberately *not* from the run id, because keyed by run
> a second run would compute a different key and cheerfully send a second email. The row is
> claimed **before** the effect, so the unique constraint is the lock.
>
> And when a process dies mid-effect, the system says `INDETERMINATE` rather than guessing.
> A person resolves that, with mandatory evidence — `rs actions --status indeterminate`.
> There's deliberately no retry button, because a retry on an uncertain action is how you
> send the same email twice."

---

## 8 · Cost and evaluation — 45 seconds

```bash
make eval
```

> "Total spend: **$0.000000**, printed to six decimals and not rounded — fixture mode consumes
> zero tokens, so that figure is the truth rather than a rounding.
>
> The evaluation is deterministic and structural: every check reads persisted rows, and no
> model is consulted — including by the reporter. Every check has a negative test proving it
> can fail, because a rubric nobody has seen fail is one nobody knows works.
>
> What this does **not** prove is answer quality. The fixtures are hand-authored; they prove
> the pipeline and the control behaviour, not that the prompts work against a live model."

---

## 9 · The catalogue — 30 seconds

> "Last screen, and it's the honest one. Every adapter, with the status it declares about
> itself and the roadmap notes it wrote in its own docstring — the API doesn't restate any
> of it, so the catalogue can't disagree with the code that would serve the request.
>
> Everything is SIMULATED. Nothing here is connected to a real CRM or mailbox, and the page
> says so in those words."

---

## Closing — 15 seconds

> "One golden scenario, end to end: detect, investigate, decide, approve, execute, account
> for every cent, and evaluate itself. Offline, reproducible, and $0.
>
> What it deliberately doesn't have: authentication, live integrations, and any claim about
> real-world precision — all of which are written down rather than glossed over."

---

## If someone asks to see it break

- **Prompt injection:** `uv run pytest tests/evaluation -k injection` — six adversarial
  payloads, contained structurally rather than by the model behaving.
- **Policy bypass:** a forged `APPROVED` row on a denied action still produces no effect.
- **A stale fixture:** edit a system prompt and run `python -m scripts.check_fixtures` —
  it fails in seconds, with no database and no network.
