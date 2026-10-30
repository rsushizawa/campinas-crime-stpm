"""Architecture gate: the subpackage dependency rule, and a light ``import crime``.

Layers (a module may import only from its own layer or layers to its left):

    core  <-  data  <-  esri / stats  <-  geoshapley  <-  viz

esri and stats are peers. Checked statically with ``ast`` (covers lazy,
function-level imports too), so no import-linter dependency is needed.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "crime"

RANK = {"core": 0, "data": 1, "esri": 2, "stats": 2, "geoshapley": 3, "viz": 4}
#: explicit, documented exceptions: (importer layer, imported layer)
ALLOWED = {("esri", "stats"), ("stats", "esri")}


def _layer(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "crime" and parts[1] in RANK else None


def _imports(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module


def _modules():
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG.parent).with_suffix("")
        yield path, ".".join(rel.parts)


@pytest.mark.parametrize("path,module", list(_modules()), ids=lambda x: str(x))
def test_layering(path, module):
    src = _layer(module)
    if src is None:                      # crime/__init__.py is the facade — may point anywhere
        return
    bad = []
    for line, imported in _imports(path):
        if imported == "crime":
            bad.append(f"{line}: 'import crime' (whole facade) inside the library")
            continue
        dst = _layer(imported)
        if dst is None or dst == src or (src, dst) in ALLOWED:
            continue
        if RANK[dst] > RANK[src]:
            bad.append(f"{line}: {src} -> {imported}")
    assert not bad, f"{module} breaks the layer rule:\n" + "\n".join(bad)


def test_no_flat_modules_left():
    flat = sorted(p.name for p in PKG.glob("*.py") if p.name != "__init__.py")
    assert not flat, f"modules outside a subpackage: {flat}"


def test_import_crime_is_light():
    code = ("import sys, crime; "
            "heavy = [m for m in ('matplotlib', 'sklearn', 'osmnx', 'plotly', 'ee', 'lightgbm', 'shap') "
            "if m in sys.modules]; print(','.join(heavy))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", f"import crime pulled in: {out.stdout.strip()}"


def test_every_export_resolves():
    code = ("import crime; missing = [n for n in crime.__all__ "
            "if not hasattr(crime, n)]; print(','.join(missing))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "", out.stdout + out.stderr
