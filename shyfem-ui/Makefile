PYTHON ?= /opt/micromamba/envs/shiny/bin/python

.PHONY: install test lint format e2e e2e-install coverage clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ -v --ignore=tests/test_playwright_*.py

lint:
	$(PYTHON) -m ruff check shyfem_ui/

format:
	$(PYTHON) -m black shyfem_ui/ tests/

e2e-install:
	$(PYTHON) -m playwright install chromium --with-deps

e2e: e2e-install
	$(PYTHON) -m pytest tests/test_playwright_*.py -v

coverage:
	$(PYTHON) -m pytest tests/ -v --ignore=tests/test_playwright_*.py \
		--cov=shyfem_ui --cov-report=term-missing

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf .ruff_cache htmlcov .coverage *.egg-info
