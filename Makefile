# campinas-crime-stpm — classical space-time pattern mining (Esri "Space Time Pattern Mining" style)
# of police-recorded crime in Campinas (SP), 2022-2025. Stages follow Alexander (2023), Telling
# Stories with Data (ch. 3): acquire -> clean -> test -> analyse.
#
#   make env              # locked environment, all extras (uv sync, uv.lock) -> .venv
#   make db               # PostGIS (PGPORT / CRIME_DB_CONTAINER / DB_PROJECT override the defaults)
#   make acquire clean-data analyse figures   # no database needed
#   make acquire clean validate       # + PostGIS load and validation
#   make test             # pytest; DB tests are skipped when PostGIS is unreachable
#
# Run against a non-default database port with e.g. `PGPORT=5433 make clean`.

PY ?= .venv/bin/python
DB_PROJECT ?= campinas-crime-stpm
export PGPORT

.PHONY: help env db acquire clean clean-data load-db validate validate-no-db analyse analyse-quick figures test

help:
	@sed -n '1,10p' Makefile

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

# 04_analyse: the core pipeline (STL, Moran, Gi*, LISA, EHSA, space-time LISA, TSC, MAUP,
# Ripley / NNI / KDE, Knox, Spearman + bivariate Moran) -> outputs/core/. No database.
# Parameters: scripts/04_analyse/core_config.py. Piecemeal: ANALYSE_ARGS="--steps where --groups property".
analyse:
	$(PY) scripts/04_analyse/run_core.py $(ANALYSE_ARGS)
analyse-quick:
	$(PY) scripts/04_analyse/run_core.py --quick

# 05_figures: outputs/core/ -> outputs/figures/<group>/*.png + index.md. Reads the stage-04 tables
# and the unit geometries only (no database, no statistics). Basemap tiles off (FIGURES_ARGS="--basemap").
# Piecemeal: FIGURES_ARGS="--groups property drug".
figures:
	$(PY) scripts/05_figures/make_figures.py $(FIGURES_ARGS)

# ---- tests ----------------------------------------------------------------------------------
test:
	$(PY) -m pytest -q
