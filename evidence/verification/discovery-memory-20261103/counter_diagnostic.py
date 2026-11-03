"""Reproduce inherited Linux ru_maxrss separately from post-exec VmHWM.
Usage: python counter_diagnostic.py OUTPUT_JSON
"""
import json,resource,subprocess,sys
from pathlib import Path
child='import json,resource; from pathlib import Path; print(json.dumps(dict(ru_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,proc_status=[l for l in Path("/proc/self/status").read_text().splitlines() if l.startswith(("VmRSS:","VmHWM:"))])))'
baseline=json.loads(subprocess.check_output([sys.executable,'-c',child],text=True))
allocation=bytearray(128*1024*1024)
parent_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
following=json.loads(subprocess.check_output([sys.executable,'-c',child],text=True))
result={'allocated_in_parent_bytes':len(allocation),'parent_peak_rss_kib':parent_peak,'child_before_parent_allocation':baseline,'fresh_exec_child_after_parent_allocation':following,'scope':'Controlled RSS-counter diagnostic only. Does not identify ancestry or cause of the historical four-event outlier.'}
Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
