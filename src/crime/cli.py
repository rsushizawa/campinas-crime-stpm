"""Explicit commands for cube generation, reconciliation and publication export."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crime.config import NOTEBOOK_OUTPUTS_DIR, STAGING_DIR


def main(argv=None) -> int:
    """Run a requested operation; importing the CLI has no side effects."""
    parser = argparse.ArgumentParser(prog='crime')
    commands = parser.add_subparsers(dest='command', required=True)
    cube = commands.add_parser('cube', help='Generate a complete cube from staged data')
    cube.add_argument('--staging-dir', type=Path, default=STAGING_DIR)
    cube.add_argument('--group', default='all')
    cube.add_argument('--time-unit', choices=['month', 'quarter', 'year'], default='quarter')
    cube.add_argument('--unit', choices=['city', 'census_tract'], default='census_tract')
    cube.add_argument('--output', type=Path, required=True)
    paper = commands.add_parser('paper', help='Render or publish the JBCS asset bundle')
    paper.add_argument('operation', choices=['render', 'validate', 'publish'])
    paper.add_argument('--paper-dir', type=Path)
    paper.add_argument('--input-dir', type=Path, default=NOTEBOOK_OUTPUTS_DIR)
    paper.add_argument('--output-dir', type=Path)
    paper.add_argument('--manifest', type=Path)
    paper.add_argument('--tracts', type=Path)
    paper.add_argument('--bulletins', type=Path)
    paper.add_argument('--brazil', type=Path)
    paper.add_argument('--basemap', action='store_true')
    verify = commands.add_parser('verify', help='Reconcile a Base dos Dados census export')
    verify.add_argument('--tracts', type=Path)
    verify.add_argument('--reference', type=Path)
    verify.add_argument('--print-sql', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'cube':
        import pandas as pd

        from crime.exporter.assets import export_table
        from crime.generator import generate_cube, load_dataset
        from crime.models import CrimeQuery

        result = generate_cube(load_dataset(args.staging_dir),
                               CrimeQuery(crime_group=args.group, time_unit=args.time_unit, unit=args.unit))
        table = pd.DataFrame(result.counts, index=result.unit_ids, columns=result.periods)
        table.index.name, table.columns.name = 'unit_id', 'period_start'
        long = table.stack(future_stack=True).rename('count').reset_index()
        export_table(long, args.output)
        print(json.dumps({'output': str(args.output), 'shape': result.counts.shape,
                          'reports': int(result.counts.sum())}))
    elif args.command == 'paper':
        from crime.exporter.jbcs import JBCSProfile, generate_jbcs, publish_jbcs, validate_manifest

        profile = JBCSProfile(args.paper_dir) if args.paper_dir else JBCSProfile()
        if args.operation == 'render':
            if args.output_dir is None:
                parser.error('paper render requires --output-dir (an empty staging directory)')
            print(generate_jbcs(args.output_dir, profile=profile, input_dir=args.input_dir,
                                tracts_path=args.tracts, bulletins_path=args.bulletins,
                                brazil_path=args.brazil, basemap=args.basemap))
        else:
            if args.manifest is None:
                parser.error('paper validate/publish requires --manifest')
            if args.operation == 'validate':
                manifest = validate_manifest(args.manifest, require_complete=True)
                print(json.dumps({'assets': len(manifest['assets']), 'status': 'validated'}))
            else:
                print(json.dumps({'written': [str(p) for p in publish_jbcs(args.manifest, profile=profile)]}))
    else:
        from crime.validation.reconciliation import main as verify_main

        flags = ['--print-sql'] if args.print_sql else []
        for flag, value in [('--tracts', args.tracts), ('--reference', args.reference)]:
            if value is not None:
                flags.extend([flag, str(value)])
        return verify_main(flags)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
