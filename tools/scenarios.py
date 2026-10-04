"""Predeclared mechanistic ensemble checks. Not empirical historical calibration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldsim.config import ENGINE_VERSION, PARAMETER_VERSION, SCHEMA_VERSION, make_manifest
from worldsim.engine import Engine
from worldsim.geography import generate_world
from worldsim.initialization import initialize
from worldsim.model import state_hash


def run(seed, provinces, years, overrides):
    m = make_manifest(seed, provinces, overrides=overrides)
    w = generate_world(m)
    s = initialize(w, m)
    e = Engine(w, m)
    chain, loans, moves, famine, births, ordinary = "0"*64, 0, 0, 0, 0, 0
    for _ in range(years):
        s, events, ledger, chain = e.step(s, chain)
        loans += sum(event["type"] == "Borrowing" for event in events)
        moves += sum(ledger["immigration"])
        famine += sum(ledger["deaths"]["famine"])
        births += sum(ledger["births"])
        ordinary += sum(ledger["deaths"]["ordinary"])
    return {"population": int(s.arrays["cohorts"].sum()), "loans": loans, "migrants": moves,
            "famine_deaths": famine, "polities": len(set(s.arrays["control"].tolist())-{-1}),
            "births": births, "ordinary_deaths": ordinary,
            "mean_urban_share": float(s.arrays["urban"].mean()), "mean_schooling": float(s.arrays["schooling"].mean()),
            "state_hash": state_hash(s)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--provinces", type=int, default=64)
    parser.add_argument("--years", type=int, default=200)
    parser.add_argument("--output", default="artifacts/scenarios.json")
    args = parser.parse_args()
    variants = {"baseline": {}, "more_food": {"food_yield": 1.2},
                "more_mortality": {"mortality": 1.2}, "barrier": {"travel_cost": 2.5}}
    start, results = time.perf_counter(), []
    for seed in range(args.seeds):
        row = {"seed": seed}
        for name, overrides in variants.items():
            row[name] = run(seed, args.provinces, args.years, overrides)
        results.append(row)
        print(f"Seed {seed}: population {row['baseline']['population']:,}; borrowing {row['baseline']['loans']} vs barrier {row['barrier']['loans']}", flush=True)
    mean = lambda variant, field: sum(row[variant][field] for row in results)/len(results)
    checks = {"food_yield_reduces_mean_famine_deaths": mean("more_food", "famine_deaths") < mean("baseline", "famine_deaths"),
              "mortality_reduces_mean_population": mean("more_mortality", "population") < mean("baseline", "population"),
              "barrier_reduces_mean_borrowing": mean("barrier", "loans") < mean("baseline", "loans"),
              "no_unexplained_population_loss": all(row["baseline"]["population"] > 0 for row in results)}
    output = {"status": "mechanistic sensitivity only; no external calibration", "settings": vars(args),
              "versions": {"engine": ENGINE_VERSION, "parameters": PARAMETER_VERSION, "schema": SCHEMA_VERSION},
              "predeclared_checks": checks, "results": results, "elapsed_seconds": time.perf_counter()-start,
              "means": {variant: {field: mean(variant, field) for field in ("population", "loans", "migrants", "famine_deaths", "polities", "births", "ordinary_deaths", "mean_urban_share", "mean_schooling")} for variant in variants}}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2)+"\n")
    print(json.dumps({"checks": checks, "means": output["means"], "elapsed_seconds": output["elapsed_seconds"]}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
