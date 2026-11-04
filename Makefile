# campinas-crime-stpm: space-time analysis of police-recorded crime in Campinas (SP), 2022-2025.
#
# The ETL is a chain of stages; each stage is one node of this Makefile and is rerun only
# when its inputs or its code changed:
#
#   acquire -> clean -> units -> load -> validate -> notebooks
#
#   make env         locked environment (uv sync, uv.lock) -> .venv
#   make db          start the PostGIS warehouse (docker; PGPORT, default 5433)
#   make load        build the warehouse release (runs acquire, clean, units first when needed)
#   make reload      rebuild the release even if make thinks it is up to date (new volume, schema bump)
#   make validate    pandera checks on the loaded warehouse
#   make notebooks   execute every notebook (they read the warehouse; it must be loaded)
#   make test        pytest (database tests skip when PostGIS is unreachable)
#   make parity      the paper's numbers against tests/baseline (needs the loaded warehouse)
#
# Every stage prints a report table and saves it under outputs/reports/<stage>.md.

PY ?= .venv/bin/python
DB_PROJECT ?= campinas-crime-stpm
export PGPORT

STAGING := outputs/data/staging
ACQUIRED := outputs/data/crimes_campinas.csv
CLEANED := $(STAGING)/clean/bulletins.parquet
UNITS := $(STAGING)/units/bulletins.parquet
LOADED := $(STAGING)/load/loaded.stamp

.PHONY: help env db acquire clean units load reload validate notebooks test parity

# every raw input listed in inputs/data/SHA256SUMS (rule 1)
RAW := $(addprefix inputs/data/,$(shell sed -n 's/^[0-9a-f]\{64\}  //p' inputs/data/SHA256SUMS))
COMMON := etl/pipeline.py etl/stage_io.py crime/core/config.py

help:
	@sed -n '1,16p' Makefile

env:
	uv sync --all-extras

db:   # password: POSTGRES_PASSWORD in the environment or in .env (cp .env.example .env)
	docker compose -p $(DB_PROJECT) $(if $(wildcard .env),--env-file .env) -f database/docker-compose.yml up -d

# ---- stage 1: raw SSP-SP extracts -> offence records (rules 1-8)
$(ACQUIRED): inputs/data/SHA256SUMS $(RAW) $(COMMON) etl/acquire.py etl/steps/acquire.py scripts/01_acquire/acquire_ssp.py
	$(PY) scripts/01_acquire/acquire_ssp.py
acquire: $(ACQUIRED)

# ---- stage 2: offence records -> bulletins in 2022-2025 (rules 9-15)
$(CLEANED): $(ACQUIRED) $(COMMON) etl/clean.py etl/sources.py etl/steps/clean.py crime/core/taxonomy.py scripts/02_clean/clean_bulletins.py
	$(PY) scripts/02_clean/clean_bulletins.py
clean: $(CLEANED)

# ---- stage 3: tracts, 2022 attributes, POIs, tract of each bulletin (rules 16-22)
$(UNITS): $(CLEANED) $(RAW) $(COMMON) etl/census.py etl/sources.py etl/postgis.py etl/steps/units.py scripts/03_units/build_units.py
	$(PY) scripts/03_units/build_units.py
units: $(UNITS)

# ---- stage 4: write the warehouse release (rules 23-25) + data profile
$(LOADED): $(UNITS) $(COMMON) database/schema.sql etl/load.py etl/profile.py crime/data/warehouse.py scripts/04_load/load_warehouse.py
	$(PY) scripts/04_load/load_warehouse.py
	@mkdir -p $(dir $@) && date -u +%FT%TZ > $@
load: $(LOADED)
reload:
	rm -f $(LOADED)
	$(MAKE) load

# ---- stage 5: pandera checks on the loaded warehouse
validate: $(LOADED)
	$(PY) scripts/05_validate/validate_warehouse.py

# ---- analysis: the notebooks, executed headless in file-name order
NB ?= notebooks/*.ipynb
notebooks: validate
	$(if $(filter notebooks/*.ipynb,$(NB)),rm -rf outputs/nb,)   # a full run starts from empty outputs
	uv run jupyter nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=python3 $(NB)

test:
	$(PY) -m pytest -q

parity:
	$(PY) -m pytest -q tests/test_parity.py
