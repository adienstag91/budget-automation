.PHONY: help dev reset db-up db-down init seed api web build

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

dev: ## One-command local setup: Postgres + schema + synthetic demo data
	./scripts/dev_setup.sh

reset: ## Wipe the local DB volume, then set everything up from scratch
	docker compose down -v
	./scripts/dev_setup.sh

db-up: ## Start the local Postgres container
	docker compose up -d postgres

db-down: ## Stop the local Postgres container (keeps data)
	docker compose stop

init: ## Initialize DB (schema + taxonomy + rules + accounts)
	budget-init

seed: ## (Re)seed synthetic demo data
	APP_MODE=demo python -m scripts.seed_demo

api: ## Run the FastAPI backend (http://localhost:8000)
	uvicorn api:app --reload --port 8000

web: ## Run the Vite dev server (http://localhost:5173)
	cd frontend && npm install && npm run dev

build: ## Build the single-container image locally
	docker build -t budget-automation .
