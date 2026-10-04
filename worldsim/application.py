"""Shared application layer for commands and the atlas."""
from __future__ import annotations

from collections import Counter
import copy
from pathlib import Path
import sqlite3

import numpy as np

from .config import CITY_MIN_POPULATION, PARAMETER_VERSION, SimError, calendar_year, canonical, check_simulation_version, digest, offset_for_year, year_label
from .engine import Engine, take_cohorts
from .linguistics import FEATURES, intelligibility
from .model import encode_state, state_hash
from .storage import RunStore
from .technology import CAPABILITIES, has, names


def simulate(store: RunStore, years: int, progress=None, stopped=None) -> dict:
    if isinstance(years, bool) or not isinstance(years, int) or not 0 <= years <= 30000 or store.latest_year+years > 30000:
        raise SimError("INVALID_PARAMETERS", "Runs support offsets from 0 through 30,000.")
    state, chain = store.load_state(), store.event_hash
    engine = Engine(store.world, store.manifest)
    start = state.year
    for _ in range(years):
        if stopped is not None and stopped.is_set():
            break
        before = state
        state, events, ledger, chain = engine.step(before, chain)
        store.append(before, state, events, ledger, chain)
        if progress is not None:
            progress(state.year)
    return {"id": store.manifest["id"], "year": state.year,
            "date": year_label(state.year, store.manifest["start_year"]), "years_advanced": state.year-start,
            "population": int(state.arrays["cohorts"].sum()), "state_hash": state_hash(state), "event_hash": chain}


def branch(store: RunStore, year: int, directory: str | Path, intervention: dict) -> RunStore:
    check_simulation_version(store.manifest)
    store.load_state(year)  # Validate the requested checkpoint before writing anything.
    kind = intervention.get("kind")
    factor, province = intervention.get("factor"), intervention.get("province")
    if kind not in ("travel_cost", "drought_severity") or isinstance(province, bool) or not isinstance(province, int) or not 0 <= province < store.world.size:
        raise SimError("INVALID_PARAMETERS", "Select a province and a travel-cost or drought-severity intervention.")
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not .1 <= factor <= 4:
        raise SimError("INVALID_PARAMETERS", "Intervention factor must be from 0.1 to 4.")
    manifest = copy.deepcopy(store.manifest)
    manifest["parent"] = {"id": store.manifest["id"], "year": year, "checkpoint_hash": state_hash(store.load_state(year))}
    manifest["interventions"].append({"kind": kind, "province": province, "factor": factor, "year": year+1})
    manifest["id"] = digest({k: v for k, v in manifest.items() if k != "id"})[:16]
    directory = Path(directory).resolve()
    if (directory/"manifest.json").exists() or (directory/"history.sqlite").exists():
        raise SimError("RUN_EXISTS", "The branch destination already contains a run.")
    directory.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(directory/"history.sqlite")
    try:
        # SQLite backup includes a consistent, committed WAL view.
        store.connection.backup(target)
        with target:
            target.execute("DELETE FROM event_entities WHERE event_id IN (SELECT id FROM events WHERE year>?)", (year,))
            target.execute("DELETE FROM events WHERE year>?", (year,))
            target.execute("DELETE FROM commits WHERE year>?", (year,))
            target.execute("DELETE FROM snapshots WHERE year>?", (year,))
            import hashlib
            import zlib
            state = store.load_state(year)
            target.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)", (year, zlib.compress(encode_state(state), 6), state_hash(state)))
            event_row = target.execute("SELECT event_hash FROM commits WHERE year=?", (year,)).fetchone()
            values = {"latest_year": str(year).encode(), "state_hash": state_hash(state).encode(),
                      "event_hash": (event_row[0] if event_row else "0"*64).encode(),
                      "manifest_hash": hashlib.sha256(canonical(manifest)).hexdigest().encode()}
            target.executemany("UPDATE metadata SET value=? WHERE key=?", [(v, k) for k, v in values.items()])
    finally:
        target.close()
    (directory/"manifest.json").write_bytes(canonical(manifest)+b"\n")
    return RunStore(directory/"manifest.json")


def speaker_counts(state) -> dict[int, int]:
    counts = Counter()
    for row, cohorts in zip(state.arrays["strata"], state.arrays["cohorts"]):
        counts[int(row[2])] += int(cohorts.sum())
    return dict(counts)


def summary(store: RunStore, state=None) -> dict:
    state = store.load_state() if state is None else state
    pop = state.population(store.world.size)
    speakers = speaker_counts(state)
    return {"id": store.manifest["id"], "seed": store.manifest["seed"], "preset": store.manifest["preset"],
            "year": state.year, "latest_year": store.latest_year, "start_year": store.manifest["start_year"],
            "date": year_label(state.year, store.manifest["start_year"]), "population": int(pop.sum()),
            "inhabited": int(np.count_nonzero(pop)), "languages": len(speakers),
            "polities": len(set(state.arrays["control"].tolist())-{-1}),
            "cities": sum(s["city_founded"] is not None and
                          (store.manifest["parameter_version"] != PARAMETER_VERSION or
                           pop[s["province"]]*state.arrays["urban"][s["province"]] >= CITY_MIN_POPULATION)
                          for s in state.settlements.values()),
            "can_simulate": store.manifest["parameter_version"] == PARAMETER_VERSION,
            "city_min_population": CITY_MIN_POPULATION if store.manifest["parameter_version"] == PARAMETER_VERSION else 1000,
            "parent": store.manifest["parent"], "capabilities": {cap.name: int(np.count_nonzero(has(state.arrays["adopted"], cap.name))) for cap in CAPABILITIES},
            "historical_calibration": "not performed"}


def map_data(store: RunStore, year: int | None = None) -> dict:
    state = store.load_state(year)
    pop = state.population(store.world.size)
    dominant = {"language": np.full(store.world.size, -1, dtype=int),
                "community": np.full(store.world.size, -1, dtype=int), "belief": np.full(store.world.size, -1, dtype=int)}
    largest = {key: np.zeros(store.world.size, dtype=int) for key in dominant}
    totals = {key: Counter() for key in dominant}
    for row, cohorts in zip(state.arrays["strata"], state.arrays["cohorts"]):
        for key, index in (("language", 2), ("community", 3), ("belief", 4)):
            totals[key][(int(row[1]), int(row[index]))] += int(cohorts.sum())
    for key in totals:
        for (pid, identity), count in sorted(totals[key].items()):
            if count > largest[key][pid]:
                largest[key][pid], dominant[key][pid] = count, identity
    war = np.zeros(store.world.size, dtype=int)
    for conflict in state.conflicts.values():
        if conflict["ended"] is None:
            war[conflict["objective"]] += 1
    ledger = store.ledger(state.year)
    displacement = np.zeros(store.world.size, dtype=np.int64)
    if ledger:
        for flow in ledger["flows"]:
            if flow["type"] == "Displacement":
                displacement[flow["from"]] += flow["count"]
    provinces = []
    for p in store.world.provinces:
        pid = p["id"]
        provinces.append({**p, "population": int(pop[pid]), "density": round(pop[pid]/p["area_km2"], 5),
                          "language": int(dominant["language"][pid]), "community": int(dominant["community"][pid]),
                          "belief": int(dominant["belief"][pid]), "control": int(state.arrays["control"][pid]),
                          "food": float(state.arrays["food"][pid]), "food_years": round(float(state.arrays["food"][pid]/max(pop[pid], 1)), 3),
                          "technology": names(int(state.arrays["adopted"][pid])), "known": names(int(state.arrays["known"][pid])),
                          "urban_population": int(pop[pid]*state.arrays["urban"][pid]), "war": int(war[pid]),
                          "migration": (ledger["emigration"][pid] if ledger else 0),
                          "displacement": int(displacement[pid]),
                          "pollution": float(state.arrays["pollution"][pid])})
    return {"summary": summary(store, state), "grid": store.world.grid, "provinces": provinces,
            "edges": store.world.edges, "geography": store.world.report,
            "languages": {k: {"id": v["id"], "name": v["name"]} for k, v in state.languages.items()},
            "polities": {k: {"id": v["id"], "name": v["name"], "form": v["form"]} for k, v in state.polities.items()},
            "communities": state.communities, "beliefs": state.beliefs,
            "settlements": {key: {k: value[k] for k in ("id", "name", "province", "city_founded")}
                            for key, value in state.settlements.items()},
            "trade": ledger["trade"] if ledger else []}


def dossier(store: RunStore, kind: str, entity_id: int, year: int | None = None) -> dict:
    state = store.load_state(year)
    pop, rows, cohorts = state.population(store.world.size), state.arrays["strata"], state.arrays["cohorts"]
    if kind == "province":
        if not 0 <= entity_id < store.world.size:
            raise SimError("NOT_FOUND", "Province does not exist.")
        selected = rows[:, 1] == entity_id
        entity = store.world.provinces[entity_id]
        details = {**entity, "food": float(state.arrays["food"][entity_id]), "control": int(state.arrays["control"][entity_id]),
                   "known": names(int(state.arrays["known"][entity_id])), "adopted": names(int(state.arrays["adopted"][entity_id])),
                   "services": {k: float(state.arrays[k][entity_id]) for k in ("roads", "schooling", "sanitation", "urban")},
                   "settlements": [s for s in state.settlements.values() if s["province"] == entity_id],
                   "community_profiles": {str(int(r[3])): state.communities[str(int(r[3]))] for r in rows[selected]}}
        ledger = store.ledger(state.year) if state.year else None
        if "cultivated_ha" in state.arrays:
            details["subsistence"] = {"cultivated_ha": float(state.arrays["cultivated_ha"][entity_id]),
                                       "surplus_years": int(state.arrays["urban_surplus_years"][entity_id]),
                                       "harvest": ledger["food_produced"][entity_id] if ledger else None,
                                       "food_workers": ledger["food_workers"][entity_id] if ledger else None,
                                       "urban_food_support": ledger["urban_food_support"][entity_id] if ledger else 0}
    elif kind == "polity":
        if str(entity_id) not in state.polities:
            raise SimError("NOT_FOUND", "Polity did not exist at this date.")
        details = copy.deepcopy(state.polities[str(entity_id)])
        territory = np.flatnonzero(state.arrays["control"] == entity_id)
        selected = np.isin(rows[:, 1], territory)
        details.update({"territory": territory.tolist(), "area_km2": sum(store.world.provinces[pid]["area_km2"] for pid in territory),
                        "wars": [c for c in state.conflicts.values() if entity_id in (c["attacker"], c["defender"])],
                        "military_capacity_estimate": int(pop[territory].sum()*.025)})
    elif kind == "language":
        if str(entity_id) not in state.languages:
            raise SimError("NOT_FOUND", "Language did not exist at this date.")
        details = copy.deepcopy(state.languages[str(entity_id)])
        selected = rows[:, 2] == entity_id
        details["phoneme_features"] = {c: FEATURES[c] for c in details["consonants"]+details["vowels"]}
        details["family_graph"] = [{"id": v["id"], "name": v["name"], "parents": v["parents"], "founded": v["founded"]}
                                  for v in state.languages.values()]
        details["similarities"] = [{"language": v["id"], "name": v["name"], **intelligibility(details, v)}
                                   for v in state.languages.values() if v["id"] != entity_id][:30]
    elif kind == "settlement":
        if str(entity_id) not in state.settlements:
            raise SimError("NOT_FOUND", "Settlement did not exist at this date.")
        details = copy.deepcopy(state.settlements[str(entity_id)])
        selected = rows[:, 1] == details["province"]
        details["urban_population"] = int(pop[details["province"]]*state.arrays["urban"][details["province"]])
        details["services"] = {k: float(state.arrays[k][details["province"]]) for k in ("roads", "schooling", "sanitation")}
    else:
        raise SimError("INVALID_PARAMETERS", "Choose province, polity, language or settlement.")
    reported_cohorts = cohorts[selected]
    population_is_estimate = kind == "settlement" and details["city_founded"] is not None
    if population_is_estimate:
        details["province_population"] = int(pop[details["province"]])
        reported_cohorts = take_cohorts(reported_cohorts, details["urban_population"])
    language_shares, community_shares, belief_shares = Counter(), Counter(), Counter()
    for row, cohort in zip(rows[selected], reported_cohorts):
        count = int(cohort.sum())
        language_shares[int(row[2])] += count
        community_shares[int(row[3])] += count
        belief_shares[int(row[4])] += count
    events = store.events(state.year, f"{kind}:{entity_id}", limit=60)
    return {"kind": kind, "id": entity_id, "year": state.year, "date": year_label(state.year, store.manifest["start_year"]),
            "name": details["name"], "population": int(reported_cohorts.sum()),
            "population_is_estimate": population_is_estimate,
            "age_structure": reported_cohorts.sum(axis=(0, 1)).tolist(),
            "language_shares": [{"id": k, "name": state.languages[str(k)]["name"], "speakers": v} for k, v in language_shares.most_common()],
            "community_shares": dict(community_shares), "belief_shares": dict(belief_shares),
            "details": details, "events": events}


def compare(left: RunStore, right: RunStore, year: int) -> dict:
    other_year = offset_for_year(calendar_year(year, left.manifest["start_year"]), right.manifest["start_year"])
    a, b = left.load_state(year), right.load_state(other_year)
    pa, pb = a.population(left.world.size), b.population(right.world.size)
    same_geography = digest(left.world.to_dict()) == digest(right.world.to_dict())
    # World names are initial-state data and identical on branches.
    earliest = None
    year_difference = other_year-year
    for y in range(max(1, 1-year_difference), year+1):
        ea = left.connection.execute("SELECT event_hash FROM commits WHERE year=?", (y,)).fetchone()
        eb = right.connection.execute("SELECT event_hash FROM commits WHERE year=?", (y+year_difference,)).fetchone()
        if ea[0] != eb[0]:
            earliest = y
            break
    delta = int(pb.sum()-pa.sum())
    speakers_a, speakers_b = speaker_counts(a), speaker_counts(b)
    lexical_difference = (sum(a.languages[k]["lexicon"] != b.languages[k]["lexicon"]
                              for k in a.languages.keys() & b.languages.keys()) if same_geography else None)
    return {"left": summary(left, a), "right": summary(right, b), "year": year, "other_year": other_year,
            "population_delta": delta, "population_relative": delta/max(1, int(pa.sum())),
            "province_population_delta": (pb-pa).tolist() if same_geography else None,
            "border_differences": int(np.count_nonzero(a.arrays["control"] != b.arrays["control"])) if same_geography else None,
            "language_speaker_delta": ({str(k): speakers_b.get(k, 0)-speakers_a.get(k, 0)
                                       for k in speakers_a.keys() | speakers_b.keys()} if same_geography else None),
            "language_count_delta": len(speakers_b)-len(speakers_a),
            "lexical_varieties_changed": lexical_difference,
            "technology_adoption_delta": {c.name: int(np.count_nonzero(has(b.arrays["adopted"], c.name))-np.count_nonzero(has(a.arrays["adopted"], c.name))) for c in CAPABILITIES},
            "earliest_recorded_divergence": earliest, "same_geography": same_geography,
            "divergence_events": {"left": left.events(earliest, since=earliest, limit=15) if earliest else [],
                                  "right": right.events(earliest+year_difference, since=earliest+year_difference, limit=15) if earliest else []},
            "interpretation": "Scenario results, not identified causal effects."}
