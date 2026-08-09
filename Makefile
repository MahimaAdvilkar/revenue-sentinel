# Revenue Sentinel
#
# Most targets below are DECLARED but not yet functional — the application code
# they invoke does not exist until Session 1. Targets marked [Sn] become real in
# that session. See PROJECT_STATUS.md and IMPLEMENTATION_PLAN.md.

.DEFAULT_GOAL := help
SHELL := /bin/bash

PYTHON  := python3.12
UV      := uv
COMPOSE := docker compose

.PHONY: help
help:  ## Show this help
	@echo "Revenue Sentinel — available targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Targets marked [Sn] are not functional until Session n."

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
.PHONY: setup
setup:  ## [S1] Install dependencies into a local venv via uv
	$(UV) sync --all-extras

.PHONY: check-env
check-env:  ## Verify the toolchain without installing anything
	@echo "python3.12 : $$($(PYTHON) --version 2>&1 || echo 'NOT FOUND')"
	@echo "uv         : $$($(UV) --version 2>&1 || echo 'NOT FOUND — installed by make setup')"
	@echo "docker     : $$(docker --version 2>&1 || echo 'NOT FOUND')"
	@echo "compose    : $$(docker compose version 2>&1 | head -1 || echo 'NOT FOUND')"
	@echo "daemon     : $$(docker info --format '{{.ServerVersion}}' 2>/dev/null || echo 'NOT RUNNING — start Docker Desktop')"
	@echo "node       : $$(node --version 2>&1 || echo 'NOT FOUND')"
	@echo "pnpm       : $$(pnpm --version 2>&1 || echo 'NOT FOUND')"
	@echo "port 55432 : $$(lsof -ti :55432 >/dev/null 2>&1 && echo 'IN USE' || echo 'free')"

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
.PHONY: up
up:  ## Start PostgreSQL (host port 55432) and wait for health
	$(COMPOSE) up -d --wait

.PHONY: down
down:  ## Stop containers, keep the data volume
	$(COMPOSE) down

.PHONY: reset-db
reset-db:  ## DESTRUCTIVE — drop the database volume and recreate it
	@printf "This DELETES all local database data. Continue? [y/N] " && read ans && [ "$$ans" = "y" ]
	$(COMPOSE) down -v
	$(COMPOSE) up -d --wait

.PHONY: psql
psql:  ## Open a psql shell against the container
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-sentinel} -d $${POSTGRES_DB:-revenue_sentinel}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate:  ## [S1] Apply Alembic migrations
	$(UV) run alembic upgrade head

.PHONY: downgrade
downgrade:  ## [S1] Roll back one Alembic revision
	$(UV) run alembic downgrade -1

.PHONY: seed
seed:  ## [S1] Load deterministic synthetic data (SEED-controlled)
	$(UV) run python -m scripts.seed

# ---------------------------------------------------------------------------
# Quality gates — never bypassed (rule 13)
# ---------------------------------------------------------------------------
.PHONY: lint
lint:  ## [S1] Ruff lint
	$(UV) run ruff check .

.PHONY: format
format:  ## [S1] Ruff format (writes)
	$(UV) run ruff format .

.PHONY: format-check
format-check:  ## [S1] Ruff format check (read-only)
	$(UV) run ruff format --check .

.PHONY: types
types:  ## [S1] Mypy strict
	$(UV) run mypy src

.PHONY: boundaries
boundaries:  ## [S1] Enforce layer boundaries (import-linter)
	$(UV) run lint-imports

.PHONY: test
test:  ## [S1] Unit + integration tests
	$(UV) run pytest tests/unit tests/integration

.PHONY: eval
eval:  ## Deterministic evaluation of the golden run — $0, no model consulted
	$(UV) run python -m scripts.evaluate

.PHONY: check
check: lint format-check types boundaries test  ## [S1] Every gate CI runs

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
.PHONY: api
api:  ## [S1] Run the FastAPI app on :8000
	$(UV) run uvicorn revenue_sentinel.api.main:app --reload --port 8000

.PHONY: web
web:  ## Run the dashboard on :3000 (needs `make api` on :8000)
	cd apps/web && NEXT_TELEMETRY_DISABLED=1 pnpm dev

.PHONY: web-install
web-install:  ## Install frontend dependencies from the lockfile
	cd apps/web && pnpm install --frozen-lockfile

.PHONY: web-build
web-build:  ## Production build of the dashboard
	cd apps/web && NEXT_TELEMETRY_DISABLED=1 pnpm build

.PHONY: web-test
web-test:  ## Frontend typecheck + Vitest
	cd apps/web && pnpm typecheck && pnpm test

.PHONY: generate-api-types
generate-api-types:  ## Regenerate the TS contract from FastAPI's OpenAPI schema (ADR-0023)
	$(UV) run python -m scripts.export_openapi
	cd apps/web && pnpm generate:api

.PHONY: mcp
mcp:  ## Run the GTM MCP server over stdio (SIMULATED adapters)
	$(UV) run python -m scripts.mcp_server

# ---------------------------------------------------------------------------
# Demo — offline by default (ADR-0007)
# ---------------------------------------------------------------------------
.PHONY: ingest
ingest:  ## Ingest SIMULATED source events, detect signals, open incidents
	$(UV) run python -m scripts.ingest

.PHONY: investigate
investigate:  ## Run the investigation graph offline. INCIDENT=INC-001
	$(UV) run python -m scripts.investigate $(or $(INCIDENT),INC-001)

.PHONY: demo
demo:  ## Run the golden scenario end to end — OFFLINE, no API key, $0
	DEMO_MODE=fixture $(UV) run python -m scripts.demo

.PHONY: smoke-live
smoke-live:  ## [S10] Live model smoke test — REQUIRES ANTHROPIC_API_KEY, costs money
	DEMO_MODE=live $(UV) run pytest -m live

.PHONY: record
record:  ## [S10] Re-record LLM fixtures — REQUIRES ANTHROPIC_API_KEY, costs money
	@printf "This makes real billable API calls. Continue? [y/N] " && read ans && [ "$$ans" = "y" ]
	DEMO_MODE=record $(UV) run python -m scripts.record

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
.PHONY: clean
clean:  ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage dist build
