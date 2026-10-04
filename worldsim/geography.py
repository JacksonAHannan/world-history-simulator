"""Earth-like heuristic geography, checked hydraulic drainage and multimodal routes."""
from __future__ import annotations

import heapq
import math
from collections import deque

import numpy as np

from .config import RandomStreams, SimError
from .model import World


def generate_world(manifest: dict) -> World:
    n, rng = manifest["provinces"], RandomStreams(manifest["seed"])
    height = int(math.ceil(math.sqrt(n / 0.56 / 2)))
    width = int(math.ceil(n / 0.56 / height))
    total = width*height
    y, x = np.divmod(np.arange(total), width)
    xx, yy = (x+.5)/width, (y+.5)/height
    relief = np.full(total, -0.18)
    for c in range(7):
        cx, cy = rng.draw("continent-x", c), .15+.7*rng.draw("continent-y", c)
        dx = np.minimum(abs(xx-cx), 1-abs(xx-cx))
        sx, sy = .10+.09*rng.draw("continent-width", c), .12+.12*rng.draw("continent-height", c)
        relief += (.65+.45*rng.draw("continent-size", c))*np.exp(-((dx/sx)**2+((yy-cy)/sy)**2)*1.8)
    relief += .075*(rng.draws("relief", np.arange(total), 0)-.5)
    land_indices = np.argsort(relief, kind="stable")[-n:]
    land = np.zeros(total, dtype=bool)
    land[land_indices] = True
    coast_threshold = float(np.min(relief[land]))
    elevation = np.maximum(5., (relief-coast_threshold)*1700.)
    for r in range(3):
        ridge_x = rng.draw("ridge-x", r)
        phase = rng.draw("ridge-phase", r)*6.28
        dx = np.minimum(abs(xx-(ridge_x+.035*np.sin(yy*8+phase)) % 1),
                        1-abs(xx-(ridge_x+.035*np.sin(yy*8+phase)) % 1))
        elevation += (900+1500*rng.draw("ridge-height", r))*np.exp(-(dx/.028)**2)*np.sin(np.pi*yy)**2
    elevation[~land] = 0.

    def neighbors(cell: int):
        row, col = divmod(cell, width)
        yield row*width+(col-1) % width
        yield row*width+(col+1) % width
        if row > 0:
            yield cell-width
        if row < height-1:
            yield cell+width

    # Priority flood: depressions become lakes with an explicit hydraulic outlet.
    hydraulic = np.full(total, np.inf)
    downstream = np.full(total, -1, dtype=np.int64)
    queue = []
    for cell in np.flatnonzero(~land):
        hydraulic[cell] = 0
        heapq.heappush(queue, (0., int(cell)))
    while queue:
        level, cell = heapq.heappop(queue)
        for target in neighbors(cell):
            if math.isinf(hydraulic[target]):
                hydraulic[target] = max(float(elevation[target]), level+.001)
                downstream[target] = cell
                heapq.heappush(queue, (float(hydraulic[target]), target))
    latitude = 68-136*yy
    temperature = 29-.60*np.abs(latitude)-elevation*.006
    # Westerlies and trade winds: dry subtropics, wet equator, orographic shadow.
    upwind = y*width+(x-1) % width
    shadow = np.maximum(0, elevation[upwind]-elevation)*.00018
    rain = np.clip(1100+650*np.cos(latitude*np.pi/48)-700*np.exp(-((abs(latitude)-27)/10)**2)
                   -shadow*800+200*(rng.draws("rain", np.arange(total), 0)-.5), 80, 2500)
    if manifest["preset"] == "river-corridor":
        rain *= 1.15
    growing = np.clip((temperature+8)*9, 20, 365)
    arable = np.clip((rain/1200)*np.maximum(0, (temperature+8)/32)*np.exp(-elevation/1600)*.65, .005, .8)
    runoff = np.maximum(0, rain-300)*land
    for cell in np.argsort(hydraulic, kind="stable")[::-1]:
        parent = downstream[cell]
        if parent >= 0:
            runoff[parent] += runoff[cell]
    land_indices = sorted(int(v) for v in land_indices)
    cell_to_province = {c: i for i, c in enumerate(land_indices)}
    basins = np.full(total, -1, dtype=np.int64)
    for cell in np.argsort(hydraulic, kind="stable"):
        if not land[cell]:
            basins[cell] = cell
        elif downstream[cell] >= 0:
            basins[cell] = basins[downstream[cell]]
    basin_ids = {b: i for i, b in enumerate(sorted(set(int(basins[c]) for c in land_indices)))}
    provinces = []
    for pid, cell in enumerate(land_indices):
        row, col = divmod(cell, width)
        lon0, lon1 = -180+360*col/width, -180+360*(col+1)/width
        lat1, lat0 = 68-136*row/height, 68-136*(row+1)/height
        area = 6371**2*math.radians(lon1-lon0)*(math.sin(math.radians(lat1))-math.sin(math.radians(lat0)))
        coast = any(not land[c] for c in neighbors(cell))
        e, t, r = float(elevation[cell]), float(temperature[cell]), float(rain[cell])
        biome = ("alpine" if e > 1800 else "tundra" if t < -4 else "boreal forest" if t < 5 else
                 "desert" if r < 260 else "grassland" if r < 650 else "rainforest" if t > 22 else "temperate forest")
        productivity = max(.002, .026*min(1.5, r/1000)*max(.1, (t+10)/35))
        capacity = max(50, area*productivity*(1.3 if coast else 1))
        provinces.append({"id": pid, "cell": cell, "name": f"Region {pid+1}", "latitude": float(latitude[cell]),
                          "longitude": (lon0+lon1)/2, "geometry": [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]],
                          "area_km2": round(area, 3), "elevation_m": round(e, 3), "hydraulic_m": round(float(hydraulic[cell]), 3),
                          "lake_depth_m": round(max(0., float(hydraulic[cell])-e), 3),
                          "temperature_c": round(t, 3), "rain_mm": round(r, 3), "growing_days": int(growing[cell]),
                          "arable_share": round(float(arable[cell]), 6), "biome": biome, "coast": coast,
                          "basin": basin_ids[int(basins[cell])], "drainage": cell_to_province.get(int(downstream[cell]), -1),
                          "river_flow": round(float(runoff[cell]), 3), "forager_capacity": round(capacity, 3),
                          "resources": {"pasture": round(max(.05, .5-float(arable[cell])*.3), 3),
                                        "timber": round(area*(.2 if "forest" in biome else .04), 3),
                                        "ore": round(area*(.15+.8*rng.draw("ore", pid))*(.2+e/2000), 3),
                                        "fossil": round(area*.7*rng.draw("fossil", pid)**3, 3),
                                        "domesticable_plants": t > 2 and r > 300,
                                        "domesticable_animals": t > -5 and biome != "rainforest",
                                        "fibers": r > 450}})
    edges = []
    for pid, cell in enumerate(land_indices):
        for other in neighbors(cell):
            if other not in cell_to_province or cell_to_province[other] <= pid:
                continue
            target = cell_to_province[other]
            a, b = provinces[pid], provinces[target]
            mode = "river" if a["drainage"] == target or b["drainage"] == pid else "pass" if max(a["elevation_m"], b["elevation_m"]) > 1300 else "land"
            distance = _distance(a, b)
            days = distance / (55 if mode == "river" else 18 if mode == "pass" else 30)
            edges.append({"id": len(edges), "a": pid, "b": target, "mode": mode,
                          "distance_km": round(distance, 3), "days": round(days*(1+abs(a["elevation_m"]-b["elevation_m"])/3000), 3),
                          "winter_fraction": .35 if mode == "pass" else .08})
    # Coastal BFS only through ocean; sea links never cut across land.
    sea_pairs = set()
    for pid, cell in enumerate(land_indices):
        if not provinces[pid]["coast"]:
            continue
        visited = {cell}
        q = deque((o, 1) for o in neighbors(cell) if not land[o])
        found = {}
        while q:
            ocean, hops = q.popleft()
            if ocean in visited or hops > 6:
                continue
            visited.add(ocean)
            for neighbor in neighbors(ocean):
                if land[neighbor]:
                    target = cell_to_province[neighbor]
                    if target != pid and target not in [cell_to_province.get(v) for v in neighbors(cell)]:
                        found.setdefault(target, hops)
                elif neighbor not in visited:
                    q.append((neighbor, hops+1))
        for target, hops in sorted(found.items(), key=lambda v: (v[1], v[0]))[:3]:
            pair = tuple(sorted((pid, target)))
            if pair in sea_pairs:
                continue
            sea_pairs.add(pair)
            distance = _distance(provinces[pid], provinces[target])
            edges.append({"id": len(edges), "a": pair[0], "b": pair[1], "mode": "sea",
                          "distance_km": round(distance, 3), "days": round(distance/90+hops, 3),
                          "ocean_hops": hops, "winter_fraction": .12})
    grid = {"width": width, "height": height, "cells": [-1]*total,
            "projection": "equirectangular; longitude wraps; latitudes ±68°",
            "earth_radius_km": 6371, "latitude_bounds": [-68, 68]}
    for cell, pid in cell_to_province.items():
        grid["cells"][cell] = pid
    report = {"land_area_km2": round(sum(p["area_km2"] for p in provinces)), "provinces": n,
              "land_share": round(n/total, 4), "arable_share": round(float(arable[land].mean()), 4),
              "growing_days_range": [int(growing[land].min()), int(growing[land].max())],
              "basins": len(basin_ids), "basin_sizes": sorted(np.bincount([p["basin"] for p in provinces]).tolist(), reverse=True),
              "travel_days_quantiles": [round(float(q), 2) for q in np.quantile([e["days"] for e in edges], [.1, .5, .9])],
              "initial_carrying_capacity": round(sum(p["forager_capacity"] for p in provinces)),
              "rejected_attempts": 0, "repair": "priority-flood lake outlets",
              "limitations": "Coarse regular land cells, heuristic climate; polar caps excluded. Hydraulic water level defines lake flow."}
    world = World(provinces, edges, grid, report)
    validate_geography(world)
    return world


def _distance(a: dict, b: dict) -> float:
    lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    lon = math.radians(b["longitude"]-a["longitude"])
    h = math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(lon/2)**2
    return 12742*math.asin(min(1., math.sqrt(h)))


def validate_geography(world: World) -> dict:
    for p in world.provinces:
        seen, current = set(), p["id"]
        while current >= 0:
            if current in seen or not 0 <= current < world.size:
                raise SimError("FAILED_INVARIANT", "Drainage is cyclic or invalid.")
            seen.add(current)
            parent = world.provinces[current]["drainage"]
            if parent >= 0 and world.provinces[parent]["hydraulic_m"] >= world.provinces[current]["hydraulic_m"]:
                raise SimError("FAILED_INVARIANT", "Water does not drain downhill.")
            if parent == -1 and not world.provinces[current]["coast"]:
                raise SimError("FAILED_INVARIANT", "An inland river has no valid outlet.")
            current = parent
    for edge in world.edges:
        if not 0 <= edge["a"] < world.size or not 0 <= edge["b"] < world.size or edge["days"] <= 0:
            raise SimError("FAILED_INVARIANT", "Invalid travel edge.")
        if edge["mode"] == "sea" and not all(world.provinces[v]["coast"] for v in (edge["a"], edge["b"])):
            raise SimError("FAILED_INVARIANT", "Sea routes must connect coasts.")
    return {"drainage": "passed", "edges": "passed", "provinces": world.size, "routes": len(world.edges)}
