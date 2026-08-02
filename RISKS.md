# Risk Register

**Last updated:** 2026-08-01 (Phase 1)

Live register. Reviewed at every milestone gate. Likelihood × impact, both High / Medium /
Low.

---

## Top five — active

### R1 · Documentation-first stall and subsequent drift
**Likelihood:** Medium · **Impact:** High · **Status:** Mitigated, monitoring

Twenty documents and seven ADRs exist before a line of application code. Two failure modes:
the project never gets past documentation, and the documents quietly stop matching the code.

**Mitigations in place**
- Documentation tiered — 9 deep, 3 initial with marked expansion points
- ADRs are immutable; a changed decision is a new ADR, never an edit
- Docs reference module paths, so drift is greppable
- Rules 11 and 15: architecture docs change in the same commit as the architecture

**Trigger to re-assess:** Session 3. If any deep-tier document already contradicts the code
by then, the tiering is not working.

---

### R2 · Scope explosion across seven future scenarios
**Likelihood:** Medium · **Impact:** High · **Status:** Contained

Seven additional scenarios are in the architecture. Implementing any of them before the
stalled-opportunity slice works would violate rule 2 and consume the sessions the slice
needs.

**Mitigations in place**
- Only `stalled_opportunity` is registered as an implemented detector
- The other seven exist as registry contracts with declared parameters and no behaviour
- All seven are ROADMAP in the capability matrix and the integration catalog
- Session-by-session "must remain unfinished" lists make the boundary explicit

**Trigger:** any commit adding a second detector implementation before Session 8.

---

### R3 · Simulated integrations read as fake
**Likelihood:** Medium · **Impact:** High · **Status:** Mitigated by design

A reviewer who sees "mocked integrations" may discount the whole project. The risk is not
that the integrations are simulated — it is that the simulation looks lazy.

**Mitigations in place**
- The seam is architectural: ports as `Protocol`s, adapters as swappable implementations
- `INTEGRATION_STATUS` is a code constant, surfaced through the MCP result envelope and the
  UI badge — honesty is data, not documentation
- Every adapter carries a "What changes when this becomes real" section naming the API,
  auth model, rate limits, and differing fields
- Simulated adapters inject latency and transient failures, so error paths are genuinely
  exercised (ADR-0004)

**Residual risk:** simulated adapters are too well-behaved. The first real integration will
surface pagination, schema drift, and partial-failure cases this design has not met.

---

### R4 · Nondeterministic LLM output breaks the demo
**Likelihood:** Low · **Impact:** High · **Status:** Mitigated

A live model call in an interview is slow, network-dependent, billable, rate-limitable, and
— worst — *different this time*.

**Mitigations in place**
- `DEMO_MODE=fixture` is the **default**; `make demo` runs fully offline with no API key
- Fixtures keyed by prompt digest; a miss raises rather than falling back to the network
- Fixed seed and injected evaluation timestamp
- Live mode is opt-in via configuration (ADR-0007)

**Residual risk:** fixture mode cannot detect model behaviour drift. Mitigated only by the
manual live smoke test, which must actually be run before a demo.

---

### R5 · Session 9 (dashboard) overruns and squeezes the finish
**Likelihood:** Medium · **Impact:** Medium · **Status:** Contingency defined

The dashboard is the largest single-session scope and the easiest place to lose time to
polish.

**Mitigations in place**
- Session 9 is read-only over APIs finalized in Sessions 6–7 — no backend work
- The approval inbox is the only interactive surface
- Explicit contingency: **cut Session 10's cost and evaluation UI, never the audit trail or
  the approval inbox**

---

## Secondary register

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R6 | **Session 6 interrupt/resume complexity** — the most intricate mechanism in the system; races on idempotency | M | H | Idempotency is a DB UNIQUE constraint, not app logic; concurrency test; process-restart test |
| R7 | **Approval inbox becomes a bottleneck** — more approvals than a human can process | M | M | v1 generates few; recorded as a scaling question in the roadmap. A HITL system that outpaces its humans has failed |
| R8 | **LangGraph absorption** — logic creeping into node bodies until the framework is the architecture | M | H | ADR-0002's three rules; `agents/` cannot import `db/`; code-review check for fat nodes |
| R9 | **Prompt-cache regression** — an accidentally dynamic system prompt silently multiplies cost | M | M | Frozen system prompt; deterministic tool ordering; test asserts `cache_read_input_tokens > 0` |
| R10 | **Stale fixtures** — a prompt changes, fixtures do not, tests pass against yesterday's prompt | M | M | Fixture-freshness check in CI; `make record`; live smoke test |
| R11 | **Detector thresholds tuned to the fixture** rather than to be defensible | M | M | Thresholds documented with rationale in the event model; boundary tests at 13 days and 39% |
| R12 | **Anaconda Python 3.11 shadowing 3.12** | L | M | `.python-version` pinned; never invoke bare `python3`; `uv` manages the environment |
| R13 | **Port 55432 not applied** — silent connection to the local Homebrew database | L | H | Set in `docker-compose.yml` and `.env.example`; Session 1 acceptance criterion |
| R14 | **Cost overrun during development** | L | M | Run/incident/global budgets default low; fixture mode is free; ceilings are pre-call |
| R15 | **Overclaiming in the README** under the temptation to sound impressive | M | H | Rule 5; capability matrix is the single source of truth; Session 11 acceptance requires plainly stated limitations |
| R16 | **A test weakened to make CI green** under time pressure | L | H | Rule 13, absolutely. No skip, no xfail, no loosened assertion. A red test is information |

R16 is listed with low likelihood and high impact deliberately. It is the failure that
would quietly invalidate every other guarantee in this document.

---

## Retired

*(none yet — Phase 1)*

---

## Review cadence

Reviewed at every milestone gate. Each review: re-score the top five, promote or demote
from the secondary register, retire what no longer applies, and record any new risk the
session surfaced. Risks are never silently dropped — they move to Retired with a reason.
