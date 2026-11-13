# Study-data releases

The Python package does not embed the 525 MB raw study bundle. Publish the
bundle as a versioned release asset with the relative paths from
`crime/downloader/campinas-2022-2025.sha256` at its root.

Each release may also contain `release.json`:

```json
{
  "version": "1.0.0",
  "files": {
    "SPDadosCriminais_2025.xlsx": "<sha256>",
    "crimes_campinas_2022_2024.csv.bak": "<sha256>"
  }
}
```

The `files` object must contain every file used by the treatment and its exact
SHA-256 digest. The downloader verifies every file before publishing it. When
updating an existing directory, old files are retained under `.releases/`.

The reserved release URL is:

```text
https://github.com/rsushizawa/campinas-crime-stpm/releases/download/data-v1.0.0
```

Override it with `CRIME_DATA_RELEASE_URL` or the notebook's
`DATA_RELEASE_URL`. Use `ensure_study_inputs(..., mode="local")` for a fully
offline run, `mode="download"` to require the selected release, or
`mode="auto"` to reuse a verified local copy. `auto_update=True` enables
optional `release.json` discovery and is disabled by default for paper
reproducibility.

## Live and hybrid acquisition

The notebooks also expose `DATA_PROFILE="live"` and `DATA_PROFILE="hybrid"`.
Live mode retrieves the current IBGE/GeoBR inputs and requires explicit HTTPS
URLs for the SSP 2022--2024 extract, SSP 2025 workbook, legacy comparison CSV,
and curated literacy CSV. Supply them as `LIVE_SOURCE_URLS_JSON`, for example:

```json
{
  "ssp_2022_2024": "https://...",
  "ssp_2025": "https://...",
  "legacy_crimes": "https://...",
  "painel": "https://..."
}
```

The live downloader records URLs, retrieval time and hashes in
`.crime-live-data.json`. Hybrid mode starts from a verified snapshot and
refreshes only the live sources that were supplied.
