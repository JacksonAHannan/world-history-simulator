"""Typed state and portable, exact snapshot/patch encoding. Never deserialize pickle."""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import json
import struct
from typing import Any

import numpy as np

from .config import SimError, canonical

AGE_BANDS = 18  # 0–4, …, 80–84, 85+
STRATUM_FIELDS = ("id", "province", "language", "community", "belief", "status")
STOCK_FIELDS = ("food", "timber", "ore", "fossil", "pollution", "roads", "sanitation",
                "schooling", "urban", "divergence", "last_split", "control", "known", "adopted")


@dataclass
class World:
    provinces: list[dict]
    edges: list[dict]
    grid: dict
    report: dict

    def to_dict(self) -> dict:
        return {"provinces": self.provinces, "edges": self.edges, "grid": self.grid, "report": self.report}

    @classmethod
    def from_dict(cls, data: dict) -> "World":
        return cls(**data)

    @property
    def size(self) -> int:
        return len(self.provinces)


@dataclass
class State:
    year: int
    arrays: dict[str, np.ndarray]
    languages: dict[str, dict]
    polities: dict[str, dict]
    communities: dict[str, dict]
    beliefs: dict[str, dict]
    ancestry: dict[str, dict]
    settlements: dict[str, dict] = field(default_factory=dict)
    conflicts: dict[str, dict] = field(default_factory=dict)
    next_ids: dict[str, int] = field(default_factory=lambda: {"stratum": 0, "language": 0, "polity": 0, "conflict": 0})
    last_events: dict[str, str] = field(default_factory=dict)

    def population(self, size: int) -> np.ndarray:
        return np.bincount(self.arrays["strata"][:, 1], weights=self.arrays["cohorts"].sum(axis=(1, 2)),
                           minlength=size).astype(np.int64)

    def metadata(self) -> dict:
        return {"year": self.year, "languages": self.languages, "polities": self.polities,
                "communities": self.communities, "beliefs": self.beliefs, "ancestry": self.ancestry,
                "settlements": self.settlements,
                "conflicts": self.conflicts, "next_ids": self.next_ids, "last_events": self.last_events}

    def clone(self) -> "State":
        # Catalog entries are immutable inputs; proposal/commit writers replace
        # changed entries. Avoid copying every historical word/loan every year.
        metadata = {k: v.copy() if isinstance(v, dict) else v for k, v in self.metadata().items()}
        return State(**metadata, arrays={k: v.copy() for k, v in self.arrays.items()})

    def freeze(self) -> None:
        for a in self.arrays.values():
            a.flags.writeable = False


def encode_state(state: State) -> bytes:
    descriptors, parts = [], []
    for name, array in sorted(state.arrays.items()):
        a = np.ascontiguousarray(array, dtype=array.dtype.newbyteorder("<"))
        raw = a.tobytes()
        descriptors.append({"name": name, "dtype": a.dtype.str, "shape": list(a.shape), "bytes": len(raw)})
        parts.append(raw)
    header = canonical({"format": 1, "metadata": state.metadata(), "arrays": descriptors})
    return b"WHS1" + struct.pack("<I", len(header)) + header + b"".join(parts)


def _unpack(data: bytes, magic: bytes) -> tuple[dict, memoryview]:
    if data[:4] != magic or len(data) < 8:
        raise SimError("CORRUPT_SAVE", "Invalid state payload.")
    header_size, = struct.unpack("<I", data[4:8])
    if header_size > len(data)-8:
        raise SimError("CORRUPT_SAVE", "Truncated state header.")
    try:
        return json.loads(data[8:8+header_size]), memoryview(data)[8+header_size:]
    except (ValueError, UnicodeError) as exc:
        raise SimError("CORRUPT_SAVE", "Unreadable state header.") from exc


def decode_state(data: bytes) -> State:
    header, body = _unpack(data, b"WHS1")
    if header.get("format") != 1:
        raise SimError("INCOMPATIBLE_VERSION", "Unsupported checkpoint encoding.")
    arrays, offset = {}, 0
    for d in header["arrays"]:
        end = offset+d["bytes"]
        if end > len(body) or np.dtype(d["dtype"]).kind not in "ifu":
            raise SimError("CORRUPT_SAVE", "Invalid numeric array.")
        arrays[d["name"]] = np.frombuffer(body[offset:end], dtype=d["dtype"]).reshape(d["shape"]).copy()
        offset = end
    if offset != len(body):
        raise SimError("CORRUPT_SAVE", "Unexpected trailing state data.")
    return State(**header["metadata"], arrays=arrays)


def state_hash(state: State) -> str:
    return hashlib.sha256(encode_state(state)).hexdigest()


def encode_patch(before: State, after: State) -> bytes:
    """XOR float/int bytes, so replay restores every bit without rounding drift."""
    descriptors, parts = [], []
    for name, array in sorted(after.arrays.items()):
        raw = np.ascontiguousarray(array, dtype=array.dtype.newbyteorder("<")).view(np.uint8).ravel()
        old = before.arrays.get(name)
        mode = "replace"
        if old is not None and old.shape == array.shape and old.dtype == array.dtype:
            raw = np.bitwise_xor(raw, np.ascontiguousarray(old).view(np.uint8).ravel())
            mode = "xor"
        descriptors.append({"name": name, "dtype": array.dtype.str, "shape": list(array.shape),
                            "bytes": raw.size, "mode": mode})
        parts.append(raw.tobytes())
    old_meta, new_meta = before.metadata(), after.metadata()
    metadata = {}
    for key, value in new_meta.items():
        if isinstance(value, dict) and isinstance(old_meta.get(key), dict):
            changes = {k: v for k, v in value.items() if k not in old_meta[key] or old_meta[key][k] != v}
            removed = sorted(set(old_meta[key])-set(value))
            if changes or removed:
                metadata[key] = {"changes": changes, "removed": removed}
        elif value != old_meta.get(key):
            metadata[key] = {"replace": value}
    header = canonical({"format": 1, "from_year": before.year, "to_year": after.year,
                        "metadata": metadata, "arrays": descriptors})
    return b"WHP1"+struct.pack("<I", len(header))+header+b"".join(parts)


def apply_patch(state: State, patch: bytes) -> State:
    header, body = _unpack(patch, b"WHP1")
    if header.get("format") != 1:
        raise SimError("INCOMPATIBLE_VERSION", "Unsupported annual patch encoding.")
    if header["from_year"] != state.year or header["to_year"] != state.year+1:
        raise SimError("CORRUPT_SAVE", "Nonsequential annual commit.")
    metadata = {k: v.copy() if isinstance(v, dict) else v for k, v in state.metadata().items()}
    arrays, offset = {}, 0
    for key, diff in header["metadata"].items():
        if "replace" in diff:
            metadata[key] = diff["replace"]
        else:
            metadata[key].update(diff["changes"])
            for removed in diff["removed"]:
                metadata[key].pop(removed, None)
    for d in header["arrays"]:
        if np.dtype(d["dtype"]).kind not in "ifu":
            raise SimError("CORRUPT_SAVE", "Invalid numeric patch array.")
        end = offset+d["bytes"]
        if end > len(body):
            raise SimError("CORRUPT_SAVE", "Truncated annual patch.")
        data = np.frombuffer(body[offset:end], dtype=np.uint8)
        if d["mode"] == "xor":
            data = np.bitwise_xor(data, np.ascontiguousarray(state.arrays[d["name"]]).view(np.uint8).ravel())
        arrays[d["name"]] = np.frombuffer(data.tobytes(), dtype=d["dtype"]).reshape(d["shape"]).copy()
        offset = end
    if offset != len(body):
        raise SimError("CORRUPT_SAVE", "Unexpected annual patch data.")
    return State(**metadata, arrays=arrays)


@dataclass
class Event:
    type: str
    rule: str
    participants: list[str]
    conditions: dict[str, Any]
    deltas: dict[str, Any]
    draw: float | None = None
    parents: list[str] = field(default_factory=list)
    text: str = ""
    uncertainty: str = "simulated; uncalibrated rule"

    def payload(self, year: int) -> dict:
        return {"year": year, "type": self.type, "rule_id": self.rule, "rule_version": 1,
                "participants": self.participants, "conditions": self.conditions,
                "deltas": self.deltas, "draw": self.draw, "parents": self.parents,
                "text": self.text, "uncertainty": self.uncertainty}
