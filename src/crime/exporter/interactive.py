"""Portable interactive figures shared by notebooks and external viewers."""
from pathlib import Path

from crime.visualizer.cube import CubeExplorer


def export_cube_html(view: CubeExplorer, destination: str | Path) -> Path:
    """Write a standalone HTML viewer; external versioned JS libraries need network."""
    destination = Path(destination)
    if destination.suffix.lower() != '.html':
        raise ValueError('Cube viewer export must use .html')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(view.document, encoding='utf-8')
    return destination
