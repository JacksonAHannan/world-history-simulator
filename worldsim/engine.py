"""One annual commit, exact ledgers, and an append-only causal truth layer."""
from __future__ import annotations

import copy
import hashlib
from collections import defaultdict

import numpy as np

from .config import CITY_MIN_POPULATION, RandomStreams, SimError, canonical, check_simulation_version, digest
from .model import Event, State, World
from .systems import (Move, context, demography, economy, environment, knowledge, migration, politics)
from .technology import CAPABILITIES, feasible, has

ROUNDING_TOLERANCE = 2e-5


def take_cohorts(cohorts: np.ndarray, count: int) -> np.ndarray:
    """Conservative largest-remainder allocation, with deterministic cell tie breaks."""
    flat = cohorts.ravel()
    total = int(flat.sum())
    count = max(0, min(int(count), total))
    if total == 0 or count == 0:
        return np.zeros_like(cohorts)
    if count == total:
        return cohorts.copy()
    expected = flat.astype(np.float64)*count/total
    selected = np.floor(expected).astype(np.int64)
    remainder = count-int(selected.sum())
    order = np.argsort(-(expected-selected), kind="stable")
    selected[order[:remainder]] += 1
    return selected.reshape(cohorts.shape)


def _province_sum(rows: np.ndarray, values: np.ndarray, n: int) -> np.ndarray:
    return np.bincount(rows[:, 1], weights=values, minlength=n).astype(np.int64)


class Engine:
    def __init__(self, world: World, manifest: dict):
        check_simulation_version(manifest)
        self.world, self.manifest = world, manifest
        self.rng = RandomStreams(manifest["seed"])

    def step(self, state: State, chain: str = "0"*64) -> tuple[State, list[dict], dict, str]:
        state.freeze()
        ctx = context(state, self.world, self.manifest, self.rng)
        env = environment(state, ctx)
        econ = economy(state, ctx, env)
        demo = demography(state, ctx, env, econ)
        moves = migration(state, ctx, econ)
        know = knowledge(state, ctx, econ)
        political = politics(state, ctx, econ)
        # Refugees use feasible routes, carry their existing identities, and enter
        # the common transfer ledger after casualties. No population is deleted.
        for pid in np.flatnonzero(political.casualties):
            destinations = [(float(ctx.cost[i]), int(ctx.target[i]) if ctx.source[i] == pid else int(ctx.source[i]))
                            for i in range(len(ctx.source)) if pid in (ctx.source[i], ctx.target[i]) and ctx.cost[i] < 240]
            destinations = [(cost, target) for cost, target in destinations if political.casualties[target] == 0]
            if not destinations:
                continue
            travel, destination = min(destinations, key=lambda pair: (pair[0], pair[1]))
            for row in np.flatnonzero(state.arrays["strata"][:, 1] == pid):
                count = int(state.arrays["cohorts"][row].sum()*min(.02, political.casualties[pid]/max(ctx.population[pid], 1)*2))
                if count:
                    moves.moves.insert(0, Move(int(row), destination, count, "Displacement", conditions={
                        "violence_deaths": int(political.casualties[pid]), "travel_days": travel, "route_feasible": True}))
        return self.commit(state, ctx, env, econ, demo, moves, know, political, chain)

    def commit(self, state, ctx, env, econ, demo, moves, know, political, chain):
        result = state.clone()
        result.year = ctx.year
        events = env.events+know.events+political.events
        for intervention in self.manifest["interventions"]:
            if intervention["year"] == ctx.year:
                events.insert(0, Event("Intervention", "scenario.bounded-intervention", [f"province:{intervention['province']}"],
                                       {"kind": intervention["kind"], "factor": intervention["factor"]},
                                       {"setting": intervention}, text=f"A scenario changed {intervention['kind'].replace('_', ' ')} in {self.world.provinces[intervention['province']]['name']}."))
        result.polities, result.conflicts = political.polities, political.conflicts
        result.next_ids["polity"], result.next_ids["conflict"] = political.next_polity, political.next_conflict
        result.languages.update(know.languages)
        result.arrays.update(econ.arrays)
        result.arrays.update(political.public)
        result.arrays["control"] = political.control
        result.arrays["known"], result.arrays["adopted"] = know.known, know.adopted
        result.arrays["divergence"] = know.divergence
        rows = [r.copy() for r in state.arrays["strata"]]
        cohorts = [c.copy() for c in demo.cohorts]
        bilingual = list(know.bilingual)
        migration_credit = list(moves.credit if hasattr(moves, "credit") else state.arrays["migration_credit"])
        proposals = moves.moves if hasattr(moves, "moves") else moves
        violence = np.zeros(self.world.size, dtype=np.int64)
        # Commit priority: ordinary/famine/disease, military casualties, migration, social shifts.
        def remove_violence(pid, wanted, adults=False):
            indices = [i for i, metadata in enumerate(rows) if metadata[1] == pid]
            eligible = [c.copy() for c in (cohorts[i] for i in indices)]
            if adults:
                for c in eligible:
                    c[:, :3], c[:, 11:] = 0, 0
            counts = np.array([c.sum() for c in eligible], dtype=np.int64)
            available = int(counts.sum())
            wanted = min(int(wanted), available)
            allocated = take_cohorts(counts, wanted).ravel()
            actual = 0
            for row, c, count in zip(indices, eligible, allocated):
                removed = take_cohorts(c, int(count))
                cohorts[row] -= removed
                actual += int(removed.sum())
            violence[pid] += actual
            return actual

        # Resolve competing military losses against surviving eligible adults.
        # Civilian losses have their own all-age allocation. Event totals reflect
        # the actual commit, including any cap, rather than proposed casualties.
        for event in political.events:
            if event.type != "Battle":
                continue
            locations = [int(p.split(":")[1]) for p in event.participants if p.startswith("province:")]
            source, target = locations
            war_id = next(p.split(":")[1] for p in event.participants if p.startswith("conflict:"))
            requested = {k: event.deltas[k] for k in ("soldier_deaths_attacker", "soldier_deaths_defender", "civilian_deaths")}
            event.deltas["soldier_deaths_attacker"] = remove_violence(source, requested["soldier_deaths_attacker"], adults=True)
            event.deltas["soldier_deaths_defender"] = remove_violence(target, requested["soldier_deaths_defender"], adults=True)
            event.deltas["civilian_deaths"] = remove_violence(target, requested["civilian_deaths"])
            actual = sum(event.deltas[k] for k in requested)
            event.conditions["requested_casualties"] = requested
            event.conditions["casualty_cap_applied"] = actual != sum(requested.values())
            result.conflicts[war_id]["deaths"] -= sum(requested.values())-actual
            event.text = f"A supplied campaign around {self.world.provinces[target]['name']} caused {actual:,} deaths."
        row_map = {tuple(int(v) for v in r[1:]): i for i, r in enumerate(rows)}
        imports, exports = np.zeros(self.world.size, dtype=np.int64), np.zeros(self.world.size, dtype=np.int64)
        flow_ledger = []
        for move in proposals+know.shifts:
            origin_row = move.row
            metadata = rows[origin_row]
            requested_count = move.count
            if move.type == "Displacement":
                pid = int(metadata[1])
                requested_count = int(move.count*violence[pid]/max(political.casualties[pid], 1))
                move.conditions = {**move.conditions, "violence_deaths": int(violence[pid])}
            removed = take_cohorts(cohorts[origin_row], min(requested_count, int(cohorts[origin_row].sum())//3))
            count = int(removed.sum())
            if count == 0:
                continue
            destination_metadata = metadata.copy()
            destination_metadata[1] = move.destination
            if move.target_language is not None:
                destination_metadata[2] = move.target_language
            key = tuple(int(v) for v in destination_metadata[1:])
            if key not in row_map:
                destination_metadata[0] = result.next_ids["stratum"]
                result.next_ids["stratum"] += 1
                row_map[key] = len(rows)
                rows.append(destination_metadata)
                cohorts.append(np.zeros_like(removed))
                bilingual.append(0.)
                migration_credit.append(0.)
                result.ancestry[str(int(destination_metadata[0]))] = {}
            destination_row = row_map[key]
            if destination_row == origin_row:
                continue
            origin_sid, destination_sid = str(int(metadata[0])), str(int(rows[destination_row][0]))
            old_count = int(cohorts[destination_row].sum())
            ancestry = result.ancestry[destination_sid]
            source_ancestry = result.ancestry[origin_sid]
            result.ancestry[destination_sid] = {k: (ancestry.get(k, 0.)*old_count+source_ancestry.get(k, 0.)*count)/(old_count+count)
                                              for k in sorted(set(ancestry)|set(source_ancestry))}
            bilingual[destination_row] = (bilingual[destination_row]*old_count+bilingual[origin_row]*count)/(old_count+count)
            cohorts[origin_row] -= removed
            cohorts[destination_row] += removed
            source_pid = int(metadata[1])
            if move.type != "LanguageShift":
                exports[source_pid] += count
                imports[move.destination] += count
                transported = int(state.arrays["known"][source_pid] & ~result.arrays["known"][move.destination])
                result.arrays["known"][move.destination] |= int(state.arrays["known"][source_pid])
            else:
                transported = 0
            record = {"type": move.type, "from": source_pid, "to": move.destination,
                      "from_stratum": int(origin_sid), "to_stratum": int(destination_sid),
                      "count": count, "cohorts": removed.tolist(), "language_before": int(metadata[2]),
                      "language_after": int(rows[destination_row][2]), "community": int(metadata[3]),
                      "belief": int(metadata[4]), "status": int(metadata[5]), "ancestry": source_ancestry,
                      "knowledge_transported": transported, "conditions": move.conditions, "draw": move.draw}
            flow_ledger.append(record)
            if move.type == "LanguageShift" or count >= 200 or count >= ctx.population[source_pid]*.007:
                events.append(Event(move.type, "population.cohort-transfer" if move.type != "LanguageShift" else "language.school-mediated-shift",
                                    [f"province:{source_pid}", f"province:{move.destination}",
                                     f"language:{metadata[2]}", f"language:{rows[destination_row][2]}"],
                                    move.conditions, record, move.draw,
                                    text=(f"{count:,} residents {'were displaced' if move.type == 'Displacement' else 'moved'} from {self.world.provinces[source_pid]['name']} to {self.world.provinces[move.destination]['name']}."
                                          if move.type != "LanguageShift" else f"{count:,} bilingual residents shifted primary language through schooling.")))
        for pid, child in know.splits:
            parent = child["parents"][0]
            result.languages[str(child["id"])] = child
            result.next_ids["language"] = max(result.next_ids["language"], child["id"]+1)
            speakers = 0
            for i, metadata in enumerate(rows):
                if metadata[1] == pid and metadata[2] == parent:
                    metadata[2] = child["id"]
                    speakers += int(cohorts[i].sum())
            result.arrays["last_split"][pid] = ctx.year
            events.append(Event("LanguageSplit", "language.sustained-separation", [f"province:{pid}", f"language:{parent}", f"language:{child['id']}"],
                                {"separation_years": float(state.arrays["divergence"][pid]), "parent": parent},
                                {"new_language": child["id"], "speakers_reclassified": speakers},
                                text=f"Sustained separation produced the recorded variety {child['name']}, with {speakers:,} speakers."))
        # Empty strata are retired; IDs are never reused. No cross-identity forced merging.
        keep = [i for i, c in enumerate(cohorts) if c.sum() > 0]
        result.arrays["strata"] = np.array([rows[i] for i in keep], dtype=np.int64).reshape(-1, 6)
        result.arrays["cohorts"] = np.array([cohorts[i] for i in keep], dtype=np.int64).reshape(-1, 2, 18)
        result.arrays["bilingual"] = np.array([bilingual[i] for i in keep], dtype=np.float64)
        result.arrays["migration_credit"] = np.array([migration_credit[i] for i in keep], dtype=np.float64)
        result.ancestry = {str(int(rows[i][0])): result.ancestry[str(int(rows[i][0]))] for i in keep}
        pop = result.population(self.world.size)
        # A province may gain residents after its harvest was calculated. Do not
        # turn those arrivals or newborns into unsupported city residents.
        result.arrays["urban"] = np.minimum(result.arrays["urban"],
                                           np.asarray(econ.ledger["urban_food_support"])/np.maximum(pop, 1))
        # Resolve loss of a complement through the same commit, retaining knowledge.
        for cap in CAPABILITIES:
            flag = 1 << next(i for i, c in enumerate(CAPABILITIES) if c.name == cap.name)
            for pid in np.flatnonzero(has(result.arrays["adopted"], cap.name)):
                okay, missing = feasible(result, self.world, int(pid), cap.name)
                if not okay:
                    result.arrays["adopted"][pid] &= ~flag
                    events.append(Event("Abandonment", "commit.operational-complements", [f"province:{pid}"],
                                        {"capability": cap.name, "missing": missing}, {"adopted_removed": cap.name},
                                        text=f"{self.world.provinces[pid]['name']} suspended {cap.name.replace('_', ' ')} after losing an operational complement."))
        for pid in np.flatnonzero(pop > 40):
            sid = str(100000+int(pid))
            if sid not in result.settlements:
                result.settlements[sid] = {"id": int(sid), "province": int(pid), "name": self.world.provinces[pid]["name"],
                                           "founded": ctx.year, "city_founded": None, "hinterland": [int(pid)]}
                events.append(Event("SettlementFounded", "settlement.viable-arrival", [f"province:{pid}", f"settlement:{sid}"],
                                    {"population": int(pop[pid])}, {"settlement_created": int(sid)},
                                    text=f"A lasting settlement was recorded at {self.world.provinces[pid]['name']}."))
            settlement = result.settlements[sid]
            city_population = int(pop[pid]*result.arrays["urban"][pid])
            previous_city = int(ctx.population[pid]*state.arrays["urban"][pid])
            if (city_population >= CITY_MIN_POPULATION and settlement["city_founded"] is None and
                    result.arrays["urban_surplus_years"][pid] >= self.manifest["parameters"]["city_surplus_years"] and
                    has(state.arrays["adopted"][pid], "agriculture") and state.arrays["control"][pid] >= 0):
                settlement = settlement.copy()
                result.settlements[sid] = settlement
                settlement["city_founded"] = ctx.year
                settlement["hinterland"] = sorted({int(pid)} | {t["from"] for t in econ.trades if t["to"] == int(pid)})
                events.append(Event("CityGrowth", "settlement.durable-surplus", [f"province:{pid}", f"settlement:{sid}"],
                                    {"net_food_per_resident": float(econ.ledger["food_renewable"][pid]/max(ctx.population[pid], 1)),
                                     "supported_urban_residents": float(econ.ledger["urban_food_support"][pid]),
                                     "surplus_years": int(result.arrays["urban_surplus_years"][pid]),
                                     "cultivated_ha": float(state.arrays["cultivated_ha"][pid]),
                                     "catchment_km": float(econ.ledger["food_catchment_km"][pid]),
                                     "roads": float(state.arrays["roads"][pid])},
                                    {"city_population_before": previous_city, "city_population_after": city_population},
                                    text=f"{settlement['name']} became a city with {city_population:,} urban residents."))
        for key, polity in result.polities.items():
            if polity["dissolved"] is None and not np.any(result.arrays["control"] == int(key)):
                polity["dissolved"] = ctx.year
                successors = sorted(set(int(v) for v in result.arrays["control"][state.arrays["control"] == int(key)] if v >= 0 and v != int(key)))
                polity["successors"] = successors
                for successor in successors:
                    if str(successor) in result.polities:
                        result.polities[str(successor)]["predecessors"] = sorted(set(result.polities[str(successor)]["predecessors"]+[int(key)]))
                events.append(Event("PolityDissolved", "politics.no-effective-territory", [f"polity:{key}"],
                                    {"effective_provinces": 0}, {"dissolved": ctx.year, "successors": successors},
                                    text=f"{polity['name']} lost its remaining effective territory."))
        for name, array in result.arrays.items():
            if array.dtype.kind == "f":
                result.arrays[name] = np.round(np.maximum(0, array), 6)
        for polity in result.polities.values():
            polity["treasury"] = round(max(0., polity["treasury"]), 6)
        ledger = econ.ledger
        for resource in ("food", "timber", "ore", "fossil"):
            ledger[resource+"_close"] = result.arrays[resource].tolist()
        ledger["treasury"] = political.treasury_ledger
        for entry in ledger["treasury"]:
            entry["close"] = result.polities[str(entry["polity"])]["treasury"]
        ledger.update({"year": ctx.year, "population_open": ctx.population.tolist(), "population_close": pop.tolist(),
                       "births": _province_sum(state.arrays["strata"], demo.births, self.world.size).tolist(),
                       "deaths": {cause: _province_sum(state.arrays["strata"], counts.sum(axis=(1, 2)), self.world.size).tolist()
                                  for cause, counts in demo.deaths.items()},
                       "immigration": imports.tolist(), "emigration": exports.tolist(), "flows": flow_ledger,
                       "diagnostics": {"rounding_tolerance": ROUNDING_TOLERANCE, "weather_floor": .12,
                                       "weather_ceiling": 1.35, "food_storage_years_cap": self.manifest["parameters"]["stock_years_cap"],
                                       "migration_survivor_cap": "one third of remaining origin cohort",
                                       "migration_batch": self.manifest["parameters"]["migration_batch"],
                                       "mortality_rate_cap": .95, "famine_rate_cap": .45,
                                       "fertility_food_floor": .1, "migration_rate_cap": .08,
                                       "city_min_population": CITY_MIN_POPULATION,
                                       "city_surplus_years": self.manifest["parameters"]["city_surplus_years"],
                                       "cultivation_ha_per_worker_year": self.manifest["parameters"]["cultivation_ha_per_worker_year"],
                                       "public_service_cap": .95, "bilingual_share_cap": .9,
                                       "urban_share_cap": .75, "military_priority": "before migration"}})
        ledger["deaths"]["violence"] = violence.tolist()
        validate_ledger(ledger)
        validate_state(result, self.world, previous=state)
        event_records = []
        # Causal inputs and shared-entity context have different contracts.
        for event in events:
            parents = set(event.parents)
            related = set()
            input_event = state.last_events.get("annual_state")
            if input_event and (not event.rule.startswith("environment.") or event.type == "Epidemic"):
                parents.add(input_event)
            for participant in event.participants:
                if participant in result.last_events:
                    related.add(result.last_events[participant])
                if event.type in ("Conquest", "Treaty") and participant.startswith("conflict:"):
                    trigger = result.last_events.get(participant+"|Battle") or result.last_events.get(participant+"|ConflictStarted")
                    if trigger:
                        parents.add(trigger)
                if event.type == "Migration" and event.conditions.get("shortage", 0) > 0:
                    trigger = result.last_events.get(participant+"|CropFailure")
                    if trigger and trigger.startswith(f"e{ctx.year:05d}-"):
                        parents.add(trigger)
                if event.type == "Displacement":
                    trigger = result.last_events.get(participant+"|Battle")
                    if trigger and trigger.startswith(f"e{ctx.year:05d}-"):
                        parents.add(trigger)
                if event.type == "Adoption" and participant.startswith("province:"):
                    trigger = state.last_events.get(participant+"|known:"+event.conditions["capability"])
                    if trigger:
                        parents.add(trigger)
                if event.type == "SoundChange" and participant.startswith("language:"):
                    for kind in ("Borrowing", "SoundChange", "LanguageSplit"):
                        trigger = state.last_events.get(participant+"|"+kind)
                        if trigger:
                            parents.add(trigger)
            event.parents = sorted(parents)
            event.participants = sorted(set(event.participants))
            payload = event.payload(ctx.year)
            payload["related_events"] = sorted(related-parents)
            payload["sequence"] = len(event_records)
            chain = hashlib.sha256(chain.encode()+canonical(payload)).hexdigest()
            payload["id"] = f"e{ctx.year:05d}-{len(event_records):04d}-{chain[:12]}"
            payload["hash"] = chain
            for participant in event.participants:
                result.last_events[participant] = payload["id"]
                result.last_events[participant+"|"+event.type] = payload["id"]
                if event.type in ("Discovery", "KnowledgeTransfer") and participant.startswith("province:"):
                    destination = event.deltas.get("destination", int(participant.split(":")[1]))
                    if participant == f"province:{destination}":
                        result.last_events[participant+"|known:"+event.conditions["capability"]] = payload["id"]
            event_records.append(payload)
        accounting = Event("YearCommitted", "commit.annual-accounting", [],
                           {"frozen_input_year": state.year, "ledger_hash": digest(ledger)},
                           {"population_before": int(ctx.population.sum()), "population_after": int(pop.sum()),
                            "births": int(sum(ledger["births"])), "deaths": {k: int(sum(v)) for k, v in ledger["deaths"].items()},
                            "migration": int(imports.sum()), "exact_state_patch": f"commits:{ctx.year}",
                            "annual_ledger": f"commits:{ctx.year}"},
                           text=f"Annual accounting recorded {int(sum(ledger['births'])):,} births and {sum(sum(v) for v in ledger['deaths'].values()):,} deaths.")
        payload = accounting.payload(ctx.year)
        payload["related_events"] = []
        if state.last_events.get("annual_state"):
            payload["parents"] = [state.last_events["annual_state"]]
        payload["sequence"] = len(event_records)
        chain = hashlib.sha256(chain.encode()+canonical(payload)).hexdigest()
        payload["id"], payload["hash"] = f"e{ctx.year:05d}-{len(event_records):04d}-{chain[:12]}", chain
        event_records.append(payload)
        result.last_events["annual_state"] = payload["id"]
        return result, event_records, ledger, chain


def validate_ledger(ledger: dict) -> dict:
    arr = lambda k: np.asarray(ledger[k], dtype=np.float64)
    deaths = sum((np.array(v, dtype=np.int64) for v in ledger["deaths"].values()), start=np.zeros(len(ledger["births"]), dtype=np.int64))
    expected = np.array(ledger["population_open"])+np.array(ledger["births"])-deaths+np.array(ledger["immigration"])-np.array(ledger["emigration"])
    if not np.array_equal(expected, ledger["population_close"]) or sum(ledger["immigration"]) != sum(ledger["emigration"]):
        raise SimError("FAILED_INVARIANT", "Population or migration does not balance.")
    balances = {"food": arr("food_open")+arr("food_produced")+arr("food_imports")-arr("food_exports")-arr("food_seed")-
                arr("food_spoilage")-arr("food_consumed")-arr("food_waste")-arr("food_close"),
                "timber": arr("timber_open")+arr("timber_regrowth")-arr("timber_used")-arr("timber_close"),
                "ore": arr("ore_open")-arr("ore_used")-arr("ore_close"),
                "fossil": arr("fossil_open")-arr("fossil_used")-arr("fossil_close"),
                "energy": arr("energy_produced")-arr("energy_used")-arr("energy_spilled")}
    for name, balance in balances.items():
        if not np.all(np.isfinite(balance)) or np.max(abs(balance), initial=0) > ROUNDING_TOLERANCE:
            raise SimError("FAILED_INVARIANT", f"{name.capitalize()} ledger does not balance.")
    if "cultivated_ha_open" in ledger:
        opened, closed = arr("cultivated_ha_open"), arr("cultivated_ha_close")
        cleared = arr("cultivated_ha_cleared")
        if (np.any(closed < 0) or np.any(cleared < 0) or
                np.any(closed > opened+cleared+ROUNDING_TOLERANCE)):
            raise SimError("FAILED_INVARIANT", "Cultivation exceeds accounted land clearance.")
        if "cultivated_ha_lost" in ledger:
            if np.any(arr("cultivated_ha_lost") < 0) or np.max(abs(opened+cleared-arr("cultivated_ha_lost")-closed), initial=0) > ROUNDING_TOLERANCE:
                raise SimError("FAILED_INVARIANT", "Cultivated land does not balance.")
    if abs(sum(ledger["food_imports"])-sum(ledger["food_exports"])) > ROUNDING_TOLERANCE*len(expected):
        raise SimError("FAILED_INVARIANT", "Trade does not conserve food.")
    if "crop_food_imports" in ledger:
        if (abs(sum(ledger["crop_food_imports"])-sum(ledger["crop_food_exports"])) > ROUNDING_TOLERANCE*len(expected) or
                np.any(arr("crop_food_imports") > arr("food_imports")+ROUNDING_TOLERANCE) or
                np.any(arr("crop_food_exports") > arr("food_exports")+ROUNDING_TOLERANCE)):
            raise SimError("FAILED_INVARIANT", "City staple shipments exceed accounted food trade.")
    for entry in ledger["treasury"]:
        error = entry["open"]+entry["taxes"]-entry["public_spending"]-entry["campaign_spending"]-entry["close"]
        if abs(error) > ROUNDING_TOLERANCE:
            raise SimError("FAILED_INVARIANT", "Treasury does not balance.")
    return {"population": "exact", "migration": "exact", "stock_max_error": {k: float(np.max(abs(v), initial=0)) for k, v in balances.items()},
            "treasuries": len(ledger["treasury"])}


def validate_state(state: State, world: World, previous: State | None = None) -> dict:
    rows, cohorts = state.arrays["strata"], state.arrays["cohorts"]
    if rows.shape != (len(cohorts), 6) or cohorts.shape[1:] != (2, 18):
        raise SimError("FAILED_INVARIANT", "Invalid cohort/stratum shape.")
    if (np.any(cohorts < 0) or len(set(rows[:, 0].tolist())) != len(rows) or
            np.any(rows[:, 1] < 0) or np.any(rows[:, 1] >= world.size)):
        raise SimError("FAILED_INVARIANT", "Invalid population stratum.")
    for name, array in state.arrays.items():
        if not np.all(np.isfinite(array)) or (name != "control" and np.any(array < 0)):
            raise SimError("FAILED_INVARIANT", f"Invalid or negative {name}.")
    if "cultivated_ha" in state.arrays:
        arable = np.array([p["area_km2"]*p["arable_share"]*100 for p in world.provinces])
        if np.any(state.arrays["cultivated_ha"] > arable+ROUNDING_TOLERANCE):
            raise SimError("FAILED_INVARIANT", "Cultivation exceeds arable land.")
    for column, catalog in ((2, state.languages), (3, state.communities), (4, state.beliefs)):
        if not np.all(np.isin(rows[:, column], np.fromiter((int(k) for k in catalog), dtype=np.int64))):
            raise SimError("FAILED_INVARIANT", "Stratum refers to a missing identity.")
    for sid, descent in state.ancestry.items():
        if previous is not None and previous.ancestry.get(sid) is descent:
            continue
        if any(v < 0 for v in descent.values()) or abs(sum(descent.values())-1) > 1e-6:
            raise SimError("FAILED_INVARIANT", "Descent shares do not sum to one.")
    for language in state.languages.values():
        if previous is not None and previous.languages.get(str(language["id"])) is language:
            continue
        for parent in language["parents"]:
            if str(parent) not in state.languages or state.languages[str(parent)]["founded"] >= language["founded"]:
                raise SimError("FAILED_INVARIANT", "Language lineage does not point backward in time.")
    for controller in set(state.arrays["control"].tolist())-{-1}:
        if str(controller) not in state.polities:
            raise SimError("FAILED_INVARIANT", "Unknown effective controller.")
    if any(p["treasury"] < 0 for p in state.polities.values()):
        raise SimError("FAILED_INVARIANT", "Negative treasury.")
    return {"strata": len(rows), "population": int(cohorts.sum()), "languages": len(state.languages), "year": state.year}
