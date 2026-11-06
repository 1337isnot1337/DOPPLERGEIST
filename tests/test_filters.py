import numpy as np
import pandas as pd

from dopplergeist.search import pair_candidates
from dopplergeist.tracks import load_tracks


def event(cpa):
    return {"cpa_receive_s":cpa,"speed_range_mps":[60,100],"slant_range_m":[1000,3000]}


def test_silence_and_locked_offset_filter():
    rows=[]
    for point in [0,1,2]:
        for flight,when in [("a",100),("b",1020 if point!=2 else 1040)]:
            rows.append({"point_id":point,"flight_id":flight,"receive_time":when,
                         "emission_time":when-5,"distance_m":2000,"speed_mps":80})
    rows.append({"point_id":1,"flight_id":"extra","receive_time":600,
                 "emission_time":595,"distance_m":1800,"speed_mps":80})
    candidates,counts=pair_candidates(pd.DataFrame(rows),[event(50),event(970)],silence={"edge_margin_s":60})
    assert [c["point_id"] for c in candidates]==[0]
    assert counts["pairs_before_silence"]==2
    assert counts["silence_rejected"]==1


def test_unknown_types_are_excluded_and_gaps_are_not_interpolated(tmp_path):
    rows=[]
    for flight,code in [("prop","C172"),("unknown","ZZZZ")]:
        for t in [0,1,2,100,101,102]:
            rows.append({"flight_id":flight,"time_s":t,"lat":40+t/1000,"lon":-100,
                         "alt_m":1000,"typecode":code})
    p=tmp_path/"tracks.csv";pd.DataFrame(rows).to_csv(p,index=False)
    db=tmp_path/"types.csv"
    pd.DataFrame({"designator":["C172"],"engine_type":["Piston"]}).to_csv(db,index=False)
    tracks,report=load_tracks(p,type_database=db)
    assert len(tracks)==2
    assert report["unknown_types_excluded"]==["unknown"]
    assert {t.id.split(":")[0] for t in tracks}=={"prop"}
    assert all(np.isnan(t.position(50)).all() for t in tracks)
