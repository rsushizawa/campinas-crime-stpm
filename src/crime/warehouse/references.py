"""Append external snapshots without converting municipal totals into bulletins."""
from __future__ import annotations

import hashlib
import json

from crime.downloader.basedosdados import ReferenceSnapshot


def store_reference(engine, snapshot: ReferenceSnapshot) -> str:
    """Store source-native JSON rows and query provenance in a separate schema.

    Snapshots are content addressed and immutable; reloading an identical
    snapshot is a no-op. The study loader never drops this schema.
    """
    from sqlalchemy import text
    records = json.loads(snapshot.data.to_json(orient='records', date_format='iso'))
    metadata = {k: v for k, v in snapshot.__dict__.items() if k != 'data'}
    canonical = json.dumps({'metadata': metadata, 'rows': records}, sort_keys=True, default=str)
    key = hashlib.sha256(canonical.encode()).hexdigest()
    with engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS external_reference'))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS external_reference.snapshot (
            snapshot_id text PRIMARY KEY, source_table text NOT NULL,
            metadata jsonb NOT NULL, observations jsonb NOT NULL)'''))
        conn.execute(text('''INSERT INTO external_reference.snapshot
            (snapshot_id, source_table, metadata, observations)
            VALUES (:id, :source, CAST(:metadata AS jsonb), CAST(:rows AS jsonb))
            ON CONFLICT (snapshot_id) DO NOTHING'''),
                     {'id': key, 'source': snapshot.table, 'metadata': json.dumps(metadata, default=str),
                      'rows': json.dumps(records)})
    return key
