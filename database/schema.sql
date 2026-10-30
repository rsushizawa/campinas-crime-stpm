CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Idempotent reset: the full object list lives here only (scripts/02_clean/load_database.py just
-- replays this file), not duplicated in a separate _DROP_ALL string.
DROP VIEW  IF EXISTS vw_sector_features    CASCADE;
DROP VIEW  IF EXISTS vw_grid_features      CASCADE;
DROP VIEW  IF EXISTS vw_analytical_dataset CASCADE;
DROP TABLE IF EXISTS fato_crimes           CASCADE;
DROP TABLE IF EXISTS dim_crime_taxonomy    CASCADE;
DROP TABLE IF EXISTS dim_cnefe_enderecos   CASCADE;
DROP TABLE IF EXISTS dim_setor_painel      CASCADE;
DROP TABLE IF EXISTS dim_utb               CASCADE;
DROP TABLE IF EXISTS dim_grid_cell         CASCADE;
DROP TABLE IF EXISTS dim_ambiente_urbano   CASCADE;
DROP TABLE IF EXISTS dim_setor_censitario  CASCADE;

-- Census tract dimension — geometry from geobr (IBGE 2022 malha, Campinas)
CREATE TABLE dim_setor_censitario (
    cd_setor        VARCHAR(20) PRIMARY KEY,
    nm_municipio    VARCHAR(100),
    nm_distrito     VARCHAR(100),
    situacao        VARCHAR(20),
    area_km2        FLOAT,
    populacao_total FLOAT,
    dom_total       FLOAT,
    income_mean     FLOAT,
    geometry        GEOMETRY(Geometry, 4326)
);
CREATE INDEX idx_setor_geom ON dim_setor_censitario USING GIST(geometry);

-- IBGE statistical grid dimension — 200m cells clipped to Campinas
CREATE TABLE dim_grid_cell (
    grid_id     VARCHAR(20) PRIMARY KEY,
    cd_setor    VARCHAR(20),
    pop_total   INT,
    dom_total   INT,
    area_km2    FLOAT,
    income_mean FLOAT,
    geometry    GEOMETRY(Geometry, 4326)
);
CREATE INDEX idx_grid_geom  ON dim_grid_cell USING GIST(geometry);
CREATE INDEX idx_grid_setor ON dim_grid_cell (cd_setor);

-- UTB polygons — income data + map overlay boundaries
CREATE TABLE dim_utb (
    gid         INT PRIMARY KEY,
    utb_sigla   VARCHAR(100),
    denominacao VARCHAR(200),
    tot_pop     FLOAT,
    tot_dom     FLOAT,
    tot_pop_fa  FLOAT,
    n_low_income_half_mw FLOAT,   -- UTB `rendatemei`: COUNT of residents earning <= 1/2 min. wage (not income)
    geometry    GEOMETRY(Geometry, 4326)
);
CREATE INDEX idx_utb_geom ON dim_utb USING GIST(geometry);

-- Sector panel — IBGE 2022 literacy indicators
CREATE TABLE dim_setor_painel (
    cd_setor              VARCHAR(20) PRIMARY KEY,
    alfa_15_29_sabe       INT,
    alfa_15_29_nao_sabe   INT,
    alfa_30_59_sabe       INT,
    alfa_30_59_nao_sabe   INT,
    alfa_60_mais_sabe     INT,
    alfa_60_mais_nao_sabe INT,
    alfa_15_mais_sabe     INT,
    alfa_15_mais_nao_sabe INT
);

-- CNEFE address points (IBGE 2022)
-- COD_ESPECIE: 1=private household, 2=collective household, 3=agro,
--              4=education, 5=health, 6=other establishments (commerce proxy),
--              7=under construction, 8=religious
CREATE TABLE dim_cnefe_enderecos (
    cod_unico_endereco  VARCHAR(20),
    cd_setor            VARCHAR(20),
    grid_id             VARCHAR(20),
    cep                 VARCHAR(8),
    dsc_localidade      VARCHAR(200),
    nv_geo_coord        SMALLINT,
    cod_tipo_especi     INT,
    dsc_estabelecimento VARCHAR(100),
    cod_especie         SMALLINT,
    geometry            GEOMETRY(Point, 4326),
    PRIMARY KEY (cod_unico_endereco, cod_especie)   -- one row per use type per address (IC-Crime#18)
);
CREATE INDEX idx_cnefe_geom    ON dim_cnefe_enderecos USING GIST(geometry);
CREATE INDEX idx_cnefe_setor   ON dim_cnefe_enderecos (cd_setor);
CREATE INDEX idx_cnefe_grid    ON dim_cnefe_enderecos (grid_id);
CREATE INDEX idx_cnefe_especie ON dim_cnefe_enderecos (cod_especie);

-- Crime taxonomy — canonical slug + group, populated at ETL time
CREATE TABLE dim_crime_taxonomy (
    crime_slug        VARCHAR(50) PRIMARY KEY,
    crime_group       VARCHAR(30) NOT NULL,
    crime_type_label  VARCHAR(100),
    crime_group_label VARCHAR(50)
);

-- Crime fact table — one row per occurrence bulletin (deduplicated in scripts/02_clean, IC-Crime#13),
-- natures translated at ingest; only bulletins with a usable coordinate are loaded
CREATE TABLE fato_crimes (
    id_crime         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    num_bo           VARCHAR(20),
    ano_bo           SMALLINT,
    nome_delegacia   VARCHAR(120),     -- with num_bo + ano_bo: the bulletin key (unique, IC-Crime#13)
    data_ocorrencia  DATE,
    hora_ocorrencia  TIME,
    periodo          VARCHAR(30),
    subtipo_local    VARCHAR(100),
    nm_bairro        VARCHAR(100),
    natureza_apurada VARCHAR(100),
    crime_slug       VARCHAR(50),
    crime_group      VARCHAR(30),
    lat              FLOAT,
    long             FLOAT,
    geometry         GEOMETRY(Geometry, 4326),
    cd_setor         VARCHAR(20),
    grid_id          VARCHAR(20)
);
CREATE INDEX idx_crimes_geom  ON fato_crimes USING GIST(geometry);
CREATE INDEX idx_crimes_setor ON fato_crimes (cd_setor);
CREATE INDEX idx_crimes_grid  ON fato_crimes (grid_id);
CREATE INDEX idx_crimes_ano   ON fato_crimes (ano_bo);
CREATE INDEX idx_crimes_slug  ON fato_crimes (crime_slug);
CREATE INDEX idx_crimes_grupo ON fato_crimes (crime_group);
