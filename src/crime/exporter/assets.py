"""Small format-specific writers; no scientific calculations or database access."""
from pathlib import Path


def _path(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def export_geojson(frame, path):
    """Write RFC 7946 longitude/latitude coordinates without mutating the input."""
    if frame.crs is None:
        raise ValueError("GeoJSON export requires a declared CRS")
    path = _path(path)
    frame.to_crs(4326).to_file(path, driver="GeoJSON", index=False)
    return path


def export_geoparquet(frame, path):
    """Keep the input CRS and geometry in GeoParquet metadata."""
    if frame.crs is None:
        raise ValueError("GeoParquet export requires a declared CRS")
    path = _path(path)
    frame.to_parquet(path, index=False)
    return path


def export_table(table, path, *, index=False, **kwargs):
    """Export a DataFrame as CSV, Parquet, or LaTeX, or verbatim LaTeX text."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".parquet", ".tex"}:
        raise ValueError(f"Unsupported table format: {suffix}")
    path = _path(path)
    if suffix == ".tex":
        text = table if isinstance(table, str) else table.to_latex(index=index, **kwargs)
        path.write_text(text, encoding="utf-8")
    elif suffix == ".csv":
        table.to_csv(path, index=index, **kwargs)
    else:
        table.to_parquet(path, index=index, **kwargs)
    return path


def export_figure(figure, path, *, dpi=300, **kwargs):
    """Write a publication figure; omit variable PDF timestamps."""
    path = _path(path)
    if path.suffix.lower() == ".pdf":
        kwargs.setdefault("metadata", {"CreationDate": None, "ModDate": None})
    figure.savefig(path, dpi=dpi, bbox_inches="tight", **kwargs)
    return path
