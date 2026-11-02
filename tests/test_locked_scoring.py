from types import SimpleNamespace

import numpy as np

from aircraft_geoloc.audio import Spectrum
from aircraft_geoloc.search import score_candidate


class Flyover:
    def __init__(self,center):self.center=center
    def acoustic(self,t,observer,c):
        factor=1.1-0.25*np.tanh((t-self.center)/8)
        return factor,np.asarray(t),np.ones_like(t)


def test_second_event_cannot_get_its_own_time_adjustment():
    point=SimpleNamespace(point_id=0,lat=40,lon=-100,elev_m=0,x=0,y=0)
    events=[];measurements=[]
    for center in [30,950]:
        t=np.arange(center-25,center+25,0.5)
        spec=Spectrum(t,np.arange(80,161),np.zeros((81,len(t))),np.zeros((81,len(t))))
        ridge=120*Flyover(center).acoustic(t,None,343)[0]
        measurements.append((spec,ridge,np.ones(len(t)),{}))
        events.append({"cpa_receive_s":center,"f0_range_hz":[119.9,120.1]})
    candidate={"passes":[{"flight_id":"a","receive_time":30},{"flight_id":"b","receive_time":950}]}
    kwargs=dict(mode="ridge",time_origin=0,time_sweep_s=10,time_step_s=0.5)
    correct=score_candidate(candidate,point,{"a":Flyover(30),"b":Flyover(950)},events,measurements,**kwargs)
    wrong=score_candidate(candidate,point,{"a":Flyover(30),"b":Flyover(958)},events,measurements,**kwargs)
    assert abs(correct["score"])<1e-8
    assert wrong["score"] < -5
