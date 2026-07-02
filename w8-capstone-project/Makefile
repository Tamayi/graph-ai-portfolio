# Developer tasks. The project uses uv for environment management.
.PHONY: install lint format test check

install:        ## Install runtime + dev dependencies
	uv sync --group dev

lint:           ## Static checks (ruff)
	uv run ruff check .

format:         ## Auto-format (black)
	uv run black .

test:           ## Run the test suite (no keys, no network)
	uv run pytest

check: lint test  ## Lint then test, as CI does
