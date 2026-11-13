"""Stage, audit and explicitly publish JBCS assets without editing the manuscript.

Example (no database)::

    profile = JBCSProfile()
    manifest = generate_jbcs("outputs/publication-review", profile=profile)
    validate_manifest(manifest, require_complete=True)
    publish_jbcs(manifest, profile=profile)  # explicit overwrite, only after validation

``generate_jbcs`` never writes into the paper repository. Empty staging folders
are required so stale outputs cannot pass the completeness check.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from crime.config import DATA_VERSION, NOTEBOOK_OUTPUTS_DIR, REPO_ROOT, __version__

DEFAULT_PAPER = Path("/home/rx78/Documents/Projects/IC-Crime/paper/jbcs")
TABLE_IDENTITIES = {
    "tab_stl.tex": (6, "tab:stl"),
    "tab_global_moran.tex": (7, "tab:globalmoran"),
    "tab_local_fdr.tex": (8, "tab:localfdr"),
    "tab_ehsa_fdr.tex": (9, "tab:ehsafdr"),
    "tab_association.tex": (10, "tab:association"),
}
ALIASES = {"fig_study_area.png": "study_area.png",
           "feature_maps.png": "fig_feature_maps.png",
           "monthly_series.pdf": "fig_monthly_series.pdf"}


@dataclass(frozen=True)
class JBCSProfile:
    """The explicit publication target; generic exports never use these paths."""

    paper_dir: Path = field(default_factory=lambda: Path(os.environ.get("CRIME_JBCS_DIR", DEFAULT_PAPER)))
    figures_dir: str = "figures"
    tables_dir: str = "tables"
    manuscript: str = "main.tex"

    def __post_init__(self):
        object.__setattr__(self, "paper_dir", Path(self.paper_dir).resolve())
        for value in (self.figures_dir, self.tables_dir, self.manuscript):
            _relative(value)


def _relative(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Expected a safe relative asset path: {name}")
    return path


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _references(manuscript):
    text = Path(manuscript).read_text(encoding="utf-8")
    # Ignore commented references, retain their order and remove duplicates.
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)
    refs = re.findall(r"\\(?:includegraphics(?:\[[^\]]*\])?|input)\{([^}]+)\}", text)
    return list(dict.fromkeys(ref if Path(ref).suffix else ref + ".tex" for ref in refs))


def generate_jbcs(output_dir, *, profile=None, input_dir=NOTEBOOK_OUTPUTS_DIR,
                  tracts_path=None, bulletins_path=None, brazil_path=None,
                  data_version=DATA_VERSION, basemap=False, overview=True):
    """Generate a scratch bundle and deterministic provenance manifest.

    Inputs default to existing ETL stage files and notebook analysis results.
    ``overview=False`` permits a result-only bundle for inspection; publication
    still requires every manuscript reference unless explicitly opted out.
    Network tiles are opt-in and recorded in the render configuration.
    """
    import geopandas as gpd

    from crime.visualizer.overview import render_overview
    from crime.visualizer.paper import RenderContext, render_paper

    profile = profile or JBCSProfile()
    output_dir = Path(output_dir).resolve()
    if output_dir == profile.paper_dir or output_dir.is_relative_to(profile.paper_dir):
        raise ValueError("Generate in a scratch directory outside the paper repository")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Staging directory must be empty")
    tracts_path = Path(tracts_path or REPO_ROOT / "outputs/data/staging/units/tracts.parquet").resolve()
    bulletins_path = Path(bulletins_path or REPO_ROOT / "outputs/data/staging/units/bulletins.parquet").resolve()
    brazil_path = Path(brazil_path or profile.paper_dir / "data/ibge_brasil_uf.geojson").resolve()
    manuscript = profile.paper_dir / profile.manuscript
    references = _references(manuscript)
    context = RenderContext(input_dir, output_dir, gpd.read_parquet(tracts_path), basemap=basemap)
    context.sources.update([tracts_path, manuscript.resolve()])
    render_paper(context)
    gaps = render_overview(context, brazil_path=brazil_path, bulletins_path=bulletins_path) if overview else []
    # Every alias is copied from a newly rendered asset in this bundle.
    for alias, canonical in ALIASES.items():
        source = output_dir / canonical
        if source.is_file():
            target = output_dir / alias
            shutil.copyfile(source, target)
            context.assets.append(target)
    assets = []
    for asset in sorted(set(context.assets)):
        relative = asset.relative_to(output_dir).as_posix()
        directory = profile.tables_dir if asset.suffix == ".tex" else profile.figures_dir
        record = {"path": relative, "target": str(Path(directory) / relative),
                  "sha256": _hash(asset), "bytes": asset.stat().st_size}
        if asset.name in TABLE_IDENTITIES:
            number, label = TABLE_IDENTITIES[asset.name]
            record.update(table_number=number, label=label)
        if asset.name in ALIASES:
            record["alias_of"] = ALIASES[asset.name]
        assets.append(record)
    # Include the renderer/writer implementation so code changes invalidate provenance.
    code_paths = [Path(__file__), Path(__file__).with_name("assets.py")]
    code_paths += list((Path(__file__).parents[1] / "visualizer").glob("*.py"))
    sources = [{"path": str(path), "sha256": _hash(path)} for path in sorted(context.sources)]
    versions = {package: importlib.metadata.version(package) for package in
                ["matplotlib", "geopandas", "pandas", "numpy", "shapely", "pyproj", "libpysal"]}
    config = {"basemap": basemap, "overview": overview, "dpi": 300,
              "basemap_provider": "Esri.WorldGrayCanvas" if basemap else None,
              "metric_crs": "EPSG:31983", "profile": "jbcs", "data_version": data_version}
    manifest = {"schema_version": 1, "package_version": __version__, "data_version": data_version,
                "config": config, "versions": versions,
                "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                "sources": sources,
                "code": [{"path": str(p.resolve()), "sha256": _hash(p)} for p in sorted(code_paths)],
                "assets": assets, "references": references,
                "missing": sorted(set(references) - {a["target"] for a in assets}), "gaps": gaps}
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validate_manifest(path)
    return path


def validate_manifest(manifest_path, *, require_complete=False):
    """Check all output, input and code hashes before any publication writes."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported publication manifest version")
    config_hash = hashlib.sha256(json.dumps(manifest["config"], sort_keys=True).encode()).hexdigest()
    if config_hash != manifest["config_sha256"]:
        raise ValueError("Publication configuration hash mismatch")
    for record in manifest["sources"] + manifest["code"]:
        path = Path(record["path"])
        if not path.is_file() or _hash(path) != record["sha256"]:
            raise ValueError(f"Source changed or missing: {path}")
    targets = set()
    for asset in manifest["assets"]:
        path = manifest_path.parent / _relative(asset["path"])
        target = _relative(asset["target"]).as_posix()
        if target in targets:
            raise ValueError(f"Duplicate publication target: {target}")
        targets.add(target)
        if not path.is_file() or path.stat().st_size == 0 or _hash(path) != asset["sha256"]:
            raise ValueError(f"Asset changed or missing: {path}")
        if path.name in TABLE_IDENTITIES:
            number, label = TABLE_IDENTITIES[path.name]
            if (asset.get("table_number"), asset.get("label")) != (number, label):
                raise ValueError(f"Table identity changed: {path.name}")
            if rf"\label{{{label}}}" not in path.read_text(encoding="utf-8"):
                raise ValueError(f"Table label missing: {label}")
    missing = sorted(set(manifest["references"]) - targets)
    if require_complete and missing:
        raise ValueError(f"Missing manuscript assets: {', '.join(missing)}")
    return manifest


def publish_jbcs(manifest_path, *, profile=None, require_complete=True):
    """Explicitly copy a validated bundle into configured figures/tables paths.

    All hashes, table identities and current manuscript references are checked
    before the first write. The manuscript itself is never modified. Each file
    replacement is atomic; the whole multi-file operation is not transactional.
    """
    profile = profile or JBCSProfile()
    manifest_path = Path(manifest_path).resolve()
    manifest = validate_manifest(manifest_path, require_complete=require_complete)
    refs = _references(profile.paper_dir / profile.manuscript)
    if refs != manifest["references"]:
        raise ValueError("Target manuscript references differ from the staged bundle")
    destinations = []
    for asset in manifest["assets"]:
        target = _relative(asset["target"])
        directory = Path(profile.tables_dir if Path(asset["path"]).suffix == ".tex" else profile.figures_dir)
        if not target.is_relative_to(directory):
            raise ValueError(f"Asset target outside profile directory: {target}")
        destination = (profile.paper_dir / target).resolve()
        if not destination.is_relative_to(profile.paper_dir) or not destination.is_relative_to((profile.paper_dir / directory).resolve()) or destination == profile.paper_dir / profile.manuscript:
            raise ValueError(f"Unsafe publication target: {destination}")
        destinations.append((manifest_path.parent / asset["path"], destination))
    written = []
    for source, destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".publication-tmp")
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        written.append(destination)
    return tuple(written)
