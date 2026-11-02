"""Download a preferred open ADS-B daily archive with resumable HTTP ranges.

Archives remain external data; the ODbL provenance and release metadata are kept.
"""
import argparse
import hashlib
import json
from pathlib import Path

import requests

parser=argparse.ArgumentParser()
parser.add_argument("date",help="YYYY-MM-DD")
parser.add_argument("--provider",default="staging-0")
args=parser.parse_args()
year=args.date[:4]
tag=f"v{args.date.replace('-','.')}-planes-readsb-{args.provider}"
root=Path(__file__).resolve().parents[1]/"data/adsb"/args.date
root.mkdir(parents=True,exist_ok=True)
s=requests.Session()
response=s.get(f"https://api.github.com/repos/adsblol/globe_history_{year}/releases/tags/{tag}",timeout=60)
response.raise_for_status()
release=response.json()
(root/"release.json").write_text(json.dumps(release,indent=2)+"\n")
for asset in sorted(release["assets"],key=lambda a:a["name"]):
    path=root/asset["name"]
    if path.exists() and path.stat().st_size==asset["size"]:
        print("Already downloaded",path.name,flush=True)
        continue
    temporary=path.with_suffix(path.suffix+".part")
    offset=temporary.stat().st_size if temporary.exists() else 0
    headers={"Range":f"bytes={offset}-"} if offset else {}
    r=s.get(asset["browser_download_url"],headers=headers,stream=True,timeout=(30,120))
    r.raise_for_status()
    if offset and r.status_code!=206:
        raise ValueError("Server did not honor resumable range; partial file preserved")
    print("Downloading",path.name,"bytes",asset["size"],"from",offset,flush=True)
    with temporary.open("ab" if offset else "wb") as f:
        for chunk in r.iter_content(4*1024*1024):
            f.write(chunk)
    if temporary.stat().st_size!=asset["size"]:
        raise ValueError("Truncated download; rerun to resume")
    if asset.get("digest"):
        algorithm,expected=asset["digest"].split(":")
        with temporary.open("rb") as f:
            actual=hashlib.file_digest(f,algorithm).hexdigest()
        if actual!=expected:
            raise ValueError("Release asset digest mismatch")
    temporary.replace(path)
    print("Complete",path.name,flush=True)
