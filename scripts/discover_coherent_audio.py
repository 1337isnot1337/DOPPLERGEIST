"""Experimental whole-file coherent discovery using an installed dopploc source.

Run in an environment with digitalis-p/doppler-locate and this checkout's src
on PYTHONPATH. No aircraft identity, location, clock or selected band is needed.
"""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
import argparse
import json
import multiprocessing as mp
import time

from dopplergeist.coherent_discovery import events_from_coherent_traces


def capture_traces(source, workers=2):
    from dopploc import detect

    traces = []
    original_refine, original_pool = detect._refine_all, detect._pool

    def capture(found, spectrum, settings, executor):
        original_refine(found, spectrum, settings, executor)
        for proposal in found:
            if not hasattr(proposal, "_trace"):
                continue
            t, f, _ = proposal._trace
            traces.append({"proposal": asdict(proposal), "ridge_points": [
                {"time_s": float(tt), "frequency_hz": float(ff)} for tt, ff in zip(t, f)]})
            # Automatic matching uses broad measured-ridge envelopes, not
            # straight-pass profile ranges. Avoid that unused nonlinear work.
            del proposal._trace

    detect._refine_all = capture
    detect._pool = lambda: ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"))
    try:
        detect.detect(source)
    finally:
        detect._refine_all, detect._pool = original_refine, original_pool
    return traces


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    if args.output.exists():
        parser.error("output exists; preserve it and choose a new path")
    started = time.monotonic()
    traces = capture_traces(args.audio, args.workers)
    events = events_from_coherent_traces(traces)
    args.output.write_text(json.dumps({"events": events, "raw_refined_traces": len(traces),
        "elapsed_s": time.monotonic() - started,
        "scope": "Experimental acoustic proposals; not aircraft identifications or geolocation"}, indent=2))
    print(f"{len(events)} measured-ridge proposals saved to {args.output}")
