from __future__ import annotations

import copy
import tempfile
from pathlib import Path
import unittest

import numpy as np

from worldsim.application import branch, compare, simulate
from worldsim.config import RandomStreams, SimError, make_manifest, offset_for_year, year_label
from worldsim.engine import Engine, take_cohorts, validate_ledger, validate_state
from worldsim.geography import generate_world, validate_geography
from worldsim.initialization import initialize
from worldsim.linguistics import create_language, phonology_valid, sound_change
from worldsim.model import Event, apply_patch, decode_state, encode_patch, encode_state, state_hash
from worldsim.storage import RunStore
from worldsim.systems import context, demography, economy, environment, knowledge, migration, politics
from worldsim.technology import bit, feasible


class Foundations(unittest.TestCase):
    def test_geography_seeds_and_outlets(self):
        for seed in (0, 1, 42, 98765):
            with self.subTest(seed=seed):
                m = make_manifest(seed, 80)
                w = generate_world(m)
                self.assertEqual(w.to_dict(), generate_world(m).to_dict())
                self.assertEqual(validate_geography(w)["provinces"], 80)
                s = initialize(w, m)
                self.assertGreater(validate_state(s, w)["population"], 0)
                self.assertTrue(all(phonology_valid(l) for l in s.languages.values()))

    def test_calendar_crosses_without_year_zero(self):
        self.assertEqual(year_label(0, -2), "2 BCE")
        self.assertEqual(year_label(1, -2), "1 BCE")
        self.assertEqual(year_label(2, -2), "1 CE")
        self.assertEqual(offset_for_year(2000, -9000), 10999)
        self.assertEqual(year_label(10999, -9000), "2,000 CE")

    def test_keyed_random_streams(self):
        rng = RandomStreams(1023)
        ids = np.arange(30)
        np.testing.assert_array_equal(rng.draws("test", ids, 80, 3),
                                      [rng.draw("test", int(i), 80, 3) for i in ids])
        self.assertNotEqual(rng.draw("food", 2, 50), rng.draw("war", 2, 50))

    def test_sound_changes_have_conditions_and_control(self):
        language = create_language(RandomStreams(4), 0)
        language["lexicon"]["water"]["form"] = "pata"
        language["lexicon"]["river"]["form"] = "tana"
        changed, changes = sound_change(language, ("t", "d", "intervocalic"), 100)
        self.assertEqual(changed["lexicon"]["water"]["form"], "pada")
        self.assertEqual(changed["lexicon"]["river"]["form"], "tana")
        self.assertEqual(language["lexicon"]["water"]["form"], "pata")
        self.assertNotIn("river", changes)


class AnnualContract(unittest.TestCase):
    def setUp(self):
        self.m = make_manifest(42, 40)
        self.w = generate_world(self.m)
        self.s = initialize(self.w, self.m)
        self.e = Engine(self.w, self.m)

    def test_frozen_input_and_exact_binary_replay(self):
        raw = encode_state(self.s)
        after, events, ledger, _ = self.e.step(self.s)
        self.assertEqual(raw, encode_state(self.s))
        self.assertEqual(encode_state(decode_state(encode_state(after))), encode_state(after))
        self.assertEqual(state_hash(apply_patch(self.s, encode_patch(self.s, after))), state_hash(after))
        self.assertEqual(validate_ledger(ledger)["migration"], "exact")
        self.assertTrue(events[-1]["deltas"]["exact_state_patch"])

    def test_transfer_cannot_create_people(self):
        c = np.arange(36, dtype=np.int64).reshape(2, 18)
        for count in (0, 1, 34, 500, 10000):
            selected = take_cohorts(c, count)
            self.assertEqual(int(selected.sum()), min(count, int(c.sum())))
            self.assertTrue(np.all(selected <= c))

    def test_drought_and_migration_are_accounted_once(self):
        self.m = make_manifest(42, 40, overrides={"drought_hazard": 10., "drought_severity": .85})
        self.s.arrays["food"][:] = 0
        after, events, ledger, _ = Engine(self.w, self.m).step(self.s)
        self.assertTrue(any(e["type"] == "CropFailure" for e in events))
        self.assertGreater(sum(ledger["deaths"]["famine"]), 0)
        self.assertEqual(sum(ledger["immigration"]), sum(ledger["emigration"]))
        self.assertEqual(int(after.arrays["cohorts"].sum()), sum(ledger["population_open"])+sum(ledger["births"])-sum(sum(v) for v in ledger["deaths"].values()))

    def test_technology_knowledge_requires_operational_complements(self):
        pid = int(self.s.arrays["strata"][0, 1])
        self.s.arrays["known"][pid] = sum(bit(t) for t in ("steam", "industry", "rail"))
        self.s.arrays["fossil"][pid] = 0
        okay, missing = feasible(self.s, self.w, pid, "rail")
        self.assertFalse(okay)
        self.assertIn("energy supply", missing)
        self.assertIn("industry", missing)

    def test_industry_output_is_limited_by_actual_material_inputs(self):
        pid = int(self.s.arrays["strata"][0, 1])
        all_flags = sum(1 << i for i in range(23))
        self.s.arrays["adopted"][pid] = all_flags
        self.s.arrays["ore"][pid] = 0
        ctx = context(self.s, self.w, self.m, self.e.rng)
        econ = economy(self.s, ctx, environment(self.s, ctx))
        self.assertEqual(econ.ledger["industrial_scale"][pid], 0)
        self.assertEqual(econ.ledger["ore_used"][pid], 0)

    def test_conquest_changes_control_without_language_replacement(self):
        # Exercise the real central commit with a feasible proposed control change.
        ctx = context(self.s, self.w, self.m, self.e.rng)
        env = environment(self.s, ctx)
        econ = economy(self.s, ctx, env)
        demo = demography(self.s, ctx, env, econ)
        know = knowledge(self.s, ctx, econ)
        pol = politics(self.s, ctx, econ)
        pid = int(self.s.arrays["strata"][0, 1])
        pol.control[pid] = 999
        pol.polities["999"] = {"id": 999, "name": "Test council", "treasury": 0., "dissolved": None,
                               "successors": [], "predecessors": [], "capital": pid}
        before = self.s.arrays["strata"][:, 2:].copy()
        after, _, _, _ = self.e.commit(self.s, ctx, env, econ, demo, [], know, pol, "0"*64)
        self.assertEqual(after.arrays["control"][pid], 999)
        np.testing.assert_array_equal(after.arrays["strata"][:, 2:], before)

    def test_invariant_rejects_corrupt_accounting(self):
        _, _, ledger, _ = self.e.step(self.s)
        ledger["population_close"][0] += 1
        with self.assertRaisesRegex(SimError, "does not balance"):
            validate_ledger(ledger)

    def test_identity_labels_do_not_change_demographic_abilities(self):
        other = self.s.clone()
        other.arrays["strata"][:, 2] = (other.arrays["strata"][:, 2]+1) % len(other.languages)
        other.arrays["strata"][:, 3] = (other.arrays["strata"][:, 3]+1) % len(other.communities)
        other.arrays["strata"][:, 4] = (other.arrays["strata"][:, 4]+1) % len(other.beliefs)
        a, _, ledger_a, _ = self.e.step(self.s)
        b, _, ledger_b, _ = self.e.step(other)
        np.testing.assert_array_equal(a.population(self.w.size), b.population(self.w.size))
        self.assertEqual(ledger_a["births"], ledger_b["births"])
        self.assertEqual(ledger_a["deaths"], ledger_b["deaths"])

    def test_causal_parents_are_distinct_from_shared_entity_history(self):
        state, events, _, chain = self.e.step(self.s)
        input_id = events[-1]["id"]
        _, next_events, _, _ = self.e.step(state, chain)
        for event in next_events:
            self.assertIn("related_events", event)
            self.assertFalse(set(event["parents"]) & set(event["related_events"]))
            if not event["rule_id"].startswith("environment."):
                self.assertIn(input_id, event["parents"])

    def test_soldier_losses_use_adult_survivors_and_events_match_committed_counts(self):
        self.s.arrays["cohorts"][:] = 0
        self.s.arrays["cohorts"][:, :, 0] = 1000
        ctx = context(self.s, self.w, self.m, self.e.rng)
        env = environment(self.s, ctx)
        econ = economy(self.s, ctx, env)
        demo = demography(self.s, ctx, env, econ)
        know = knowledge(self.s, ctx, econ)
        pol = politics(self.s, ctx, econ)
        source, target = [int(r[1]) for r in self.s.arrays["strata"][:2]]
        pol.casualties[source], pol.casualties[target] = 5000, 5010
        pol.conflicts["999"] = {"deaths": 10010}
        pol.events.append(Event("Battle", "conflict.supplied-campaign", ["conflict:999", f"province:{source}", f"province:{target}"], {},
                                {"soldier_deaths_attacker": 5000, "soldier_deaths_defender": 5000, "civilian_deaths": 10}, text="Test campaign"))
        _, events, ledger, _ = self.e.commit(self.s, ctx, env, econ, demo, [], know, pol, "0"*64)
        event = next(e for e in events if e["type"] == "Battle")
        self.assertEqual(event["deltas"]["soldier_deaths_attacker"], 0)
        self.assertEqual(event["deltas"]["soldier_deaths_defender"], 0)
        self.assertEqual(event["deltas"]["civilian_deaths"], sum(ledger["deaths"]["violence"]))
        self.assertTrue(event["conditions"]["casualty_cap_applied"])


class Persistence(unittest.TestCase):
    def test_independent_seeds_do_not_align_unrelated_language_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with RunStore.create(root/"left", make_manifest(42, 24)) as left:
                with RunStore.create(root/"right", make_manifest(73, 24)) as right:
                    result = compare(left, right, 0)
                    self.assertFalse(result["same_geography"])
                    self.assertIsNone(result["language_speaker_delta"])
                    self.assertIsNone(result["lexical_varieties_changed"])
                    self.assertEqual(result["language_count_delta"], result["right"]["languages"]-result["left"]["languages"])

    def test_validation_reads_one_committed_view_while_another_writer_advances(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            with RunStore.create(Path(tmp)/"run", make_manifest(42, 24)) as reader:
                simulate(reader, 1)
                with RunStore(reader.manifest_path) as writer:
                    advanced = False
                    def advance_during_validation(ledger):
                        nonlocal advanced
                        result = validate_ledger(ledger)
                        if not advanced:
                            advanced = True
                            simulate(writer, 1)
                        return result
                    with patch("worldsim.storage.validate_ledger", side_effect=advance_during_validation):
                        result = reader.validate(deep=True)
                    self.assertTrue(result["ok"])
                    self.assertEqual(result["years_checked"], 1)
                    self.assertEqual(reader.latest_year, 2)

    def test_validation_rejects_a_balanced_but_altered_annual_ledger(self):
        import zlib
        from worldsim.config import canonical
        with tempfile.TemporaryDirectory() as tmp:
            with RunStore.create(Path(tmp)/"run", make_manifest(42, 24)) as store:
                simulate(store, 1)
                ledger = store.ledger(1)
                ledger["food_open"][0] += 1
                ledger["food_close"][0] += 1
                validate_ledger(ledger)  # The local balance alone cannot detect this.
                with store.connection:
                    store.connection.execute("UPDATE commits SET ledger=? WHERE year=1",
                                             (zlib.compress(canonical(ledger)),))
                with self.assertRaises(SimError) as raised:
                    store.validate(deep=True)
                self.assertEqual(raised.exception.code, "CORRUPT_SAVE")

    def test_stale_writer_cannot_append_over_a_committed_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RunStore.create(Path(tmp)/"run", make_manifest(84, 24)) as first:
                with RunStore(first.manifest_path) as second:
                    before = second.load_state()
                    after, events, ledger, chain = Engine(second.world, second.manifest).step(before, second.event_hash)
                    simulate(first, 1)
                    with self.assertRaises(SimError) as raised:
                        second.append(before, after, events, ledger, chain)
                    self.assertEqual(raised.exception.code, "STALE_STATE")
                    self.assertEqual(second.latest_year, 1)
                    self.assertTrue(second.validate(deep=True)["ok"])

    def test_comparison_aligns_different_start_dates_across_bce_ce(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with RunStore.create(root/"early", make_manifest(42, 24, start_year=-2)) as early:
                with RunStore.create(root/"later", make_manifest(42, 24, start_year=1)) as later:
                    simulate(early, 3)
                    simulate(later, 1)
                    result = compare(early, later, 3)
                    self.assertEqual(result["other_year"], 1)
                    self.assertEqual(result["left"]["date"], "2 CE")
                    self.assertEqual(result["right"]["date"], "2 CE")
                    self.assertEqual(result["earliest_recorded_divergence"], 3)
                    with self.assertRaises(SimError) as raised:
                        compare(early, later, 1)
                    self.assertEqual(raised.exception.code, "UNAVAILABLE_CHECKPOINT")

    def test_reproducible_resume_replay_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = make_manifest(84, 32, overrides={"snapshot_interval": 7})
            with RunStore.create(root/"continuous", manifest) as a:
                simulate(a, 24)
                hash_a, events_a = state_hash(a.load_state()), a.event_hash
                state_9 = state_hash(a.load_state(9))
                self.assertTrue(a.validate(deep=True)["ok"])
                with branch(a, 9, root/"branch", {"kind": "travel_cost", "province": 0, "factor": .5}) as b:
                    self.assertEqual(state_hash(b.load_state()), state_9)
                    simulate(b, 15)
                    self.assertTrue(b.validate(deep=True)["ok"])
                    self.assertEqual(compare(a, b, 24)["earliest_recorded_divergence"], 10)
            with RunStore.create(root/"resumed", manifest) as b:
                simulate(b, 8)
            with RunStore(root/"resumed"/"manifest.json") as b:
                simulate(b, 16)
                self.assertEqual(state_hash(b.load_state()), hash_a)
                self.assertEqual(b.event_hash, events_a)
                self.assertEqual(state_hash(b.load_state(9)), state_9)

    def test_mutated_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RunStore.create(Path(tmp)/"run", make_manifest(1, 24)) as a:
                path = a.manifest_path
            import json
            m = json.loads(path.read_text())
            m["seed"] = 2
            path.write_text(json.dumps(m))
            with self.assertRaises(SimError) as raised:
                RunStore(path)
            self.assertEqual(raised.exception.code, "INVALID_MANIFEST")

    def test_checkpoint_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RunStore.create(tmp, make_manifest(1, 24)) as a:
                with self.assertRaises(SimError):
                    a.load_state(1)


class DemographicViability(unittest.TestCase):
    def test_well_fed_cohorts_can_replace_themselves(self):
        # Isolate the actual cohort transition from war, migration and disease.
        m = make_manifest(42, 240, overrides={"epidemic_hazard": 0., "drought_hazard": 0.})
        w = generate_world(m)
        state = initialize(w, m)
        rng = RandomStreams(m["seed"])
        starting = int(state.arrays["cohorts"].sum())
        state.arrays["urban"][:] = .1  # A modest market-town share, without modern fertility decline.
        for _ in range(600):
            ctx = context(state, w, m, rng)
            env = environment(state, ctx)
            econ = economy(state, ctx, env)
            econ.shortage[:] = 0
            demo = demography(state, ctx, env, econ)
            state.arrays["cohorts"] = demo.cohorts
            state.year += 1
        self.assertGreater(int(state.arrays["cohorts"].sum()), starting,
                           "Well-fed preindustrial cohorts must not systematically die out under the baseline priors.")


if __name__ == "__main__":
    unittest.main()
