"""Targeted reload of dim_setor_painel (literacy indicators) — no full rebuild.

    python scripts/02_clean/reload_painel.py

Truncates dim_setor_painel and repopulates it from etl.sources.extract_literacy(),
restricted to the sectors already in dim_setor_censitario. The feature views
recompute literacy_rate on the next query (they are plain VIEWs).
"""
import logging

from sqlalchemy import text

from crime.core.config import DBConfig, engine
from etl import sources
from etl.postgis import write_df

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("reload_painel")


def main() -> None:
    eng = engine(DBConfig())
    with eng.connect() as c:
        sectors = {r[0] for r in c.execute(text("SELECT cd_setor FROM dim_setor_censitario"))}
    log.info("%d sectors in dim_setor_censitario", len(sectors))

    painel = sources.extract_literacy()
    painel = painel[painel["cd_setor"].isin(sectors)]
    nonzero = int((painel["alfa_15_mais_sabe"].fillna(0) > 0).sum())
    log.info("extract_literacy: %d rows, %d with literate-15+ > 0", len(painel), nonzero)

    with eng.begin() as c:
        c.execute(text("TRUNCATE dim_setor_painel"))
    write_df(eng, painel, "dim_setor_painel")

    with eng.connect() as c:
        filled = c.execute(text("SELECT count(literacy_rate) FROM vw_sector_features")).scalar()
    log.info("dim_setor_painel: %d rows loaded; vw_sector_features.literacy_rate non-null: %d",
             len(painel), filled)


if __name__ == "__main__":
    main()
