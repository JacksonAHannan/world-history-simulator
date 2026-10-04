"""Portable maps, structured truth, and deterministic event-cited history."""
from __future__ import annotations

import csv
import heapq
import html
import json
from pathlib import Path
import zipfile

from .application import map_data
from .config import SimError, year_label
from .technology import names


def export_run(store, directory: str | Path, year: int | None = None, format: str = "all") -> dict:
    if format not in ("all", "csv", "geojson", "svg", "history"):
        raise SimError("INVALID_PARAMETERS", "Choose all, csv, geojson, svg or history.")
    data = map_data(store, year)
    year = data["summary"]["year"]
    state = store.load_state(year)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    files = []

    def write(name, content):
        path = directory/name
        if path.exists():
            raise SimError("EXPORT_EXISTS", f"Export file already exists: {path.name}.")
        path.write_text(content, encoding="utf-8")
        files.append(path)

    write("manifest.json", json.dumps(store.manifest, indent=2)+"\n")
    write("export-metadata.json", json.dumps({"year_offset": year, "date": data["summary"]["date"],
          "run": store.manifest["id"], "geography": store.world.report,
          "units": {"population": "people, exact engine counts", "food": "person-years of consumption",
                    "area": "km²", "routes": "scheduled travel days", "treasury": "abstract fiscal output units"},
          "model_status": "Uncalibrated exploratory simulation; scenario comparisons are not identified causal effects."}, indent=2)+"\n")
    if format in ("all", "geojson"):
        features = [{"type": "Feature", "id": p["id"],
                     "geometry": {"type": "Polygon", "coordinates": [p["geometry"]]},
                     "properties": {k: v for k, v in p.items() if k != "geometry"}} for p in data["provinces"]]
        write("atlas.geojson", json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
    if format in ("all", "svg"):
        width, height = 1440, 640
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height+60}" viewBox="0 0 {width} {height+60}">',
               '<rect width="100%" height="100%" fill="#dcecf3"/>',
               f'<text x="22" y="32" font-size="21" fill="#17334a">World {store.manifest["seed"]}: {html.escape(data["summary"]["date"])}</text>']
        for p in data["provinces"]:
            points = " ".join(f"{(lon+180)/360*width:.2f},{(68-lat)/136*height+50:.2f}" for lon, lat in p["geometry"])
            hue = 50+p["control"]*137.508 % 310 if p["control"] >= 0 else 90
            color = f"hsl({hue:.1f},30%,68%)" if p["control"] >= 0 else "#bdcba2"
            svg.append(f'<polygon points="{points}" fill="{color}" stroke="#577265" stroke-width="0.4"><title>{html.escape(p["name"])}: {p["population"]:,} people</title></polygon>')
        svg.append('<text x="22" y="685" font-size="12" fill="#17334a">Equirectangular; polar caps excluded. Political control; colors indicate distinct organizations.</text></svg>')
        write("atlas.svg", "\n".join(svg))
    if format in ("all", "csv"):
        def table(name, headings, rows):
            path = directory/name
            if path.exists():
                raise SimError("EXPORT_EXISTS", f"Export file already exists: {path.name}.")
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(headings)
                writer.writerows(rows)
            files.append(path)
        table("provinces.csv", ["id", "name", "area_km2", "population", "food_person_years", "control", "language", "urban_population", "capabilities"],
              ([p["id"], p["name"], p["area_km2"], p["population"], p["food"], p["control"], p["language"], p["urban_population"], ";".join(p["technology"])] for p in data["provinces"]))
        table("cohorts.csv", ["stratum", "province", "language", "community", "belief", "status", "sex_model", "age_band", "population", "ancestry"],
              ([*metadata.tolist(), sex, "85+" if age == 17 else f"{age*5}-{age*5+4}", int(cohort[sex, age]), json.dumps(state.ancestry[str(int(metadata[0]))])]
               for metadata, cohort in zip(state.arrays["strata"], state.arrays["cohorts"]) for sex in (0, 1) for age in range(18)))
        table("lexicon.csv", ["language", "name", "meaning", "form", "root", "formation", "history"],
              ([language["id"], language["name"], meaning, entry["form"], entry["root"], entry["formation"], json.dumps(entry["history"])]
               for language in state.languages.values() for meaning, entry in language["lexicon"].items()))
        table("polities.csv", ["id", "name", "form", "founded", "dissolved", "treasury", "legitimacy", "institutions"],
              ([p["id"], p["name"], p["form"], p["founded"], p["dissolved"], p["treasury"], p["legitimacy"], ";".join(p["institutions"])] for p in state.polities.values()))
        table("timeline.csv", ["year_offset", "date", "population", "events"],
              ([r["year"], year_label(r["year"], store.manifest["start_year"]), r["population"], r["event_count"]] for r in store.timeline() if r["year"] <= year))
        def flows():
            for y in range(1, year+1):
                ledger = store.ledger(y)
                for flow in ledger["flows"]:
                    yield [y, flow["type"], flow["from"], flow["to"], flow["count"], flow["language_before"], flow["language_after"],
                           flow["from_stratum"], flow["to_stratum"], json.dumps(flow["cohorts"])]
        table("population-flows.csv", ["year_offset", "type", "from", "to", "count", "language_before", "language_after", "from_stratum", "to_stratum", "cohorts"], flows())
    if format in ("all", "history"):
        import zlib
        truth_path = directory/"events.jsonl"
        history_path = directory/"history.md"
        if truth_path.exists() or history_path.exists():
            raise SimError("EXPORT_EXISTS", "This destination already has a history export.")
        with truth_path.open("w", encoding="utf-8") as truth, history_path.open("w", encoding="utf-8") as prose:
            prose.write(f"# History of world {store.manifest['seed']}\n\nGenerated through {data['summary']['date']}. Every event statement below cites its source in events.jsonl. Rules are exploratory and uncalibrated.\n\nThis overview selects at most 50 events per century, prioritizing institutional, territorial, language and capability changes before routine flows. The complete event truth layer, annual timeline and population flows are exported separately.\n\n")
            priorities = {"StateFormation": 0, "Conquest": 0, "Secession": 0,
                          "Treaty": 0, "PolityDissolved": 0, "LanguageSplit": 0,
                          "Discovery": 1, "Adoption": 1, "CityGrowth": 1,
                          "Battle": 2, "CropFailure": 2, "Epidemic": 2,
                          "ConflictStarted": 3, "Abandonment": 3, "SoundChange": 3,
                          "KnowledgeTransfer": 4, "Borrowing": 4}
            pending, century, count = [], None, 0
            def chapter():
                if not pending:
                    return
                first = century*100+1
                last = min(year, (century+1)*100)
                prose.write(f"## {year_label(first, store.manifest['start_year'])} to {year_label(last, store.manifest['start_year'])}\n\nSelected {len(pending)} of {count:,} recorded events.\n\n")
                for _, event in sorted(pending, key=lambda item: (item[1]["year"], item[1]["sequence"])):
                    prose.write(f"- {year_label(event['year'], store.manifest['start_year'])}: {event['text']} [{event['id']}]\n")
                prose.write("\n")
            for record in store.connection.execute("SELECT data FROM events WHERE year<=? ORDER BY year,sequence", (year,)):
                event = json.loads(zlib.decompress(record[0]))
                truth.write(json.dumps(event, ensure_ascii=False)+"\n")
                bucket = (event["year"]-1)//100
                if century is not None and century != bucket:
                    chapter()
                    pending, count = [], 0
                century = bucket
                if event["type"] != "YearCommitted":
                    count += 1
                    key = (-priorities.get(event["type"], 5), -event["year"], -event["sequence"])
                    if len(pending) < 50:
                        heapq.heappush(pending, (key, event))
                    elif key > pending[0][0]:
                        heapq.heapreplace(pending, (key, event))
            chapter()
        files.extend([truth_path, history_path])
    archive = directory/"world-history.zip"
    if archive.exists():
        raise SimError("EXPORT_EXISTS", "Export archive already exists.")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for file in files:
            z.write(file, file.name)
    return {"year": year, "directory": str(directory), "files": [str(p) for p in files], "archive": str(archive)}
