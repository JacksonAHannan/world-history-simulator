"""Loopback atlas server; its handlers call the same application layer as the CLI."""
from __future__ import annotations

from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlparse

from .application import branch, compare, dossier, map_data, simulate, summary
from .config import PRESETS, SimError, check_simulation_version, make_manifest
from .exporting import export_run
from .storage import RunStore


class Atlas:
    def __init__(self, runs_dir: Path, extra_manifest=None):
        self.root = runs_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {}
        self.jobs = {}
        self.downloads = {}
        self.cache = {}
        self.lock = threading.RLock()
        for path in self.root.glob("*/manifest.json"):
            try:
                with RunStore(path) as store:
                    self.paths[store.manifest["id"]] = path
            except SimError:
                continue
        if extra_manifest:
            with RunStore(extra_manifest) as store:
                self.paths[store.manifest["id"]] = store.manifest_path

    def path(self, run_id):
        with self.lock:
            if run_id not in self.paths:
                raise SimError("NOT_FOUND", "Run does not exist.")
            return self.paths[run_id]

    def busy(self, run_id):
        with self.lock:
            return self.jobs.get(run_id, {}).get("running", False)

    def status(self, run_id):
        self.path(run_id)
        with self.lock:
            job = self.jobs.get(run_id, {})
            return {k: v for k, v in job.items() if k not in ("stop", "thread")}

    def list_runs(self):
        results = []
        with self.lock:
            paths = list(self.paths.items())
        for run_id, path in paths:
            with RunStore(path) as store:
                with self.lock:
                    cached = self.cache.get((run_id, "summary"))
                if cached and cached["latest_year"] == store.latest_year:
                    info = cached.copy()
                else:
                    info = summary(store)
                    with self.lock:
                        self.cache[(run_id, "summary")] = info
                results.append({**info, "job": self.status(run_id)})
        return sorted(results, key=lambda r: (not r["can_simulate"], r["parent"] is not None, r["seed"], r["id"]))

    def generate(self, payload):
        manifest = make_manifest(payload.get("seed", 42), payload.get("provinces", 320),
                                 payload.get("preset", "balanced"), payload.get("start_year", -9000), payload.get("parameters"))
        with self.lock:
            if manifest["id"] in self.paths:
                with RunStore(self.paths[manifest["id"]]) as store:
                    return summary(store)
            with RunStore.create(self.root/manifest["id"], manifest) as store:
                self.paths[manifest["id"]] = store.manifest_path
                return summary(store)

    def start(self, run_id, years):
        if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 30000:
            raise SimError("INVALID_PARAMETERS", "Advance by 1–30,000 years.")
        path = self.path(run_id)
        with self.lock:
            if self.busy(run_id):
                raise SimError("RUN_BUSY", "This run is already advancing. Pause it before starting another job.")
            with RunStore(path) as store:
                check_simulation_version(store.manifest)
                if store.latest_year+years > 30000:
                    raise SimError("INVALID_PARAMETERS", "The latest supported offset is 30,000.")
                beginning = store.latest_year
            stop = threading.Event()
            job = {"running": True, "year": beginning, "target": beginning+years, "error": None, "stop": stop}
            self.jobs[run_id] = job

            def progress(year):
                with self.lock:
                    job["year"] = year

            def work():
                try:
                    with RunStore(path) as store:
                        simulate(store, years, progress, stop)
                except Exception as exc:
                    with self.lock:
                        job["error"] = {"code": getattr(exc, "code", "SIMULATION_ERROR"), "message": str(exc)}
                finally:
                    with self.lock:
                        job["running"] = False

            thread = threading.Thread(target=work, name=f"simulate-{run_id}", daemon=True)
            job["thread"] = thread
            thread.start()
            return self.status(run_id)

    def pause(self, run_id):
        self.path(run_id)
        with self.lock:
            if run_id in self.jobs:
                self.jobs[run_id]["stop"].set()
            return self.status(run_id)

    def make_branch(self, run_id, payload):
        if self.busy(run_id):
            raise SimError("RUN_BUSY", "Pause the source run before branching.")
        with RunStore(self.path(run_id)) as store:
            parent_year = payload.get("year", store.latest_year)
            intervention = {"kind": payload.get("kind"), "factor": payload.get("factor"), "province": payload.get("province")}
            # Branch ID is deterministic; temporary directory name is local bookkeeping.
            destination = self.root/f"branch-{run_id}-{time.time_ns()}"
            with branch(store, parent_year, destination, intervention) as new:
                with self.lock:
                    self.paths[new.manifest["id"]] = new.manifest_path
                return summary(new)

    def world(self, run_id, year):
        with RunStore(self.path(run_id)) as store:
            year = store.latest_year if year is None else year
            key = (run_id, year)
            with self.lock:
                cached = self.cache.get(key)
            if cached is not None:
                return {**cached, "summary": {**cached["summary"], "latest_year": store.latest_year}}
            data = map_data(store, year)
            with self.lock:
                if len(self.cache) > 24:
                    self.cache.clear()
                self.cache[key] = data
            return data

    def stop_all(self):
        with self.lock:
            threads = []
            for job in self.jobs.values():
                job["stop"].set()
                threads.append(job["thread"])
        for thread in threads:
            thread.join(timeout=10)


class Handler(BaseHTTPRequestHandler):
    server_version = "WorldAtlas/0.1"

    def __init__(self, *args, atlas: Atlas, **kwargs):
        self.atlas = atlas
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        if args and isinstance(args[0], str) and "/api/job/" in args[0]:
            return
        super().log_message(format, *args)

    def respond(self, body, status=200, content_type="application/json; charset=utf-8", download=None):
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if not isinstance(body, bytes) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(raw)

    def error(self, exc):
        code = getattr(exc, "code", "INVALID_INPUT")
        status = 404 if code == "NOT_FOUND" else 409 if code in ("RUN_BUSY", "RUN_EXISTS") else 400
        self.respond({"ok": False, "error": {"code": code, "message": str(exc)}}, status)

    def do_GET(self):
        try:
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)
            q = lambda key, default=None: query.get(key, [default])[0]
            year = int(q("year")) if q("year") is not None else None
            parts = path.strip("/").split("/")
            if path == "/api/runs":
                return self.respond({"runs": self.atlas.list_runs(), "presets": PRESETS})
            if len(parts) == 3 and parts[:2] == ["api", "job"]:
                return self.respond(self.atlas.status(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "run"]:
                run_id, operation = parts[2:]
                if operation == "world":
                    return self.respond(self.atlas.world(run_id, year))
                with RunStore(self.atlas.path(run_id)) as store:
                    if operation == "timeline":
                        return self.respond({"timeline": store.timeline(), "start_year": store.manifest["start_year"]})
                    if operation == "events":
                        return self.respond({"events": store.events(year, q("entity"), int(q("limit", 100)), event_type=q("type"))})
                    if operation == "event":
                        return self.respond(store.event(q("id", "")))
                    if operation == "dossier":
                        return self.respond(dossier(store, q("kind", "province"), int(q("id", 0)), year))
                    if operation == "ledger":
                        return self.respond({"ledger": store.ledger(store.latest_year if year is None else year)})
                    if operation == "compare":
                        with RunStore(self.atlas.path(q("other", ""))) as other:
                            return self.respond(compare(store, other, min(store.latest_year, other.latest_year) if year is None else year))
            if len(parts) == 2 and parts[0] == "download":
                with self.atlas.lock:
                    file = self.atlas.downloads.get(parts[1])
                if file is None:
                    raise SimError("NOT_FOUND", "Export download is unavailable.")
                return self.respond(file.read_bytes(), content_type="application/zip", download="world-history.zip")
            web = Path(__file__).parent/"web"
            file = (web/("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not file.is_relative_to(web.resolve()) or not file.is_file():
                raise SimError("NOT_FOUND", "Page does not exist.")
            return self.respond(file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        except (SimError, ValueError, TypeError, OSError) as exc:
            self.error(exc)

    def do_POST(self):
        try:
            # No CORS; reject browser cross-origin writes and non-JSON form submissions.
            origin = self.headers.get("Origin")
            accepted = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if origin and origin not in accepted:
                raise SimError("INVALID_ORIGIN", "Write requests must come from this local atlas.")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise SimError("INVALID_INPUT", "Send an application/json request.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 1_048_576:
                raise SimError("INVALID_INPUT", "Request is too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise SimError("INVALID_INPUT", "Request must be a JSON object.")
            parts = urlparse(self.path).path.strip("/").split("/")
            if parts == ["api", "generate"]:
                return self.respond(self.atlas.generate(payload), 201)
            if len(parts) == 4 and parts[:2] == ["api", "run"]:
                run_id, operation = parts[2:]
                if operation == "simulate":
                    return self.respond(self.atlas.start(run_id, payload.get("years", 100)), 202)
                if operation == "pause":
                    return self.respond(self.atlas.pause(run_id))
                if operation == "branch":
                    return self.respond(self.atlas.make_branch(run_id, payload), 201)
                if operation == "export":
                    with RunStore(self.atlas.path(run_id)) as store:
                        key = f"{run_id}-{time.time_ns()}"
                        result = export_run(store, store.directory/"exports"/key, payload.get("year"))
                    with self.atlas.lock:
                        self.atlas.downloads[key] = Path(result["archive"])
                    return self.respond({"download": f"/download/{key}", "year": result["year"]})
                if operation == "validate":
                    if self.atlas.busy(run_id):
                        raise SimError("RUN_BUSY", "Pause the run before validating.")
                    with RunStore(self.atlas.path(run_id)) as store:
                        return self.respond(store.validate(payload.get("deep", False)))
            raise SimError("NOT_FOUND", "Operation does not exist.")
        except (SimError, ValueError, TypeError, OSError) as exc:
            self.error(exc)


def serve(runs_dir: Path, port=8765, manifest=None):
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise SimError("INVALID_PARAMETERS", "Choose a port from 1,024 to 65,535.")
    atlas = Atlas(runs_dir, manifest)
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, atlas=atlas))
    print(f"World History Atlas: http://127.0.0.1:{port}", flush=True)
    print(f"Run folder: {atlas.root}", flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        atlas.stop_all()
        server.server_close()
