# Common tasks. `make help` lists them.
.DEFAULT_GOAL := help
.PHONY: help install test cov verify clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Create .venv and install dependencies
	python3 -m venv .venv
	./.venv/bin/pip install -q -r requirements.txt
	@echo "done — activate with: source .venv/bin/activate"

test:  ## Run the test suite
	pytest -q

cov:  ## Run tests with a coverage report
	pytest --cov=app --cov-report=term-missing -q

verify:  ## Run the full verification script
	./verify.sh

clean:  ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage .coverage.* htmlcov

.PHONY: up down load chaos
up:  ## Start the full stack (3 replicas + LB + DB + cache + monitoring)
	docker compose up --build

down:  ## Stop the stack and remove volumes
	docker compose down -v

load:  ## Run the k6 load test (needs: brew install k6)
	k6 run loadtest/redirect_load.js

chaos:  ## Kill a live replica under traffic and assert zero downtime
	./loadtest/chaos_test.sh
