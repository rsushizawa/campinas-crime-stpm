"""Known-answer checks for the general-weights Gi* z (Ord & Getis 1995).

esda 2.6.0's ``G_Local.Zs`` uses the binary-weights variance; the general
(Ord & Getis 1995) form is checked here. ``gi_star_z``'s p is two-sided, i.e.
twice esda's one-sided ``p_norm``.
"""
import warnings

import numpy as np
import pandas as pd
from esda.getisord import G_Local
from libpysal.weights import WSP, lat2W

from crime.esri.ehsa import gi_space_time
from crime.esri.local import gi_star_z
from crime.esri.weights import space_time_weights

RNG = np.random.default_rng(0)


def _gi(x, w, transform):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return G_Local(x, w, transform=transform, star=True, permutations=0)


def test_equals_esda_for_binary_weights():
    w = lat2W(5, 5, rook=False)
    x = RNG.poisson(2.0, 25).astype(float)
    gi = _gi(x, w, "B")
    z, p = gi_star_z(x, w, transform="B")
    np.testing.assert_allclose(z, gi.Zs, rtol=1e-12)
    np.testing.assert_allclose(p, 2 * gi.p_norm, rtol=1e-12)


def test_row_standardised_matches_hand_formula():
    # esda fills the self-weight with the row max (1/k) and re-standardises,
    # so every cell of {i} ∪ N(i) weighs 1/(k_i + 1): L_i is a plain mean.
    w = lat2W(5, 5, rook=False)
    x = RNG.poisson(2.0, 25).astype(float)
    N, xbar = len(x), x.mean()
    s = np.sqrt((x ** 2).mean() - xbar ** 2)
    expected = []
    for i in range(N):
        cells = [i, *w.neighbors[i]]
        k1 = len(cells)
        L = x[cells].mean()
        expected.append((L - xbar) / (s * np.sqrt((N / k1 - 1) / (N - 1))))
    z, _ = gi_star_z(x, w)
    np.testing.assert_allclose(z, expected, rtol=1e-12)
    gi = _gi(x, w, "R")
    # esda's z is smaller in magnitude by sqrt(S2) up to the (N-1) factor
    assert np.all(np.abs(gi.Zs) <= np.abs(z) + 1e-12)


def test_space_time_weights_and_z_ratio():
    # q = 1 backward on a 5x5 queen lattice: interior tract (k = 8) at t >= 2
    # gets 1/4 on its own two cells and 1/(4k) on each neighbour cell.
    # Needs row-standardised spatial input, as resolve_weights returns.
    w = lat2W(5, 5, rook=False)
    w.transform = "R"
    n, T = 25, 4
    W_st = WSP(space_time_weights(w, T, time_step=1)).to_W()
    x = RNG.poisson(2.0, n * T).astype(float)
    gi = _gi(x, W_st, "R")
    row = gi.w.sparse.tocsr()[2 * n + 12].toarray().ravel()   # tract 12, t = 3
    nz = np.sort(row[row > 0])
    np.testing.assert_allclose(nz, [1 / 32] * 16 + [1 / 4] * 2)
    z, _ = gi_star_z(x, W_st)
    S2 = 1 / 8 + 1 / (8 * 8)
    N = n * T
    # with W_i = 1, esda's z is (L - xbar) / s, so the ratio is the OG denominator
    np.testing.assert_allclose(gi.Zs[2 * n + 12] / z[2 * n + 12],
                               np.sqrt((N * S2 - 1) / (N - 1)), rtol=1e-12)


def test_gi_space_time_uses_general_z():
    w = lat2W(5, 5, rook=False)
    w.transform = "R"
    wide = pd.DataFrame(RNG.poisson(2.0, (25, 6)).astype(float))
    z, p, hot, cold = gi_space_time(wide, w, time_step=1)
    x = wide.to_numpy().reshape(-1, order="F")
    np.testing.assert_allclose(z, gi_star_z(x, WSP(space_time_weights(w, 6, time_step=1)).to_W())[0]
                               .reshape(6, 25).T, rtol=1e-12)


def test_sign_matches_esda():
    # same centre as esda's Zs, different scale
    w = lat2W(5, 5, rook=False)
    w.transform = "R"
    wide = pd.DataFrame(RNG.poisson(0.7, (25, 6)).astype(float))
    z0 = gi_space_time(wide, w, time_step=1)[0]
    x = wide.to_numpy().reshape(-1, order="F")
    gi = _gi(x, WSP(space_time_weights(w, 6, time_step=1)).to_W(), "R")
    assert np.array_equal(np.sign(z0.reshape(-1, order="F")), np.sign(gi.Zs))
