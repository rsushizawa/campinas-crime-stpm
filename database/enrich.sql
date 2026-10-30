-- Post-load enrichment: computed columns and feature views. Idempotent.

UPDATE dim_setor_censitario SET area_km2 = ST_Area(ST_Transform(geometry, 31983)) / 1e6;
UPDATE dim_grid_cell        SET area_km2 = ST_Area(ST_Transform(geometry, 31983)) / 1e6;

UPDATE dim_grid_cell g SET cd_setor = (
    SELECT s.cd_setor FROM dim_setor_censitario s
    WHERE ST_Contains(s.geometry, ST_Centroid(g.geometry))
    LIMIT 1
);

-- Sector population/households: exact Censo 2022 values are merged at load time
-- (Agregados por Setores Censitários); the area-weighted grid apportionment
-- below is only a fallback for tracts missing from that CSV.
UPDATE dim_setor_censitario s SET populacao_total = sub.pop, dom_total = sub.dom
FROM (
    SELECT s2.cd_setor,
           SUM(g.pop_total * ST_Area(ST_Intersection(g.geometry, s2.geometry))
               / NULLIF(ST_Area(g.geometry), 0)) AS pop,
           SUM(g.dom_total * ST_Area(ST_Intersection(g.geometry, s2.geometry))
               / NULLIF(ST_Area(g.geometry), 0)) AS dom
    FROM dim_setor_censitario s2
    JOIN dim_grid_cell g ON ST_Intersects(g.geometry, s2.geometry)
    GROUP BY s2.cd_setor
) sub
WHERE sub.cd_setor = s.cd_setor AND s.populacao_total IS NULL;

-- KNOWN MISLABEL (IC-Crime#1/#6): the sector/grid `income_mean` columns below hold the
-- UTB count of residents earning <= 1/2 minimum wage, NOT an income. Kept only so the
-- old schema keeps loading; use the IBGE 2022 V06004/V06006 columns (etl.sources.extract_income_2022).
UPDATE dim_setor_censitario s SET income_mean = (
    SELECT u.n_low_income_half_mw FROM dim_utb u
    WHERE ST_Contains(u.geometry, ST_Centroid(s.geometry))
    LIMIT 1
);

UPDATE dim_grid_cell g SET income_mean = (
    SELECT u.n_low_income_half_mw FROM dim_utb u
    WHERE ST_Contains(u.geometry, ST_Centroid(g.geometry))
    LIMIT 1
);

CREATE OR REPLACE VIEW vw_sector_features AS
WITH poi AS (
    SELECT cd_setor,
           COUNT(*) FILTER (WHERE cod_especie = 6) AS n_commercial,
           COUNT(*) FILTER (WHERE cod_especie = 4) AS n_educational,
           COUNT(*) FILTER (WHERE cod_especie = 5) AS n_health,
           COUNT(*) FILTER (WHERE cod_especie = 8) AS n_religious
    FROM dim_cnefe_enderecos
    GROUP BY cd_setor
)
SELECT
    s.cd_setor AS unit_id,
    s.area_km2,
    s.populacao_total AS pop_total,
    s.dom_total,
    s.income_mean,
    LN(1 + COALESCE(s.populacao_total, 0) / NULLIF(s.area_km2, 0))  AS log_pop_density,
    CASE
        WHEN COALESCE(p.alfa_15_mais_sabe, 0) + COALESCE(p.alfa_15_mais_nao_sabe, 0) > 0
        THEN p.alfa_15_mais_sabe::FLOAT / (p.alfa_15_mais_sabe + p.alfa_15_mais_nao_sabe)
    END                                                              AS literacy_rate,
    LN(1 + COALESCE(poi.n_commercial,  0) / NULLIF(s.area_km2, 0))  AS log_commercial_density,
    LN(1 + COALESCE(poi.n_educational, 0) / NULLIF(s.area_km2, 0))  AS log_educational_density,
    LN(1 + COALESCE(poi.n_health,      0) / NULLIF(s.area_km2, 0))  AS log_health_density,
    LN(1 + COALESCE(poi.n_religious,   0) / NULLIF(s.area_km2, 0))  AS log_religious_density,
    s.geometry
FROM dim_setor_censitario s
LEFT JOIN dim_setor_painel p ON s.cd_setor = p.cd_setor
LEFT JOIN poi                ON s.cd_setor = poi.cd_setor;

CREATE OR REPLACE VIEW vw_grid_features AS
WITH poi AS (
    SELECT grid_id,
           COUNT(*) FILTER (WHERE cod_especie = 6) AS n_commercial,
           COUNT(*) FILTER (WHERE cod_especie = 4) AS n_educational,
           COUNT(*) FILTER (WHERE cod_especie = 5) AS n_health,
           COUNT(*) FILTER (WHERE cod_especie = 8) AS n_religious
    FROM dim_cnefe_enderecos
    GROUP BY grid_id
)
SELECT
    g.grid_id AS unit_id,
    g.cd_setor,
    g.area_km2,
    g.pop_total::FLOAT AS pop_total,
    g.dom_total::FLOAT AS dom_total,
    g.income_mean,
    LN(1 + COALESCE(g.pop_total, 0) / NULLIF(g.area_km2, 0))        AS log_pop_density,
    CASE
        WHEN COALESCE(p.alfa_15_mais_sabe, 0) + COALESCE(p.alfa_15_mais_nao_sabe, 0) > 0
        THEN p.alfa_15_mais_sabe::FLOAT / (p.alfa_15_mais_sabe + p.alfa_15_mais_nao_sabe)
    END                                                              AS literacy_rate,
    LN(1 + COALESCE(poi.n_commercial,  0) / NULLIF(g.area_km2, 0))  AS log_commercial_density,
    LN(1 + COALESCE(poi.n_educational, 0) / NULLIF(g.area_km2, 0))  AS log_educational_density,
    LN(1 + COALESCE(poi.n_health,      0) / NULLIF(g.area_km2, 0))  AS log_health_density,
    LN(1 + COALESCE(poi.n_religious,   0) / NULLIF(g.area_km2, 0))  AS log_religious_density,
    g.geometry
FROM dim_grid_cell g
LEFT JOIN dim_setor_painel p ON g.cd_setor = p.cd_setor
LEFT JOIN poi                ON g.grid_id = poi.grid_id;
