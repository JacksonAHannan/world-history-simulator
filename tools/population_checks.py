"""Reproducible long-run food/population checks; exploratory screening, not a fit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from worldsim.config import make_manifest, year_label
from worldsim.engine import Engine
from worldsim.geography import generate_world
from worldsim.initialization import initialize


def run(seed, provinces, years):
    manifest = make_manifest(seed, provinces)
    world = generate_world(manifest)
    state = initialize(world, manifest)
    initial = int(state.arrays["cohorts"].sum())
    engine, chain = Engine(world, manifest), "0"*64
    points, first_city = [], None
    start = time.monotonic()
    for year in range(1, years+1):
        state, events, ledger, chain = engine.step(state, chain)
        urban = state.population(world.size)*state.arrays["urban"]
        # Commit quantization may alter a derived resident estimate by < 1.
        assert np.all(np.floor(urban) <= np.asarray(ledger["urban_food_support"])+1.)
        if first_city is None and any(s["city_founded"] is not None for s in state.settlements.values()):
            first_city = year
        if year in {400, 1000, 2000, 3000, years}:
            point = {"year": year, "date": year_label(year, manifest["start_year"]),
                     "population": int(state.arrays["cohorts"].sum()),
                     "historical_city_sites": sum(s["city_founded"] is not None for s in state.settlements.values()),
                     "largest_urban_population": int(np.max(urban, initial=0)),
                     "famine_deaths_in_year": sum(ledger["deaths"]["famine"])}
            points.append(point)
            print(json.dumps({"seed": seed, **point}), flush=True)
    assert int(state.arrays["cohorts"].sum()) > initial*.25, "Unexplained global demographic collapse"
    # Broad screening for the Earth-sized, early-Holocene balanced preset.
    if years <= 3000:
        assert int(state.arrays["cohorts"].sum()) <= 20_000_000, "Early population exceeds the declared broad screening range"
    return {"manifest": manifest, "initial_population": initial, "points": points,
            "first_city_year": first_city, "elapsed_seconds": round(time.monotonic()-start, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 73, 819801813])
    parser.add_argument("--provinces", type=int, default=64)
    parser.add_argument("--years", type=int, default=3000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.years <= 30000:
        parser.error("years must be from 1 through 30,000")
    if args.output.exists():
        parser.error("output already exists; keep prior evidence and select another file")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted((Path(__file__).resolve().parents[1]/"worldsim").glob("*.py"))}
    for seed in args.seeds:
        results.append(run(seed, args.provinces, args.years))
        args.output.write_text(json.dumps({"ok": True, "scope": "completed seeds only",
                              "source_hashes": source_hashes,
                              "completed_seeds": len(results), "requested_seeds": len(args.seeds),
                              "results": results}, indent=2)+"\n")


if __name__ == "__main__":
    main()
