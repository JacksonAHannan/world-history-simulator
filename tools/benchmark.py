"""Measure actual annual simulation throughput, storage, memory and checkpoint access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldsim.application import map_data, simulate
from worldsim.config import PRESETS, calendar_year, digest, make_manifest
from worldsim.storage import RunStore
from worldsim.technology import CAPABILITIES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provinces", type=int, default=2000)
    parser.add_argument("--years", type=int, default=11000)
    parser.add_argument("--seed", type=int, default=1024)
    parser.add_argument("--preset", choices=PRESETS, default="balanced")
    parser.add_argument("--start-year", type=int, default=-9000)
    parser.add_argument("--parameters", default="{}", help="JSON parameter overrides; record scenario differences explicitly")
    parser.add_argument("--run-dir", default="runs/reference")
    parser.add_argument("--report", default="artifacts/reference-benchmark.json")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    start = time.perf_counter()
    store = RunStore(Path(args.run_dir)/"manifest.json") if args.resume else RunStore.create(args.run_dir, make_manifest(args.seed,args.provinces,args.preset,args.start_year,json.loads(args.parameters)))
    with store:
        initial_year = store.latest_year
        def progress(year):
            if year % 100 == 0:
                print(f"Year {year}: {time.perf_counter()-start:.1f}s", flush=True)
        result = simulate(store, args.years, progress)
        elapsed = time.perf_counter()-start
        access_year = max(0, store.latest_year-50)
        access_start = time.perf_counter()
        view = map_data(store, access_year)
        access = time.perf_counter()-access_start
        state = store.load_state()
        report = {"settings": vars(args), "manifest_hash": digest(store.manifest),
                  "versions": {key: store.manifest[key] for key in ("engine_version", "parameter_version", "schema_version", "world_generation", "data_sources", "numpy_version", "python_version")},
                  "initial_year": initial_year, "result": result,
                  "calendar_year": calendar_year(state.year, store.manifest["start_year"]),
                  "capability_provinces": {c.name: int(((state.arrays["adopted"] & (1 << i)) != 0).sum()) for i, c in enumerate(CAPABILITIES)},
                  "measured_seconds": elapsed, "years_per_second": args.years/elapsed,
                  "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                  "database_mb": (store.directory/"history.sqlite").stat().st_size/2**20,
                  "historical_map_seconds": access, "historical_map_year": access_year,
                  "estimated_11000_year_seconds": elapsed/args.years*11000,
                  "reference_target_measured": args.provinces==2000 and args.years==11000,
                  "caveat": "Throughput changes as populations and identities accumulate; short-run extrapolation is not a reference benchmark."}
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2)+"\n")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
