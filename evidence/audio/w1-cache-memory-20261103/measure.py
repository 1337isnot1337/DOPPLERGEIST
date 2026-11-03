import hashlib,json,resource,sys,time
from pathlib import Path
import numpy as np
from aircraft_geoloc.intake import IntakeRecording
source=Path(sys.argv[1]);sr=4000;count=source.stat().st_size//4
recording=IntakeRecording(source,{'sample_rate_hz':sr,'duration_s':count/sr,'source_sha256':'0'*64,'channels':1,'source_format':'synthetic-zero-cache','time_window':None},{'sample_count':count})
before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;began=time.monotonic();chunks=0;checksum=0.0
for start,values in recording.iter_chunks():
 chunks+=1;checksum+=float(values.sum())
last_end=start+len(values)/sr
print(json.dumps({'scope':'Synthetic raw-cache iterator RSS only; not a recording or field acquisition','cache_bytes':source.stat().st_size,'chunks':chunks,'checksum':checksum,'last_end_s':last_end,'duration_s':count/sr,'baseline_rss_kib':before,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'elapsed_s':time.monotonic()-began}))
