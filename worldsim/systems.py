"""Annual proposal systems. All state inputs are frozen; only the engine commits."""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import math

import numpy as np

from .config import CITY_MIN_POPULATION, FERTILITY_SHAPE, MORTALITY_RATES, RandomStreams, probability
from .linguistics import MEANINGS, SOUND_RULES, adapt_loan, sound_change
from .model import AGE_BANDS, Event, State, World
from .technology import CAPABILITIES, bit, capacity, farming_productivity, feasible, has


@dataclass
class Context:
    world: World
    manifest: dict
    rng: RandomStreams
    population: np.ndarray
    capacity: np.ndarray
    source: np.ndarray
    target: np.ndarray
    cost: np.ndarray
    contact: np.ndarray
    year: int


def context(state: State, world: World, manifest: dict, rng: RandomStreams) -> Context:
    source = np.array([e["a"] for e in world.edges], dtype=np.int64)
    target = np.array([e["b"] for e in world.edges], dtype=np.int64)
    cost = np.array([e["days"]/(1-e["winter_fraction"]) for e in world.edges])*manifest["parameters"]["travel_cost"]
    roads = (state.arrays["roads"][source]+state.arrays["roads"][target])/2
    cost /= (1+roads*.8)
    rail = has(state.arrays["adopted"][source], "rail") & has(state.arrays["adopted"][target], "rail")
    cost[rail] *= .20
    sea = np.array([e["mode"] == "sea" for e in world.edges])
    navigable = has(state.arrays["adopted"][source], "boats") | has(state.arrays["adopted"][target], "boats")
    navigation = has(state.arrays["adopted"][source], "navigation") | has(state.arrays["adopted"][target], "navigation")
    cost[sea & navigation] *= .5
    cost[sea & ~navigable] = np.inf
    # Political borders have a cost, never an ethnicity-based capability modifier.
    borders = (state.arrays["control"][source] != state.arrays["control"][target]) & (state.arrays["control"][source] >= 0)
    cost[borders] *= 1.15
    for intervention in manifest["interventions"]:
        if state.year+1 >= intervention["year"] and intervention["kind"] == "travel_cost":
            mask = (source == intervention["province"]) | (target == intervention["province"])
            cost[mask] *= intervention["factor"]
    contact = np.exp(-cost/55)
    return Context(world, manifest, rng, state.population(world.size), capacity(state, world)*manifest["parameters"]["food_yield"],
                   source, target, cost, contact, state.year+1)


@dataclass
class EnvironmentProposal:
    weather: np.ndarray
    epidemic: np.ndarray
    events: list[Event]


def environment(state: State, ctx: Context) -> EnvironmentProposal:
    params, year = ctx.manifest["parameters"], ctx.year
    zones = np.array([int((p["latitude"]+68)//25)*8+int((p["longitude"]+180)//45) for p in ctx.world.provinces])
    regional = ctx.rng.draws("weather-zone", zones, year)
    local = ctx.rng.draws("weather-local", np.arange(ctx.world.size), year)
    weather = 1+(regional-.5)*.20+(local-.5)*.08
    drought_draw = ctx.rng.draws("drought", zones, year)
    drought = drought_draw < probability(params["drought_hazard"])
    severity = np.full(ctx.world.size, params["drought_severity"])
    for intervention in ctx.manifest["interventions"]:
        if intervention["kind"] == "drought_severity" and year >= intervention["year"]:
            severity[intervention["province"]] *= intervention["factor"]
    weather -= drought*severity
    # Floods are correlated by drainage basin, with an agricultural benefit in mild years.
    basins = np.array([p["basin"] for p in ctx.world.provinces])
    flood_draw = ctx.rng.draws("flood", basins, year)
    floods = flood_draw < .006
    weather -= floods*.22
    weather += has(state.arrays["adopted"], "irrigation")*.05
    weather = np.clip(weather, .12, 1.35)
    density = ctx.population/np.array([p["area_km2"] for p in ctx.world.provinces])
    contact_volume = np.bincount(ctx.source, weights=ctx.contact, minlength=ctx.world.size)+np.bincount(ctx.target, weights=ctx.contact, minlength=ctx.world.size)
    hazard = params["epidemic_hazard"]*(1+state.arrays["urban"]*5+density*.05+contact_volume*.3)
    disease_draw = ctx.rng.draws("epidemic", np.arange(ctx.world.size), year)
    epidemic = (disease_draw < probability(hazard))*(.012+.035*state.arrays["urban"])*(1-state.arrays["sanitation"]*.6)
    events = []
    for zone in sorted(set(zones[drought & (ctx.population > 0)].tolist())):
        ids = np.flatnonzero((zones == zone) & drought & (ctx.population > 0)).tolist()
        events.append(Event("CropFailure", "environment.drought", [f"province:{i}" for i in ids],
                            {"weather_zone": zone, "hazard": params["drought_hazard"], "severity": float(np.mean(severity[ids]))},
                            {"harvest_multipliers": {str(i): round(float(weather[i]), 6) for i in ids}},
                            float(drought_draw[ids[0]]), text=f"A drought reduced harvest conditions in {len(ids)} regions."))
    for pid in np.flatnonzero(floods & (ctx.population > 0)):
        events.append(Event("Flood", "environment.flood", [f"province:{pid}"],
                            {"basin": int(basins[pid]), "hazard": -math.log(1-.006)},
                            {"harvest_multiplier": float(weather[pid])}, float(flood_draw[pid]),
                            text=f"Flooding reduced the harvest in {ctx.world.provinces[pid]['name']}."))
    for pid in np.flatnonzero((epidemic > 0) & (ctx.population > 0)):
        events.append(Event("Epidemic", "environment.epidemic", [f"province:{pid}"],
                            {"hazard": float(hazard[pid]), "density_per_km2": float(density[pid]),
                             "urban_share": float(state.arrays["urban"][pid])},
                            {"extra_mortality_rate": float(epidemic[pid])}, float(disease_draw[pid]),
                            text=f"A disease shock exposed residents of {ctx.world.provinces[pid]['name']}."))
    return EnvironmentProposal(weather, epidemic, events)


@dataclass
class EconomyProposal:
    arrays: dict[str, np.ndarray]
    production: np.ndarray
    consumption: np.ndarray
    shortage: np.ndarray
    income: np.ndarray
    ledger: dict
    trades: list[dict]


def economy(state: State, ctx: Context, env: EnvironmentProposal) -> EconomyProposal:
    a, pop, params = state.arrays, ctx.population, ctx.manifest["parameters"]
    adopted = a["adopted"]
    agriculture, industry = has(adopted, "agriculture"), has(adopted, "industry")
    forest_capacity = np.array([p["resources"]["timber"] for p in ctx.world.provinces])
    regen = np.maximum(0, (forest_capacity-a["timber"])*.012)
    timber_use = np.minimum(a["timber"]+regen, pop*(.018+industry*.03))
    fossil_use = np.minimum(a["fossil"], pop*.008*has(adopted, "steam"))
    natural_energy = pop*(.05*has(adopted, "waterpower")+.12*has(adopted, "renewables"))
    energy = timber_use+fossil_use*4+natural_energy
    energy_need = pop*(.016+industry*.035)
    energy_use = np.minimum(energy, energy_need)
    energy_ratio = np.minimum(1, energy/np.maximum(energy_need, 1))
    ore_use = np.minimum(a["ore"], pop*.002*(has(adopted, "metallurgy")+industry*3)*energy_ratio)
    ore_ratio = np.minimum(1., a["ore"]/np.maximum(pop*.008, 1))
    industrial_labor = np.minimum(1., a["urban"]/.20)
    industrial_scale = industry*energy_ratio*ore_ratio*industrial_labor
    deployed = np.zeros(ctx.world.size)
    for war in state.conflicts.values():
        if war["ended"] is None and a["control"][war["source"]] == war["attacker"]:
            deployed[war["source"]] += min(.02, math.exp(-float(ctx.cost[war["route"]])/300)*.01)
    deployed = np.minimum(.15, deployed)
    adults = np.bincount(a["strata"][:, 1], weights=a["cohorts"][:, :, 3:12].sum(axis=(1, 2)), minlength=ctx.world.size)
    workers = adults*.85*(1-a["urban"])*(1-deployed)
    hectares_per_worker, crop_yield = farming_productivity(adopted, industrial_scale)
    land_ha = np.array([p["area_km2"]*100 for p in ctx.world.provinces])
    arable_ha = np.array([p["area_km2"]*p["arable_share"]*100 for p in ctx.world.provinces])
    cultivated = np.minimum(a["cultivated_ha"], arable_ha)*agriculture
    cultivated_target = np.minimum(arable_ha, workers*hectares_per_worker)*agriculture
    cleared = np.minimum(np.maximum(0., cultivated_target-cultivated), workers*params["cultivation_ha_per_worker_year"])
    unmaintained = np.maximum(0., cultivated-cultivated_target)
    land_lost = a["cultivated_ha"]-cultivated+unmaintained*.001
    # Newly cleared plots bear food next year. Clearance uses up to 5% of labor.
    clearing_labor = np.minimum(workers*.05, cleared/.2)
    food_workers = np.maximum(0., workers-clearing_labor)
    farm_workers = np.minimum(food_workers, cultivated/hectares_per_worker)
    crop = farm_workers*hectares_per_worker*crop_yield
    forage_capacity = np.array([p["forager_capacity"] for p in ctx.world.provinces])
    forage_capacity *= np.maximum(0., 1-cultivated/land_ha)*(1+has(adopted, "herding")*.3)
    forage = np.minimum(forage_capacity, (food_workers-farm_workers)*2.9*(1+has(adopted, "herding")*.1))
    harvest_factor = env.weather*params["food_yield"]*np.maximum(.7, 1-a["pollution"]*.08)
    crop *= harvest_factor
    raw = crop+forage*harvest_factor
    seed = crop*.045
    spoilage = a["food"]*.08+raw*.025
    available = np.maximum(0, a["food"]+raw-seed-spoilage)
    imports, exports = np.zeros(ctx.world.size), np.zeros(ctx.world.size)
    producer_dependents = farm_workers*(pop*(1-a["urban"])/np.maximum(food_workers, 1))
    crop_budget = np.maximum(0., crop*.93-producer_dependents)
    crop_imports, crop_exports = np.zeros(ctx.world.size), np.zeros(ctx.world.size)
    trades = []
    food_needs, army_supply = pop.astype(float).copy(), []
    for war in state.conflicts.values():
        if war["ended"] is not None:
            continue
        source, target = war["source"], war["objective"]
        if (a["control"][source] != war["attacker"] or a["control"][target] != war["defender"] or
                not math.isfinite(ctx.cost[war["route"]]) or ctx.cost[war["route"]] > 240):
            continue
        amount = min(available[source]*.10, pop[source]*.01*math.exp(-float(ctx.cost[war["route"]])/300))
        available[source] -= amount
        available[target] += amount
        exports[source] += amount
        imports[target] += amount
        food_needs[source] -= amount
        food_needs[target] += amount
        army_supply.append({"conflict": war["id"], "from": source, "to": target, "food": amount, "route": war["route"]})
    for index, (origin, destination) in enumerate(zip(ctx.source, ctx.target)):
        if ctx.contact[index] < .035:
            continue
        oi, di = int(origin), int(destination)
        spare_o, spare_d = available[oi]-pop[oi]*1.2, available[di]-pop[di]*1.2
        need_o, need_d = pop[oi]-available[oi], pop[di]-available[di]
        if spare_o > 0 and need_d > 0:
            donor, receiver, surplus, need = oi, di, spare_o, need_d
        elif spare_d > 0 and need_o > 0:
            donor, receiver, surplus, need = di, oi, spare_d, need_o
        else:
            continue
        amount = min(surplus, need, max(1., pop[donor]*.16)*float(ctx.contact[index]))
        available[donor] -= amount
        available[receiver] += amount
        exports[donor] += amount
        imports[receiver] += amount
        # Earmark only accounted crop surplus for the city's imported staple
        # budget. Ordinary forage/reserve shipments still prevent local hunger.
        crop_amount = min(amount, max(0., crop_budget[donor]-crop_exports[donor]))
        crop_imports[receiver] += crop_amount
        crop_exports[donor] += crop_amount
        trades.append({"from": donor, "to": receiver, "food": round(amount, 6),
                       "crop_food": round(crop_amount, 6), "route": index, "days": float(ctx.cost[index])})
    consumed = np.minimum(available, food_needs)
    shortage = np.maximum(0, 1-consumed/np.maximum(food_needs, 1))
    remainder = available-consumed
    # Foraged foods cannot be treated as multi-year grain inventories.
    reserve_years = np.where(agriculture, params["stock_years_cap"], np.minimum(.5, params["stock_years_cap"]))
    stock_cap = np.maximum(pop, 1)*reserve_years
    waste = np.maximum(0, remainder-stock_cap)
    food = remainder-waste
    stocks = {"food": food, "timber": a["timber"]+regen-timber_use,
              "ore": a["ore"]-ore_use, "fossil": a["fossil"]-fossil_use,
              "pollution": np.maximum(0, a["pollution"]*.995+fossil_use/np.maximum(pop, 1)*.3),
              "cultivated_ha": np.minimum(arable_ha, a["cultivated_ha"]-land_lost+cleared)}
    # Taxable output is an abstract fiscal value, not an extra withdrawal of food.
    income = (raw*.07+ore_use*5+industrial_scale*pop*.04)*(a["control"] >= 0)
    income *= (.2+a["roads"]*.2+has(adopted, "writing")*.15)
    # Cities can draw only a transferable crop surplus within local transport
    # reach and actual imports. Provincial harvests are not a single city.
    water_transport = has(adopted, "boats") & np.array([p["coast"] or p["river_flow"] >= 400 for p in ctx.world.provinces])
    catchment_km = 10.+water_transport*10.+has(adopted, "irrigation")*5.+a["roads"]*25.+has(adopted, "rail")*100.
    catchment_ha = np.minimum(arable_ha, np.pi*catchment_km**2*np.array([p["arable_share"] for p in ctx.world.provinces])*100)
    transferable_crop = np.maximum(0., crop_budget-crop_exports)
    crop_support = transferable_crop*np.minimum(1., catchment_ha/np.maximum(cultivated, 1))
    renewable_food = raw-seed-raw*.025+imports-exports
    rural_needs = np.maximum(0., food_needs-pop*a["urban"])
    urban_support = np.minimum(crop_support+crop_imports, np.maximum(0., renewable_food-rural_needs))
    ledger = {"food_open": a["food"].tolist(), "food_produced": raw.tolist(), "food_seed": seed.tolist(),
              "food_spoilage": spoilage.tolist(), "food_imports": imports.tolist(), "food_exports": exports.tolist(),
              "food_consumed": consumed.tolist(), "food_waste": waste.tolist(), "food_close": food.tolist(),
              "timber_open": a["timber"].tolist(), "timber_regrowth": regen.tolist(), "timber_used": timber_use.tolist(),
              "timber_close": stocks["timber"].tolist(), "ore_open": a["ore"].tolist(), "ore_used": ore_use.tolist(),
              "ore_close": stocks["ore"].tolist(), "fossil_open": a["fossil"].tolist(), "fossil_used": fossil_use.tolist(),
              "fossil_close": stocks["fossil"].tolist(), "energy_produced": energy.tolist(),
              "energy_used": energy_use.tolist(), "energy_spilled": (energy-energy_use).tolist(),
              "trade": trades, "army_supply": army_supply, "industrial_scale": industrial_scale.tolist(), "treasury": [],
              "industrial_labor_ratio": industrial_labor.tolist(),
              "food_workers": food_workers.tolist(), "cultivated_ha_open": a["cultivated_ha"].tolist(),
              "cultivated_ha_cleared": cleared.tolist(), "cultivated_ha_close": stocks["cultivated_ha"].tolist(),
              "cultivated_ha_lost": land_lost.tolist(),
              "food_renewable": renewable_food.tolist(), "urban_food_support": urban_support.tolist(),
              "crop_food_imports": crop_imports.tolist(), "crop_food_exports": crop_exports.tolist(),
              "food_catchment_km": catchment_km.tolist()}
    return EconomyProposal(stocks, raw, consumed, shortage, income, ledger, trades)


@dataclass
class DemographyProposal:
    cohorts: np.ndarray
    births: np.ndarray
    deaths: dict[str, np.ndarray]


def _round(expected: np.ndarray, draws: np.ndarray) -> np.ndarray:
    return np.floor(expected+draws).astype(np.int64)


def demography(state: State, ctx: Context, env: EnvironmentProposal, econ: EconomyProposal) -> DemographyProposal:
    rows, old = state.arrays["strata"], state.arrays["cohorts"]
    province = rows[:, 1]
    ids = rows[:, 0, None, None]*100+np.arange(2*AGE_BANDS).reshape(1, 2, AGE_BANDS)
    # Approximate annual progression within five-year bands; terminal band remains open.
    age_out = _round(old*.2, ctx.rng.draws("ageing", ids, ctx.year))
    age_out[:, :, -1] = 0
    aged = old-age_out
    aged[:, :, 1:] += age_out[:, :, :-1]
    mortality = np.array(MORTALITY_RATES)
    health = 1-state.arrays["sanitation"][province]*.35-has(state.arrays["adopted"][province], "medicine")*.22
    urban_cost = 1+state.arrays["urban"][province]*(1-state.arrays["sanitation"][province])*.25
    base = np.clip(mortality[None, None, :]*health[:, None, None]*urban_cost[:, None, None]*ctx.manifest["parameters"]["mortality"], 0, .95)
    baseline = np.minimum(aged, _round(aged*base, ctx.rng.draws("mortality", ids, ctx.year)))
    survivors = aged-baseline
    famine_rate = np.clip(econ.shortage[province]*.22, 0, .45)
    famine = np.minimum(survivors, _round(survivors*famine_rate[:, None, None], ctx.rng.draws("famine", ids, ctx.year)))
    survivors -= famine
    epidemic = np.minimum(survivors, _round(survivors*env.epidemic[province, None, None], ctx.rng.draws("disease-deaths", ids, ctx.year)))
    survivors -= epidemic
    fertility = np.zeros(AGE_BANDS)
    # Matched to the survival schedule: slow replacement rather than the old
    # 1.8% annual intrinsic growth. Schooling/urban fertility transition requires
    # modern practical capabilities; a granary alone does not cause it.
    fertility[3:9] = np.array(FERTILITY_SHAPE)*(ctx.manifest["parameters"]["lifetime_births"]/5.65)
    modern = has(state.arrays["adopted"][province], "medicine") | has(state.arrays["adopted"][province], "industry")
    transition = 1-(state.arrays["schooling"][province]*.45+state.arrays["urban"][province]*.25)*modern
    food_factor = np.maximum(.1, 1-econ.shortage[province])
    births = _round((survivors[:, 0, :]*fertility).sum(axis=1)*transition*food_factor*ctx.manifest["parameters"]["fertility"],
                    ctx.rng.draws("births", rows[:, 0], ctx.year))
    females = _round(births*.488, ctx.rng.draws("birth-sex", rows[:, 0], ctx.year))
    survivors[:, 0, 0] += females
    survivors[:, 1, 0] += births-females
    return DemographyProposal(survivors, births, {"ordinary": baseline, "famine": famine, "epidemic": epidemic})


@dataclass
class Move:
    row: int
    destination: int
    count: int
    type: str = "Migration"
    target_language: int | None = None
    conditions: dict = field(default_factory=dict)
    draw: float | None = None


@dataclass
class MigrationProposal:
    moves: list[Move]
    credit: np.ndarray


def migration(state: State, ctx: Context, econ: EconomyProposal) -> MigrationProposal:
    best, best_score = np.full(ctx.world.size, -1, dtype=np.int64), np.full(ctx.world.size, -np.inf)
    suitability = np.log1p(ctx.capacity/(ctx.population+100))+.3*np.array([p["arable_share"] for p in ctx.world.provinces])
    for i, (a, b) in enumerate(zip(ctx.source, ctx.target)):
        if not math.isfinite(ctx.cost[i]) or ctx.cost[i] > 420:
            continue
        for origin, destination in ((int(a), int(b)), (int(b), int(a))):
            score = suitability[destination]-suitability[origin]-ctx.cost[i]/150-econ.shortage[destination]*3
            if score > best_score[origin]:
                best[origin], best_score[origin] = destination, score
    moves = []
    credit = state.arrays["migration_credit"].copy()
    for row, metadata in enumerate(state.arrays["strata"]):
        pid, sid = int(metadata[1]), int(metadata[0])
        if best[pid] < 0 or state.arrays["cohorts"][row].sum() < 30:
            continue
        pressure = max(0., ctx.population[pid]/max(ctx.capacity[pid], 1)-.65)
        rate = min(.08, .001+econ.shortage[pid]*.055+pressure*.025)
        if best_score[pid] < -.8 and econ.shortage[pid] < .12:
            continue
        draw = ctx.rng.draw("migration", sid, ctx.year)
        # Retain annual expected departures until a viable cohort can move.
        # Credits are proposals, never additional residents; shocks bypass batching.
        credit[row] = min(float(state.arrays["cohorts"][row].sum())/3, credit[row]+float(state.arrays["cohorts"][row].sum())*rate)
        count = int(credit[row]+draw)
        if count >= ctx.manifest["parameters"]["migration_batch"] or (econ.shortage[pid] > .22 and count > 0):
            credit[row] = max(0., credit[row]-count)
            moves.append(Move(row, int(best[pid]), count, conditions={"shortage": float(econ.shortage[pid]),
                              "pressure": pressure, "destination_score": float(best_score[pid]), "annual_rate": rate,
                              "batch_threshold": ctx.manifest["parameters"]["migration_batch"]}, draw=draw))
    return MigrationProposal(moves, credit)


@dataclass
class KnowledgeProposal:
    known: np.ndarray
    adopted: np.ndarray
    languages: dict[str, dict]
    splits: list[tuple[int, dict]]
    shifts: list[Move]
    divergence: np.ndarray
    bilingual: np.ndarray
    events: list[Event]


def knowledge(state: State, ctx: Context, econ: EconomyProposal) -> KnowledgeProposal:
    params, a = ctx.manifest["parameters"], state.arrays
    known, adopted = a["known"].copy(), a["adopted"].copy()
    events, languages, splits, shifts = [], {}, [], []
    ids = np.arange(ctx.world.size)
    surplus = np.clip(econ.production/np.maximum(ctx.population, 1)-.8, .1, 2.)
    for index, cap in enumerate(CAPABILITIES):
        flag = bit(cap.name)
        prerequisite_mask = sum(bit(p) for p in cap.prerequisites)
        prereqs_known = (a["known"] & prerequisite_mask) == prerequisite_mask
        hazard = params["discovery_hazard"]*surplus*(1+np.log1p(ctx.population)/8)*(1+a["schooling"]*2)
        draws = ctx.rng.draws(f"discovery-{cap.name}", ids, ctx.year)
        candidates = np.flatnonzero((ctx.population > 100) & prereqs_known & ((a["known"] & flag) == 0) & (draws < probability(hazard)))
        for pid in candidates:
            okay, _ = feasible(state, ctx.world, int(pid), cap.name, knowledge=True)
            if not okay:
                continue
            known[pid] |= flag
            events.append(Event("Discovery", "knowledge.experiment", [f"province:{pid}"],
                                {"capability": cap.name, "hazard": float(hazard[pid]), "prerequisites": list(cap.prerequisites)},
                                {"known_added": cap.name}, float(draws[pid]),
                                text=f"Experimenters in {ctx.world.provinces[pid]['name']} discovered {cap.name.replace('_', ' ')}."))
        adopt_draws = ctx.rng.draws(f"adoption-{cap.name}", ids, ctx.year)
        adopt_hazard = params["adoption_hazard"]*surplus
        candidates = np.flatnonzero((ctx.population > 100) & has(a["known"], cap.name) & ~has(a["adopted"], cap.name) &
                                    (adopt_draws < probability(adopt_hazard)))
        for pid in candidates:
            okay, _ = feasible(state, ctx.world, int(pid), cap.name)
            if not okay or a["food"][pid]/max(ctx.population[pid], 1) < cap.cost:
                continue
            adopted[pid] |= flag
            events.append(Event("Adoption", "knowledge.operational-use", [f"province:{pid}"],
                                {"capability": cap.name, "hazard": float(adopt_hazard[pid]), "resource": cap.resource,
                                 "surplus_years": float(a["food"][pid]/max(ctx.population[pid], 1)), "prerequisites": list(cap.prerequisites)},
                                {"adopted_added": cap.name}, float(adopt_draws[pid]),
                                text=f"{ctx.world.provinces[pid]['name']} put {cap.name.replace('_', ' ')} into practical use."))
        # Exhausted fuel/input access can end practical use while preserving know-how.
        if cap.resource in ("ore", "timber", "fossil"):
            for pid in np.flatnonzero(has(a["adopted"], cap.name) & (a[cap.resource] <= 0)):
                adopted[pid] &= ~flag
                events.append(Event("Abandonment", "knowledge.inputs-exhausted", [f"province:{pid}"],
                                    {"capability": cap.name, "resource": cap.resource}, {"adopted_removed": cap.name},
                                    text=f"{ctx.world.provinces[pid]['name']} suspended {cap.name.replace('_', ' ')} after losing an input."))
    # Use prior-year knowledge only: no chain of future discoveries in one tick.
    dominant = np.full(ctx.world.size, -1, dtype=np.int64)
    largest = np.zeros(ctx.world.size, dtype=np.int64)
    row_counts = a["cohorts"].sum(axis=(1, 2))
    for row, metadata in enumerate(a["strata"]):
        if row_counts[row] > largest[metadata[1]]:
            largest[metadata[1]], dominant[metadata[1]] = row_counts[row], metadata[2]
    contact_sum = np.zeros(ctx.world.size)
    changed_languages = set()
    for index, (source, target) in enumerate(zip(ctx.source, ctx.target)):
        source, target = int(source), int(target)
        volume = float(ctx.contact[index])
        contact_sum[source] += volume
        contact_sum[target] += volume
        if ctx.population[source] <= 0 or ctx.population[target] <= 0:
            continue
        for donor, recipient in ((source, target), (target, source)):
            transferable = int(a["known"][donor] & ~a["known"][recipient])
            draw = ctx.rng.draw("knowledge-contact", index, ctx.year, slot=recipient)
            if transferable and draw < probability(.035*volume):
                lowest = transferable & -transferable
                capname = CAPABILITIES[lowest.bit_length()-1].name
                if not known[recipient] & lowest:
                    known[recipient] |= lowest
                    events.append(Event("KnowledgeTransfer", "knowledge.route-contact", [f"province:{donor}", f"province:{recipient}"],
                                        {"capability": capname, "route": index, "contact": volume, "hazard": .035*volume},
                                        {"known_added": capname, "destination": recipient}, draw,
                                        text=f"Contact carried knowledge of {capname.replace('_', ' ')} to {ctx.world.provinces[recipient]['name']}."))
        donor_lid, recipient_lid = int(dominant[source]), int(dominant[target])
        draw = ctx.rng.draw("lexical-contact", index, ctx.year)
        if donor_lid >= 0 and recipient_lid >= 0 and donor_lid != recipient_lid and recipient_lid not in changed_languages and draw < probability(params["borrowing_hazard"]*volume):
            meaning = MEANINGS[int(ctx.rng.draw("loan-meaning", index, ctx.year)*len(MEANINGS))]
            donor, recipient = state.languages[str(donor_lid)], state.languages[str(recipient_lid)].copy()
            recipient["lexicon"] = recipient["lexicon"].copy()
            recipient["contact_sources"] = recipient["contact_sources"].copy()
            before = recipient["lexicon"][meaning]
            loan = copy.deepcopy(donor["lexicon"][meaning])
            loan["form"] = adapt_loan(loan["form"], recipient)
            loan["formation"] = "adapted loan"
            loan["history"] = before["history"]+[{"year": ctx.year, "form": loan["form"], "donor": donor_lid}]
            recipient["lexicon"][meaning] = loan
            recipient["contact_sources"].append({"year": ctx.year, "donor": donor_lid, "meaning": meaning, "route": index})
            languages[str(recipient_lid)] = recipient
            changed_languages.add(recipient_lid)
            events.append(Event("Borrowing", "language.route-loan", [f"language:{donor_lid}", f"language:{recipient_lid}", f"province:{target}"],
                                {"contact": volume, "route": index, "hazard": params["borrowing_hazard"]*volume, "meaning": meaning},
                                {"before": before["form"], "after": loan["form"], "root": loan["root"]}, draw,
                                text=f"{recipient['name']} borrowed its word for {meaning} through contact with {donor['name']}."))
    for lid, language in sorted(state.languages.items(), key=lambda item: int(item[0])):
        if int(lid) in changed_languages or int(lid) not in dominant:
            continue
        draw = ctx.rng.draw("sound-change", int(lid), ctx.year)
        if draw < probability(params["sound_change_hazard"]):
            rule = SOUND_RULES[int(ctx.rng.draw("sound-rule", int(lid), ctx.year)*len(SOUND_RULES))]
            new, changes = sound_change(language, rule, ctx.year)
            if changes:
                languages[lid] = new
                events.append(Event("SoundChange", "language.regular-sound-rule", [f"language:{lid}"],
                                    {"hazard": params["sound_change_hazard"], "rule": list(rule)},
                                    {"lexicon_changes": changes, "inventory": new["consonants"]+new["vowels"]}, draw,
                                    text=f"A regular sound change altered {len(changes)} recorded forms in {language['name']}."))
    divergence = np.maximum(0, a["divergence"]+np.where(contact_sum < .75, 1., -.35))
    # One bounded variety proposal per year, separated by centuries in each location.
    candidates = np.flatnonzero((divergence > 350) & (ctx.year-a["last_split"] > 600) & (ctx.population > 250))
    if candidates.size:
        pid = int(candidates[np.argmax(divergence[candidates])])
        parent = int(dominant[pid])
        if parent >= 0 and np.count_nonzero(dominant == parent) > 1:
            child = copy.deepcopy(state.languages[str(parent)])
            child["id"], child["parents"], child["founded"] = state.next_ids["language"], [parent], ctx.year
            child["name"] = child["name"]+f" {child['id']+1}"
            child["historical_names"] = [{"year": ctx.year, "name": child["name"], "reason": "sustained separation"}]
            splits.append((pid, child))
            divergence[pid] = 0
    # Writing has a separate lineage and does not replace the spoken variety.
    for pid in np.flatnonzero(has(adopted, "writing") & ~has(a["adopted"], "writing")):
        lid = str(dominant[pid])
        if lid != "-1":
            language = languages.get(lid, copy.deepcopy(state.languages[lid]))
            if not language["writing"]:
                language["writing"] = [{"id": f"script-{pid}", "founded": ctx.year, "type": "phonographic convention", "source_province": int(pid)}]
                language["usage_domains"] = sorted(set(language["usage_domains"]+["administration", "records"]))
                languages[lid] = language
    bilingual = np.clip(a["bilingual"]*.995+contact_sum[a["strata"][:, 1]]*.001+a["schooling"][a["strata"][:, 1]]*.002, 0, .9)
    for row, metadata in enumerate(a["strata"]):
        pid = int(metadata[1])
        controller = int(a["control"][pid])
        if controller < 0 or str(controller) not in state.polities:
            continue
        capital = state.polities[str(controller)]["capital"]
        official = int(dominant[capital])
        if official >= 0 and official != metadata[2] and a["schooling"][pid] > .08:
            rate = a["schooling"][pid]*bilingual[row]*.006
            draw = ctx.rng.draw("language-shift", int(metadata[0]), ctx.year)
            count = int(row_counts[row]*rate+draw)
            if count:
                shifts.append(Move(row, pid, count, "LanguageShift", official,
                                   {"schools": float(a["schooling"][pid]), "bilingual_share": float(bilingual[row]), "annual_rate": float(rate)}, draw))
    return KnowledgeProposal(known, adopted, languages, splits, shifts, divergence, bilingual, events)


@dataclass
class PoliticsProposal:
    polities: dict[str, dict]
    conflicts: dict[str, dict]
    control: np.ndarray
    casualties: np.ndarray
    public: dict[str, np.ndarray]
    treasury_ledger: list[dict]
    events: list[Event]
    next_polity: int
    next_conflict: int


def politics(state: State, ctx: Context, econ: EconomyProposal) -> PoliticsProposal:
    a, params = state.arrays, ctx.manifest["parameters"]
    polities, conflicts = copy.deepcopy(state.polities), copy.deepcopy(state.conflicts)
    control = a["control"].copy()
    casualties = np.zeros(ctx.world.size, dtype=np.int64)
    public = {k: a[k].copy()*.998 for k in ("roads", "sanitation", "schooling", "urban")}
    events, treasury_ledger = [], []
    next_polity, next_conflict = state.next_ids["polity"], state.next_ids["conflict"]
    for pid in np.flatnonzero((a["control"] < 0) & (ctx.population > 1200) & (econ.shortage < .05)):
        draw = ctx.rng.draw("state-formation", int(pid), ctx.year)
        hazard = params["state_formation_hazard"]*min(2., ctx.population[pid]/15000)*min(1., a["food"][pid]/max(ctx.population[pid], 1))
        if draw >= probability(hazard):
            continue
        government = ["council", "confederation", "kingdom", "republic", "tributary league"][int(ctx.rng.draw("government", int(pid), ctx.year)*5)]
        polity = {"id": next_polity, "name": ctx.world.provinces[pid]["name"]+" "+government,
                  "form": government, "capital": int(pid), "founded": ctx.year, "dissolved": None,
                  "treasury": 0., "legitimacy": .65, "administrative_reach": .25, "tax_capacity": .2,
                  "representation": ctx.rng.draw("representation", next_polity),
                  "accountability": ctx.rng.draw("accountability", next_polity),
                  "coercion": ctx.rng.draw("coercion", next_polity),
                  "succession": "assembly selection" if government in ("council", "republic", "confederation") else "negotiated inheritance",
                  "institutions": ["local adjudication", "shared defense", "common reserve"],
                  "claims": [int(pid)], "predecessors": [], "successors": [], "budget": {}, "last_income": 0.}
        polities[str(next_polity)], control[pid] = polity, next_polity
        events.append(Event("StateFormation", "politics.coordination", [f"province:{pid}", f"polity:{next_polity}"],
                            {"hazard": float(hazard), "population": int(ctx.population[pid]), "surplus_years": float(a["food"][pid]/max(ctx.population[pid], 1)), "form": government},
                            {"control_before": -1, "control_after": next_polity, "institutions": polity["institutions"]}, draw,
                            text=f"Communities around {ctx.world.provinces[pid]['name']} formed a {government}."))
        next_polity += 1
    for key, polity in sorted(polities.items(), key=lambda item: int(item[0])):
        pid = int(key)
        owned = np.flatnonzero(a["control"] == pid)
        if not owned.size:
            continue
        income = float(econ.income[owned].sum())
        opening = polity["treasury"]
        spent = min(opening+income, income*.85+opening*.012)
        budgets = {"defense": spent*.28, "roads": spent*.22, "schools": spent*.16,
                   "health": spent*.16, "elite_transfers": spent*.10, "adjudication": spent*.08}
        polity["treasury"] = opening+income-spent
        polity["budget"], polity["last_income"] = budgets, income
        polity["legitimacy"] = float(np.clip(polity["legitimacy"]+.0005-float(econ.shortage[owned].mean())*.04, .05, .98))
        polity["administrative_reach"] = float(np.clip(.2+np.mean(a["roads"][owned])*.45+np.mean(has(a["adopted"][owned], "writing"))*.25, .1, .95))
        amount = max(1., ctx.population[owned].sum())
        public["roads"][owned] += budgets["roads"]/amount*.025
        public["schooling"][owned] += budgets["schools"]/amount*.12*has(a["adopted"][owned], "education")
        public["sanitation"][owned] += budgets["health"]/amount*.15*has(a["adopted"][owned], "sanitation")
        treasury_ledger.append({"polity": pid, "open": opening, "taxes": income, "public_spending": spent,
                                "campaign_spending": 0., "close": polity["treasury"]})
    fiscal = {v["polity"]: v for v in treasury_ledger}
    # Integration and diplomacy use real routes and fiscal reach, including negotiated unions.
    for index, (source, target) in enumerate(zip(ctx.source, ctx.target)):
        source, target = int(source), int(target)
        if not math.isfinite(ctx.cost[index]) or ctx.cost[index] > 250:
            continue
        for core, frontier in ((source, target), (target, source)):
            controller = int(a["control"][core])
            if controller < 0 or a["control"][frontier] >= 0 or control[frontier] >= 0 or ctx.population[frontier] < 300:
                continue
            polity = polities[str(controller)]
            hazard = .015*float(ctx.contact[index])*polity["legitimacy"]*polity["administrative_reach"]
            draw = ctx.rng.draw("integration", index, ctx.year, slot=frontier)
            if draw < probability(hazard):
                control[frontier] = controller
                polity["claims"] = sorted(set(polity["claims"]+[frontier]))
                events.append(Event("Treaty", "politics.negotiated-integration", [f"province:{frontier}", f"polity:{controller}"],
                                    {"hazard": hazard, "route": index, "travel_days": float(ctx.cost[index]), "legitimacy": polity["legitimacy"]},
                                    {"control_before": -1, "control_after": controller, "obligation": "shared defense and public dues"}, draw,
                                    text=f"{ctx.world.provinces[frontier]['name']} joined {polity['name']} by agreement."))
        attacker, defender = int(a["control"][source]), int(a["control"][target])
        if attacker < 0 or defender < 0 or attacker == defender:
            continue
        existing = any(c["ended"] is None and {c["attacker"], c["defender"]} == {attacker, defender} for c in conflicts.values())
        if existing or polities[str(attacker)]["treasury"] < ctx.population[source]*.015 or a["food"][source] < ctx.population[source]*.20:
            continue
        hazard = params["war_hazard"]*float(ctx.contact[index])*(.5+polities[str(attacker)]["coercion"])
        draw = ctx.rng.draw("war-start", index, ctx.year)
        if draw < probability(hazard):
            cid = next_conflict
            next_conflict += 1
            conflicts[str(cid)] = {"id": cid, "attacker": attacker, "defender": defender, "objective": target,
                                   "source": source, "route": index, "started": ctx.year, "ended": None, "deaths": 0,
                                   "displacement": 0, "cost": 0., "phases": 0, "outcome": None}
            events.append(Event("ConflictStarted", "conflict.feasible-objective", [f"polity:{attacker}", f"polity:{defender}", f"conflict:{cid}"],
                                {"hazard": hazard, "objective": target, "route": index, "supply_food": float(a["food"][source])},
                                {"conflict_created": cid}, draw, text=f"{polities[str(attacker)]['name']} opened a border conflict over {ctx.world.provinces[target]['name']}."))
    # Existing wars only: newly proposed wars start campaigning next year.
    contested = {}
    for key, original in sorted(state.conflicts.items(), key=lambda item: int(item[0])):
        if original["ended"] is not None:
            continue
        war = conflicts[key]
        source, target, attacker, defender = war["source"], war["objective"], war["attacker"], war["defender"]
        supply = min(float(a["food"][source]), ctx.population[source]*.04)
        budget = ctx.population[source]*.02
        actual_budget = min(budget, polities[str(attacker)]["treasury"])
        travel = float(ctx.cost[war["route"]])
        if (not math.isfinite(travel) or travel > 240 or supply < ctx.population[source]*.015 or
                actual_budget < budget*.4 or a["control"][source] != attacker or a["control"][target] != defender):
            war["ended"], war["outcome"] = ctx.year, "negotiated exhaustion"
            events.append(Event("Treaty", "conflict.exhaustion", [f"conflict:{key}", f"polity:{attacker}", f"polity:{defender}"],
                                {"travel_days": travel if math.isfinite(travel) else None, "supply": supply, "budget": actual_budget},
                                {"ended": ctx.year, "territory_changed": False}, text="The belligerents ended an unsustainable campaign by settlement."))
            continue
        polities[str(attacker)]["treasury"] -= actual_budget
        if attacker in fiscal:
            fiscal[attacker]["campaign_spending"] += actual_budget
            fiscal[attacker]["close"] -= actual_budget
        draw = ctx.rng.draw("battle", int(key), ctx.year)
        attacker_force = ctx.population[source]*.025*min(1., supply/max(ctx.population[source]*.025, 1))
        defender_force = ctx.population[target]*.023*(1+ctx.world.provinces[target]["elevation_m"]/2500)
        chance = attacker_force/max(attacker_force+defender_force, 1)*math.exp(-travel/400)
        soldier_a = int(min(ctx.population[source]*.012, attacker_force*(.05+.12*(1-draw))))
        soldier_d = int(min(ctx.population[target]*.012, defender_force*(.04+.10*draw)))
        civilian = int(ctx.population[target]*.0015)
        casualties[source] += soldier_a
        casualties[target] += soldier_d+civilian
        war["deaths"] += soldier_a+soldier_d+civilian
        war["cost"] += actual_budget
        war["phases"] += 1
        events.append(Event("Battle", "conflict.supplied-campaign", [f"conflict:{key}", f"province:{source}", f"province:{target}"],
                            {"hazard": None, "victory_probability": chance, "travel_days": travel, "supply_food": supply,
                             "mobilized_attacker": attacker_force, "mobilized_defender": defender_force},
                            {"soldier_deaths_attacker": soldier_a, "soldier_deaths_defender": soldier_d,
                             "civilian_deaths": civilian, "campaign_spending": actual_budget}, draw,
                            text=f"A supplied campaign around {ctx.world.provinces[target]['name']} caused {soldier_a+soldier_d+civilian:,} deaths."))
        if draw < chance*.35:
            score = chance-draw
            if target not in contested or score > contested[target][0]:
                contested[target] = (score, attacker, key)
        elif war["phases"] >= 8:
            war["ended"], war["outcome"] = ctx.year, "negotiated exhaustion"
            events.append(Event("Treaty", "conflict.campaign-limit", [f"conflict:{key}"],
                                {"campaign_years": war["phases"]}, {"ended": ctx.year, "territory_changed": False},
                                text="A prolonged border war ended without a territorial settlement."))
    for target, (_, attacker, key) in sorted(contested.items()):
        previous = int(a["control"][target])
        control[target] = attacker
        conflicts[key]["ended"], conflicts[key]["outcome"] = ctx.year, "objective occupied"
        polities[str(attacker)]["claims"] = sorted(set(polities[str(attacker)]["claims"]+[target]))
        events.append(Event("Conquest", "conflict.control-resolution", [f"conflict:{key}", f"province:{target}", f"polity:{attacker}", f"polity:{previous}"],
                            {"resolution": "highest feasible campaign score", "residents_keep_identity": True},
                            {"control_before": previous, "control_after": attacker},
                            text=f"{polities[str(attacker)]['name']} gained control of {ctx.world.provinces[target]['name']}; residents retained their languages."))
    for pid in np.flatnonzero((a["control"] >= 0) & (econ.shortage > .22)):
        controller = int(a["control"][pid])
        polity = polities[str(controller)]
        draw = ctx.rng.draw("secession", int(pid), ctx.year)
        hazard = .01*econ.shortage[pid]*(1-polity["legitimacy"])
        if draw < probability(hazard):
            control[pid] = -1
            events.append(Event("Secession", "politics.fiscal-food-stress", [f"province:{pid}", f"polity:{controller}"],
                                {"hazard": float(hazard), "shortage": float(econ.shortage[pid]), "legitimacy": polity["legitimacy"]},
                                {"control_before": controller, "control_after": -1}, draw,
                                text=f"Food and fiscal stress led {ctx.world.provinces[pid]['name']} to leave central control."))
    agricultural = has(a["adopted"], "agriculture") & has(a["adopted"], "storage") & has(a["adopted"], "pottery")
    water_access = has(a["adopted"], "boats") & np.array([p["coast"] or p["river_flow"] >= 400 for p in ctx.world.provinces])
    transport = water_access | has(a["adopted"], "irrigation") | (a["roads"] >= .05)
    coordinated = a["control"] >= 0
    renewable = np.asarray(econ.ledger["food_renewable"])
    urban_support = np.asarray(econ.ledger["urban_food_support"])
    reliable = (agricultural & transport & coordinated & (econ.shortage < .01) &
                (renewable >= ctx.population*1.02) & (urban_support >= CITY_MIN_POPULATION))
    duration = np.where(reliable, np.minimum(1000, a["urban_surplus_years"]+1),
                        np.where(econ.shortage >= .01, 0, np.maximum(0, a["urban_surplus_years"]-1)))
    public["urban_surplus_years"] = duration.astype(np.int64)
    support_share = urban_support/np.maximum(ctx.population, 1)
    share_ceiling = np.minimum(.75, .02+has(a["adopted"], "irrigation")*.04+
                               has(a["adopted"], "ironworking")*.04+a["roads"]*.04+
                               has(a["adopted"], "industry")*.50+has(a["adopted"], "rail")*.10)
    eligible = agricultural & transport & coordinated & (duration >= params["city_surplus_years"])
    urban_target = np.minimum(share_ceiling, support_share)*eligible
    public["urban"] += (urban_target-public["urban"])*.015
    # Residents return to rural production when the hinterland cannot feed them;
    # this changes settlement distribution, never the population ledger.
    public["urban"] = np.minimum(public["urban"], support_share)*agricultural
    for name in public:
        if name == "urban_surplus_years":
            continue
        public[name] = np.clip(public[name], 0, .95 if name != "urban" else .75)
    return PoliticsProposal(polities, conflicts, control, casualties, public, treasury_ledger, events, next_polity, next_conflict)
