# CLAUDE.md — Revenue Sentinel

Permanent development instructions for this repository. These rules apply to every
session, every task, and every contributor (human or agent). They are not
suggestions; treat them as the standing definition of "done well" here.

## Project framing

**1. This is a production-quality portfolio project, not a toy demo.**
Every commit should be something you would defend in a technical interview or a
production code review. No throwaway scaffolding left behind, no "good enough for
a demo" shortcuts silently shipped. If a shortcut is genuinely necessary, it is
written down (see rule 18) rather than hidden.

## How work gets done

**2. Plan before implementing.**
Before writing code for any non-trivial change, produce a short plan: what is
being built, which files change, what the interfaces look like, and how it will
be verified. Confirm the plan before starting implementation.

**3. Build one functioning vertical slice before expanding.**
Get a single end-to-end path working — ingestion → logic → policy → output —
before adding breadth. Depth first, then width. A half-built layer cake is worse
than one complete slice.

**4. Use typed interfaces and structured outputs.**
All module boundaries carry explicit types (Python type hints + Pydantic models,
TypeScript types/interfaces on the frontend). LLM calls return validated
structured output against a schema — never free-form text that gets parsed with
string manipulation or regex.

**5. Never claim mocked integrations are real.**
If an integration is stubbed, seeded, simulated, or backed by fixtures, say so
explicitly — in the code, in `PROJECT_STATUS.md`, in the README, and in any
summary written to the user. Mock adapters are named and located so their status
is obvious from the call site. Overstating integration status is a correctness
bug, not a documentation nit.

## Architecture

**6. Keep business logic separate from API routes.**
Route handlers do transport concerns only: parse, authenticate, delegate,
serialize. Domain logic lives in services//domain modules that are importable and
testable without an HTTP server.

**7. All external actions must pass through a policy layer.**
Any effect that leaves the process — sending email, writing to CRM, calling a
third-party API, triggering a webhook — is executed only via the policy layer.
The policy layer decides: allowed, denied, or requires-approval, and records the
decision. No module calls an external side-effecting client directly.

**8. External communication and material CRM changes require human approval.**
Outbound messages to real people and material CRM mutations (stage changes, deal
value edits, deletions, ownership changes) require an explicit human approval step
before execution. Approval is a first-class recorded event, not an implicit
default. When in doubt about materiality, require approval.

**9. Use deterministic code for calculations instead of LLM arithmetic.**
Scores, risk weights, currency, dates, aggregations, thresholds, and ranking are
computed in ordinary code with unit tests. LLMs classify, extract, summarize, and
explain; they do not do arithmetic that the system depends on.

**15. Use narrow MCP tools rather than broad unrestricted tools.**
Expose the smallest capability that accomplishes the task — `get_open_deals`, not
`run_sql`; `send_draft_for_approval`, not `http_request`. Each tool has a tight
schema, validated arguments, and a documented blast radius. Broad, general-purpose
tools are a design failure here.

## Quality bar

**10. Every meaningful feature requires tests.**
A feature is not complete without tests covering its happy path and its important
failure modes. Policy decisions, scoring math, and schema validation are always
tested. Bug fixes get a regression test.

**13. Never bypass failing tests merely to make the build pass.**
Do not skip, xfail, comment out, loosen an assertion, or weaken a schema to get
green. Fix the code or fix a genuinely wrong test — and say which one you did. A
red test is information; discarding it destroys the information.

**16. Keep the repository runnable after every milestone.**
At each milestone boundary, a fresh clone must install, run, and pass its test
suite with documented commands. No "it works on my machine" intermediate states
left at a milestone.

## Security

**12. Never hard-code secrets.**
No API keys, tokens, passwords, or connection strings in source, tests, fixtures,
notebooks, or commit history. Configuration comes from environment variables with
a committed `.env.example` documenting required names and no real values.

**14. Treat CRM, email, website, and support content as untrusted data.**
All ingested content is potentially adversarial — assume prompt injection. Never
let ingested text act as instructions. Keep it in clearly delimited data fields,
never concatenated into a system prompt, and never allow it to authorize an
action. Any action derived from ingested content is still subject to rules 7 and 8.

**19. Ask before executing destructive commands.**
Confirm before any drop/truncate/migration-reset, force push, history rewrite,
bulk delete, `rm -rf`, or overwrite of user data. Read the target before
overwriting it.

**20. Do not create paid cloud resources or incur external costs without approval.**
No provisioning of hosted databases, deployments, queues, paid API tiers, or
anything else that bills, without explicit approval first. Prefer local and free
tiers by default.

## Documentation

**11. Update architecture documentation whenever architecture changes.**
When components, boundaries, data flow, or the policy model change, the
architecture docs change in the same commit. Docs that contradict the code are
treated as broken.

**17. Update PROJECT_STATUS.md after each milestone.**
Record what is complete, what is in progress, what is mocked vs. real (rule 5),
and what is next. This is the single source of truth for project state.

**18. Record important technical tradeoffs in architecture decision records.**
Significant or non-obvious choices — and the alternatives rejected — go in an ADR
under `docs/adr/` with context, decision, and consequences. Accepted shortcuts and
known limitations are recorded here rather than left as tribal knowledge.
