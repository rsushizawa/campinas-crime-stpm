"""Explicit notebook warehouse setup and loading; no effects at import time."""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from crime.config import WarehouseConfig

_COLAB_CONFIG = None


def start_colab_postgis() -> WarehouseConfig:
    """Start a disposable, loopback-only PostGIS database in a Colab runtime.

    System package installation is explicit because the caller runs this cell.
    An external PostGIS connection is the alternative on non-Colab platforms.
    No Docker daemon or public tunnel is needed.
    """
    global _COLAB_CONFIG
    try:
        import google.colab  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('Temporary setup is for Colab; locally use a configured PostGIS server or an external PostGIS server') from exc
    if _COLAB_CONFIG is not None:
        return _COLAB_CONFIG
    if os.geteuid() != 0:
        raise RuntimeError('Temporary PostGIS setup needs the standard Colab root runtime')
    def run(args):
        return subprocess.run(args, check=True, capture_output=True, text=True)
    run(['apt-get', 'update', '-qq'])
    run(['apt-get', 'install', '-y', '-qq', 'postgresql', 'postgis'])
    bindir = Path(run(['pg_config', '--bindir']).stdout.strip())
    major = run([str(bindir / 'postgres'), '--version']).stdout.split()[-1].split('.')[0]
    run(['apt-get', 'install', '-y', '-qq', f'postgresql-{major}-postgis-3'])
    root = Path(tempfile.mkdtemp(prefix='crime-postgis-'))
    password = secrets.token_urlsafe(32)
    shutil.chown(root, user='postgres', group='postgres')
    pwfile = root / 'password'
    pwfile.write_text(password)
    pwfile.chmod(0o600)
    shutil.chown(pwfile, user='postgres', group='postgres')
    def pg(args):
        return run(['runuser', '-u', 'postgres', '--', *map(str, args)])
    try:
        pg([bindir / 'initdb', '-D', root / 'data', '--auth-local=trust', '--auth-host=scram-sha-256',
            '--pwfile', pwfile])
    finally:
        pwfile.unlink(missing_ok=True)
    pg([bindir / 'pg_ctl', '-D', root / 'data', '-l', root / 'postgres.log',
        '-o', f'-p 55432 -h 127.0.0.1 -k {root}', '-w', 'start'])
    pg([bindir / 'createdb', '-h', root, '-p', '55432', 'crime_notebook'])
    _COLAB_CONFIG = WarehouseConfig(host='127.0.0.1', port=55432, user='postgres',
                                   database='crime_notebook', password=password)
    return _COLAB_CONFIG


def load_notebook_warehouse(dataset, config: WarehouseConfig, *, replace_existing=False):
    """Load the pinned dataset only into a new database or an explicit rebuild."""
    from sqlalchemy import text

    from crime.config import engine
    from crime.generator.pipeline import no_rejects
    from crime.warehouse.load import LoadInput, load_pipeline
    eng = engine(config)
    try:
        with eng.connect() as conn:
            existing = conn.execute(text("SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' "
                                         "AND tablename <> 'spatial_ref_sys')")).scalar_one()
        if existing and not replace_existing:
            raise ValueError('A warehouse already exists; select reuse, or explicitly enable replacement')
        reports = {}
        for report in dataset.reports:
            reports.setdefault(report.step, []).append(asdict(report))
        raw = {s.name: {'location': s.location, 'sha256': s.sha256} for s in dataset.sources}
        load = LoadInput(eng, dataset.bulletins, dataset.tracts, dataset.poi,
                         dataset.rejects if dataset.rejects is not None and len(dataset.rejects) else no_rejects(),
                         reports, raw)
        return load_pipeline().run(load)
    finally:
        eng.dispose()
