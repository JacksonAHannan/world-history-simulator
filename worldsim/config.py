"""Versioned parameters, manifests and stateless independent random streams."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import platform
from typing import Any

import numpy as np

ENGINE_VERSION = "0.1.0"
SCHEMA_VERSION = 1
PARAMETER_VERSION = "earthlike-0.7"
READABLE_PARAMETER_VERSIONS = {"earthlike-0.6", PARAMETER_VERSION}
CITY_MIN_POPULATION = 5000
# Annual age-specific probabilities, not observed prehistoric life tables.
MORTALITY_RATES = (.075, .010, .007, .008, .010, .012, .015, .019, .024,
                   .031, .041, .058, .078, .105, .15, .22, .30, .42)
FERTILITY_SHAPE = (.10, .25, .26, .24, .20, .08)
MASK = (1 << 64) - 1


class SimError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class Parameters:
    food_yield: float = 1.0
    mortality: float = 1.0
    fertility: float = 1.0
    travel_cost: float = 1.0
    drought_severity: float = 0.45
    drought_hazard: float = 0.018
    epidemic_hazard: float = 0.003
    discovery_hazard: float = 0.0006
    adoption_hazard: float = 0.03
    borrowing_hazard: float = 0.045
    sound_change_hazard: float = 0.0015
    state_formation_hazard: float = 0.012
    war_hazard: float = 0.007
    snapshot_interval: int = 100
    stock_years_cap: float = 3.0
    strata_merge_threshold: int = 8
    migration_batch: int = 24
    lifetime_births: float = 3.6
    cultivation_ha_per_worker_year: float = .0002
    city_surplus_years: int = 40


PRESETS = {
    "balanced": {"description": "Unscripted histories on an Earth-like world."},
    "river-corridor": {"description": "Wetter basins and productive river land.",
                       "food_yield": 1.15},
    "modern-capable": {"description": "Faster experimentation; no dated unlocks.",
                       "discovery_hazard": 0.002, "adoption_hazard": 0.06},
}


def make_manifest(seed: int = 42, provinces: int = 320, preset: str = "balanced",
                  start_year: int = -9000, overrides: dict | None = None) -> dict:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**53:
        raise SimError("INVALID_PARAMETERS", "Seed must be an integer from 0 to 2^53 − 1.")
    if isinstance(provinces, bool) or not isinstance(provinces, int) or not 24 <= provinces <= 4000:
        raise SimError("INVALID_PARAMETERS", "Choose 24–4,000 land provinces.")
    if preset not in PRESETS or isinstance(start_year, bool) or not isinstance(start_year, int) or start_year == 0:
        raise SimError("INVALID_PARAMETERS", "Use a listed preset and a calendar year other than zero.")
    if overrides is not None and not isinstance(overrides, dict):
        raise SimError("INVALID_PARAMETERS", "Parameter overrides must be a JSON object.")
    params = asdict(Parameters())
    params.update({k: v for k, v in PRESETS[preset].items() if k in params})
    for k, v in (overrides or {}).items():
        if k not in params or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise SimError("INVALID_PARAMETERS", f"Invalid parameter: {k}.")
        if k in ("snapshot_interval", "strata_merge_threshold", "migration_batch", "city_surplus_years"):
            if not isinstance(v, int) or not 1 <= v <= 1000:
                raise SimError("INVALID_PARAMETERS", f"{k} must be an integer from 1 to 1,000.")
        elif not 0 <= v <= 10 or (k in ("travel_cost", "food_yield", "stock_years_cap") and v <= 0):
            raise SimError("INVALID_PARAMETERS", f"{k} is outside its supported range.")
        params[k] = v
    manifest = {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION,
                "parameter_version": PARAMETER_VERSION, "seed": seed, "preset": preset,
                "start_year": start_year, "provinces": provinces, "parameters": params,
                "world_generation": "priority-flood-grid-1", "data_sources": {
                    "population_screening": "https://www.census.gov/data/tables/time-series/demo/international-programs/historical-est-worldpop.html",
                    "prehistoric_growth_prior": "https://doi.org/10.1073/pnas.1517650112",
                    "urban_comparison": "https://www.metmuseum.org/essays/uruk-the-first-city"},
                "numeric_contract": "little-endian int64/float64; quantized economic stocks",
                "numpy_version": np.__version__, "python_version": platform.python_version(),
                "parent": None, "interventions": []}
    manifest["id"] = digest(manifest)[:16]
    return manifest


def check_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict):
        raise SimError("INVALID_MANIFEST", "A manifest must be a JSON object.")
    if (manifest.get("schema_version") != SCHEMA_VERSION or
            manifest.get("engine_version") != ENGINE_VERSION or
            manifest.get("parameter_version") not in READABLE_PARAMETER_VERSIONS):
        raise SimError("INCOMPATIBLE_VERSION", "This save needs its original engine and parameter versions.")
    if manifest.get("numpy_version") != np.__version__:
        raise SimError("INCOMPATIBLE_VERSION", "This run was created with a different NumPy version.")
    if manifest.get("id") != digest({k: v for k, v in manifest.items() if k != "id"})[:16]:
        raise SimError("INVALID_MANIFEST", "Manifest contents changed; create an intervention branch instead.")


def check_simulation_version(manifest: dict) -> None:
    if manifest.get("parameter_version") != PARAMETER_VERSION:
        raise SimError("INCOMPATIBLE_VERSION", "This history uses the earlier population model and is read-only. "
                       "Generate a new world with the same seed to use food-limited populations and cities.")


def calendar_year(offset: int, start_year: int) -> int:
    astronomical = (start_year + 1 if start_year < 0 else start_year) + offset
    return astronomical - 1 if astronomical <= 0 else astronomical


def year_label(offset: int, start_year: int) -> str:
    y = calendar_year(offset, start_year)
    return f"{abs(y):,} {'BCE' if y < 0 else 'CE'}"


def offset_for_year(year: int, start_year: int) -> int:
    if year == 0:
        raise SimError("INVALID_PARAMETERS", "The display calendar has no year zero.")
    return (year + (year < 0)) - (start_year + (start_year < 0))


class RandomStreams:
    """SplitMix64 keyed by seed/subsystem/stable ID/year, with no mutable RNG state."""
    def __init__(self, seed: int):
        self.seed = seed
        self.keys: dict[str, int] = {}

    def key(self, subsystem: str) -> int:
        if subsystem not in self.keys:
            self.keys[subsystem] = int.from_bytes(hashlib.blake2b(subsystem.encode(), digest_size=8).digest(), "little")
        return self.keys[subsystem]

    def draw(self, subsystem: str, entity: int, year: int = 0, slot: int = 0) -> float:
        x = (self.seed ^ self.key(subsystem) ^ (int(entity)*0x9e3779b97f4a7c15) ^
             (year*0xd1b54a32d192ed03) ^ (slot*0x94d049bb133111eb)) & MASK
        x = ((x ^ (x >> 30))*0xbf58476d1ce4e5b9) & MASK
        x = ((x ^ (x >> 27))*0x94d049bb133111eb) & MASK
        return ((x ^ (x >> 31)) >> 11) / 2**53

    def draws(self, subsystem: str, entities: np.ndarray, year: int, slot: int = 0) -> np.ndarray:
        with np.errstate(over="ignore"):
            x = (np.asarray(entities, dtype=np.uint64)*np.uint64(0x9e3779b97f4a7c15) ^
                 np.uint64(self.seed ^ self.key(subsystem)) ^
                 np.uint64((year*0xd1b54a32d192ed03) & MASK) ^
                 np.uint64((slot*0x94d049bb133111eb) & MASK))
            x = (x ^ (x >> np.uint64(30)))*np.uint64(0xbf58476d1ce4e5b9)
            x = (x ^ (x >> np.uint64(27)))*np.uint64(0x94d049bb133111eb)
            return ((x ^ (x >> np.uint64(31))) >> np.uint64(11)).astype(np.float64) / 2**53


def probability(hazard: float | np.ndarray):
    return -np.expm1(-np.asarray(hazard))
