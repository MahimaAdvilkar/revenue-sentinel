# Project Status

**Last updated:** 2026-08-06
**Current milestone:** Session 5 — Strategy and policy ✅ **COMPLETE**
**Next milestone:** Session 6 — Execution and audit (awaiting approval)

---

## Where the project actually is

**The investigation runs through a real MCP server, offline and for free.** Seed → ingest →
investigate produces a plan, six evidence items, two cited hypotheses, and **$108,000.00
weighted / $32,130.00 at risk** — with no API key, no network, and no money spent. As of
Session 4 the evidence arrives through **MCP tool calls**, not repository reads, and the
figures did not move by a cent.

| Question | Answer |
|---|---|
| Can you run it? | Yes — `make setup && make up && make migrate && make seed && make ingest && make investigate` |
| Can you run the tests? | Yes — **789 pass, 0 skipped, 0 xfailed** |
| Does detection work? | Yes — 1 signal across 15 opportunities, `INC-001` at `HIGH` |
| Does the investigation work? | Yes — **6 nodes, 7 transitions**, 6 evidence items, 2 hypotheses, 3 ranked interventions |
| **Is the MCP server real?** | **Yes.** 15 tools, both transports. `make mcp` runs a spec-compliant stdio server; a test drives it as a real subprocess |
| **Are the integrations real?** | **No. Every one is SIMULATED**, and every tool result says so — over both transports |
| Are the money figures right? | Yes — computed by `analytics/`, asserted to the cent |
| **Is the policy engine real?** | **Yes.** Four tiers, default-deny, escalation on ambiguity, every decision recording its rules. A pure function (ADR-0015) |
| Can the system write to anything? | **No.** 4 write tools are registered but unwired; the graph binds no policy engine, so a write would raise |
| **Did anything execute?** | **No.** Session 5 decides and records. `action_records` is empty, and a test asserts it |
| Is it replay-safe? | Ingestion yes. **Investigation replay is Session 6** and is refused with an explanation. |
| **Has this system ever called a model?** | **No. Not once.** |
| Are the LLM fixtures real? | **No — hand-authored, not recorded.** See ADR-0013. |
| Does `make demo` work? | No. There is no execution, cost governance, or dashboard yet. |

---

## Milestone log

### Phase 0 / Phase 1 ✅
Architecture, 20 documents, 7 ADRs, scaffolding. No application code.

### Session 1 — Foundations ✅
`core/`, `domain/` (29 models), `analytics/pipeline_impact.py`, `db/` (29 tables),
Alembic baseline, deterministic seeder, `GET /health`. 228 tests. ADRs 0008–0010.

### Session 2 — Events, signals, incidents ✅
SIMULATED source feed, replay-safe ingestion, normalization, the `stalled_opportunity`
detector, 7 ROADMAP contracts, severity bands, incident lifecycle, three endpoints.
432 tests. ADR-0011.

### Session 3 — Investigation graph ✅

**Delivered**

| Group | Detail |
|---|---|
| `intelligence/` | LLM port, prompt digest, frozen prompts with escaped evidence blocks, structured-output schemas, fixture client, live client (unexecuted) |
| `agents/` | `EvidenceSource` port, planner, researcher, analyst, citation gate |
| `orchestration/` | State, 4 thin nodes, graph with transition-recording wrapper, persistence, runner |
| `alembic/0003` | `model_calls.is_replay` |
| `fixtures/llm/` | 3 hand-authored fixtures |
| `tests/` | 116 new — 548 total |
| Docs | ADR-0012 (checkpointer), ADR-0013 (hand-authored fixtures) |

**Acceptance — all thirteen criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | Graph runs the four nodes in order | ✅ `plan → evidence → hypotheses → impact` |
| 2 | Transitions written **before** the next node; gapless | ✅ 5 rows, sequence 0–4, chain verified |
| 3 | Every LLM call schema-validated; no free-text parsing | ✅ validation happens inside the client |
| 4 | ≥2 hypotheses citing real evidence; fabrication persists nothing | ✅ run aborts, tables stay empty |
| 5 | Impact from `analytics/`; inputs recorded | ✅ `computed_by = deterministic`, `model_call_id IS NULL` |
| 6 | Fixture mode runs with **no network**; a miss raises | ✅ full run with `socket.socket` refusing |
| 7 | Untrusted content only inside delimited `<evidence>` blocks | ✅ tag-forgery payload contained |
| 8 | Node bodies thin — no domain logic, no persistence | ✅ AST-asserted: no `db` import, ≤6 statements |
| 9 | Migration `0003` up and down clean; no drift | ✅ `alembic check` reports nothing pending |
| 10 | **Zero dollars spent** | ✅ no live call made, `make record` never run |
| 11 | Incident advances `TRIAGED → INVESTIGATING → ANALYZED` | ✅ audit row per transition |
| 12 | All 432 existing tests still pass | ✅ unmodified |
| 13 | Docs updated | ✅ this commit |

**Demo result**

```
make investigate INCIDENT=INC-001        # DEMO_MODE=fixture, no key, no network

  PLAN (5 steps)          crm_get_opportunity, crm_list_account_activities,
                          product_get_usage_summary, engagement_get_email_activity,
                          support_get_open_issues
  EVIDENCE (6 items)      EV-001..EV-006 across 4 source systems
  HYPOTHESES (2)          H1 conf 0.72 cites EV-002, EV-004
                          H2 conf 0.41 cites EV-005, EV-006
  IMPACT                  pipeline 180000.00   weighted 108000.00
                          stall risk 0.3500    gross 37800.00
                          usage offset 0.1500  AT RISK 32130.00 USD
```

### Session 4 — GTM MCP server ✅

**Delivered**

| Group | Detail |
|---|---|
| `integrations/ports/` | 6 Protocols (crm, product, engagement, support, enrichment, messaging). **`MessagingPort` has no send method** |
| `integrations/simulated/` | 6 adapters, each declaring `INTEGRATION_STATUS = "SIMULATED"` and a substantive "What changes when this becomes real" section |
| `integrations/status.py` | `status_of()` — an adapter that does not declare a status **raises**; there is no default |
| `integrations/simulated/behaviour.py` | Deterministic latency and scripted failure injection, **inert by default** |
| `mcp/` | errors, envelope, schemas, registry, gate, dispatcher, ledger, context |
| `mcp/tools/` | All **15** tools, strict Pydantic args (`extra="forbid"` → `additionalProperties: false`) |
| `mcp/client.py` | Synchronous `McpClient` port, `InProcessMcpClient`, `AsyncBridge` (ADR-0014) |
| `mcp/server.py` + `scripts/mcp_server.py` | Low-level MCP `Server` and the stdio entry point behind `make mcp` |
| `governance/stub.py` | `StubPolicyEngine` / `DenyAllPolicyEngine` — **for tests only**; never used to demonstrate a write |
| `orchestration/mcp_evidence_source.py` | The evidence port, MCP-backed. Wired into `run_investigation` |
| `tests/` | **182 new — 730 total** |
| Docs | **ADR-0014** (sync/async boundary) |

**Acceptance — all nine criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | 15 tools with `additionalProperties: false` | ✅ asserted per tool, in-process **and as received over stdio** |
| 2 | Write tools cannot reach an adapter without a policy decision | ✅ no engine bound → raises; denied write verified against a spy adapter |
| 3 | Every adapter declares `INTEGRATION_STATUS = "SIMULATED"`, stamped on every result | ✅ survives both transports |
| 4 | Every adapter docstring has "What changes when this becomes real" | ✅ named APIs, auth, rate limits, differing fields |
| 5 | Seven typed error codes; `POLICY_DENIED` forbids rerouting | ✅ `retry=False, alternative_route=False`, tested |
| 6 | In-process client and stdio server, identical handlers | ✅ both delegate to `dispatcher.dispatch`; payload equality tested |
| 7 | Every call writes a `tool_calls` row with trace and span IDs | ✅ success, typed error, **and denial** |
| 8 | Deterministic simulated latency and failures | ✅ scripted, not random; disabled by default |
| 9 | Research Agent gathers evidence exclusively through MCP | ✅ `McpEvidenceSource`; parity **byte-equivalent** |

**The stdio proof**

```
handshake OK | server: revenue-sentinel-gtm | protocol: 2025-11-25
tools via stdio: 15
additionalProperties via stdio: False
stdio call ok: True | status: SIMULATED | name: Northwind Logistics
stdio NOT_FOUND: NOT_FOUND | is_error: True
```

A real subprocess over real pipes, not a simulation of a transport. 11 automated tests in
`tests/integration/test_transport_parity.py` hold that claim to account.

### Session 5 — Strategy and policy ✅

**Delivered**

| Group | Detail |
|---|---|
| `governance/` | `outcomes.py` (the shared `PolicyOutcome`), `tiers.py`, `rules.py`, `policy_engine.py`, `approvals.py` |
| `analytics/intervention_scoring.py` | Banded recovery/effort tables, tier-derived risk, normalised composite, total ordering |
| `agents/strategist.py` | Drafts 3-5 interventions; **supplies no numbers and no ordering** |
| `agents/policy_agent.py` | Deterministic; one decision per intervention |
| `orchestration/` | Two new nodes (`draft_interventions`, `evaluate_policy`), state fields, governance persistence |
| `alembic/0004` | `interventions.action_type` widened to `proposed_action` |
| `fixtures/llm/` | 1 hand-authored strategy fixture — 4 total |
| `tests/` | **56 new — 789 total** |
| Docs | **ADR-0015** (policy as a pure function) |

**Acceptance — all nine criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | Exactly 3 interventions, ranked by a tested deterministic score | ✅ model drafted 4; scorer kept 3 |
| 2 | The LLM drafts; the scorer ranks | ✅ `analytics/` cannot import `intelligence/` or `agents/` (R3), asserted again per-module by AST |
| 3 | Policy engine is a pure function | ✅ no I/O, no clock; 25 identical evaluations asserted |
| 4 | All four tiers; "material CRM change" matches the security model exactly | ✅ set transcribed and compared by test |
| 5 | **Default-deny** for unclassified actions | ✅ unknown action, unknown field, and *no* field all deny |
| 6 | Ambiguity escalates to the higher tier | ✅ `max()`; mixed field update → tier 2; unclassified field → tier 3 |
| 7 | Every decision records `matched_rules` and a readable reason | ✅ asserted on all three golden rows |
| 8 | Approvals with `expires_at`; no self-approval | ✅ plus expiry evaluated **on read**, not by a sweeper |
| 9 | Golden scenario: 1 ALLOW, 1 REQUIRE_APPROVAL, 1 DENY | ✅ and `action_records` is empty |

---

## What is real and what is not

**Real:** the graph and its four nodes; transition recording before each node; the LLM
port and its fixture implementation; every structured-output schema and its validation;
the source allowlist; the citation gate and the foreign keys beneath it; the impact
figures; the audit trail. **And as of Session 4: the MCP tool catalog, all 15 tools and
their strict schemas, the dispatcher, both transports (in-process and stdio), the policy
gate at the tool boundary, the tool-call ledger, and MCP-backed evidence retrieval.**

**SIMULATED:** the event source (Session 2), the model responses (Session 3), **and every
integration behind the MCP server (Session 4).** Ports being real does not make
integrations real. Each adapter declares `INTEGRATION_STATUS = "SIMULATED"` and the server
stamps it on every tool result; an adapter that fails to declare one raises rather than
defaulting to something reassuring. The LLM fixtures are hand-authored, not recorded — every
replayed `model_calls` row says so: `is_replay = true`, zero tokens,
`stop_reason = 'fixture_replay'`.

**Written but never executed:** `AnthropicLLMClient` and `make record`. Both are
type-checked and unit-tested against a stubbed SDK. **Neither has been run against the
API, and no live call has been made by this project at any point.**

**Registered but not wired:** the **four write tools** — `crm_create_task`,
`crm_update_opportunity`, `messaging_create_email_draft`, `messaging_send_slack_approval`.
They exist, they are policy-gated, and they are tested. **None is reachable from the
investigation graph, and none has ever been executed.** `run_investigation` binds
`policy=None` deliberately: the graph is read-only and every tool it calls is Tier 0, so a
write attempted from that path raises rather than executing — and certainly not under the
allow-everything stub. **`StubPolicyEngine` was never used to demonstrate a write.**

**Not real, and not claimed to be:** execution, the retry engine, the approval UI and its
endpoints, cost governance, evaluation, and the dashboard. **Nothing the policy engine
allows is carried out** — an ALLOW in Session 5 is a recorded decision, not an action. There is **no
`messaging_send_email` tool** and no send method on `MessagingPort` — Tier 3 is absent from
the interface, not merely unrouted. **`BUDGET_EXCEEDED` is a defined error code with no
real producer until Session 7**; nothing raises it today.

**Nothing external was touched.** No real credentials, no external integration, no paid API
call, no live LLM call. **Session 4 spent $0.**

---

## The honest sentence about the fixtures

> The offline fixtures are hand-authored and the recording path has not been run, so they
> prove the pipeline and the schemas — **not** that the prompts work against a live model.

That gap closes when `make record` is run, which needs an API key and a decision to spend
roughly $0.10–0.60. ADR-0013 records the tradeoff, the mitigations, and the trigger to
revisit.

---

## Deviations from the Session 3 plan

**`InvestigationPlan` has five steps, not four.** `docs/demo-scenario.md` describes a
"4-step plan naming CRM, usage, engagement, support". Four *source systems*, but CRM
contributes two distinct tools — the opportunity record and the activity history — so the
plan has five steps across those four systems. Evidence still lands on the documented
**6 items across ≥3 source systems**.

**`EvidenceSource` methods return a tuple, not a single record.** One call can yield
several distinct facts: two weekly usage periods are two things a hypothesis may cite
separately. This is what makes six evidence items fall out of five requests naturally
rather than by calling a source twice for the same data.

**`langgraph` resolved to 1.2.10, not the 0.2.x ADR-0002 assumed.** The `_Node` protocol
requires a callable whose parameter is literally named `state`; a bare
`Callable[[GraphState], ...]` does not satisfy it. Handled with a matching local protocol
rather than a type-ignore.

### Two bugs the tests found

**Attribute values were not quote-escaped.** Content escaping covered `& < >`, which is
right for element text and insufficient for an attribute: an `evidence_ref` of
`EV-001" trust="trusted` would have closed the id attribute and injected a second one.
Fixed with a separate `escape_attribute`, and the test that found it is kept.

**Re-investigating produced a traceback.** The state machine correctly refused
`ANALYZED → INVESTIGATING`, but through an unhandled exception. There is now an explicit
precondition and a clean CLI message pointing at `make seed && make ingest`.

---

## Deviations and findings from Session 4

**The MCP SDK resolved to 2.0.0, not the 1.1 the plan assumed.** `mcp.server.fastmcp` does
not exist in 2.x. The ergonomic `MCPServer` silently accepts unknown constructor arguments,
which is the opposite of what a strict-schema server wants, so the low-level
`mcp.server.lowlevel.Server` is used instead — handlers registered explicitly, results
returned as `ListToolsResult` / `CallToolResult`. Several SDK attributes are snake_case in
2.x (`Tool.input_schema`, `CallToolResult.is_error`, `InitializeResult.server_info`); the
dependency is pinned to `>=2.0.0,<2.1.0`.

**MCP is async; this system is not.** Rather than convert repositories, agents, nodes, and
730 tests, async is confined to `mcp/client.py` (a persistent `asyncio.Runner`) and the
`asyncio.run()` line in `scripts/mcp_server.py`. `InProcessMcpClient` touches no event loop
at all. Recorded as **ADR-0014**, with the reversal path written down.

**`RepositoryEvidenceSource` has a real contract defect, found by writing the MCP contract
next to it.** Its `get_email_activity` counts *all* engagement events, including
`meeting_held` — it conflates meetings with email activity. **The MCP contract is correct**:
`engagement_get_email_activity` and `engagement_get_meeting_activity` are separate tools.

The difference **does not surface for `ACC-1001`** (the golden account has no meetings in
the window), which is why byte-equivalent parity holds and **the golden scenario is
unaffected**. The repository source is now **legacy, retained only as the control in
`tests/integration/test_evidence_parity.py`**, and the defect is documented in its module
docstring rather than quietly fixed to make a test pass. Fixing it would change no output
today and is not Session 4's business.

**`make mcp` was broken and is now fixed.** The target ran `python -m
revenue_sentinel.mcp.server`, a module with no `__main__` block — so it imported, did
nothing, and exited 0. A target that silently succeeds while serving nothing is worse than
one that fails. It now runs `python -m scripts.mcp_server`, which is what the transport
tests drive.

**CI caught two defects the local suite could not.** The transport-parity tests passed
locally and failed on CI, and both causes were real rather than environmental flake.

`stdio_client` does **not** forward the parent environment — it starts the server with a
deliberately minimal one. Locally the child still found its configuration in the
repository's `.env`; on CI, where configuration lives in environment variables and no
`.env` exists, it died during startup with `ValidationError: database_url Field required`.
The child's environment is now derived explicitly from the resolved `Settings`, so it is
configured identically whichever source the parent read — and `ANTHROPIC_API_KEY` is
deliberately **not** among the variables passed, so the offline guarantee does not depend
on a developer's shell being clean.

Second, and only visible once the first was fixed: **the subprocess had been reading the
development database while `committed_scenario` seeded the test database.** The payloads
matched because both had been seeded from the same deterministic seed — which made the
parity assertion accidental rather than earned. The child is now pointed at the test
database, so the fixture's data is the data it reads.

**One assertion deliberately not written.** There is no stdio test for "a write with no
policy engine is refused". The refusal does happen — the stdio server binds `policy=None` —
but its client-visible shape was not verified, and asserting an unverified shape would be
worse than leaving it unasserted. The guarantee is proven four ways in-process against the
same dispatcher. A comment in `test_transport_parity.py` records it as an open Session 5
question. **No test was weakened, skipped, or xfailed to reach green.**

---

## Deviations and findings from Session 5

**A refused proposal had nowhere to live.** `interventions.action_type` and
`action_records.action_type` shared one enum whose members were all executable. A denied
proposal therefore could not be persisted at all — the refusal would have been dropped on
the floor, and a denial nobody can point at is indistinguishable from a denial that never
happened. Migration `0004` gives `interventions` a wider `proposed_action` type. The
execution enum stays narrow deliberately: a prohibited action has no representation in
the execution tables.

**Default-deny was almost dead code.** The natural way to classify an action is an
exhaustive `match` with a `case _` default — and mypy correctly reported that default as
unreachable, because the match covered every enum member. Left that way, a member added
later and forgotten would have fallen through to whichever branch happened to be last
rather than to DENY. `classify` now uses a mapping with a denying default, so
default-deny is a runtime property and not a comment.

**LangGraph checkpoints workflow state, and it must be serialisable.**
`ScoredIntervention` started as a plain class with `__slots__` and the whole suite failed
with `Type is not msgpack serializable` the moment it reached state. It is a frozen
dataclass now. Recorded because it is a real constraint on anything added to
`WorkflowState`, not a one-off.

**Six existing assertions changed, and none was weakened.** All six are exact-equality
assertions that were exactly right about a four-node graph and are now exactly right
about a six-node one: `graph_version` `v1` → `v2`; transitions `5` → `7`; model calls
`3` → `4`; enum types `26` → `27`. Nothing was relaxed to a range or an inequality.

**`detected` and `investigated` moved to `tests/integration/conftest.py`.**
`test_governance.py` asserts against the *same* golden run as `test_investigation.py`,
and two modules each running their own investigation would be two runs that could
disagree.

---

## Honest caveats

**The live path is unexercised.** See above. This is the largest gap in the project.

**Investigation is not replayable.** Running `make investigate` twice refuses, by design —
replay and idempotency are Session 6. Ingestion *is* replay-safe at three levels.

**`InMemorySaver` only.** No checkpoint survives a process restart. Inert today (nothing
interrupts); Session 6 changes that and ADR-0012 says so.

**Prompt quality is untested.** The prompts are reasonable and the framing is
deliberate, but no live response has ever been evaluated against them.

**Nothing executes.** The policy engine is real and its decisions are recorded, but an
ALLOW causes nothing to happen. The four write tools are still unwired from the graph and
`action_records` is empty — asserted by a test rather than assumed.

**Approvals have no UI and no endpoints.** `governance/approvals.py` is reachable from
tests and from persistence, and nowhere else. Approving something requires calling
Python. That is Session 6.

**`approval_requests` has no `requested_by` column.** The requesting actor is stored in
`decision_note` as `requested_by=<actor>`, and self-approval rejection reads it back from
there. It works and it is tested, but it is a workaround; the column belongs in the
schema. Recorded as an accepted limitation in ADR-0015.

**The scoring bands are heuristics, and the claim for them is narrow.** They are not
calibrated against historical outcomes — no such dataset exists for a synthetic account.
What they are is deterministic, versioned, inspectable, and tested at every boundary. The
same caveat ADR-0008 makes for the risk bands applies here.

**The stdio write-refusal shape is unpinned.** See the Session 4 deviations above.

**`make investigate` needs a database whose incident sequence has not advanced.** The
incident reference is part of the prompt digest, so a run against `INC-002` correctly raises
`FixtureMissError` rather than fabricating a response. That is fixture mode working as
designed (it never falls back to a live call), but it means the CLI demo wants a fresh
database. The full MCP-backed graph on `INC-001` is exercised by the integration suite on
every run.

**11 of 29 tables still have no accessor** — the governance, execution, cost, and
evaluation tables. `tool_calls` gained one in Session 4.

---

## Verified commands

```bash
make setup && make up && make migrate && make seed
make ingest                        # INC-001 opened at HIGH
make investigate INCIDENT=INC-001  # offline, no key, $0 — evidence now via MCP
make mcp                           # the GTM MCP server over stdio (SIMULATED adapters)
make check                         # lint, format, mypy --strict, boundaries, 730 tests
uv run alembic downgrade base && uv run alembic upgrade head
uv run alembic check               # no drift
```

---

## Next milestone — Session 6: Execution and audit

**Objective.** Carry out what the policy layer approved, idempotently, with a durable
checkpointer and a real human-in-the-loop interrupt.

**Session 5 leaves it well positioned:** the decisions exist and are recorded; the four
write tools exist, are policy-gated, and are tested; `action_records.idempotency_key` is
already `UNIQUE`. Session 6 wires the graph to act on an approval rather than inventing
the authorisation model under deadline.

**Carried into Session 6:**

1. Pin the client-visible shape of a stdio write refused for want of a policy engine.
2. Add `approval_requests.requested_by` as a real column — see the accepted limitation in
   ADR-0015.
3. Replace `InMemorySaver` with the durable checkpointer (ADR-0012), which only becomes
   load-bearing once an interrupt genuinely has to survive the process exiting.

**Will remain unfinished:** cost governance, evaluation, the dashboard.

---

## Standing risks

| Risk | State |
|---|---|
| **Hand-authored fixtures diverging from real model behaviour** | **Active and largest.** ADR-0013; closes only by running `make record` |
| Framework absorption into node bodies | Mitigated: AST test asserts no `db` import and ≤6 statements per node |
| Ingestion honesty eroding as adapters land | **Re-checked at Session 4 and held.** Every adapter declares SIMULATED; an undeclared one raises; the status is stamped on every result and survives stdio |
| Two transports drifting apart | Mitigated structurally: both call `dispatcher.dispatch`. Payload-equality test guards it |
| Schema over-modelled before use | 12 tables unused; corrective revisions expected in 5–7 |
| Session 9 dashboard overrun | Unchanged |

---

## Git state

| Item | Value |
|---|---|
| Branch | `main`, tracking `origin/main` |
| Pushed | Phase 0/1, Sessions 1–4 (39 commits, `82bee2b`) |
| Session 5 | **Uncommitted** — awaiting review |

---

## How this file is maintained

Updated at the end of **every** milestone, before the work is considered done (rule 17). It
records what is actually true, including what does not work and what was harder than
planned. If this file and the code disagree, the code is right and this file is a bug.
