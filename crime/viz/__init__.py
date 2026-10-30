"""Viz: draw results — never compute statistics.

Every function takes a result object (or a GeoDataFrame) produced by
:mod:`crime.esri` / :mod:`crime.stats` plus an optional ``style=PlotStyle()``;
static maps/charts return ``(fig, ax)``, interactive ones a plotly ``Figure``.

    style     ``PlotStyle`` — sizes, colour maps, category palettes
    frame     map furniture: axes, graticule, scale bar, north arrow, overlay
    basemap   ``add_basemap`` + a provider registry (``register_basemap``)
    classify  choropleth class breaks (quantile / equal interval / natural)
    maps      unit-level maps (Gi*, LISA, EHSA, choropleths, trends, interactive)
    charts    non-map charts (time series, STL, correlation, Moran, EHSA emergence)
    cubes     3-D space-time cubes, per-slice Gi* small multiples

Nothing is imported here, so ``import crime.viz`` pulls in no plotting
backend; import the submodule you need (or use the top-level ``crime.*``
names, which load on first use).
"""
