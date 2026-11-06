"""Make blind end-to-end cases with an independent emission-domain renderer.

The renderer never calls the search's acoustic/Doppler code. It transports a
source oscillator into receiver time, making a wrong delay law fail validation.
Truth is written separately and is never read by the search pipeline.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
import soundfile as sf


root=Path(__file__).resolve().parents[1]
out=root/"data/synthetic"
out.mkdir(parents=True,exist_ok=True)
rng=np.random.default_rng(78139)
epoch=1790000000.0
sr=4000
duration=1180
receiver_time=np.arange(duration*sr)/sr
audio=rng.normal(0,0.8,len(receiver_time))
audio+=0.08*np.sin(2*np.pi*60*receiver_time)+0.05*np.sin(2*np.pi*180*receiver_time)
earth=Transformer.from_crs("EPSG:4979","EPSG:4978",always_xy=True)


def positions(t,event,variant=0):
    if event==0:
        return 88*t+0.045*t*t,1000+0.10*t*t+variant*0.0015*t**3,1500+0.4*t
    return -700+0.08*t*t+variant*0.0008*t**3,75*t-0.025*t*t,1100+0.8*t


rows=[]
truth={"lat":40.03173,"lon":-100.01829,"elev_m":120.0,"recording_start_time_s":epoch,
       "flight_ids":["true-A","true-B"],"f0_hz":[135.0,115.0]}
for region,(lat0,lon0) in enumerate([(40.0,-100.0),(35.0,-90.0),(43.0,-112.0)]):
    local=f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m"
    inverse=Transformer.from_crs(local,"EPSG:4326",always_xy=True)
    forward=Transformer.from_crs("EPSG:4326",local,always_xy=True)
    # In the true region the receiver is off the path coordinate origin and off
    # every 200/100/25 m global grid, so including truth as a grid point is impossible.
    ox,oy=forward.transform(truth["lon"],truth["lat"]) if region==0 else (0,0)
    observer=np.array(earth.transform(truth["lon"],truth["lat"],truth["elev_m"]))
    for event,center in enumerate([150.0,1070.0]):
        identifier=("true" if region==0 else f"false{region}")+"-"+"AB"[event]
        t=np.arange(-115,116,1.0)
        x,y,h=positions(t,event,region)
        lon,lat=inverse.transform(x+ox,y+oy)
        for j in range(len(t)):
            rows.append({"flight_id":identifier,"time_s":epoch+center+t[j],"lat":lat[j],
                         "lon":lon[j],"alt_m":h[j]+120,"typecode":"C172"})
        if region==0:
            te=np.arange(-115,115,1/sr)
            x,y,h=positions(te,event)
            lon,lat=inverse.transform(x+ox,y+oy)
            xyz=np.column_stack(earth.transform(lon,lat,h+120))
            distance=np.linalg.norm(xyz-observer,axis=1)
            arrival=center+te+distance/343.0
            amplitude=0.16*np.minimum(1,1800/distance)
            # Weak second harmonic and a smoothly varying acoustic envelope.
            f0=truth["f0_hz"][event]
            emitted=amplitude*(np.sin(2*np.pi*f0*te)+0.35*np.sin(2*np.pi*2*f0*te+0.4))
            audio+=np.interp(receiver_time,arrival,emitted,left=0,right=0)
            truth.setdefault("events",[]).append({"flight_id":identifier,"center_emission_s":center})

pd.DataFrame(rows).to_csv(out/"tracks.csv",index=False)
pd.DataFrame({"designator":["C172"],"engine_type":["Piston"]}).to_csv(out/"types.csv",index=False)
sf.write(out/"recording.wav",audio/5,sr,subtype="FLOAT")
config={"audio":"recording.wav","tracks":["tracks.csv"],"type_database":"types.csv",
        "terrain":{"constant_m":120},"grid":{"spacing_m":200,"scoring_spacing_m":100,"refine_spacing_m":25,"refine_pairs":3},
        "events":[{"start_s":65,"end_s":250,"band_hz":[95,185],"speed_range_mps":[60,120],"slant_range_m":[1300,2500],"f0_range_hz":[132,138]},
                  {"start_s":985,"end_s":1170,"band_hz":[80,155],"speed_range_mps":[50,105],"slant_range_m":[1000,2200],"f0_range_hz":[112,118]}],
        "filters":{"offset_tolerance_s":6,"silence":{"edge_margin_s":100}},
        "scoring":{"mode":"brightness","time_sweep_s":3,"time_step_s":0.5}}
(out/"two-events.json").write_text(json.dumps(config,indent=2)+"\n")
single=json.loads(json.dumps(config))
single["recording_start_utc"]=epoch
single["events"]=[dict(config["events"][0],start_s=123,end_s=183)]
single["scoring"]["mode"]="ridge"
single["scoring"]["time_sweep_s"]=0.5
single["filters"]={"known_time_tolerance_s":5}
(out/"known-time-minute.json").write_text(json.dumps(single,indent=2)+"\n")
(out/"truth.json").write_text(json.dumps(truth,indent=2)+"\n")
print(out)
