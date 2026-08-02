# Assumptions

**Last updated:** 2026-08-01 (Phase 1)

Assumptions this project rests on. Each is stated so it can be challenged, and each names
what breaks if it turns out to be wrong. An unstated assumption is a defect waiting to be
discovered late.

---

## 1. Domain assumptions

| # | Assumption | If wrong |
|---|---|---|
| A1 | Sales inactivity plus rising product usage is a genuine revenue-leakage signal, not noise | The whole first slice detects nothing meaningful; the detector needs redesign, not retuning |
| A2 | 14 days of inactivity is a reasonable stall threshold for a mid-market deal in `Proposal` | Threshold moves; the detector framework is unaffected |
| A3 | 40% week-over-week usage growth is a meaningful spike rather than normal variance | Threshold moves; may need a baseline-relative measure instead of a fixed percentage |
| A4 | Weighted pipeline value (`amount × stage probability`) is an acceptable impact basis | The calculator changes; the deterministic boundary does not |
| A5 | RevOps teams want ranked interventions, not a single recommendation | Strategy agent output shape changes |
| A6 | A human wants to approve customer-facing communication, and will | The approval inbox becomes a bottleneck rather than a feature — see [`RISKS.md`](RISKS.md) R7 |

A1 is load-bearing. If it is false, the demo is well-engineered and pointless. It is
plausible on its face — engaged buyer, absent seller — but it is an assumption, not a
finding, because there is no outcome data to validate it against.

---

## 2. Data assumptions

| # | Assumption | If wrong |
|---|---|---|
| A7 | Synthetic deterministic fixtures are sufficient to demonstrate the architecture | Need recorded real-shape data; adapter design unaffected |
| A8 | Six evidence items across three source systems is enough context for useful hypotheses | Evidence gathering widens; the plan step count grows |
| A9 | Source systems can be modelled with a single canonical event envelope | Per-source envelopes needed; normalizer becomes larger |
| A10 | Business keys (`ACC-1001`, `OPP-2001`) are stable across systems | Need an identity-resolution layer — a significant addition |

A10 is the one that would hurt most in a real deployment. Cross-system identity resolution
is a genuine problem that this project sidesteps entirely by controlling both sides of
every integration.

---

## 3. Technical assumptions

| # | Assumption | If wrong |
|---|---|---|
| A11 | Postgres is an adequate event substrate at demo volume | ADR-0006 revisit trigger fires; swap `events/` substrate |
| A12 | LangGraph's checkpointer can coexist with our transition table without conflict | ADR-0002's open question resolves the other way; may need to own the runtime |
| A13 | A modular monolith with enforced boundaries can later be extracted | Extraction costs more than planned; boundaries are still valuable |
| A14 | `claude-opus-5` structured outputs are reliable enough that schema failures are rare | More retries, higher cost; the validation gate still holds |
| A15 | Prompt caching works across nodes because the prefix is stable | Cost rises; correctness is unaffected |
| A16 | Recorded fixtures stay representative of live model behaviour | Fixture mode passes while the live path breaks — mitigated by the live smoke test (ADR-0007) |
| A17 | 15 narrow MCP tools cover the slice without a general-purpose escape hatch | Add tools; **never** add a broad one (rule 11 / ADR design) |

A16 is the sharpest technical assumption. Fixture mode buys determinism at the cost of
blindness to model drift, and the only mitigation is the manual live smoke test.

---

## 4. Environment assumptions

Verified on this machine, 2026-08-01.

| # | Assumption | Verified | Note |
|---|---|---|---|
| A18 | Python 3.12.3 available as `python3.12` | ✅ | `python3` is Anaconda **3.11.4** — never invoke it bare |
| A19 | Docker CLI 29.1.3 + Compose v5.0.1 present | ✅ | Daemon **not running**; must be started before Session 1 |
| A20 | Local Homebrew PostgreSQL 16.11 occupies port 5432 | ✅ | Compose binds **55432** to avoid a silent wrong-database connection |
| A21 | Node 22.22.3 and pnpm 10.28.1 available | ✅ | For Session 9 |
| A22 | `uv`, `ruff`, `mypy`, `gh` not installed | ✅ | `uv` installed Session 1 with approval; `gh` not required |
| A23 | No GitHub remote configured | ✅ | Nothing is pushed automatically |

---

## 5. Process assumptions

| # | Assumption |
|---|---|
| A24 | Eleven focused working sessions, not eleven calendar days |
| A25 | Each session ends at a milestone gate and waits for approval (rule 20) |
| A26 | Progress is committed incrementally; nothing is pushed automatically |
| A27 | The repository is public-facing and must contain no employer or customer data |
| A28 | The audience is technical interviewers who will read the code, not only the README |

A28 shapes more decisions than it looks like it should. It is why the `no_llm_arithmetic`
check queries the ledger rather than asserting the claim in prose, and why every ADR has a
"revisit when" section.

---

## 6. Assumptions deliberately not made

Worth recording, because each represents a shortcut that was available and declined.

| Not assumed | Why it matters |
|---|---|
| That an LLM will reliably refuse a malicious instruction | The policy layer bounds the consequence rather than trusting the model to resist (ADR-0005) |
| That fixture-backed integrations are "basically real" | They are SIMULATED everywhere, in code and in the UI (rule 5 / ADR-0004) |
| That approval can be implicit for "obviously safe" actions | Approval is always an explicit recorded event |
| That deterministic detection is less impressive than an LLM detector | It is more defensible, and the capability matrix says which is which |
| That documentation written now will stay accurate on its own | ADRs are immutable; docs are updated in the same commit as the change (rules 11, 15) |
