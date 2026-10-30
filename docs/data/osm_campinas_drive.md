# OpenStreetMap drive network, Campinas (`inputs/data/osm/campinas_drive.graphml`)

The street network used for the street-segment support (`load_segments`) and
for network KDE.

## Provenance

| Item | Value |
|---|---|
| Source | OpenStreetMap contributors, downloaded with OSMnx: `ox.graph_from_place("Campinas, São Paulo, Brazil", network_type="drive")`, then `ox.truncate.largest_component`. See `crime/data/osm.py:street_graph` |
| Download date | **2026-08-06 18:34:22**, from the graph attribute `created_date` |
| Tool | `created_with = OSMnx 2.0.5` (the same version is installed in `.venv`; OSMnx itself is MIT-licensed) |
| Licence | OSM data: Open Database Licence (ODbL) 1.0, per `https://www.openstreetmap.org/copyright`. **Not re-checked in this session.** Attribution "© OpenStreetMap contributors" is required |
| Format | GraphML, `crs = epsg:4326`, `simplified = True` |
| Size | 38,175,187 bytes |
| SHA-256 | `fed6538d670d4ea8018d523827b1da5c52d5a6b22680e210752644960201b5af` |
| Git | LFS, `6891c8b` (2026-08-16) |

## What one row is

As stored, this is a directed `MultiDiGraph`:

- **32,326 nodes**: intersections and dead ends.
- **80,258 directed edges.** A two-way street appears as two edges.
- 1 weakly connected component.
- The sum of edge `length` is 8,908.6 km; two-way streets count twice.

`street_graph` converts the graph to an undirected graph on load. The
segments built from it are documented in `crime/data/segments.py`.

## Edge attributes

| Attribute | Meaning (OSM / OSMnx) | Notes |
|---|---|---|
| `osmid` | OSM way id(s) | — |
| `highway` | OSM road class | 99 of 80,258 edges hold a **list** of classes (merged by simplification) |
| `lanes`, `maxspeed`, `name`, `ref`, `bridge` | OSM tags | sparsely filled |
| `oneway`, `reversed` | direction flags | — |
| `length` | metres (OSMnx) | — |
| `geometry` | LineString | — |

The tag definitions are on the OSM wiki (`https://wiki.openstreetmap.org/wiki/Key:highway`;
**not re-checked**).

## Code that reads it

- `crime/data/osm.py:street_graph`. If the file is absent, this rebuilds it
  from the live OSM API, so a rebuild gives a *different* network snapshot.
- `crime/data/osm.py:street_segments` and `crime/data/segments.py:load_segments`
  use the edge geometry, the endpoint ids `u`/`v` and `name`. Segment length
  is recomputed from the geometry in EPSG:31983; the stored `length` attribute
  is not used.
- `paper/presentation_puc/src/make_fapesp_figs.py` uses it for a deck figure.
