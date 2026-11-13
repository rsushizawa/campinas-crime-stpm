"""Explicit, bounded BigQuery reads; authentication never runs on import."""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from crime.utils.checksums import sha256

POPULATION_TABLE = 'basedosdados.br_ibge_populacao.municipio'
SINESP_TABLE = 'basedosdados.br_mj_sinesp.municipio_mes'
SSP_TABLE = 'basedosdados.br_sp_gov_ssp.ocorrencias_registradas'
POPULATION_SQL = f"""SELECT ano, id_municipio, populacao
FROM `{POPULATION_TABLE}`
WHERE ano = 2022 AND id_municipio = '3509502'"""


@dataclass(frozen=True)
class ReferenceQuery:
    """One source-native municipal extraction; do not mix reporting institutions."""

    project_id: str
    municipality: str = '3509502'
    start_year: int = 2022
    end_year: int = 2025
    maximum_bytes_billed: int = 1_000_000_000

    def __post_init__(self):
        if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', self.project_id):
            raise ValueError('Supply a Google Cloud project ID, not a project name or number')
        if not re.fullmatch(r'\d{7}', self.municipality):
            raise ValueError('Municipality must be a seven-digit IBGE code')
        if not 1900 <= self.start_year <= self.end_year <= 2100:
            raise ValueError('Require 1900 <= start_year <= end_year <= 2100')
        if self.maximum_bytes_billed <= 0:
            raise ValueError('maximum_bytes_billed must be positive')


@dataclass
class ReferenceSnapshot:
    """Data plus the exact query and job identity used to retrieve it."""

    data: pd.DataFrame
    table: str
    sql: str
    parameters: dict
    retrieved_at: str
    project_id: str
    job_id: str | None = None
    bytes_processed: int | None = None
    metadata: dict = field(default_factory=dict)

    def save(self, directory: str | Path, name: str = 'reference') -> Path:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Snapshot name must be a filename stem')
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{name}.parquet'
        self.data.to_parquet(path, index=False)
        meta = {k: v for k, v in self.__dict__.items() if k != 'data'}
        meta.update(sha256=sha256(path), rows=len(self.data))
        path.with_suffix('.json').write_text(json.dumps(meta, indent=2, default=str), encoding='utf-8')
        return path


def authenticate_google(project_id: str) -> None:
    """Explicit user-invoked Colab login, or validate existing local ADC credentials.

    Locally run ``gcloud auth application-default login`` first. Tokens are never
    returned or printed. Colab owns its browser-based authentication prompt.
    """
    ReferenceQuery(project_id)
    try:
        from google.colab import auth
    except ImportError:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError
        try:
            google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        except DefaultCredentialsError as exc:
            raise RuntimeError('Run gcloud auth application-default login locally, then rerun this cell') from exc
    else:
        auth.authenticate_user(project_id=project_id)


def _read(sql: str, request: ReferenceQuery, *, table: str, parameters=None, dry_run=False):
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise ImportError('Install campinas-crime-stpm[verification] for BigQuery access') from exc
    parameters = parameters or {}
    params = [bigquery.ScalarQueryParameter(k, 'INT64' if isinstance(v, int) else 'STRING', v)
              for k, v in parameters.items()]
    config = bigquery.QueryJobConfig(maximum_bytes_billed=request.maximum_bytes_billed,
                                    query_parameters=params, dry_run=dry_run, use_query_cache=not dry_run)
    client = bigquery.Client(project=request.project_id)
    try:
        job = client.query(sql, job_config=config)
        if dry_run:
            return {'table': table, 'estimated_bytes': job.total_bytes_processed,
                    'maximum_bytes_billed': request.maximum_bytes_billed}
        data = job.result().to_dataframe(create_bqstorage_client=False)
        return ReferenceSnapshot(data, table, sql, parameters, dt.datetime.now(dt.timezone.utc).isoformat(),
                                 request.project_id, job.job_id, job.total_bytes_processed)
    finally:
        client.close()


def read_sinesp(request: ReferenceQuery, *, dry_run=False):
    """Keep source-native indicators, institution, coverage flags and count units.

    No institutional filtering or summing is performed here. The importer
    requires an explicit reporting institution before constructing a series.
    """
    sql = f"""SELECT ano, mes, sigla_uf, id_municipio, tipo_ocorrencia,
       abrangencia, situacao_registro, quantidade_ocorrencias, quantidade_vitimas
FROM `{SINESP_TABLE}`
WHERE ano BETWEEN @start_year AND @end_year AND id_municipio = @municipality
ORDER BY ano, mes, tipo_ocorrencia, abrangencia"""
    return _read(sql, request, table=SINESP_TABLE, dry_run=dry_run,
                 parameters={'start_year': request.start_year, 'end_year': request.end_year,
                             'municipality': request.municipality})


def read_population(request: ReferenceQuery, *, year=2022, dry_run=False):
    sql = f"""SELECT ano, id_municipio, populacao FROM `{POPULATION_TABLE}`
WHERE ano = @year AND id_municipio = @municipality"""
    return _read(sql, request, table=POPULATION_TABLE, dry_run=dry_run,
                 parameters={'year': year, 'municipality': request.municipality})


def inspect_reference_schema(request: ReferenceQuery, source='sinesp'):
    """Inspect fields before extraction; table identifiers come from an allowlist."""
    tables = {'sinesp': SINESP_TABLE, 'ssp_history': SSP_TABLE, 'population': POPULATION_TABLE}
    table = tables[source]
    project, dataset, name = table.split('.')
    sql = f"SELECT column_name, data_type FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = @table_name ORDER BY ordinal_position"
    return _read(sql, request, table=table, parameters={'table_name': name})


def read_campinas_population(billing_project_id: str):
    """Return the 2022 municipal population, preserving the existing public call."""
    return read_population(ReferenceQuery(billing_project_id)).data
