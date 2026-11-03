import numpy as np
from numpy.testing import assert_allclose
from pyproj import Transformer

from dopplergeist.geometry import Track,ecef,straight_doppler


def straight_track(epoch=0.0):
    observer=ecef(40,-100,100)
    # Constant Cartesian source velocity is independent of the geodetic import.
    t=np.arange(-100,101,1.0)
    xyz=observer+np.column_stack((80*t,np.full(len(t),1300),np.full(len(t),700)))
    inverse=Transformer.from_crs("EPSG:4978","EPSG:4979",always_xy=True)
    lon,lat,h=inverse.transform(*xyz.T)
    track=Track("straight",t+epoch,lat,lon,h,velocity=np.tile([80,0,0],(len(t),1)))
    return track,observer,np.hypot(1300,700)


def test_retarded_time_against_closed_form_and_large_epoch():
    for epoch in [0.0,1_790_000_000.0]:
        track,observer,slant=straight_track(epoch)
        receive=np.linspace(-65,65,501)+epoch
        factor,emission,distance=track.acoustic(receive,observer)
        assert_allclose(emission+distance/343,receive,atol=3e-7,rtol=0)
        expected=straight_doppler(receive-epoch,120,80,slant,slant/343)
        assert_allclose(120*factor,expected,atol=3e-6,rtol=0)


def test_cpa_and_no_extrapolation():
    track,observer,slant=straight_track(1_790_000_000)
    cpa=track.closest_approaches(observer)[0]
    assert abs(cpa["emission_time"]-1_790_000_000)<0.001
    assert abs(cpa["distance_m"]-slant)<0.001
    factor,_,_=track.acoustic(np.array([1_789_999_800.0,1_790_000_200.0]),observer)
    assert np.all(np.isnan(factor))


def test_vectorized_cpa_matches_independent_continuous_minimum():
    import pandas as pd
    from dopplergeist.search import cpa_table
    track,observer,slant=straight_track(1_790_000_000)
    points=pd.DataFrame({"point_id":[0,1],"lat":[40,30],"lon":[-100,-80],"elev_m":[100,0]})
    table=cpa_table([track],points,5000)
    assert list(table.point_id)==[0]
    assert abs(table.distance_m.iloc[0]-slant)<0.01
    assert abs(table.emission_time.iloc[0]-1_790_000_000)<0.001


def test_repeated_flyovers_are_not_collapsed_to_one_global_cpa():
    import pandas as pd
    from dopplergeist.search import cpa_table
    observer=ecef(40,-100,100)
    t=np.arange(-20,100.1,0.5)
    xyz=observer+np.column_stack((4000*np.sin(2*np.pi*t/80),np.full(len(t),1300),np.full(len(t),700)))
    inverse=Transformer.from_crs("EPSG:4978","EPSG:4979",always_xy=True)
    lon,lat,h=inverse.transform(*xyz.T)
    track=Track("repeated",t,lat,lon,h)
    points=pd.DataFrame({"point_id":[0],"lat":[40],"lon":[-100],"elev_m":[100]})
    table=cpa_table([track],points,1800)
    assert len(table)==3
    assert_allclose(sorted(table.emission_time),[0,40,80],atol=0.01)


def test_sparse_cpa_graph_agrees_with_dense_reference_on_curved_track():
    import pandas as pd
    from dopplergeist.search import cpa_table,cpa_table_dense
    observer=ecef(40,-100,100)
    t=np.arange(-80,81,0.5)
    xyz=observer+np.column_stack((90*t+0.03*t*t,1200+0.1*t*t,900+0.5*t))
    inverse=Transformer.from_crs("EPSG:4978","EPSG:4979",always_xy=True)
    lon,lat,h=inverse.transform(*xyz.T)
    track=Track("curve",t,lat,lon,h)
    points=pd.DataFrame({"point_id":np.arange(15),"lat":np.linspace(39.99,40.01,15),
                         "lon":np.linspace(-100.01,-99.99,15),"elev_m":100})
    fast=cpa_table([track],points,5000).sort_values("point_id")
    slow=cpa_table_dense([track],points,5000).sort_values("point_id")
    assert list(fast.point_id)==list(slow.point_id)
    assert_allclose(fast.emission_time,slow.emission_time,atol=1e-9)
    assert_allclose(fast.distance_m,slow.distance_m,atol=1e-8)
