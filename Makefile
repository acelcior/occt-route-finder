# Day-to-day commands. `make help` lists them. SEASON defaults to the current one.
SEASON ?= fall2026
PY = .venv/bin/python

.PHONY: help setup test run check snapshot build promote update

help:
	@echo "make setup            create .venv and install deps"
	@echo "make test             run the test suite"
	@echo "make run              serve the app locally on http://localhost:8765"
	@echo "make check            diff live occtransport.org against the snapshot (SEASON=$(SEASON))"
	@echo "make update           refresh snapshot + rebuild the candidate dataset (review, then promote)"
	@echo "make build            rebuild the candidate from the committed snapshot"
	@echo "make promote          validate the candidate and make it live"
	@echo "make snapshot         fetch a fresh snapshot only (e.g. make snapshot SEASON=spring2027)"

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

test:
	$(PY) -m pytest -q

run:
	OCCT_SERVE_STATIC=1 .venv/bin/uvicorn api.index:app --app-dir src --reload --port 8765

check:
	$(PY) scripts/check_for_updates.py --season $(SEASON)

snapshot:
	$(PY) scripts/scrape_schedules.py --season $(SEASON)

build:
	$(PY) scripts/build_dataset.py --season $(SEASON) --strict

promote:
	$(PY) scripts/promote.py --season $(SEASON)

update:
	-$(PY) scripts/check_for_updates.py --season $(SEASON) --write
	$(PY) scripts/build_dataset.py --season $(SEASON) --strict
	@echo "Review: git diff data/occt_dataset.$(SEASON).candidate.json — then: make promote SEASON=$(SEASON)"
