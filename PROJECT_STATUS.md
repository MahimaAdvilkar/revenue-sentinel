# Project Status

**Last updated:** 2026-08-02
**Current milestone:** Session 1 — Foundations ✅ **COMPLETE**
**Next milestone:** Session 2 — Events, signals, incidents (awaiting approval)

---

## Where the project actually is

**It runs.** A fresh clone can install, start PostgreSQL, migrate, seed, and pass 228 tests
with the documented commands.

| Question | Answer |
|---|---|
| Can you run it? | Yes — `make setup && make up && make migrate && make seed && make test` |
| Can you run the tests? | Yes — 228 pass, 0 skipped, 0 xfailed |
| Are dependencies installed? | Yes — `uv` manages a Python 3.12.3 virtualenv |
| Is the database created? | Yes — 29 tables, 26 native enum types, one baseline migration |
| Is there data? | Yes — 92 deterministically seeded rows, all `is_simulated = true` |
| Does the API work? | `GET /health` only. Nothing else exists. |
| Does the demo work? | **No.** There is no workflow to demo yet — no agents, no LLM, no MCP. |
| Has this system ever called a model? | **No.** Not once. `anthropic` is installed and unimported. |

---

## Milestone log

### Phase 0 — Inspection and proposal ✅
Repository inspected; architecture proposed; complexity cut; vertical slice defined;
risks identified; five-minute demo designed.

### Phase 1 — Documentation and scaffolding ✅
20 documents + 7 ADRs; package boundaries; `pyproject.toml`, `Makefile`,
`docker-compose.yml`, `.env.example`, CI workflow. No application logic, no dependencies
installed.

### Session 1 — Foundations ✅

**Delivered**

| Group | Detail |
|---|---|
| `core/` | Pydantic Settings, structlog, injected clock, seeded IDs, error types, recursive `JSONValue` |
| `domain/` | 29 Pydantic models, 26 enums, cross-field invariants. Frozen, `extra="forbid"`, tz-aware, `Decimal` money |
| `analytics/` | `pipeline_impact.py` + `risk_bands.py` — the money math, exact to the cent |
| `db/` | 29 SQLAlchemy models, sync session factory, 7 repositories, deterministic seeder |
| `alembic/` | `alembic.ini`, `env.py`, `0001_baseline` — up and down both verified |
| `fixtures/seed/` | 7 JSON files, 92 rows, offsets relative to the injected clock |
| `api/` | `main.py` (app factory) + `health.py`. One route. |
| `tests/` | 228 tests: 167 unit, 61 integration |
| ADRs | 0008 (banded risk factors), 0009 (sync persistence), 0010 (no-`Any` enforcement) |

**Acceptance — all eleven criteria met**

| # | Criterion | Result |
|---|---|---|
| 1 | `make setup && make up && make migrate && make seed && make test` | ✅ verified from a clean database |
| 2 | PostgreSQL 16 on host **55432**, no conflict with the local 5432 | ✅ container healthy; the Homebrew instance on 5432 was left untouched |
| 3 | One baseline creates all tables; `downgrade` returns to empty | ✅ including `DROP TYPE` for all 26 enums, which autogenerate omits |
| 4 | Domain models are Pydantic v2 with zero `Any`; `mypy --strict` clean | ✅ — enforcement method changed, see "Deviations" below |
| 5 | `ruff check` and `ruff format --check` pass with no new ignores | ✅ zero ignores added |
| 6 | Seeding is deterministic — same seed, byte-identical rows | ✅ asserted by row digest across repeated runs |
| 7 | The golden scenario exists in the database and is asserted | ✅ 10 tests against `ACC-1001` / `OPP-2001` |
| 8 | `import-linter` proves all six boundary rules | ✅ 6 kept, 0 broken — with a caveat, see below |
| 9 | ≥25 tests pass, including the impact arithmetic to the cent | ✅ **228** |
| 10 | CI runs the identical gates | ✅ workflow corrected; a latent failure was fixed (below) |
| 11 | `PROJECT_STATUS.md` and `CAPABILITY_MATRIX.md` updated | ✅ this commit |

**Demo result.** `make seed` then `psql` shows `OPP-2001` at $180,000.00, stage `proposal`,
probability 0.6000, close date 2026-09-15, a 14-day sales-activity gap, and usage growth of
exactly +40.0% (1,250 → 1,750 feature events).

---

## What is real and what is not

**Real:** the schema and its constraints; the migration round trip; the deterministic
seeder; the pipeline-impact calculator; the repositories; the health endpoint; the layer
boundaries; the test suite.

**Simulated:** nothing yet, in the adapter sense. The seeded GTM data is loaded straight
into the mirror tables by [`db/seeding.py`](src/revenue_sentinel/db/seeding.py) — there is
no adapter, no port, and no `INTEGRATION_STATUS` constant in existence. Every seeded row
still carries `is_simulated = true`, which is what the dashboard will read later.

**Not real, and not claimed to be:** all agent behaviour, every LLM call, the MCP server,
the policy engine, execution, cost tracking, evaluation, and the dashboard. No real HubSpot,
Salesforce, Gmail, Slack, customer, or employer data is connected, and none will be.

---

## Deviations from the Session 1 plan — and why

Three things did not go as `IMPLEMENTATION_PLAN.md` specified. Recording them here rather
than letting them pass silently (rules 5 and 13).

**1. `disallow_any_explicit` was removed from `pyproject.toml`.**
Phase 1 set it for `domain/` and `analytics/`. It cannot be satisfied by *any* Pydantic
model: the pydantic mypy plugin synthesises an `Any`-typed `__init__`, so the flag fires on
the `class` line of every model regardless of what is written. It measured the plugin, not
our code. The intent — zero `Any` in the pure layers — is now enforced by
[`tests/unit/test_no_any_in_pure_layers.py`](tests/unit/test_no_any_in_pure_layers.py),
which walks the AST and is strictly stronger: it also catches `Any` inside string
annotations and `cast(Any, ...)`. `strict = true` remains in force everywhere. **ADR-0010.**

**2. `.importlinter` was not created.** The plan's file list named it, but the six contracts
already live in `pyproject.toml` from Phase 1. Two config sources would conflict, so the
contracts stayed where they were.

**3. `EvaluationOutcome` values are `passed`/`failed`/`skipped`, not `PASS`/`FAIL`/`SKIP`.**
`bandit` flags `PASS = "..."` as a possible hardcoded password. The alternative was an
`S105` suppression on the enum module, which would have silenced a real finding there later.
`docs/data-model.md` §3.7 was updated in the same commit.

### Two problems found and fixed

**A latent CI failure.** The Phase 1 workflow gated on `find tests -name 'test_*.py'`
anywhere under `tests/`. The moment unit tests existed, it would also have run
`pytest tests/evaluation` — which has no tests until Session 8, so pytest would exit 5 ("no
tests collected") and fail the build. The evaluation step now has its own guard.

**A real configuration bug.** `.env.example` ships `ANTHROPIC_API_KEY=` empty, and an empty
string satisfied the "key is present" check. `DEMO_MODE=live` would have started and then
failed at the first API call with an auth error, instead of refusing at startup. A blank key
is now treated as absent.

---

## Honest caveats about Session 1's guarantees

Two things are weaker than the headline suggests, and will strengthen on their own schedule:

**The `import-linter` contracts are partly vacuous today.** R1, R2, R4, R5, and R6 forbid
imports of packages that are still empty, so they pass partly by default. R3 (`analytics/`
cannot reach `intelligence/` or `agents/`) is real now, because `analytics/` has content —
and it is additionally checked by reading every import statement in the package. The rest
gain teeth as Sessions 2–6 fill those packages in.

**22 of the 29 tables have no accessor and no rows.** They exist in the schema, are covered
by the migration tests, and are typed in `domain/` — but nothing reads or writes them yet.
Building the whole schema on day one follows `docs/data-model.md` §6; the cost is that some
columns will be found wrong in Sessions 5–7 and corrected by a later revision.

---

## Verified commands

Every command below was run against this commit.

```bash
make setup                        # uv sync --all-extras
make up                           # PostgreSQL 16 on 55432, healthy
make migrate                      # 29 tables, 26 enum types
make seed                         # 92 rows, SEED=20260801
make check                        # lint, format, mypy, boundaries, tests
uv run alembic downgrade base     # returns to empty, enum types dropped
uv run alembic upgrade head       # restores cleanly
make api                          # then: curl localhost:8000/health
```

---

## Next milestone — Session 2: Events, signals, incidents

**Objective.** Turn raw events into a detected stalled opportunity and an open incident.

**Will build:** the canonical envelope and ingestion, per-source normalizers, the detector
framework, the `stalled_opportunity` detector, incident lifecycle transitions,
`POST /ingest`, `GET /incidents`.

**Session 1 leaves it well positioned:** the detector's inputs are already seeded and
asserted — a 14-day sales gap that an internal note deliberately does not reset, and usage
growth of exactly 40.0%, sitting precisely on the threshold boundary.

**Will remain unfinished:** investigation, agents, LLM calls, MCP.

---

## Standing risks

| Risk | State |
|---|---|
| Schema over-modelled before the workflow proves what it needs | **Active.** 22 tables unused. Accepted per data-model §6; expect corrective revisions in Sessions 5–7 |
| Risk-factor bands read as arbitrary | Mitigated by ADR-0008: bands are explicit, versioned, boundary-tested, and their claim is stated narrowly |
| Boundary contracts weaker than they appear | Tracked above; re-check at Session 4 when `mcp/` and `integrations/` become non-empty |
| Session 9 (dashboard) overrun | Unchanged. Contingency: cut Session 10 UI, never the audit trail or approval inbox |

---

## Git state

| Item | Value |
|---|---|
| Branch | `main`, tracking `origin/main` |
| Remote | `origin` → `github.com/MahimaAdvilkar/revenue-sentinel` — **configured**, contrary to what this file claimed at the end of Phase 1. The Phase 0/1 commit is already on it. |
| Commits | 2 local — Phase 0/1 documentation (pushed), Session 1 foundations (**local only**) |
| Push policy | Nothing is pushed automatically. Session 1 is committed locally and awaits review before any push. |

---

## How this file is maintained

Updated at the end of **every** milestone, before the work is considered done (rule 17). It
records what is actually true, including what does not work and what was harder than
planned. If this file and the code disagree, the code is right and this file is a bug.
