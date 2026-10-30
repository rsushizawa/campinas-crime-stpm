"""Method-agnostic statistics shared across the analysis.

    eda          descriptive statistics, temporal trends, STL
    correlation  feature / crime-type correlation, VIF collinearity
    bivariate    global / local bivariate Moran's I, ordered-pair matrix
    knox         Knox space-time interaction test, near-repeat band table
    validation   label agreement (Jaccard, Cohen's kappa, MCC)

Submodules are imported on demand.
"""
