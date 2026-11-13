-- Warehouse schema of campinas-crime-stpm, schema version 1.0.0
-- (crime.core.config.SCHEMA_VERSION must match; the reader refuses another version).
--
-- A star schema in the sense of Kimball & Ross (2013), The Data Warehouse Toolkit, 3rd ed.:
--   fact_bulletin       one row per police bulletin with an occurrence date in 2022-2025
--   dim_date            one row per calendar day of the study window
--   dim_offence         one row per offence slug (crime group, label, maximum penalty)
--   dim_census_tract    one row per IBGE 2022 census tract, with its 2022 attributes
--   poi                 one row per CNEFE point of interest (address and use type)
--   build               one row: the data release this database holds
--   reject              one row per record a treatment rule removed (Kimball & Caserta 2004,
--                       error event table)
--
-- Geometry is EPSG:31983 (SIRGAS 2000 / UTM 23S, metres). Every object is dropped and recreated,
-- so `the guided notebook warehouse setup` always rebuilds the release from scratch.

CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS reject           CASCADE;
DROP TABLE IF EXISTS build            CASCADE;
DROP TABLE IF EXISTS fact_bulletin    CASCADE;
DROP TABLE IF EXISTS poi              CASCADE;
DROP TABLE IF EXISTS dim_census_tract CASCADE;
DROP TABLE IF EXISTS dim_offence      CASCADE;
DROP TABLE IF EXISTS dim_date         CASCADE;

-- ------------------------------------------------------------------ build
CREATE TABLE build (
    data_version    TEXT PRIMARY KEY,
    schema_version  TEXT        NOT NULL,
    package_version TEXT        NOT NULL,
    code_commit     TEXT        NOT NULL,
    code_dirty      BOOLEAN     NOT NULL,
    built_at        TIMESTAMPTZ NOT NULL,
    raw_inputs      JSONB       NOT NULL,
    funnel          JSONB       NOT NULL,
    stage_reports   JSONB       NOT NULL
);
COMMENT ON TABLE  build IS 'The data release held by this database: one row, written last by the load.';
COMMENT ON COLUMN build.data_version IS 'Release version; git tag data-v<data_version>.';
COMMENT ON COLUMN build.schema_version IS 'Version of crime/warehouse/schema.sql used for this build.';
COMMENT ON COLUMN build.code_commit IS 'Git commit of the code that built the release.';
COMMENT ON COLUMN build.code_dirty IS 'True when the working tree had uncommitted changes at build time.';
COMMENT ON COLUMN build.raw_inputs IS 'SHA-256 of every raw input file, by path under inputs/data.';
COMMENT ON COLUMN build.funnel IS 'Rows at every cleaning stage, all groups and property (paper Data section).';
COMMENT ON COLUMN build.stage_reports IS 'Report lines of every treatment step (etl.pipeline.ReportLine).';

-- ------------------------------------------------------------------ dim_date
CREATE TABLE dim_date (
    date          DATE PRIMARY KEY,
    year          SMALLINT NOT NULL,
    quarter       SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month         SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year_start    DATE     NOT NULL,
    quarter_start DATE     NOT NULL,
    month_start   DATE     NOT NULL,
    iso_weekday   SMALLINT NOT NULL CHECK (iso_weekday BETWEEN 1 AND 7)
);
COMMENT ON TABLE dim_date IS 'One row per day of the study window 2022-01-01 to 2025-12-31; the *_start columns are the time bins.';

-- ------------------------------------------------------------------ dim_offence
CREATE TABLE dim_offence (
    crime_slug        TEXT PRIMARY KEY,
    crime_group       TEXT    NOT NULL CHECK (crime_group IN
                          ('property', 'bodily_harm', 'traffic', 'drug', 'violent', 'sexual')),
    offence_label     TEXT    NOT NULL,
    crime_group_label TEXT    NOT NULL,
    max_penalty_years NUMERIC NOT NULL,
    legal_basis       TEXT    NOT NULL,
    is_generic        BOOLEAN NOT NULL
);
COMMENT ON TABLE  dim_offence IS 'Offence slugs of etl.taxonomy: crime group, English label, maximum penalty used to pick one offence per bulletin.';
COMMENT ON COLUMN dim_offence.max_penalty_years IS 'Maximum penalty of the base form in Brazilian law (years; -1 ranks a seizure record lowest).';
COMMENT ON COLUMN dim_offence.is_generic IS 'True for the residual *_outros / *_outras slug of an offence family.';

-- ------------------------------------------------------------------ dim_census_tract
CREATE TABLE dim_census_tract (
    census_tract_id    TEXT PRIMARY KEY,
    district           TEXT,
    situation          TEXT,
    area_km2           DOUBLE PRECISION NOT NULL CHECK (area_km2 > 0),
    population         INTEGER CHECK (population >= 0),
    households         INTEGER CHECK (households >= 0),
    income_head_mean   DOUBLE PRECISION CHECK (income_head_mean >= 0),
    income_head_median DOUBLE PRECISION CHECK (income_head_median >= 0),
    literate_15_plus   DOUBLE PRECISION CHECK (literate_15_plus >= 0),
    illiterate_15_plus DOUBLE PRECISION CHECK (illiterate_15_plus >= 0),
    literacy_rate      DOUBLE PRECISION CHECK (literacy_rate BETWEEN 0 AND 1),
    n_commercial       INTEGER NOT NULL CHECK (n_commercial >= 0),
    n_education        INTEGER NOT NULL CHECK (n_education >= 0),
    n_health           INTEGER NOT NULL CHECK (n_health >= 0),
    n_religious        INTEGER NOT NULL CHECK (n_religious >= 0),
    geometry           GEOMETRY(Geometry, 31983) NOT NULL
                       CHECK (GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON') AND ST_IsValid(geometry))
);
CREATE INDEX dim_census_tract_geometry_idx ON dim_census_tract USING GIST (geometry);
COMMENT ON TABLE  dim_census_tract IS 'IBGE 2022 census tracts of Campinas (geobr) with their 2022 attributes; definitions in etl/census.py.';
COMMENT ON COLUMN dim_census_tract.population IS 'Residents, IBGE 2022 Agregados por Setores, Basico, V0001.';
COMMENT ON COLUMN dim_census_tract.households IS 'Occupied private households, same table, V0007.';
COMMENT ON COLUMN dim_census_tract.income_head_mean IS 'Mean nominal monthly income (R$) of household heads with income, IBGE 2022 Rendimento do Responsavel V06004; missing where IBGE suppresses.';
COMMENT ON COLUMN dim_census_tract.income_head_median IS 'Median of the same, V06006.';
COMMENT ON COLUMN dim_census_tract.literacy_rate IS 'literate_15_plus / (literate_15_plus + illiterate_15_plus).';
COMMENT ON COLUMN dim_census_tract.n_commercial IS 'CNEFE 2022 addresses of use type 6 (other purposes, the commerce proxy) inside the tract.';
COMMENT ON COLUMN dim_census_tract.area_km2 IS 'Polygon area in EPSG:31983, km2.';

-- ------------------------------------------------------------------ poi
CREATE TABLE poi (
    address_id      TEXT     NOT NULL,
    poi_type_code   SMALLINT NOT NULL CHECK (poi_type_code IN (4, 5, 6, 8)),
    poi_type        TEXT     NOT NULL CHECK (poi_type IN ('education', 'health', 'commercial', 'religious')),
    census_tract_id TEXT REFERENCES dim_census_tract (census_tract_id),
    geometry        GEOMETRY(Point, 31983) NOT NULL,
    PRIMARY KEY (address_id, poi_type_code)
);
CREATE INDEX poi_tract_idx ON poi (census_tract_id);
COMMENT ON TABLE poi IS 'CNEFE 2022 points of interest: one row per address and use type (COD_UNICO_ENDERECO, COD_ESPECIE).';

-- ------------------------------------------------------------------ fact_bulletin
CREATE TABLE fact_bulletin (
    bulletin_id          TEXT PRIMARY KEY,
    bulletin_year        SMALLINT NOT NULL,
    bulletin_number      TEXT     NOT NULL,
    police_station       TEXT     NOT NULL,
    occurrence_date      DATE     NOT NULL REFERENCES dim_date (date),
    occurrence_time      TIME,
    period_of_day        TEXT,
    registration_date    TIMESTAMP,
    location_type        TEXT,
    neighbourhood        TEXT,
    offence_reported     TEXT     NOT NULL,
    crime_slug           TEXT     NOT NULL REFERENCES dim_offence (crime_slug),
    n_offence_records    SMALLINT NOT NULL CHECK (n_offence_records >= 1),
    offences_on_bulletin TEXT     NOT NULL,
    coord_status         TEXT     NOT NULL CHECK (coord_status IN
                             ('ok', 'fixed_decimal', 'zero', 'redacted', 'missing', 'invalid')),
    latitude             DOUBLE PRECISION,
    longitude            DOUBLE PRECISION,
    census_tract_id      TEXT REFERENCES dim_census_tract (census_tract_id),
    geometry             GEOMETRY(Point, 31983),
    source_file          TEXT     NOT NULL,
    UNIQUE (bulletin_year, bulletin_number, police_station),
    CHECK ((coord_status IN ('ok', 'fixed_decimal')) = (latitude IS NOT NULL AND longitude IS NOT NULL)),
    CHECK ((geometry IS NULL) = (latitude IS NULL)),
    CHECK (census_tract_id IS NULL OR geometry IS NOT NULL)
);
CREATE INDEX fact_bulletin_date_idx  ON fact_bulletin (occurrence_date);
CREATE INDEX fact_bulletin_tract_idx ON fact_bulletin (census_tract_id);
CREATE INDEX fact_bulletin_slug_idx  ON fact_bulletin (crime_slug);
CREATE INDEX fact_bulletin_geom_idx  ON fact_bulletin USING GIST (geometry);
COMMENT ON TABLE  fact_bulletin IS 'One row per SSP-SP police bulletin (NUM_BO + ANO_BO + NOME_DELEGACIA) with an occurrence date in 2022-2025; the spatial event set is the rows with census_tract_id.';
COMMENT ON COLUMN fact_bulletin.bulletin_id IS 'ANO_BO/NUM_BO/NOME_DELEGACIA.';
COMMENT ON COLUMN fact_bulletin.offence_reported IS 'NATUREZA_APURADA of the kept record, as published.';
COMMENT ON COLUMN fact_bulletin.crime_slug IS 'Offence of the kept record: the most serious offence on the bulletin (rule 9).';
COMMENT ON COLUMN fact_bulletin.n_offence_records IS 'Offence records the bulletin had before the collapse.';
COMMENT ON COLUMN fact_bulletin.offences_on_bulletin IS 'Sorted, |-joined slugs of every record on the bulletin.';
COMMENT ON COLUMN fact_bulletin.coord_status IS 'Rules 5-7: ok, fixed_decimal (repaired), zero, redacted, missing, invalid.';
COMMENT ON COLUMN fact_bulletin.latitude IS 'Published latitude (WGS84) when coord_status is ok or fixed_decimal.';
COMMENT ON COLUMN fact_bulletin.census_tract_id IS 'Tract containing the point (rules 16-17); missing outside every tract or without a coordinate.';
COMMENT ON COLUMN fact_bulletin.location_type IS 'DESCR_SUBTIPOLOCAL, as published.';
COMMENT ON COLUMN fact_bulletin.neighbourhood IS 'BAIRRO, as published.';

-- ------------------------------------------------------------------ reject
CREATE TABLE reject (
    reject_id    BIGSERIAL PRIMARY KEY,
    data_version TEXT NOT NULL,
    stage        TEXT NOT NULL CHECK (stage IN ('acquire', 'clean', 'units', 'load')),
    step         TEXT NOT NULL,
    rule         TEXT NOT NULL,
    record_key   TEXT NOT NULL,
    reason       TEXT NOT NULL,
    record       JSONB NOT NULL
);
CREATE INDEX reject_rule_idx ON reject (rule);
COMMENT ON TABLE  reject IS 'Records removed by a treatment rule, with the original values (error event table, Kimball & Caserta 2004).';
COMMENT ON COLUMN reject.rule IS 'Rule number of the treatment table (docs/TREATMENTS.md).';
COMMENT ON COLUMN reject.record IS 'The removed row as JSON, as it was when the rule removed it.';
