"""Data catalog: the urban-feature set and the crime-slug readiness scopes.

``DEFAULT_FEATURES`` — the urban-feature columns on the warehouse views
``vw_sector_features`` / ``vw_grid_features`` (``database/enrich.sql``).

Per-crime-slug readiness scope, from the number of geocoded bulletins of the
slug (``fato_crimes`` rows) over the whole study period:

  - ESDA_SLUGS        -- total_n >= 100: enough events for a non-degenerate
    Gi* / LISA / EHSA / Spearman surface.
  - EHSA_SPARSE_SLUGS -- the subset of ESDA_SLUGS with total_n < 500. EHSA
    bins events into 48 monthly slices across ~2,592 tracts; below this
    count most slices are zero. Reported with a "sparse" flag, not excluded.
  - EXCLUDED_SLUGS    -- total_n < 100. Listed in the readiness table with
    their raw N, never silently dropped.

The lists were fixed on earlier data and are kept as stated. The counts are
not typed in: :func:`slug_counts` derives them from the cleaned bulletins, and
:func:`readiness_table` shows the scope next to the tier the same thresholds
give on the current data (``tier_now``). The notebooks analyse crime
*groups* (``etl/taxonomy.py``, :data:`crime.data.api.GROUPS`), not single
slugs; this table documents data readiness per slug.
"""

#: the urban-feature columns on ``vw_sector_features`` / ``vw_grid_features``
DEFAULT_FEATURES = (
    "log_pop_density", "income_mean", "literacy_rate", "log_commercial_density",
    "log_educational_density", "log_health_density", "log_religious_density",
)

# --- ESDA / EHSA / Spearman: total_n >= 100 (16 slugs) --------------------
ESDA_SLUGS = (
    "furto_outros",
    "roubo_outros",
    "furto_veiculo",
    "lesao_corporal_dolosa",
    "lesao_culposa_transito",
    "roubo_veiculo",
    "trafico_entorpecente",
    "roubo_carga",
    "porte_entorpecente",
    "homicidio_culposo_transito",
    "homicidio_doloso",
    "tentativa_homicidio",
    "apreensao_entorpecente",
    "porte_arma",
    "estupro_vulneravel",
    "lesao_culposa_outras",
)

# --- EHSA sparse flag: subset of ESDA_SLUGS with total_n < 500 -------------
EHSA_SPARSE_SLUGS = (
    "roubo_carga",
    "homicidio_culposo_transito",
    "porte_arma",
    "homicidio_doloso",
    "estupro_vulneravel",
    "tentativa_homicidio",
    "apreensao_entorpecente",
    "lesao_culposa_outras",
)

# --- excluded: total_n < 100 (7 slugs) -------------------------------------
EXCLUDED_SLUGS = (
    "estupro",
    "furto_carga",
    "extorsao_sequestro",
    "latrocinio",
    "homicidio_culposo_outros",
    "lesao_corporal_morte",
    "roubo_banco",
)


def slug_counts(path=None) -> dict[str, int]:
    """``{slug: total_n}`` computed from the data, never typed in: rows of the
    cleaned bulletins (``outputs/data/bulletins_clean.parquet``,
    ``scripts/02_clean``) with a usable coordinate (the rows ``fato_crimes``
    holds), any occurrence date."""
    import pandas as pd

    from crime.core.config import BULLETINS_PARQUET

    b = pd.read_parquet(path or BULLETINS_PARQUET, columns=["crime_slug", "LATITUDE", "LONGITUDE"])
    b = b[b["LATITUDE"].notna() & b["LONGITUDE"].notna()]
    return {s: int(n) for s, n in b.groupby("crime_slug").size().items()}


def tier(total_n: int) -> str:
    """The threshold rule (module docstring) applied to a count."""
    return "esda" if total_n >= 100 else "excluded"


def status(slug: str) -> str:
    """'esda' or 'excluded' — the stated scope of any known slug."""
    if slug in ESDA_SLUGS:
        return "esda"
    if slug in EXCLUDED_SLUGS:
        return "excluded"
    raise KeyError(f"unknown crime slug: {slug!r}")


def readiness_table(counts=None):
    """One row per slug: slug, total_n, status (the stated scope), tier_now
    (the same threshold on the current data) and ehsa_sparse. ``counts``
    defaults to :func:`slug_counts`."""
    import pandas as pd

    counts = slug_counts() if counts is None else counts
    rows = []
    for slug in ESDA_SLUGS + EXCLUDED_SLUGS:            # every scoped slug, also with 0 rows
        total_n = int(counts.get(slug, 0))
        rows.append({
            "crime_slug": slug,
            "total_n": total_n,
            "status": status(slug),
            "tier_now": tier(total_n),
            "ehsa_sparse": slug in EHSA_SPARSE_SLUGS,
        })
    return pd.DataFrame(rows).sort_values("total_n", ascending=False).reset_index(drop=True)
