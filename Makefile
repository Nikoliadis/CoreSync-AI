.DEFAULT_GOAL := help
API := apps/api
UV := uv --directory $(API)

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ environment
.PHONY: install
install: ## Install API dependencies
	$(UV) sync --all-extras --dev

.PHONY: up
up: ## Start the local stack (postgres, redis, api, worker, minio, mailhog, web)
	docker compose up -d
	@echo "API   → http://localhost:8000/docs"
	@echo "Web   → http://localhost:3000"
	@echo "Mail  → http://localhost:8025"
	@echo "MinIO → http://localhost:9001"

.PHONY: down
down: ## Stop the local stack
	docker compose down

.PHONY: reset
reset: ## Destroy local data and rebuild from scratch
	docker compose down -v
	docker compose up -d
	sleep 5
	$(MAKE) migrate

.PHONY: logs
logs: ## Tail API logs
	docker compose logs -f api worker

# -------------------------------------------------------------------- database
.PHONY: migrate
migrate: ## Apply migrations
	$(UV) run alembic upgrade head

.PHONY: migration
migration: ## Create a migration: make migration m="add exercises"
	@test -n "$(m)" || (echo "usage: make migration m=\"description\"" && exit 1)
	$(UV) run alembic revision --autogenerate -m "$(m)"
	@echo "⚠  Autogenerate is a DRAFT. Review it by hand before committing."

.PHONY: downgrade
downgrade: ## Roll back one migration
	$(UV) run alembic downgrade -1

# ----------------------------------------------------------------------- serve
.PHONY: dev
dev: ## Run the API with hot reload
	$(UV) run uvicorn coresync.presentation.main:app --reload --port 8000

# ----------------------------------------------------------------------- tests
.PHONY: test
test: ## Run every test
	$(UV) run pytest -q

.PHONY: test-unit
test-unit: ## Run unit tests only (no database needed, <5s)
	$(UV) run pytest tests/unit -q

.PHONY: test-api
test-api: ## Run API + integration tests (requires Docker)
	$(UV) run pytest tests/api tests/integration -q

.PHONY: cov
cov: ## Run tests with a coverage report
	$(UV) run pytest --cov=coresync --cov-report=term-missing --cov-report=html
	@echo "Report → $(API)/htmlcov/index.html"

# --------------------------------------------------------------------- quality
.PHONY: lint
lint: ## Lint and type-check
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy src/coresync/domain src/coresync/application src/coresync/core
	$(UV) run lint-imports

.PHONY: fmt
fmt: ## Auto-fix and format
	$(UV) run ruff check . --fix
	$(UV) run ruff format .

.PHONY: check
check: lint test-unit ## What CI runs on a PR, minus the database tests

# --------------------------------------------------------------------- utility
.PHONY: openapi
openapi: ## Export the OpenAPI spec to apps/api/openapi.json
	@cd $(API) && uv run python -c "import json; \
from coresync.core.config import Settings; \
from coresync.presentation.main import create_app; \
print(json.dumps(create_app(Settings()).openapi(), indent=2))" > openapi.json
	@echo "→ $(API)/openapi.json"
