from __future__ import annotations

from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
import zipfile

from worldsim.application import branch, dossier, map_data, simulate, summary
from worldsim.config import SimError, canonical, digest, make_manifest
from worldsim.exporting import export_run
from worldsim.server import Atlas, Handler
from worldsim.storage import RunStore


def request(atlas, method, path, body=None, origin=None):
    """Exercise real HTTP routing without a listening socket, including write guards."""
    handler = object.__new__(Handler)
    handler.atlas = atlas
    handler.path = path
    handler.server = SimpleNamespace(server_port=8765)
    handler.headers = Message()
    raw = json.dumps(body).encode() if body is not None else b""
    handler.headers["Content-Type"] = "application/json"
    handler.headers["Content-Length"] = str(len(raw))
    if origin:
        handler.headers["Origin"] = origin
    handler.rfile = io.BytesIO(raw)
    captured = {}
    def respond(value, status=200, content_type=None, download=None):
        captured.update(body=value, status=status, content_type=content_type, download=download)
    handler.respond = respond
    getattr(handler, f"do_{method}")()
    return captured


class ApplicationTests(unittest.TestCase):
    def test_earlier_histories_remain_readable_but_cannot_be_advanced_or_branched(self):
        import hashlib
        from worldsim.model import state_hash
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with RunStore.create(root/"earlier", make_manifest(0, 24)) as store:
                before = state_hash(store.load_state())
                manifest = dict(store.manifest, parameter_version="earthlike-0.6")
                manifest["id"] = digest({k: v for k, v in manifest.items() if k != "id"})[:16]
                store.manifest_path.write_bytes(canonical(manifest)+b"\n")
                with store.connection:
                    store.connection.execute("UPDATE metadata SET value=? WHERE key='manifest_hash'",
                                             (hashlib.sha256(canonical(manifest)).hexdigest().encode(),))
            with RunStore(root/"earlier"/"manifest.json") as earlier:
                self.assertEqual(state_hash(earlier.load_state()), before)
                self.assertFalse(summary(earlier)["can_simulate"])
                self.assertEqual(map_data(earlier, 0)["summary"]["city_min_population"], 1000)
                with self.assertRaisesRegex(SimError, "read-only"):
                    simulate(earlier, 1)
                with self.assertRaisesRegex(SimError, "read-only"):
                    branch(earlier, 0, root/"branch", {"kind": "travel_cost", "province": 0, "factor": .5})
                self.assertFalse((root/"branch").exists())
                self.assertEqual(earlier.latest_year, 0)
            with RunStore.create(root/"current", make_manifest(42, 24)):
                pass
            atlas = Atlas(root)
            listed = atlas.list_runs()
            self.assertTrue(listed[0]["can_simulate"])
            self.assertEqual(listed[0]["city_min_population"], 5000)
            rejected = request(atlas, "POST", f"/api/run/{manifest['id']}/simulate", {"years": 1})
            self.assertGreaterEqual(rejected["status"], 400)
            self.assertEqual(rejected["body"]["error"]["code"], "INCOMPATIBLE_VERSION")
            self.assertEqual(atlas.status(manifest["id"]), {})

    def test_city_dossier_reports_urban_residents_with_consistent_estimated_composition(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            with RunStore.create(Path(tmp)/"run", make_manifest(42, 32)) as store:
                simulate(store, 1)
                state = store.load_state()
                settlement = next(iter(state.settlements.values()))
                pid = settlement["province"]
                settlement["city_founded"] = 1
                state.arrays["urban"][pid] = .25
                with patch.object(store, "load_state", return_value=state):
                    result = dossier(store, "settlement", settlement["id"], 1)
                province_population = int(state.population(store.world.size)[pid])
                self.assertTrue(result["population_is_estimate"])
                self.assertEqual(result["population"], int(province_population*.25))
                self.assertLess(result["population"], province_population)
                self.assertEqual(sum(result["age_structure"]), result["population"])
                self.assertEqual(sum(s["speakers"] for s in result["language_shares"]), result["population"])
                self.assertEqual(sum(result["community_shares"].values()), result["population"])

    def test_map_distinguishes_all_migration_from_war_displacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RunStore.create(Path(tmp)/"run", make_manifest(42, 32,
                                 overrides={"drought_hazard": 10., "drought_severity": .85})) as store:
                simulate(store, 1)
                ledger = store.ledger(1)
                self.assertGreater(sum(ledger["emigration"]), 0)
                data = map_data(store, 1)
                self.assertEqual(sum(p["migration"] for p in data["provinces"]), sum(ledger["emigration"]))
                self.assertEqual(sum(p["displacement"] for p in data["provinces"]),
                                 sum(f["count"] for f in ledger["flows"] if f["type"] == "Displacement"))
                self.assertEqual(sum(p["displacement"] for p in data["provinces"]), 0)

    def test_dated_dossiers_and_export_truth_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with RunStore.create(root/"run", make_manifest(42, 32)) as store:
                simulate(store, 15)
                d = dossier(store, "province", 0, 7)
                self.assertEqual(d["year"], 7)
                self.assertTrue(all(e["year"] <= 7 for e in d["events"]))
                data = map_data(store, 7)
                self.assertEqual(sum(p["population"] for p in data["provinces"]), data["summary"]["population"])
                result = export_run(store, root/"export", 7)
                with zipfile.ZipFile(result["archive"]) as archive:
                    self.assertTrue({"manifest.json", "atlas.svg", "atlas.geojson", "provinces.csv", "population-flows.csv", "events.jsonl", "history.md"}.issubset(archive.namelist()))
                    events = [json.loads(line) for line in archive.read("events.jsonl").splitlines()]
                    self.assertTrue(all(e["year"] <= 7 for e in events))
                    history = archive.read("history.md").decode()
                    for event in events:
                        if event["type"] != "YearCommitted":
                            self.assertIn(event["id"], history)
                with self.assertRaises(SimError):
                    export_run(store, root/"export", 7)

    def test_real_handlers_generate_simulate_pause_inspect_branch_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            atlas = Atlas(Path(tmp))
            try:
                self.assertEqual(request(atlas, "GET", "/api/runs")["body"]["runs"], [])
                generated = request(atlas, "POST", "/api/generate", {"seed": 42, "provinces": 32})
                self.assertEqual(generated["status"], 201)
                run_id = generated["body"]["id"]
                base = f"/api/run/{run_id}"
                started = request(atlas, "POST", base+"/simulate", {"years": 15})
                self.assertEqual(started["status"], 202)
                deadline = time.monotonic()+20
                while atlas.busy(run_id) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(atlas.busy(run_id))
                self.assertIsNone(atlas.status(run_id)["error"])
                world = request(atlas, "GET", base+"/world?year=7")
                self.assertEqual(world["body"]["summary"]["year"], 7)
                inspected = request(atlas, "GET", base+"/dossier?kind=province&id=0&year=7")
                self.assertEqual(inspected["body"]["year"], 7)
                new = request(atlas, "POST", base+"/branch", {"year": 7, "province": 0, "kind": "travel_cost", "factor": .5})
                self.assertEqual(new["status"], 201)
                other = new["body"]["id"]
                comparison = request(atlas, "GET", base+f"/compare?other={other}&year=7")
                self.assertEqual(comparison["body"]["population_delta"], 0)
                self.assertIsNone(comparison["body"]["earliest_recorded_divergence"])
                download = request(atlas, "POST", base+"/export", {"year": 7})
                archive = request(atlas, "GET", download["body"]["download"])
                self.assertEqual(archive["content_type"], "application/zip")
                self.assertTrue(request(atlas, "POST", base+"/validate", {"deep": True})["body"]["ok"])
                request(atlas, "POST", base+"/simulate", {"years": 30000-15})
                request(atlas, "POST", base+"/pause", {})
                deadline = time.monotonic()+20
                while atlas.busy(run_id) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(atlas.busy(run_id))
                self.assertLess(atlas.status(run_id)["year"], 30000)
            finally:
                atlas.stop_all()

    def test_http_errors_are_structured_and_cross_origin_writes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            atlas = Atlas(Path(tmp))
            bad = request(atlas, "POST", "/api/generate", {"seed": -1, "provinces": 32})
            self.assertEqual(bad["status"], 400)
            self.assertEqual(bad["body"]["error"]["code"], "INVALID_PARAMETERS")
            rejected = request(atlas, "POST", "/api/generate", {"seed": 42, "provinces": 32}, "https://example.com")
            self.assertEqual(rejected["body"]["error"]["code"], "INVALID_ORIGIN")
            missing = request(atlas, "GET", "/api/run/missing/world")
            self.assertEqual(missing["status"], 404)
            traversal = request(atlas, "GET", "/../../../etc/passwd")
            self.assertEqual(traversal["status"], 404)


if __name__ == "__main__":
    unittest.main()
