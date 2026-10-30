"""Known-answer checks independent of the database and previous project outputs."""
import itertools

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from libpysal.weights import lat2W
from scipy.stats import norm
from shapely.geometry import box

from crime.core.dataset import Dataset
from crime.esri.cube import space_time_cube
from crime.esri.ehsa import classify_pattern, gi_time_series
from crime.esri.trend import mann_kendall
from crime.esri.weights import space_time_weights
from crime.stats.validation import label_agreement


def test_mk_tie_variance_against_exhaustive_null():
    values = [0, 0, 1, 1, 2]
    scores = []
    for order in set(itertools.permutations(values)):
        scores.append(sum(np.sign(order[j]-order[i]) for i in range(5) for j in range(i+1, 5)))
    s = sum(np.sign(values[j]-values[i]) for i in range(5) for j in range(i+1, 5))
    expected_z = (s-1)/np.sqrt(np.var(scores))
    z, p = mann_kendall(values)
    assert z == pytest.approx(expected_z)
    assert p == pytest.approx(2*norm.sf(expected_z))
    assert mann_kendall(values[::-1])[0] == pytest.approx(-z)
    assert mann_kendall([1]*20) == (0, 1)
    assert np.isnan(mann_kendall([1, np.nan, 2])[0])


def test_autocorrelation_variance_adjustment():
    # Independent algebra for the configured significant lag on detrended ranks.
    from scipy.stats import rankdata
    x = np.arange(48)*.05 + np.sin(np.arange(48)/4)
    slope = np.median([(x[j]-x[i])/(j-i) for i in range(48) for j in range(i+1,48)])
    r = rankdata(x-slope*np.arange(48)); r -= r.mean()
    rho = r[:-1]@r[1:]/(r@r)
    assert rho > norm.ppf(.975)/np.sqrt(48)
    factor = 1 + 2*47*46*45*rho/(48*47*46)
    assert mann_kendall(x, method="hamed_rao", max_lag=1)[0] == pytest.approx(mann_kendall(x)[0]/np.sqrt(factor))


def test_cube_preserves_empty_boundary_months_and_units():
    gdf = gpd.GeoDataFrame({'unit_id':['a','b'], 'crime_count':[1,0]}, geometry=[box(0,0,1,1),box(1,0,2,1)],crs=31983)
    events = pd.DataFrame({'unit_id':['a'], 'data_ocorrencia':pd.to_datetime(['2022-06-01'])})
    ds=Dataset(gdf, 'sector', years=(2022,2022), events=events)
    cube=space_time_cube(ds)
    assert cube.wide.shape == (2,12)
    assert cube.wide.values.sum() == 1
    assert cube.wide.iloc[:,[0,-1]].values.sum() == 0
    ds=ds.replace(events=events.iloc[:0])
    assert space_time_cube(ds).wide.values.sum() == 0
    assert space_time_cube(ds, freq='QE').wide.shape == (2,4)


def test_temporal_weights_no_future_and_own_history():
    w=lat2W(2,2); w.transform='r'
    past=space_time_weights(w, 3, temporal_direction='backward').toarray()
    sym=space_time_weights(w, 3, temporal_direction='symmetric').toarray()
    assert np.all(past[:4,4:] == 0)
    assert past[4,0] > 0  # same place at previous time
    assert past[4,8] == 0
    assert sym[4,8] > 0
    assert np.allclose(past.sum(axis=1),1)


@pytest.mark.parametrize('hot,cold,z,p,expected', [
 ([0,0,0,1],[0]*4,0,1,'new hotspot'),
 ([0,0,1,1],[0]*4,0,1,'consecutive hotspot'),
 ([1]*10,[0]*10,3,.001,'intensifying hotspot'),
 ([1]*10,[0]*10,-3,.001,'diminishing hotspot'),
 ([1]*10,[0]*10,0,1,'persistent hotspot'),
 ([1]*9+[0],[0]*10,0,1,'historical hotspot'),
 ([1,0,0,1],[0]*4,0,1,'sporadic hotspot'),
 ([1,0,0,1],[0,1,0,0],0,1,'oscillating hotspot'),
 ([0]*4,[0,0,0,1],0,1,'new coldspot'),
 ([0]*4,[0]*4,0,1,'no pattern'),
])
def test_ehsa_taxonomy(hot,cold,z,p,expected):
    assert classify_pattern(np.array(hot,bool),np.array(cold,bool),z,p,.05,.9)==expected


def test_constant_gi_is_not_significant():
    z,p,h,c=gi_time_series(pd.DataFrame(np.zeros((4,3))),lat2W(2,2))
    assert not h.any() and not c.any() and np.all(p==1)


def test_majority_labels_cannot_hide_hotspot_disagreement():
    a=['no pattern']*98+['new hotspot','no pattern']; b=['no pattern']*99+['new hotspot']
    result=label_agreement(a,b)
    assert result['label_agreement']==.98 and result['hotspot_jaccard']==0


def test_space_time_lisa_all_non_significant_does_not_crash():
    """Regression (#13): when no slice has a significant unit, modal_label is all 'ns'."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    import crime
    from crime.core.dataset import Dataset

    g = gpd.GeoDataFrame({"unit_id": [f"u{i}" for i in range(9)]},
                         geometry=[box(i % 3, i // 3, i % 3 + 1, i // 3 + 1) for i in range(9)], crs="EPSG:31983")
    m = pd.DataFrame(1.0, index=g["unit_id"], columns=pd.date_range("2022-12-31", periods=3, freq="YE"))
    r = crime.space_time_lisa(Dataset(g, "sector", years=(2022, 2024)), matrix=m, permutations=99, fdr=True)
    assert (r.gdf["modal_label"] == "ns").all() and len(r.gdf) == 9
