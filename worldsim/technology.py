"""Know-how and local use are separate, with operational resource complements."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import CITY_MIN_POPULATION
from .model import State, World


@dataclass(frozen=True)
class Capability:
    name: str
    prerequisites: tuple[str, ...] = ()
    resource: str | None = None
    cost: float = .1
    institution: str | None = None
    description: str = ""


CAPABILITIES = (
    Capability("storage", cost=.03, description="Preservation and managed food reserves"),
    Capability("boats", resource="timber", cost=.05, description="Local river and coastal vessels"),
    Capability("agriculture", ("storage",), "domesticable_plants", .08, description="Cultivation alongside other subsistence"),
    Capability("herding", resource="domesticable_animals", cost=.06),
    Capability("pottery", ("storage",), "timber", .05),
    Capability("irrigation", ("agriculture",), cost=.12),
    Capability("metallurgy", ("pottery",), "ore", .14),
    Capability("writing", ("storage",), cost=.09),
    Capability("navigation", ("boats",), cost=.13),
    Capability("roads", ("agriculture",), cost=.10),
    Capability("ironworking", ("metallurgy",), "ore", .20),
    Capability("waterpower", ("metallurgy",), cost=.16),
    Capability("printing", ("writing", "metallurgy"), "fibers", .18),
    Capability("education", ("writing",), cost=.20, institution="administration"),
    Capability("sanitation", ("irrigation",), cost=.20, institution="administration"),
    Capability("machine_tools", ("ironworking", "waterpower"), "ore", .25),
    Capability("steam", ("machine_tools",), "fossil", .30),
    Capability("industry", ("steam", "machine_tools"), "ore", .35, "administration"),
    Capability("rail", ("steam", "industry", "roads"), "ore", .45, "administration"),
    Capability("electricity", ("industry",), cost=.30),
    Capability("medicine", ("education", "sanitation", "industry"), cost=.25,
               description="Modern medicine with industrial equipment and trained practitioners"),
    Capability("telecommunication", ("electricity", "writing"), cost=.30),
    Capability("renewables", ("electricity", "machine_tools"), cost=.35),
)
INDEX = {c.name: i for i, c in enumerate(CAPABILITIES)}


def bit(name: str) -> int:
    return 1 << INDEX[name]


def has(flags, name: str):
    return (flags & bit(name)) != 0


def names(flags: int) -> list[str]:
    return [c.name for i, c in enumerate(CAPABILITIES) if int(flags) & (1 << i)]


def feasible(state: State, world: World, province: int, tech: str, knowledge: bool = False) -> tuple[bool, list[str]]:
    capability = CAPABILITIES[INDEX[tech]]
    flags = int(state.arrays["known" if knowledge else "adopted"][province])
    missing = [p for p in capability.prerequisites if not has(flags, p)]
    if capability.resource:
        resource = capability.resource
        value = (state.arrays[resource][province] if resource in ("ore", "timber", "fossil")
                 else world.provinces[province]["resources"].get(resource, False))
        if value <= 0:
            missing.append(resource)
    if tech in ("irrigation", "waterpower") and world.provinces[province]["river_flow"] < 400:
        missing.append("usable water")
    if tech == "rail" and state.population(world.size)[province] < 5000:
        missing.append("transport demand")
    if tech in ("machine_tools", "steam", "industry", "rail", "electricity", "medicine", "telecommunication", "renewables"):
        residents = state.population(world.size)[province]*state.arrays["urban"][province]
        if residents < CITY_MIN_POPULATION:
            missing.append("food-supported specialist workforce")
    if not knowledge and capability.institution and state.arrays["control"][province] < 0:
        missing.append(capability.institution)
    if not knowledge and tech in ("steam", "industry", "rail") and state.arrays["fossil"][province] <= 0:
        missing.append("energy supply")
    return not missing, missing


def capacity(state: State, world: World) -> np.ndarray:
    base = np.array([p["forager_capacity"] for p in world.provinces])
    adopted = state.arrays["adopted"]
    _, crop_yield = farming_productivity(adopted)
    cultivated = state.arrays["cultivated_ha"]*has(adopted, "agriculture")
    land_ha = np.array([p["area_km2"]*100 for p in world.provinces])
    return (base*np.maximum(0., 1-cultivated/land_ha)*(1+has(adopted, "herding")*.3)+
            cultivated*crop_yield)


def farming_productivity(adopted: np.ndarray, industrial_scale=None) -> tuple[np.ndarray, np.ndarray]:
    """Workable hectares/worker and gross food person-years/hectare/year.

    Nominal capability ceilings are used for capacity; actual energy/material
    availability replaces the industry flag when calculating a harvest.
    """
    industry = has(adopted, "industry") if industrial_scale is None else industrial_scale
    hectares = 2.+has(adopted, "ironworking")+industry*5.
    yield_per_ha = 1.2*(1+has(adopted, "irrigation")*.30+has(adopted, "ironworking")*.15+industry*1.8)
    return hectares, yield_per_ha
