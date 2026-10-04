"""Viable starting communities, separate social identity and descent."""
from __future__ import annotations

import numpy as np

from .config import FERTILITY_SHAPE, MORTALITY_RATES, Parameters, RandomStreams
from .linguistics import create_language, place_name
from .model import AGE_BANDS, State, World
from .technology import bit


def initialize(world: World, manifest: dict) -> State:
    n, rng = world.size, RandomStreams(manifest["seed"])
    roots = max(4, min(16, n//35))
    languages = {str(i): create_language(rng, i) for i in range(roots)}
    centers = sorted(range(n), key=lambda i: rng.draw("language-center", i))[:roots]
    communities, beliefs = {}, {}
    for i in range(roots):
        communities[str(i)] = {"id": i, "name": languages[str(i)]["name"]+" communities",
                               "law_sources": ["custom", ["negotiated agreement", "council decree", "precedent"][i % 3]],
                               "economy": ["household production", "reciprocal exchange", "shared reserves"],
                               "household": ["extended kin", "multihousehold cooperation", "bilateral kin"][i % 3],
                               "prestige": ["hospitality", "craft skill", "public service", "ancestral memory"][i % 4],
                               "shared_practice": "Mutual aid in failed harvests",
                               "contested_practice": "Who may allocate shared reserves",
                               "minority_position": "Local assemblies should audit common stocks",
                               "standard_class": "Local elders and skilled providers; influence varies by settlement"}
    for i in range(4):
        beliefs[str(i)] = {"id": i, "name": ["River observance", "Hearth tradition", "Sky cycle", "Ancestor remembrance"][i],
                          "ritual": ["seasonal gatherings", "household offerings", "calendar observation", "oral commemoration"][i],
                          "status": "in-world beliefs, not claims of supernatural action"}
    strata, cohort_rows, ancestry = [], [], {}
    # Match the initial age pyramid to the baseline cohort transition, avoiding
    # an artificial baby boom from an arbitrary youthful exponential pyramid.
    ageing = np.eye(AGE_BANDS)*.8+np.eye(AGE_BANDS, k=-1)*.2
    ageing[-1, -1] = 1.
    survival = (1-np.array(MORTALITY_RATES))[:, None]*ageing
    fertility = np.zeros(AGE_BANDS)
    fertility[3:9] = np.array(FERTILITY_SHAPE)*(Parameters().lifetime_births/5.65)
    projection = survival.copy()
    projection[0] += .488*fertility@survival
    values, vectors = np.linalg.eig(projection)
    weights = np.abs(vectors[:, np.argmax(values.real)].real)
    weights /= weights.sum()
    weights = np.array([weights*.488, weights*.512])
    for p in world.provinces:
        pid = p["id"]
        lid = min(range(roots), key=lambda i: _distance(p, world.provinces[centers[i]]))
        feature = "river" if p["river_flow"] > 1000 else "hill" if p["elevation_m"] > 1000 else "home"
        p["name"], p["etymology"] = place_name(languages[str(lid)], feature, pid)
        # Distinguish homonymous places without violating the language's forms.
        if any(q["name"] == p["name"] for q in world.provinces[:pid]):
            p["display_name"] = f"{p['name']} (basin {p['basin']+1}, {pid+1})"
        else:
            p["display_name"] = p["name"]
        viable = p["temperature_c"] > -3 and p["rain_mm"] > 230 and p["growing_days"] > 90
        if not viable or rng.draw("settlement", pid) > .60:
            continue
        # Ecological density scales with land area, rather than a fixed number
        # per map cell. More provinces must not create a larger starting world.
        count = max(1, int(p["forager_capacity"]*.65*(.8+.4*rng.draw("initial-population", pid))))
        sid = len(strata)
        strata.append([sid, pid, lid, lid, int(rng.draw("belief", pid)*4), 0])
        expected = count*weights
        cohort = np.floor(expected).astype(np.int64)
        remaining = count-int(cohort.sum())
        order = np.argsort(-(expected-cohort).ravel(), kind="stable")
        cohort.ravel()[order[:remaining]] += 1
        cohort_rows.append(cohort)
        ancestry[str(sid)] = {f"descent-{lid}": 1.}
    if not strata:
        # A viable niche repair is explicit rather than leaving an empty run.
        pid = max(range(n), key=lambda i: world.provinces[i]["forager_capacity"])
        strata, cohort_rows = [[0, pid, 0, 0, 0, 0]], [np.full((2, AGE_BANDS), 20, dtype=np.int64)]
        ancestry = {"0": {"descent-0": 1.}}
        world.report["starting_niche_repair"] = pid
    arrays = {name: np.zeros(n, dtype=np.float64) for name in
              ("food", "timber", "ore", "fossil", "pollution", "roads", "sanitation", "schooling", "urban", "divergence", "cultivated_ha")}
    arrays.update({"last_split": np.zeros(n, dtype=np.int64), "control": np.full(n, -1, dtype=np.int64),
                   "known": np.zeros(n, dtype=np.int64), "adopted": np.zeros(n, dtype=np.int64),
                   "strata": np.array(strata, dtype=np.int64), "cohorts": np.array(cohort_rows, dtype=np.int64),
                   "bilingual": np.zeros(len(strata), dtype=np.float64),
                   "migration_credit": np.zeros(len(strata), dtype=np.float64)})
    arrays["urban_surplus_years"] = np.zeros(n, dtype=np.int64)
    state = State(0, arrays, languages, {}, communities, beliefs, ancestry,
                  next_ids={"stratum": len(strata), "language": roots, "polity": 0, "conflict": 0})
    pop = state.population(n)
    arrays["food"][:] = pop*.5
    for p in world.provinces:
        for resource in ("timber", "ore", "fossil"):
            arrays[resource][p["id"]] = p["resources"][resource]
        if pop[p["id"]] > 0:
            arrays["known"][p["id"]] = bit("storage") | (bit("boats") if p["coast"] else 0)
            arrays["adopted"][p["id"]] = bit("storage")
    world.report["initial_population"] = int(pop.sum())
    world.report["initial_settlements"] = int(np.count_nonzero(pop))
    state.settlements = {str(100000+int(pid)): {"id": 100000+int(pid), "province": int(pid),
                         "name": world.provinces[pid]["name"], "founded": 0, "city_founded": None,
                         "hinterland": [int(pid)]} for pid in np.flatnonzero(pop)}
    return state


def _distance(a: dict, b: dict) -> float:
    lon = min(abs(a["longitude"]-b["longitude"]), 360-abs(a["longitude"]-b["longitude"]))
    return (a["latitude"]-b["latitude"])**2+(lon*.7)**2
