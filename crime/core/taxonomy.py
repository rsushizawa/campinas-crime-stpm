"""Crime taxonomy: raw SSP-SP ``NATUREZA_APURADA`` names to offence slugs and crime groups.

    from crime.core.taxonomy import to_slug, to_group, taxonomy_rows

``to_slug`` and ``to_group`` translate one raw name (``None`` when unknown;
the clean stage then stops, rule 11). The warehouse table ``dim_offence`` is
built from these tables by :func:`etl.load.offence_dimension`.
"""
import re
import unicodedata

import pandas as pd

CRIME_TYPE_LABELS = {
    "homicidio_doloso": "Intentional Homicide",
    "latrocinio": "Robbery Resulting in Death",
    "tentativa_homicidio": "Attempted Homicide",
    "extorsao_sequestro": "Kidnapping for Ransom",
    "roubo_outros": "Other Robbery",
    "furto_veiculo": "Vehicle Theft",
    "roubo_veiculo": "Vehicle Robbery",
    "furto_outros": "Other Theft",
    "roubo_carga": "Cargo Robbery",
    "furto_carga": "Cargo Theft",
    "roubo_banco": "Bank Robbery",
    "lesao_corporal_dolosa": "Intentional Bodily Harm",
    "lesao_corporal_morte": "Bodily Harm (Resulting in Death)",
    "porte_entorpecente": "Drug Possession",
    "trafico_entorpecente": "Drug Trafficking",
    "apreensao_entorpecente": "Drug Seizure",
    "porte_arma": "Illegal Firearm Possession",
    "homicidio_culposo_transito": "Negligent Homicide (Traffic)",
    "lesao_culposa_transito": "Negligent Bodily Harm (Traffic)",
    "homicidio_culposo_outros": "Negligent Homicide (Other)",
    "lesao_culposa_outras": "Negligent Bodily Harm (Other)",
    "estupro": "Rape",
    "estupro_vulneravel": "Rape of Vulnerable Person",
}

CRIME_GROUPS = {
    "violent": ["homicidio_doloso", "latrocinio", "tentativa_homicidio", "extorsao_sequestro"],
    "property": ["roubo_outros", "furto_veiculo", "roubo_veiculo", "furto_outros",
                 "roubo_carga", "furto_carga", "roubo_banco"],
    "bodily_harm": ["lesao_corporal_dolosa", "lesao_corporal_morte", "lesao_culposa_outras",
                    "homicidio_culposo_outros"],
    "drug": ["porte_entorpecente", "trafico_entorpecente", "apreensao_entorpecente", "porte_arma"],
    "traffic": ["homicidio_culposo_transito", "lesao_culposa_transito"],
    "sexual": ["estupro", "estupro_vulneravel"],
}

CRIME_GROUP_LABELS = {
    "violent": "Violent Crimes",
    "property": "Property Crimes",
    "bodily_harm": "Bodily Harm",
    "drug": "Drug-Related",
    "traffic": "Traffic Crimes",
    "sexual": "Sexual Crimes",
}

NATUREZA_TO_SLUG = {
    "homicidio_doloso": "homicidio_doloso",
    "latrocinio": "latrocinio",
    "latrocinio_roubo_seguido_de_morte": "latrocinio",
    "tentativa_de_homicidio": "tentativa_homicidio",
    "tentativa_homicidio": "tentativa_homicidio",
    "extorsao_mediante_sequestro": "extorsao_sequestro",
    "extorsao_sequestro": "extorsao_sequestro",
    "roubo_outros": "roubo_outros",
    "outros_roubos": "roubo_outros",
    "furto_de_veiculo": "furto_veiculo",
    "furto_veiculo": "furto_veiculo",
    "roubo_de_veiculo": "roubo_veiculo",
    "roubo_veiculo": "roubo_veiculo",
    "furto_outros": "furto_outros",
    "outros_furtos": "furto_outros",
    "roubo_de_carga": "roubo_carga",
    "roubo_carga": "roubo_carga",
    "furto_de_carga": "furto_carga",
    "furto_carga": "furto_carga",
    "roubo_a_banco": "roubo_banco",
    "roubo_banco": "roubo_banco",
    "lesao_corporal_dolosa": "lesao_corporal_dolosa",
    "lesao_corporal_seguida_de_morte": "lesao_corporal_morte",
    "lesao_corporal_morte": "lesao_corporal_morte",
    "porte_de_entorpecente": "porte_entorpecente",
    "porte_de_entorpecentes": "porte_entorpecente",
    "porte_entorpecente": "porte_entorpecente",
    "trafico_de_entorpecente": "trafico_entorpecente",
    "trafico_de_entorpecentes": "trafico_entorpecente",
    "trafico_entorpecente": "trafico_entorpecente",
    "apreensao_de_entorpecente": "apreensao_entorpecente",
    "apreensao_de_entorpecentes": "apreensao_entorpecente",
    "apreensao_entorpecente": "apreensao_entorpecente",
    "porte_ilegal_de_arma_de_fogo": "porte_arma",
    "porte_de_arma": "porte_arma",
    "porte_arma": "porte_arma",
    "homicidio_culposo_por_acidente_de_transito": "homicidio_culposo_transito",
    "homicidio_culposo_acidente_de_transito": "homicidio_culposo_transito",
    "homicidio_culposo_transito": "homicidio_culposo_transito",
    "homicidio_culposo_outros": "homicidio_culposo_outros",
    "lesao_corporal_culposa_por_acidente_de_transito": "lesao_culposa_transito",
    "lesao_corporal_culposa_acidente_de_transito": "lesao_culposa_transito",
    "lesao_culposa_transito": "lesao_culposa_transito",
    "lesao_corporal_culposa_outras": "lesao_culposa_outras",
    "estupro": "estupro",
    "estupro_de_vulneravel": "estupro_vulneravel",
    "estupro_vulneravel": "estupro_vulneravel",
}

SLUG_TO_GROUP = {slug: group for group, slugs in CRIME_GROUPS.items() for slug in slugs}


def normalize(s: str) -> str:
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def to_slug(raw: str) -> str | None:
    return NATUREZA_TO_SLUG.get(normalize(raw))


def to_group(raw: str) -> str | None:
    return SLUG_TO_GROUP.get(to_slug(raw))


def taxonomy_rows() -> pd.DataFrame:
    """Slug, group and labels of every slug, one row each (for documentation and audits)."""
    return pd.DataFrame([
        {
            "crime_slug": slug,
            "crime_group": SLUG_TO_GROUP.get(slug, "other"),
            "crime_type_label": CRIME_TYPE_LABELS.get(slug),
            "crime_group_label": CRIME_GROUP_LABELS.get(SLUG_TO_GROUP.get(slug, "")),
        }
        for slug in sorted(set(NATUREZA_TO_SLUG.values()))
    ])


# --------------------------------------------------------------------------- #
#  Maximum penalty per slug: the one-row-per-bulletin rule (IC-Crime#13)
# --------------------------------------------------------------------------- #
# A bulletin (NUM_BO + ANO_BO + NOME_DELEGACIA) can carry several offence
# records. ``collapse_bulletins`` keeps the record whose offence has the highest
# **maximum penalty of the base form (caput)** in Brazilian law, in years of
# imprisonment. Table approved by the project owner (2026-10-22). Ties are
# broken by preferring a specific slug over a ``*_outros``/``*_outras`` slug.
# ``apreensao_entorpecente`` is a seizure record, not an offence: ranked lowest.
# CP = Código Penal (Decreto-Lei 2.848/1940); CTB = Código de Trânsito
# Brasileiro (Lei 9.503/1997); L11.343 = Lei de Drogas; L10.826 = Estatuto do
# Desarmamento.
MAX_PENALTY = {
    # slug: (maximum penalty in years, legal basis)
    "latrocinio": (30.0, "CP art. 157 §3 II"),
    "homicidio_doloso": (20.0, "CP art. 121"),
    "extorsao_sequestro": (15.0, "CP art. 159"),
    "estupro_vulneravel": (15.0, "CP art. 217-A"),
    "trafico_entorpecente": (15.0, "Lei 11.343/2006 art. 33"),
    "tentativa_homicidio": (13.33, "CP art. 121 c/c art. 14 II (20 x 2/3)"),
    "lesao_corporal_morte": (12.0, "CP art. 129 §3"),
    "roubo_outros": (10.0, "CP art. 157"),
    "roubo_veiculo": (10.0, "CP art. 157"),
    "roubo_carga": (10.0, "CP art. 157"),
    "roubo_banco": (10.0, "CP art. 157"),
    "estupro": (10.0, "CP art. 213"),
    "porte_arma": (4.0, "Lei 10.826/2003 art. 14"),
    "furto_outros": (4.0, "CP art. 155"),
    "furto_veiculo": (4.0, "CP art. 155"),
    "furto_carga": (4.0, "CP art. 155"),
    "homicidio_culposo_transito": (4.0, "CTB art. 302"),
    "homicidio_culposo_outros": (3.0, "CP art. 121 §3"),
    "lesao_culposa_transito": (2.0, "CTB art. 303"),
    "lesao_corporal_dolosa": (1.0, "CP art. 129"),
    "lesao_culposa_outras": (1.0, "CP art. 129 §6"),
    "porte_entorpecente": (0.0, "Lei 11.343/2006 art. 28 (no imprisonment)"),
    "apreensao_entorpecente": (-1.0, "seizure record, not an offence (ranked lowest)"),
}


def is_generic(slug: str) -> bool:
    """``*_outros`` / ``*_outras``: the residual slug of an offence family."""
    return slug.endswith("_outros") or slug.endswith("_outras")


def severity_key(slug: str | None) -> tuple[float, int]:
    """Sort key, larger = kept: (maximum penalty, specific-over-generic).

    ``None`` (an unmapped ``NATUREZA_APURADA``) ranks below every slug; it is
    reported, not silently mapped. A slug missing from :data:`MAX_PENALTY`
    raises, so a new slug cannot enter the rule without a legal basis.
    """
    if slug is None or (isinstance(slug, float) and slug != slug):
        return (float("-inf"), 0)
    if slug not in MAX_PENALTY:
        raise KeyError(f"slug {slug!r} has no entry in crime.core.taxonomy.MAX_PENALTY")
    return (MAX_PENALTY[slug][0], 0 if is_generic(slug) else 1)


def penalty_rows() -> pd.DataFrame:
    """The :data:`MAX_PENALTY` table as a DataFrame (for docs / audit)."""
    return pd.DataFrame(
        [{"crime_slug": s, "max_years": y, "legal_basis": a, "crime_group": SLUG_TO_GROUP.get(s)}
         for s, (y, a) in sorted(MAX_PENALTY.items(), key=lambda kv: -kv[1][0])])
