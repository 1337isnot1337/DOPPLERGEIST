import numpy as np
from numpy.testing import assert_allclose
from pyproj import Transformer

from aircraft_geoloc.geometry import Track,ecef,straight_doppler


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
