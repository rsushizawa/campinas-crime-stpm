# campinas-crime-stpm — space-time analysis (Esri "Space Time Pattern Mining" style)
# of police-recorded crime in Campinas (SP), 2022-2025. Stages follow Alexander (2023), Telling
# Stories with Data (ch. 3): acquire -> clean -> test -> analyse (Jupyter notebooks).
#
#   make env              # locked environment, all extras (uv sync, uv.lock) -> .venv
#   make db               # PostGIS (PGPORT / CRIME_DB_CONTAINER / DB_PROJECT override the defaults)
#   make acquire clean-data           # no database needed
#   make acquire clean validate       # + PostGIS load and validation
#   make notebooks        # execute every notebooks/*.ipynb in place (the analysis; no database)
#   make test             # pytest; DB tests are skipped when PostGIS is unreachable
#
# Run against a non-default database port with e.g. `PGPORT=5433 make clean`.

PY ?= .venv/bin/python
DB_PROJECT ?= campinas-crime-stpm
export PGPORT

.PHONY: help env db acquire clean clean-data load-db validate validate-no-db notebooks test

help:
	@sed -n '1,12p' Makefile

# Locked environment (uv.lock). Install uv: https://docs.astral.sh/uv/getting-started/installation/
env:
	uv sync --all-extras

db:   # password: POSTGRES_PASSWORD in the environment or in .env (cp .env.example .env)
	docker compose -p $(DB_PROJECT) $(if $(wildcard .env),--env-file .env) -f database/docker-compose.yml up -d

# 01_acquire: inputs/data (SSP-SP raw) -> outputs/data/crimes_campinas.csv
acquire:
	$(PY) scripts/01_acquire/acquire_ssp.py

# 02_clean: one row per bulletin + funnel, then the PostGIS rebuild
clean: clean-data load-db
clean-data:
	$(PY) scripts/02_clean/clean_bulletins.py
load-db:
	$(PY) scripts/02_clean/load_database.py

# 03_test: pandera validation of the cleaned table and the cube input.
# `validate` needs PostGIS and fails if it is unreachable; `validate-no-db` checks the parquet only.
validate:
	$(PY) scripts/03_test/validate_data.py
validate-no-db:
	$(PY) scripts/03_test/validate_data.py --no-db

# 04_analyse: the notebooks (notebooks/README.md), executed headless in file-name order.
# Each writes its tables / figures to outputs/nb/<notebook-stem>/. NB=notebooks/04_global_moran.ipynb runs one.
NB ?= notebooks/*.ipynb
notebooks:
	uv run jupyter nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=python3 $(NB)

# ---- tests ----------------------------------------------------------------------------------
test:
	$(PY) -m pytest -q
