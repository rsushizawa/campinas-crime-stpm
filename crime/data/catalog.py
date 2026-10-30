"""Data catalog: the model feature set and the pre-registered crime-slug scopes.

``DEFAULT_FEATURES`` — the model-ready urban-feature columns on
``vw_sector_features`` / ``vw_grid_features``.

Pre-registered per-crime-slug modeling scope.

Fixed BEFORE any model or statistic runs, from raw counts in ``fato_crimes``
(train = 2022-01-01..2023-12-31, test = 2024-01-01..2025-12-31):

    SELECT f.crime_slug,
           SUM(CASE WHEN f.data_ocorrencia < DATE '2024-01-01' THEN 1 ELSE 0 END) AS train_n,
           SUM(CASE WHEN f.data_ocorrencia >= DATE '2024-01-01' THEN 1 ELSE 0 END) AS test_n,
           COUNT(*) AS total_n
    FROM fato_crimes f GROUP BY 1;

Thresholds (pre-registered, not tuned on any downstream result):
  - CLASSIFIER_SLUGS  -- train_n >= 100 AND test_n >= 100. A case-control
    classifier + 5-fold CV needs both periods non-trivially populated.
  - ESDA_SLUGS        -- total_n >= 100 (superset of CLASSIFIER_SLUGS). Gi*/
    LISA/EHSA/Spearman need no train-test split, just enough events for a
    non-degenerate cross-sectional rate surface.
  - EHSA_SPARSE_SLUGS -- the subset of ESDA_SLUGS with total_n < 500. EHSA
    bins events into 48 monthly slices across ~2,592 sectors; below this
    count most slices are zero. Reported with a "sparse" flag, not excluded.
  - EXCLUDED_SLUGS    -- total_n < 100. Listed in the readiness table with
    their raw N, never silently dropped.

Every module that loops over crime slugs imports its slug list from here so
the three lists can't drift between the prediction and ESDA workstreams.

The scopes were fixed on the pre-#13 data and are kept as pre-registered.
The counts are no longer typed in: :func:`slug_counts` derives them from the
cleaned bulletins, and :func:`readiness_table` shows the scope next to the
tier the same thresholds give on the current data (``tier_now``).
"""

#: the model-ready urban-feature columns on ``vw_sector_features`` / ``vw_grid_features``
DEFAULT_FEATURES = (
    "log_pop_density", "income_mean", "literacy_rate", "log_commercial_density",
    "log_educational_density", "log_health_density", "log_religious_density",
)

# --- classifier pipeline: train_n >= 100 and test_n >= 100 (12 slugs) ------
CLASSIFIER_SLUGS = (
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
)

# --- ESDA / EHSA / Spearman: total_n >= 100 (16 slugs, superset of above) --
ESDA_ONLY_SLUGS = (
    "apreensao_entorpecente",
    "porte_arma",
    "estupro_vulneravel",
    "lesao_culposa_outras",
)
ESDA_SLUGS = CLASSIFIER_SLUGS + ESDA_ONLY_SLUGS

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

def slug_counts(path=None):
    """``{slug: (train_n, test_n, total_n)}`` computed from the data, never typed in.

    Reads the cleaned bulletins (``outputs/data/bulletins_clean.parquet``,
    ``scripts/02_clean``) and applies the query in the module docstring to the
    rows ``fato_crimes`` holds (bulletins with a usable coordinate). A missing
    occurrence date counts in ``total_n`` only, as ``CASE``/``COUNT(*)`` do.
    """
    import pandas as pd

    from crime.core.config import BULLETINS_PARQUET

    b = pd.read_parquet(path or BULLETINS_PARQUET,
                        columns=["crime_slug", "DATA_OCORRENCIA_BO", "LATITUDE", "LONGITUDE"])
    b = b[b["LATITUDE"].notna() & b["LONGITUDE"].notna()]
    cut = pd.Timestamp("2024-01-01")
    g = b.assign(train=b["DATA_OCORRENCIA_BO"].lt(cut), test=b["DATA_OCORRENCIA_BO"].ge(cut)).groupby("crime_slug")
    out = pd.DataFrame({"train_n": g["train"].sum(), "test_n": g["test"].sum(), "total_n": g.size()})
    return {s: (int(r.train_n), int(r.test_n), int(r.total_n)) for s, r in out.iterrows()}


def tier(train_n: int, test_n: int, total_n: int) -> str:
    """The pre-registered threshold rule (module docstring) applied to counts."""
    if train_n >= 100 and test_n >= 100:
        return "classifier"
    return "esda_only" if total_n >= 100 else "excluded"


def status(slug: str) -> str:
    """One of 'classifier', 'esda_only', or 'excluded' for any known slug."""
    if slug in CLASSIFIER_SLUGS:
        return "classifier"
    if slug in ESDA_ONLY_SLUGS:
        return "esda_only"
    if slug in EXCLUDED_SLUGS:
        return "excluded"
    raise KeyError(f"unknown crime slug: {slug!r}")


def readiness_table(counts=None):
    """One row per slug: slug, train_n, test_n, total_n, status (the
    pre-registered scope), tier_now (the same thresholds on the current data)
    and ehsa_sparse. ``counts`` defaults to :func:`slug_counts`."""
    import pandas as pd

    counts = slug_counts() if counts is None else counts
    rows = []
    for slug in ESDA_SLUGS + EXCLUDED_SLUGS:            # every scoped slug, also with 0 rows
        train_n, test_n, total_n = counts.get(slug, (0, 0, 0))
        rows.append({
            "crime_slug": slug,
            "train_n": train_n,
            "test_n": test_n,
            "total_n": total_n,
            "status": status(slug),
            "tier_now": tier(train_n, test_n, total_n),
            "ehsa_sparse": slug in EHSA_SPARSE_SLUGS,
        })
    return pd.DataFrame(rows).sort_values("total_n", ascending=False).reset_index(drop=True)
