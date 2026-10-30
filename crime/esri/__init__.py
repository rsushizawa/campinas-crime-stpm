"""ESRI-style classical space-time pattern mining, one module per tool.

Run order of the method (see the ``crime`` package docstring):

    weights    neighbourhoods: queen / rook / knn / network, space-time blocks
    inference  Benjamini–Hochberg FDR
    moran      global Moran's I                       — is crime clustered?
    local      Getis-Ord Gi*, local Moran (LISA)      — where?
    cube       space-time cube                        — bin events in time
    trend      Mann–Kendall, Theil–Sen                — is a series trending?
    ehsa       Emerging Hot Spot Analysis             — how do hot spots evolve?
    stlisa     space-time LISA
    tsclust    time series clustering
    nkde       network KDE / temporal NKDE, street-segment structure
    maup       support (MAUP) sensitivity

Submodules are imported on demand; ``import crime.esri`` is cheap.
"""
