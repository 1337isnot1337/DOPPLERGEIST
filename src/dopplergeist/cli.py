import argparse
import json


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
    args=parser.parse_args()
    if args.command=="run":
        from .pipeline import run
        run(args.config,args.output)
    elif args.command=="measure":
        from .audio import measure
        result=measure(args.audio,{"start_s":args.start,"end_s":args.end,"band_hz":args.band},args.output)
        print(json.dumps(result[-1],indent=2))


if __name__=="__main__":
    main()
