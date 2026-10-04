"""Population and city regressions at the real annual-system boundary."""
from __future__ import annotations

import unittest

import numpy as np

from worldsim.config import make_manifest
from worldsim.engine import Engine
from worldsim.geography import generate_world
from worldsim.initialization import initialize
from worldsim.systems import EnvironmentProposal, context, economy, environment, politics
from worldsim.technology import bit, feasible


class SubsistenceRegression(unittest.TestCase):
    def setUp(self):
        self.manifest = make_manifest(42, 64, overrides={
            "discovery_hazard": 0., "epidemic_hazard": 0.,
            "drought_hazard": 0., "war_hazard": 0.,
        })
        self.world = generate_world(self.manifest)
        self.state = initialize(self.world, self.manifest)
        self.engine = Engine(self.world, self.manifest)

    def test_foragers_grow_slowly_and_never_create_cities(self):
        state = self.state
        opening = int(state.arrays["cohorts"].sum())
        chain = "0"*64
        for _ in range(400):
            state, _, _, chain = self.engine.step(state, chain)
        self.assertFalse(any(s["city_founded"] is not None for s in state.settlements.values()),
                         "Forager-only regions must not become agricultural cities.")
        self.assertLessEqual(int(state.arrays["cohorts"].sum()), opening*1.65,
                             "Prehistoric populations must not grow dozens of times in four centuries.")
        self.assertGreater(int(state.arrays["cohorts"].sum()), opening*.8)

    def test_food_production_requires_working_age_labor(self):
        state = self.state
        state.arrays["cohorts"][:] = 0
        state.arrays["cohorts"][:, :, 0] = 1000
        state.arrays["food"][:] = 0
        ctx = context(state, self.world, self.manifest, self.engine.rng)
        econ = economy(state, ctx, environment(state, ctx))
        self.assertEqual(float(econ.production.sum()), 0.,
                         "Children alone cannot supply an adult-sized annual food harvest.")
        self.assertEqual(float(econ.consumption.sum()), 0.)

    def test_industrial_food_bonus_needs_a_fed_specialist_workforce(self):
        state = self.state.clone()
        state.arrays["known"][:] = state.arrays["adopted"][:] = (1 << 23)-1
        pid = int(state.arrays["strata"][0, 1])
        okay, missing = feasible(state, self.world, pid, "industry")
        self.assertFalse(okay)
        self.assertIn("food-supported specialist workforce", missing)
        ctx = context(state, self.world, self.manifest, self.engine.rng)
        econ = economy(state, ctx, environment(state, ctx))
        self.assertEqual(econ.ledger["industrial_scale"][pid], 0.)

    def test_reserves_cannot_be_replaced_by_a_gross_harvest_surplus(self):
        state = self.state
        state.arrays["food"][:] = 0
        state.arrays["cohorts"] *= 50
        ctx = context(state, self.world, self.manifest, self.engine.rng)
        econ = economy(state, ctx, environment(state, ctx))
        self.assertGreater(float(econ.shortage.sum()), 0.)
        self.assertLessEqual(float(econ.production.sum()), float(ctx.capacity.sum())*1.2)

    def test_adopting_agriculture_does_not_instantly_cultivate_a_province(self):
        self.state.arrays["adopted"] |= bit("agriculture")
        ctx = context(self.state, self.world, self.manifest, self.engine.rng)
        econ = economy(self.state, ctx, environment(self.state, ctx))
        cleared = np.asarray(econ.ledger["cultivated_ha_cleared"])
        self.assertGreater(float(cleared.sum()), 0.)
        adults = self.state.arrays["cohorts"][:, :, 3:12].sum(axis=(1, 2))
        self.assertLessEqual(float(cleared.sum()), float(adults.sum())*
                             self.manifest["parameters"]["cultivation_ha_per_worker_year"])
        self.assertTrue(np.all(self.state.arrays["cultivated_ha"] == 0.))
        arable = sum(p["area_km2"]*p["arable_share"]*100 for p in self.world.provinces)
        self.assertLess(float(cleared.sum()), arable*.001)

    def test_maintained_fields_persist_when_expansion_is_disabled(self):
        state = self.state.clone()
        pid = int(state.arrays["strata"][0, 1])
        state.arrays["adopted"][pid] |= bit("agriculture")
        state.arrays["cultivated_ha"][pid] = 100.
        manifest = make_manifest(42, 64, overrides={**self.manifest["parameters"],
                                 "cultivation_ha_per_worker_year": 0.})
        ctx = context(state, self.world, manifest, self.engine.rng)
        econ = economy(state, ctx, environment(state, ctx))
        self.assertEqual(econ.arrays["cultivated_ha"][pid], 100.,
                         "Tended fields must not decay solely because regional expansion stops.")

    def test_less_food_reduces_births_and_survival(self):
        self.state.arrays["food"][:] = 0.
        low = make_manifest(42, 64, overrides={**self.manifest["parameters"], "food_yield": .3})
        high = make_manifest(42, 64, overrides={**self.manifest["parameters"], "food_yield": 1.2})
        poor, _, poor_ledger, _ = Engine(self.world, low).step(self.state.clone())
        fed, _, fed_ledger, _ = Engine(self.world, high).step(self.state.clone())
        self.assertGreater(sum(poor_ledger["deaths"]["famine"]), sum(fed_ledger["deaths"]["famine"]))
        self.assertLess(sum(poor_ledger["births"]), sum(fed_ledger["births"]))
        self.assertLess(int(poor.arrays["cohorts"].sum()), int(fed.arrays["cohorts"].sum()))

    def test_schooling_alone_does_not_trigger_modern_fertility_decline(self):
        educated = self.state.clone()
        educated.arrays["schooling"][:] = .9
        _, _, baseline, _ = self.engine.step(self.state.clone())
        _, _, schooled, _ = self.engine.step(educated)
        self.assertEqual(baseline["births"], schooled["births"])

    def agricultural_region(self):
        state = self.state.clone()
        state.arrays["cohorts"] *= 20
        flags = sum(bit(name) for name in ("agriculture", "storage", "pottery", "irrigation", "boats"))
        state.arrays["known"][:] = flags
        state.arrays["adopted"][:] = flags
        arable = np.array([p["area_km2"]*p["arable_share"]*100 for p in self.world.provinces])
        state.arrays["cultivated_ha"][:] = np.minimum(arable, state.population(self.world.size))
        state.arrays["food"][:] = state.population(self.world.size)*3.
        formation = make_manifest(42, 64, overrides={**self.manifest["parameters"], "state_formation_hazard": 10.})
        ctx = context(state, self.world, formation, self.engine.rng)
        econ = economy(state, ctx, environment(state, ctx))
        political = politics(state, ctx, econ)
        state.polities, state.arrays["control"] = political.polities, political.control
        state.next_ids["polity"] = political.next_polity
        state.next_ids["conflict"] = political.next_conflict
        state.arrays["urban"][:] = .05
        return state

    def test_city_needs_sustained_surplus_and_records_actual_support(self):
        young = self.agricultural_region()
        mature = young.clone()
        mature.arrays["urban_surplus_years"][:] = self.manifest["parameters"]["city_surplus_years"]-1
        after, _, _, _ = self.engine.step(young)
        self.assertFalse(any(s["city_founded"] is not None for s in after.settlements.values()))
        after, events, ledger, _ = self.engine.step(mature)
        founded = [e for e in events if e["type"] == "CityGrowth"]
        self.assertTrue(founded, "A genuinely supported agricultural city must remain possible.")
        for event in founded:
            pid = int(next(p.split(":")[1] for p in event["participants"] if p.startswith("province:")))
            self.assertGreaterEqual(event["conditions"]["surplus_years"], 40)
            self.assertLessEqual(event["deltas"]["city_population_after"], ledger["urban_food_support"][pid]+1.)

    def test_crop_failure_shrinks_city_support_without_deleting_residents(self):
        state = self.agricultural_region()
        state.arrays["urban_surplus_years"][:] = 100
        state.arrays["food"][:] = 0.
        failure = make_manifest(42, 64, overrides={**self.manifest["parameters"],
                               "drought_hazard": 10., "drought_severity": .9})
        after, _, ledger, _ = Engine(self.world, failure).step(state)
        self.assertTrue(np.all(after.arrays["urban"] <= .05))
        self.assertGreater(sum(ledger["deaths"]["famine"]), 0)
        self.assertEqual(int(after.arrays["cohorts"].sum()), sum(ledger["population_open"])+
                         sum(ledger["births"])-sum(sum(d) for d in ledger["deaths"].values()))

    def test_foraging_surplus_does_not_qualify_a_city_hinterland(self):
        state = self.agricultural_region()
        state.arrays["cohorts"] //= 20
        state.arrays["cultivated_ha"][:] = 0.
        state.arrays["urban"][:] = 0.
        state.arrays["urban_surplus_years"][:] = 39
        ctx = context(state, self.world, self.manifest, self.engine.rng)
        econ = economy(state, ctx, environment(state, ctx))
        public = politics(state, ctx, econ).public
        self.assertTrue(np.all(public["urban_surplus_years"] < 40))
        self.assertEqual(float(public["urban"].sum()), 0.)

    def test_crop_shipments_are_a_conserved_subset_of_actual_food_trade(self):
        state = self.agricultural_region()
        ctx = context(state, self.world, self.manifest, self.engine.rng)
        candidates = [i for i, (a, b) in enumerate(zip(ctx.source, ctx.target))
                      if ctx.population[a] and ctx.population[b] and ctx.contact[i] >= .035]
        route = min(candidates, key=lambda i: ctx.cost[i])
        receiver = int(ctx.target[route])
        state.arrays["food"][receiver] = 0.
        weather = np.ones(self.world.size)
        weather[receiver] = .12
        econ = economy(state, ctx, EnvironmentProposal(weather, np.zeros(self.world.size), []))
        self.assertGreater(econ.ledger["crop_food_imports"][receiver], 0.)
        self.assertAlmostEqual(sum(econ.ledger["crop_food_imports"]), sum(econ.ledger["crop_food_exports"]))
        for shipment in econ.trades:
            self.assertLessEqual(shipment["crop_food"], shipment["food"])


if __name__ == "__main__":
    unittest.main()
