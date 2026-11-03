import argparse
import json
from pathlib import Path


def operator_config(path, online):
    config = json.loads(Path(path).read_text()) if path else {}
    if online:
        if not isinstance(config, dict):
            raise ValueError("Operator configuration must be a JSON object")
        config.setdefault("cache_root", str(Path.home() / ".cache" / "dopplergeist"))
        config["offline"] = False
    return config


def main():
    parser=argparse.ArgumentParser(description="Aircraft acoustic geolocation research pipeline")
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
    analyze.add_argument("--max-runtime",type=float,default=3600,help="Wall-time limit in seconds")
    serve=sub.add_parser("serve",help="Launch the local MP3 upload interface and job API")
    serve.add_argument("--jobs",default="jobs")
    serve.add_argument("--config",help="Operator provider/cache/search configuration JSON")
    serve.add_argument("--online",action="store_true",help="Download public data to the local cache; this can require tens of gigabytes and hours")
    serve.add_argument("--port",type=int,default=8765)
    serve.add_argument("--max-runtime",type=float,default=3600)
    serve.add_argument("--max-upload-mb",type=int,default=100)
    job=sub.add_parser("job",help="Read a persisted job result without rerunning it")
    job.add_argument("job_id")
    job.add_argument("--jobs",default="jobs")
    resume=sub.add_parser("resume",help="Continue a wall-time-limited job using its search checkpoints")
    resume.add_argument("job_id")
    resume.add_argument("--jobs",default="jobs")
    resume.add_argument("--max-runtime",type=float,default=3600,help="New wall-time limit in seconds")
    args=parser.parse_args()
    if args.command=="run":
        from .pipeline import run
        run(args.config,args.output)
    elif args.command=="measure":
        from .audio import measure
        result=measure(args.audio,{"start_s":args.start,"end_s":args.end,"band_hz":args.band},args.output)
        print(json.dumps(result[-1],indent=2))
    elif args.command=="serve":
        from .service import serve
        config=operator_config(args.config,args.online)
        serve(args.jobs,config,port=args.port,max_runtime_s=args.max_runtime,max_upload_bytes=args.max_upload_mb*1024*1024)
    elif args.command=="analyze":
        from .jobs import JobManager
        if args.end_utc and not args.start_utc:
            parser.error("--end-utc requires --start-utc")
        request={"schema_version":1,"search":{"coverage":"conus"}}
        if args.start_utc:
            request["time_window"]={"start_utc":args.start_utc,"end_utc":args.end_utc or args.start_utc,"source":"user"}
            if args.time_source:
                request["time_window"]["source_detail"]=args.time_source
        config=operator_config(args.config,args.online)
        manager=JobManager(args.jobs,config,max_runtime_s=args.max_runtime)
        try:
            audio=Path(args.audio)
            with audio.open("rb") as source:
                queued=manager.submit(request,source,audio.stat().st_size,suffix=audio.suffix)
            print(json.dumps(manager.wait(queued["job_id"]),indent=2))
        finally:
            manager.close()
    elif args.command=="job":
        from pathlib import Path
        from .jobs import read_json
        import uuid
        try:
            if uuid.UUID(args.job_id).hex!=args.job_id:
                raise ValueError
        except ValueError:
            parser.error("job_id must be the 32-character job identifier")
        print(json.dumps(read_json(Path(args.jobs)/args.job_id/"result.json"),indent=2))
    elif args.command=="resume":
        from .jobs import JobManager
        manager=JobManager(args.jobs,max_runtime_s=args.max_runtime)
        try:
            queued=manager.resume(args.job_id)
            print(json.dumps(manager.wait(queued["job_id"]),indent=2))
        finally:
            manager.close()


if __name__=="__main__":
    main()
