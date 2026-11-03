import argparse
import json
import math
import shlex
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


def operator_config(path, online):
    config = json.loads(Path(path).read_text()) if path else {}
    if not isinstance(config, dict):
        raise ValueError("Operator configuration must be a JSON object")
    if online:
        config.setdefault("cache_root", str(Path.home() / ".cache" / "dopplergeist"))
        config["offline"] = False
    return config


def positive_runtime(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Runtime must be positive and finite")
    return number


def job_identifier(value):
    try:
        if uuid.UUID(value).hex != value:
            raise ValueError
    except ValueError as error:
        raise argparse.ArgumentTypeError("job_id must be the 32-character job identifier") from error
    return value


def main():
    parser=argparse.ArgumentParser(description="Aircraft acoustic geolocation research pipeline")
    try:
        installed_version=version("dopplergeist")
    except PackageNotFoundError:
        installed_version="development"
    parser.add_argument("--version",action="version",version=f"%(prog)s {installed_version}")
    sub=parser.add_subparsers(dest="command",required=True)
    run=sub.add_parser("run",help="Measure events, filter geometry, rank and refine locations")
    run.add_argument("config")
    run.add_argument("--output",required=True)
    measure=sub.add_parser("measure",help="Measure one Doppler event without locating it")
    measure.add_argument("audio")
    measure.add_argument("--start",type=float,required=True)
    measure.add_argument("--end",type=float,required=True)
    measure.add_argument("--band",type=float,nargs=2,required=True)
    measure.add_argument("--output",required=True)
    analyze=sub.add_parser("analyze",help="Automatically locate aircraft audio, or explain insufficient evidence")
    analyze.add_argument("audio")
    analyze.add_argument("--start-utc",help="Earliest UTC recording start, including explicit timezone")
    analyze.add_argument("--end-utc",help="Latest UTC recording start; defaults to earliest")
    analyze.add_argument("--time-source",help="How the recording start window was established")
    analyze.add_argument("--jobs",default="jobs",help="Persistent job directory")
    analyze.add_argument("--config",help="Operator provider/cache/search configuration JSON")
    analyze.add_argument("--online",action="store_true",help="Download public data to the local cache; this can require tens of gigabytes and hours")
    analyze.add_argument("--max-runtime",type=positive_runtime,default=3600,help="Wall-time limit in seconds")
    serve=sub.add_parser("serve",help="Launch the local MP3 upload interface and job API")
    serve.add_argument("--jobs",default="jobs")
    serve.add_argument("--config",help="Operator provider/cache/search configuration JSON")
    serve.add_argument("--online",action="store_true",help="Download public data to the local cache; this can require tens of gigabytes and hours")
    serve.add_argument("--port",type=int,default=8765)
    serve.add_argument("--max-runtime",type=positive_runtime,default=3600)
    serve.add_argument("--max-upload-mb",type=int,default=100)
    job=sub.add_parser("job",help="Read a persisted job result without rerunning it")
    job.add_argument("job_id",type=job_identifier)
    job.add_argument("--jobs",default="jobs")
    job.add_argument("--watch",action="store_true",help="Watch local checkpoints until the job stops")
    job.add_argument("--interval",type=positive_runtime,default=10,help="Watch interval in seconds")
    cancel=sub.add_parser("cancel",help="Cancel a job managed by the local upload service")
    cancel.add_argument("job_id",type=job_identifier)
    cancel.add_argument("--server-url",default="http://127.0.0.1:8765",
                        help="Base URL of the service managing this job")
    resume=sub.add_parser("resume",help="Resume a stopped job after completed audio discovery")
    resume.add_argument("job_id",type=job_identifier)
    resume.add_argument("--jobs",default="jobs")
    resume.add_argument("--max-runtime",type=positive_runtime,default=3600)
    args=parser.parse_args()
    if args.command in {"analyze", "serve"}:
        try:
            config=operator_config(args.config,args.online)
        except (OSError, ValueError) as exc:
            parser.error(f"Invalid operator configuration: {exc}")
    if args.command=="run":
        from .pipeline import run
        run(args.config,args.output)
    elif args.command=="measure":
        from .audio import measure
        result=measure(args.audio,{"start_s":args.start,"end_s":args.end,"band_hz":args.band},args.output)
        print(json.dumps(result[-1],indent=2))
    elif args.command=="serve":
        from .service import serve
        serve(args.jobs,config,port=args.port,max_runtime_s=args.max_runtime,max_upload_bytes=args.max_upload_mb*1024*1024)
    elif args.command=="analyze":
        from .jobs import JobManager
        from .contracts import validate_request
        audio=Path(args.audio)
        if not audio.is_file():
            parser.error(f"Audio file is unavailable or not a regular file: {audio}")
        if args.end_utc and not args.start_utc:
            parser.error("--end-utc requires --start-utc")
        request={"schema_version":1,"search":{"coverage":"conus"}}
        if args.start_utc:
            request["time_window"]={"start_utc":args.start_utc,"end_utc":args.end_utc or args.start_utc,"source":"user"}
            if args.time_source:
                request["time_window"]["source_detail"]=args.time_source
        try:
            validate_request(dict(request, audio_path=str(audio)))
        except ValueError as exc:
            parser.error(str(exc))
        manager=JobManager(args.jobs,config,max_runtime_s=args.max_runtime)
        try:
            with audio.open("rb") as source:
                queued=manager.submit(request,source,audio.stat().st_size,suffix=audio.suffix)
            print(f"Job {queued['job_id']} started. Monitor: dopplergeist job {queued['job_id']} "
                  f"--jobs {shlex.quote(str(args.jobs))} --watch",file=sys.stderr,flush=True)
            print(json.dumps(manager.wait(queued["job_id"]),indent=2))
        finally:
            manager.close()
    elif args.command=="job":
        from .jobs import read_json
        directory=Path(args.jobs)/args.job_id
        previous_count=previous_time=None
        try:
            while True:
                try:
                    value = read_json(directory/"result.json")
                except (OSError, ValueError) as exc:
                    parser.error(f"Could not read job {args.job_id}: {exc}")
                if not args.watch:
                    break
                tiles=[path for path in (directory/"search").glob("tile-*.json") if not path.name.endswith(".error.json")]
                count=len(tiles)
                wall_now=time.time()
                progress=value.get("progress")
                progress_text=(f", {progress:.1%}" if isinstance(progress,(int,float)) and math.isfinite(progress) else "")
                result_age=max(0.0,wall_now-(directory/"result.json").stat().st_mtime)
                age_text=lambda seconds: f"{seconds:.0f}s" if seconds<60 else f"{seconds/60:.1f}m"
                now=time.monotonic()
                rate=""
                if previous_count is not None and count >= previous_count and now > previous_time:
                    rate=f", {(count-previous_count)*60/(now-previous_time):.1f} pieces/min since last check"
                latest=max(tiles,key=lambda path:path.stat().st_mtime,default=None)
                tile_age=(f", newest tile {age_text(max(0.0,wall_now-latest.stat().st_mtime))} ago"
                          if latest else "")
                print(f"{value['status']} ({value.get('stage', 'no stage')}{progress_text}): "
                      f"{count} local checkpoint pieces{rate}{tile_age}, "
                      f"status updated {age_text(result_age)} ago",file=sys.stderr,flush=True)
                if value["status"] in {"needs_input", "succeeded", "inconclusive", "failed", "cancelled"}:
                    break
                previous_count,previous_time=count,now
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("Stopped watching; the job continues.",file=sys.stderr)
            raise SystemExit(130)
        print(json.dumps(value,indent=2))
    elif args.command=="cancel":
        url=args.server_url.rstrip("/")+f"/api/jobs/{args.job_id}/cancel"
        request=Request(url,data=b"",method="POST")
        try:
            with urlopen(request,timeout=10) as response:
                body=response.read()
        except HTTPError as exc:
            try:
                detail=json.loads(exc.read()).get("error",str(exc))
            except (AttributeError,ValueError):
                detail=str(exc)
            parser.error(f"Could not cancel job {args.job_id}: HTTP {exc.code}: {detail}")
        except (URLError,ValueError) as exc:
            parser.error(f"Could not reach job service at {args.server_url}: {exc}")
        try:
            value=json.loads(body)
        except ValueError as exc:
            parser.error(f"Job service returned invalid JSON when cancelling {args.job_id}: {exc}")
        print(json.dumps(value,indent=2))
    elif args.command=="resume":
        from .jobs import JobManager
        try:
            manager=JobManager(args.jobs,max_runtime_s=args.max_runtime)
        except (OSError, ValueError) as exc:
            parser.error(f"Could not open job store: {exc}")
        try:
            manager.resume(args.job_id)
            print(json.dumps(manager.wait(args.job_id),indent=2))
        except (KeyError, OSError, OverflowError, ValueError) as exc:
            parser.error(f"Could not resume job {args.job_id}: {exc}")
        finally:
            manager.close()


if __name__=="__main__":
    main()
