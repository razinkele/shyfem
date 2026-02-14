PYTHON ?= /opt/micromamba/envs/shiny/bin/python

.PHONY: install test lint format e2e e2e-install coverage clean \
        docker-build docker-run pre-commit

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ -v --ignore=tests/test_playwright_*.py

lint:
	$(PYTHON) -m ruff check shyfem_ui/

format:
	$(PYTHON) -m black shyfem_ui/ tests/
	$(PYTHON) -m ruff check --fix shyfem_ui/

e2e-install:
	$(PYTHON) -m playwright install chromium --with-deps

e2e: e2e-install
	$(PYTHON) -m pytest tests/test_playwright_*.py -v

coverage:
	$(PYTHON) -m pytest tests/ -v --ignore=tests/test_playwright_*.py \
		--cov=shyfem_ui --cov-report=term-missing

docker-build:
	docker build -t shyfem-ui .

docker-run: docker-build
	docker run --rm -p 8000:8000 \
		-v $${SHYFEM_DIR:-/home/razinka/shyfem}:/shyfem:ro \
		-e SHYFEM_UI_SHYFEM_DIR=/shyfem \
		shyfem-ui

pre-commit:
	pre-commit run --all-files

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf .ruff_cache htmlcov .coverage coverage.xml *.egg-info
