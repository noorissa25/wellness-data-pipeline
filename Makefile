PYTHON ?= python3
VENV   ?= .venv
PY     := $(VENV)/bin/python
DATA   ?= data

.PHONY: help setup generate pipeline run incremental status dashboard preview site test lint clean

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

$(PY):
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -e ".[dashboard,dev]"

setup: $(PY)  ## create the virtualenv and install dependencies

generate: $(PY)  ## write seeded synthetic landing files (deterministic)
	$(PY) -m wellness --data-dir $(DATA) generate

pipeline: $(PY)  ## ingest new landing files, build silver and gold, run quality checks
	$(PY) -m wellness --data-dir $(DATA) run

run: generate pipeline  ## generate data and build every layer

incremental: $(PY)  ## land three more weeks of data and load only that batch
	$(PY) -m wellness --data-dir $(DATA) generate --start 2026-10-01 --days 21 --batches 1 --seed 7
	$(PY) -m wellness --data-dir $(DATA) run

status: $(PY)  ## show runs, watermarks, quality results and quarantine
	$(PY) -m wellness --data-dir $(DATA) status

$(DATA)/warehouse/wellness.duckdb:
	$(MAKE) run

PORT ?= 8501

dashboard: $(PY) $(DATA)/warehouse/wellness.duckdb  ## serve the dashboard at http://localhost:8501
	WELLNESS_DATA_DIR=$(DATA) $(VENV)/bin/streamlit run dashboard/app.py \
		--server.port $(PORT) --server.headless true --browser.gatherUsageStats false

preview: dashboard  ## one command: set up, build the data if needed, serve the dashboard

site: $(PY) $(DATA)/warehouse/wellness.duckdb  ## export the static web page to ./site (open site/index.html)
	$(PY) -m wellness --data-dir $(DATA) site --out site

test: $(PY)  ## run unit and end-to-end tests
	$(PY) -m pytest

lint: $(PY)  ## lint with ruff
	$(VENV)/bin/ruff check src tests dashboard

clean:  ## delete generated data and the warehouse
	rm -rf $(DATA)/landing $(DATA)/warehouse site
