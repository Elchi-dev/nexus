.DEFAULT_GOAL := help
.PHONY: help setup dev test lint fmt build clean

PYTHON := uv run python
PYTEST := uv run pytest
RUFF   := uv run ruff
MYPY   := uv run mypy

help:
	@echo ""
	@echo "  nexus — make targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""

setup: ## install all dependencies (Python + Rust + frontend)
	uv sync
	cargo build -p nexus-core-rs
	cd web/frontend && bun install

dev: ## start all nexus services in development mode
	$(PYTHON) scripts/dev.py

test: ## run Python + Rust test suites
	$(PYTEST)
	cargo test

lint: ## run ruff, mypy, and clippy
	$(RUFF) check .
	$(MYPY) .
	cargo clippy -- -D warnings

fmt: ## auto-format Python + Rust
	$(RUFF) format .
	cargo fmt

build: ## compile the Rust event bus (release mode)
	cargo build -p nexus-core-rs --release

clean: ## remove all build artifacts
	cargo clean
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
