"""Transactional SQLite event ledger and compressed, exact annual state patches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import zlib

from .config import SimError, canonical, check_manifest, check_simulation_version, digest
from .engine import validate_ledger, validate_state
from .geography import generate_world, validate_geography
from .initialization import initialize
from .model import World, apply_patch, decode_state, encode_patch, encode_state, state_hash

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE events (id TEXT PRIMARY KEY, year INTEGER NOT NULL, sequence INTEGER NOT NULL,
                     type TEXT NOT NULL, hash TEXT NOT NULL, data BLOB NOT NULL,
                     UNIQUE(year, sequence));
CREATE INDEX event_year ON events(year, sequence);
CREATE INDEX event_type ON events(type, year);
CREATE TABLE event_entities (event_id TEXT NOT NULL REFERENCES events(id), entity TEXT NOT NULL,
                            PRIMARY KEY(entity, event_id));
CREATE TABLE commits (year INTEGER PRIMARY KEY, patch BLOB NOT NULL, ledger BLOB NOT NULL,
                      before_hash TEXT NOT NULL, state_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
                      population INTEGER NOT NULL, event_count INTEGER NOT NULL);
CREATE TABLE snapshots (year INTEGER PRIMARY KEY, state BLOB NOT NULL, hash TEXT NOT NULL);
"""


class RunStore:
    def __init__(self, manifest_path: str | Path):
        self.manifest_path = Path(manifest_path).resolve()
        self.directory = self.manifest_path.parent
        try:
            self.manifest = json.loads(self.manifest_path.read_text())
        except (OSError, ValueError) as exc:
            raise SimError("INVALID_MANIFEST", f"Cannot read manifest: {self.manifest_path}") from exc
        check_manifest(self.manifest)
        if not (self.directory/"history.sqlite").is_file():
            raise SimError("CORRUPT_SAVE", "Run database is missing.")
        self.connection = sqlite3.connect(self.directory/"history.sqlite", timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.world = World.from_dict(json.loads(zlib.decompress(self.meta("world"))))
        if self.meta("manifest_hash").decode() != hashlib.sha256(canonical(self.manifest)).hexdigest():
            raise SimError("INVALID_MANIFEST", "Manifest does not match this run's database.")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.connection.close()

    def meta(self, key: str) -> bytes:
        row = self.connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        if row is None:
            raise SimError("CORRUPT_SAVE", f"Missing run metadata: {key}.")
        return row[0]

    @property
    def latest_year(self) -> int:
        return int(self.meta("latest_year"))

    @property
    def event_hash(self) -> str:
        return self.meta("event_hash").decode()

    @classmethod
    def create(cls, directory: str | Path, manifest: dict) -> "RunStore":
        check_manifest(manifest)
        check_simulation_version(manifest)
        directory = Path(directory).resolve()
        if (directory/"manifest.json").exists() or (directory/"history.sqlite").exists():
            raise SimError("RUN_EXISTS", "This folder already contains a run. Choose a new folder.")
        world = generate_world(manifest)
        state = initialize(world, manifest)
        validate_state(state, world)
        directory.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(directory/"history.sqlite")
        try:
            conn.executescript(SCHEMA)
            raw = encode_state(state)
            values = {"world": zlib.compress(canonical(world.to_dict()), 6), "latest_year": b"0",
                      "event_hash": ("0"*64).encode(), "state_hash": hashlib.sha256(raw).hexdigest().encode(),
                      "manifest_hash": hashlib.sha256(canonical(manifest)).hexdigest().encode()}
            with conn:
                conn.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", values.items())
                conn.execute("INSERT INTO snapshots VALUES (?,?,?)", (0, zlib.compress(raw, 6), values["state_hash"].decode()))
        finally:
            conn.close()
        (directory/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        return cls(directory/"manifest.json")

    def load_state(self, year: int | None = None):
        year = self.latest_year if year is None else year
        if isinstance(year, bool) or not isinstance(year, int) or not 0 <= year <= self.latest_year:
            raise SimError("UNAVAILABLE_CHECKPOINT", f"Choose an offset from 0 to {self.latest_year}.")
        checkpoint = self.connection.execute("SELECT * FROM snapshots WHERE year<=? ORDER BY year DESC LIMIT 1", (year,)).fetchone()
        if checkpoint is None:
            raise SimError("UNAVAILABLE_CHECKPOINT", "No preceding checkpoint exists.")
        try:
            state = decode_state(zlib.decompress(checkpoint["state"]))
            expected = checkpoint["hash"]
            for record in self.connection.execute("SELECT year,patch,state_hash FROM commits WHERE year>? AND year<=? ORDER BY year", (state.year, year)):
                state = apply_patch(state, zlib.decompress(record["patch"]))
                expected = record["state_hash"]
        except (zlib.error, ValueError, KeyError, TypeError) as exc:
            raise SimError("CORRUPT_SAVE", "A checkpoint or annual patch is damaged.") from exc
        if state.year != year or state_hash(state) != expected:
            raise SimError("CORRUPT_SAVE", "Historical replay failed its state hash.")
        return state

    def append(self, before, after, events: list[dict], ledger: dict, chain: str) -> str:
        check_simulation_version(self.manifest)
        raw_after = encode_state(after)
        current_hash = hashlib.sha256(raw_after).hexdigest()
        patch = zlib.compress(encode_patch(before, after), 1)
        packed_ledger = zlib.compress(canonical(ledger), 1)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if before.year != self.latest_year:
                raise SimError("STALE_STATE", "Another writer has advanced this run.")
            before_hash = self.meta("state_hash").decode()
            self.connection.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)",
                                        [(e["id"], after.year, e["sequence"], e["type"], e["hash"], zlib.compress(canonical(e), 1)) for e in events])
            self.connection.executemany("INSERT INTO event_entities VALUES (?,?)",
                                        [(e["id"], entity) for e in events for entity in e["participants"]])
            self.connection.execute("INSERT INTO commits VALUES (?,?,?,?,?,?,?,?)",
                                    (after.year, patch, packed_ledger, before_hash, current_hash, chain,
                                     int(after.arrays["cohorts"].sum()), len(events)))
            if after.year % self.manifest["parameters"]["snapshot_interval"] == 0:
                self.connection.execute("INSERT INTO snapshots VALUES (?,?,?)", (after.year, zlib.compress(raw_after, 6), current_hash))
            self.connection.executemany("UPDATE metadata SET value=? WHERE key=?",
                                        [(str(after.year).encode(), "latest_year"), (chain.encode(), "event_hash"),
                                         (current_hash.encode(), "state_hash")])
        return current_hash

    def ledger(self, year: int) -> dict | None:
        row = self.connection.execute("SELECT ledger FROM commits WHERE year=?", (year,)).fetchone()
        return json.loads(zlib.decompress(row[0])) if row else None

    def events(self, year: int | None = None, entity: str | None = None, limit: int = 100,
               include_accounting: bool = False, since: int = 0, event_type: str | None = None) -> list[dict]:
        year = self.latest_year if year is None else year
        clauses, args = ["e.year<=?", "e.year>=?"], [year, since]
        join = ""
        if entity:
            join = " JOIN event_entities x ON x.event_id=e.id"
            clauses.append("x.entity=?")
            args.append(entity)
        if not include_accounting:
            clauses.append("e.type!='YearCommitted'")
        if event_type:
            clauses.append("e.type=?")
            args.append(event_type)
        args.append(max(1, min(1000, int(limit))))
        query = "SELECT e.data FROM events e"+join+" WHERE "+" AND ".join(clauses)+" ORDER BY e.year DESC,e.sequence DESC LIMIT ?"
        return [json.loads(zlib.decompress(r[0])) for r in self.connection.execute(query, args)]

    def event(self, event_id: str) -> dict:
        row = self.connection.execute("SELECT data FROM events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise SimError("NOT_FOUND", "Event does not exist in this run.")
        return json.loads(zlib.decompress(row[0]))

    def timeline(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT year,population,event_count FROM commits ORDER BY year")]

    def validate(self, deep: bool = False) -> dict:
        # WAL writers may advance while auditing. Keep all tables and metadata
        # in the same committed read view to avoid spurious corruption reports.
        with self.connection:
            self.connection.execute("BEGIN")
            return self._validate(deep)

    def _validate(self, deep: bool) -> dict:
        geography = validate_geography(self.world)
        checks = 0
        previous_hash = self.connection.execute("SELECT hash FROM snapshots WHERE year=0").fetchone()[0]
        chain = "0"*64
        known_events = set()
        state = self.load_state(0) if deep else None
        for row in self.connection.execute("SELECT * FROM commits ORDER BY year"):
            ledger = json.loads(zlib.decompress(row["ledger"]))
            validate_ledger(ledger)
            if row["year"] != checks+1 or row["before_hash"] != previous_hash:
                raise SimError("CORRUPT_SAVE", "Commit chain is incomplete.")
            if row["population"] != sum(ledger["population_close"]):
                raise SimError("CORRUPT_SAVE", "Stored population differs from the annual ledger.")
            if deep:
                if not (state.population(self.world.size) == ledger["population_open"]).all():
                    raise SimError("CORRUPT_SAVE", "Opening population differs from the replayed state.")
                state = apply_patch(state, zlib.decompress(row["patch"]))
                validate_state(state, self.world)
                if state_hash(state) != row["state_hash"]:
                    raise SimError("CORRUPT_SAVE", "Annual replay hash differs.")
                if not (state.population(self.world.size) == ledger["population_close"]).all():
                    raise SimError("CORRUPT_SAVE", "Closing population differs from the replayed state.")
            event_count, receipts = 0, 0
            for record in self.connection.execute("SELECT data FROM events WHERE year=? ORDER BY sequence", (row["year"],)):
                event = json.loads(zlib.decompress(record[0]))
                if event["year"] != row["year"] or event["sequence"] != event_count:
                    raise SimError("CORRUPT_SAVE", "Event year or sequence differs from its commit.")
                if any(parent not in known_events for parent in event["parents"]+event.get("related_events", [])):
                    raise SimError("FAILED_INVARIANT", "Event provenance points forward or outside the run.")
                if not event["rule_id"] or not event["deltas"] or not event["text"]:
                    raise SimError("FAILED_INVARIANT", "Event has incomplete provenance.")
                payload = {k: v for k, v in event.items() if k not in ("id", "hash")}
                chain = hashlib.sha256(chain.encode()+canonical(payload)).hexdigest()
                if chain != event["hash"] or event["id"] != f"e{row['year']:05d}-{event_count:04d}-{chain[:12]}":
                    raise SimError("CORRUPT_SAVE", "Event content hash differs.")
                if event["type"] == "YearCommitted":
                    if event["conditions"]["ledger_hash"] != digest(ledger):
                        raise SimError("CORRUPT_SAVE", "Annual ledger differs from its immutable event receipt.")
                    receipts += 1
                    if event_count != row["event_count"]-1:
                        raise SimError("CORRUPT_SAVE", "Accounting receipt is not the final annual event.")
                known_events.add(event["id"])
                event_count += 1
            if event_count != row["event_count"] or receipts != 1:
                raise SimError("CORRUPT_SAVE", "Annual event count or accounting receipt is missing.")
            if chain != row["event_hash"]:
                raise SimError("CORRUPT_SAVE", "Annual event chain differs.")
            checks += 1
            previous_hash = row["state_hash"]
        if checks != self.latest_year or chain != self.event_hash:
            raise SimError("CORRUPT_SAVE", "Latest metadata does not reconcile.")
        summary = validate_state(self.load_state(), self.world)
        return {"ok": True, "years_checked": checks, "events_checked": len(known_events), "geography": geography,
                "state": summary, "state_hash": self.meta("state_hash").decode(), "event_hash": chain,
                "replayed_every_year": deep, "historical_calibration": "not performed"}
