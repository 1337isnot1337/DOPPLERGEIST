"""Stream a split daily tar archive into a CONUS prop/unknown parquet table."""
import argparse
import gzip
import io
import json
import tarfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from dopplergeist.tracks import adsblol_frame,unix_time
from dopplergeist.flight_selection import intersects_index_query

parser=argparse.ArgumentParser()
parser.add_argument("date")
parser.add_argument("--bounds",type=float,nargs=4,default=[-125,24,-66,50],metavar=("WEST","SOUTH","EAST","NORTH"))
parser.add_argument("--output",default="conus-prop-unknown.parquet")
parser.add_argument("--keep-jets",action="store_true",help="Include jet types for the single-event ablation")
parser.add_argument("--time-range",nargs=2,metavar=("START_UTC","END_UTC"))
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
directory=root/"data/adsb"/args.date
west,south,east,north=args.bounds
time_range=[unix_time(t) for t in args.time_range] if args.time_range else None
output_path=directory/args.output
report_path=directory/(Path(args.output).stem+"-ingestion-report.json")
if output_path.exists() or report_path.exists():
    raise FileExistsError("Ingestion output exists; choose a new --output name to preserve historical evidence")
types_path=root/"data/source/icao_aircraft_types.json"
if not types_path.exists():
    r=requests.get("https://raw.githubusercontent.com/wiedehopf/tar1090-db/master/db/icao_aircraft_types.js",timeout=60)
    r.raise_for_status()
    raw=r.content
    if raw[:2]==b"\x1f\x8b":raw=gzip.decompress(raw)
    text=raw.decode()
    # The public database is a JS assignment containing one JSON dictionary.
    start,end=text.find("{"),text.rfind("}")+1
    json.loads(text[start:end])
    types_path.write_text(text[start:end])
types=json.loads(types_path.read_text())
print("Type examples",list(types.items())[:3],flush=True)
engines={}
for code,value in types.items():
    classification=value.get("desc","") if isinstance(value,dict) else (value[2] if len(value)>2 else "")
    engines[code]="Jet" if classification.endswith("J") else "Other/unknown"
pd.DataFrame({"designator":list(engines),"engine_type":list(engines.values())}).to_csv(directory/"type-database.csv",index=False)


class SplitReader(io.RawIOBase):
    def __init__(self,paths):
        self.paths=iter(paths)
        self.current=None
    def readable(self):return True
    def readinto(self,b):
        while True:
            if self.current is None:
                path=next(self.paths,None)
                if path is None:return 0
                self.current=open(path,"rb")
            n=self.current.readinto(b)
            if n:return n
            self.current.close();self.current=None


paths=sorted(directory.glob("*.tar.a?"))
if len(paths)<2:raise ValueError("Daily archive download is incomplete")
stats={"trace_files":0,"known_jets_removed":0,"no_conus_points":0,"retained_aircraft":0,"rows":0,"barometric_rows":0}
stats["normalization_scope"]="full_native_trace_before_segment_selection"
stats["selection_max_gap_s"]=30.0
selection={"bounds":[west,south,east,north],"time_range_s":time_range,
           "all_aircraft":args.keep_jets,"max_gap_s":30.0}
writer=None
with io.BufferedReader(SplitReader(paths),buffer_size=1024*1024) as stream:
    with tarfile.open(fileobj=stream,mode="r|") as archive:
        for member in archive:
            if not member.isfile() or "trace_full_" not in member.name:continue
            raw=archive.extractfile(member).read()
            d=json.loads(gzip.decompress(raw) if raw[:2]==b"\x1f\x8b" else raw)
            stats["trace_files"]+=1
            if not args.keep_jets and engines.get(d.get("t",""))=="Jet":
                stats["known_jets_removed"]+=1
                continue
            # A segment can cross a query without a sample inside it. Temporal
            # extents can reject only traces entirely before or after the query.
            if time_range is not None:
                offsets=[p[0] for p in d.get("trace",[]) if isinstance(p[0],(int,float)) and np.isfinite(p[0])]
                if not offsets or d["timestamp"]+min(offsets)>time_range[1] or d["timestamp"]+max(offsets)<time_range[0]:
                    stats["no_conus_points"]+=1
                    continue
            frame=adsblol_frame(d)
            if frame.empty:continue
            if not intersects_index_query(frame,(west,south,east,north),time_range):
                stats["no_conus_points"]+=1
                continue
            # Keep the native trace intact: FlightIndex performs its own
            # gap splitting and uses neighboring samples to infer velocity.
            frame["heading_deg"]=frame.heading_deg.astype(float)
            # Bound schema explicitly so an all-null metadata field in one
            # aircraft cannot change a later parquet batch's physical type.
            schema=pa.schema([(c,pa.string() if c in ["flight_id","typecode","altitude_basis"] else pa.float64()) for c in frame.columns],
                             metadata={b"dopplergeist.selection.v1":json.dumps(selection,allow_nan=False).encode()})
            batch=pa.Table.from_pandas(frame,schema=schema,preserve_index=False)
            if writer is None:writer=pq.ParquetWriter(output_path,schema,compression="zstd")
            writer.write_table(batch)
            stats["retained_aircraft"]+=1;stats["rows"]+=len(frame)
            stats["barometric_rows"]+=int((frame.altitude_basis=="barometric").sum())
            if stats["retained_aircraft"]%500==0:print(stats,flush=True)
if writer:writer.close()
report_path.write_text(json.dumps(stats,indent=2)+"\n")
print(stats,flush=True)
