"""Documented CLI; every run operation uses an authoritative manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .application import branch, compare, dossier, simulate, summary
from .config import PRESETS, SimError, make_manifest, offset_for_year
from .exporting import export_run
from .storage import RunStore


def parser():
    p = argparse.ArgumentParser(prog="worldsim", description="Generate and explore reproducible alternate histories locally.")
    sub = p.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="Generate a seeded world and year-zero checkpoint")
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--provinces", type=int, default=320)
    generate.add_argument("--preset", choices=PRESETS, default="balanced")
    generate.add_argument("--start-year", type=int, default=-9000, help="Negative means BCE; no year zero")
    generate.add_argument("--run-dir", default="runs/world-42")
    generate.add_argument("--manifest", help="Output manifest path, instead of --run-dir")
    generate.add_argument("--parameters", default="{}", help="JSON parameter overrides")
    for name in ("simulate", "resume"):
        cmd = sub.add_parser(name, help="Advance using annual transitions; resume matches an uninterrupted run")
        cmd.add_argument("--manifest", required=True)
        group = cmd.add_mutually_exclusive_group(required=True)
        group.add_argument("--years", type=int)
        group.add_argument("--until", type=int, help="Display calendar year, negative for BCE")
    inspect = sub.add_parser("inspect", help="Dated entity dossier")
    inspect.add_argument("--manifest", required=True)
    inspect.add_argument("--kind", choices=("province", "polity", "language", "settlement"), default="province")
    inspect.add_argument("--id", type=int, required=True)
    inspect.add_argument("--year", type=int, help="Integer offset from start; defaults to latest")
    validate = sub.add_parser("validate", help="Check every stored ledger, provenance and hashes")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--deep", action="store_true", help="Also replay and hash every annual patch")
    branching = sub.add_parser("branch", help="Copy history at an exact year and apply a bounded intervention")
    branching.add_argument("--manifest", required=True)
    branching.add_argument("--year", type=int, required=True, help="Year offset")
    branching.add_argument("--run-dir", required=True)
    branching.add_argument("--kind", choices=("travel_cost", "drought_severity"), required=True)
    branching.add_argument("--province", type=int, required=True)
    branching.add_argument("--factor", type=float, required=True)
    comparison = sub.add_parser("compare", help="Align runs by calendar date and inspect recorded divergence")
    comparison.add_argument("--manifest", required=True)
    comparison.add_argument("--other-manifest", required=True)
    comparison.add_argument("--year", type=int, required=True)
    export = sub.add_parser("export", help="Export maps, tables and event-cited history")
    export.add_argument("--manifest", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--year", type=int)
    export.add_argument("--format", choices=("all", "csv", "geojson", "svg", "history"), default="all")
    serve = sub.add_parser("serve", help="Open the local atlas application")
    serve.add_argument("--runs-dir", default="runs")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--manifest", help="Include an existing run outside --runs-dir")
    sub.add_parser("presets", help="List world presets and supported capabilities")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve
            serve(Path(args.runs_dir), args.port, args.manifest)
            return 0
        if args.command == "presets":
            from .technology import CAPABILITIES
            output = {"presets": PRESETS, "capabilities": [c.name for c in CAPABILITIES]}
        elif args.command == "generate":
            manifest = make_manifest(args.seed, args.provinces, args.preset, args.start_year, json.loads(args.parameters))
            destination = Path(args.manifest).parent if args.manifest else Path(args.run_dir)
            if args.manifest and Path(args.manifest).name != "manifest.json":
                raise SimError("INVALID_PARAMETERS", "A run's manifest filename must be manifest.json.")
            with RunStore.create(destination, manifest) as store:
                output = {**summary(store), "manifest": str(store.manifest_path), "geography": store.world.report}
        else:
            with RunStore(args.manifest) as store:
                if args.command in ("simulate", "resume"):
                    years = args.years if args.years is not None else offset_for_year(args.until, store.manifest["start_year"])-store.latest_year
                    output = simulate(store, years)
                elif args.command == "inspect":
                    output = dossier(store, args.kind, args.id, args.year)
                elif args.command == "validate":
                    output = store.validate(args.deep)
                elif args.command == "branch":
                    with branch(store, args.year, args.run_dir, {"kind": args.kind, "province": args.province, "factor": args.factor}) as branched:
                        output = {**summary(branched), "manifest": str(branched.manifest_path)}
                elif args.command == "compare":
                    with RunStore(args.other_manifest) as other:
                        output = compare(store, other, args.year)
                elif args.command == "export":
                    output = export_run(store, args.output, args.year, args.format)
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0
    except SimError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "INVALID_INPUT", "message": str(exc)}}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": {"code": "INTERRUPTED", "message": "Committed years are saved; resume from the same manifest."}}), file=sys.stderr)
        return 130
