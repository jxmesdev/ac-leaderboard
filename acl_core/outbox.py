# Durable local queue of not-yet-synced changes. Python 3.3 compatible.
#
# The main thread NEVER writes into the shared docs/data directory: every lap,
# driver add, and track asset is appended here (a gitignored _localdata dir),
# and the git sync worker replays the queue onto a fresh checkout of the
# remote's state. Entries survive crashes (atomic JSON writes) and are only
# removed after the push that contains them succeeds.

import io
import json
import os
import threading


def _rel_of(entry):
    """The staged rel path an entry references, or None."""
    if entry.get("type") == "lap":
        return (entry.get("record") or {}).get("telemetry")
    if entry.get("type") == "asset":
        return entry.get("rel")
    return None


def _atomic_write(path, text):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class Outbox(object):
    """Thread-safe, disk-backed queue of pending sync operations.

    Entry types:
      {"id": n, "type": "lap",   "record": {...}}          # record incl.
                                                           # "telemetry" rel
      {"id": n, "type": "user",  "name": "James"}
      {"id": n, "type": "asset", "rel": "trackmaps/x.png"}
    Payload bytes for laps ("telemetry" rel path) and assets live under
    <local_dir>/assets/, flat, named by the rel path with separators
    flattened -- immune to git operations on the repo.
    """

    def __init__(self, local_dir):
        self.local_dir = local_dir
        self.path = os.path.join(local_dir, "outbox.json")
        self.assets_dir = os.path.join(local_dir, "assets")
        self._lock = threading.Lock()
        self._entries = []
        self._next_id = 1
        self._load()
        self._gc_stage()

    # -- persistence (call with lock held) --------------------------------
    def _load(self):
        try:
            with io.open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries") or []
            self._entries = [e for e in entries if isinstance(e, dict)]
            self._next_id = int(data.get("next_id") or 1)
        except (IOError, OSError, ValueError):
            self._entries = []
            self._next_id = 1

    def _save(self):
        _atomic_write(self.path, json.dumps(
            {"next_id": self._next_id, "entries": self._entries},
            ensure_ascii=False, indent=1))

    def _gc_stage(self):
        """Delete staged files no entry references (left by a crash between
        push-success and remove, or interrupted writes)."""
        refs = set()
        for e in self._entries:
            rel = _rel_of(e)
            if rel:
                refs.add(os.path.basename(self._asset_file(rel)))
        try:
            names = os.listdir(self.assets_dir)
        except (IOError, OSError):
            return
        for name in names:
            if name not in refs:
                try:
                    os.remove(os.path.join(self.assets_dir, name))
                except (IOError, OSError):
                    pass

    def _asset_file(self, rel):
        flat = rel.replace("\\", "__").replace("/", "__")
        return os.path.join(self.assets_dir, flat)

    def _stage_bytes(self, rel, data):
        path = self._asset_file(rel)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        tmp = path + ".tmp"
        with io.open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    # -- public API -------------------------------------------------------
    def add_lap(self, record, payload_text=None):
        """Queue a lap record; payload_text is the telemetry JSON (or None).

        `record` is copied. If it links telemetry, the payload is staged
        locally so the repo file can be (re)created at replay time.
        """
        with self._lock:
            rec = dict(record)
            e = {"id": self._next_id, "type": "lap", "record": rec}
            self._next_id += 1
            rel = rec.get("telemetry")
            if rel and payload_text is not None:
                self._stage_bytes(rel, payload_text.encode("utf-8"))
            self._entries.append(e)
            self._save()
            return e["id"]

    def add_user(self, name):
        with self._lock:
            e = {"id": self._next_id, "type": "user", "name": name}
            self._next_id += 1
            self._entries.append(e)
            self._save()
            return e["id"]

    def add_asset(self, rel, src_path):
        """Queue a data-dir file (trackmap/edges/sections) from a staged copy.

        Replaces any earlier pending entry for the same rel path.
        """
        try:
            with io.open(src_path, "rb") as f:
                data = f.read()
        except (IOError, OSError):
            return None
        with self._lock:
            self._entries = [x for x in self._entries
                             if not (x.get("type") == "asset" and
                                     x.get("rel") == rel)]
            e = {"id": self._next_id, "type": "asset", "rel": rel}
            self._next_id += 1
            self._stage_bytes(rel, data)
            self._entries.append(e)
            self._save()
            return e["id"]

    def snapshot(self):
        """Copy of the current entries (worker replays these)."""
        with self._lock:
            return [dict(e) for e in self._entries]

    def remove(self, ids):
        """Drop entries whose ids are in `ids` (after a successful push)."""
        ids = set(ids)
        with self._lock:
            removed, keep = [], []
            for e in self._entries:
                (removed if e.get("id") in ids else keep).append(e)
            self._entries = keep
            kept_rels = set()
            for e in keep:
                rel = _rel_of(e)
                if rel:
                    kept_rels.add(rel)
            for e in removed:
                rel = _rel_of(e)
                if rel and rel not in kept_rels:
                    try:
                        os.remove(self._asset_file(rel))
                    except (IOError, OSError):
                        pass
            self._save()

    def staged_path(self, rel):
        """Local staged file for a rel path (may not exist)."""
        return self._asset_file(rel)

    def has_asset(self, rel):
        with self._lock:
            for e in self._entries:
                if e.get("type") == "asset" and e.get("rel") == rel:
                    return True
            return False

    def count(self):
        with self._lock:
            return len(self._entries)

    def lap_count(self):
        with self._lock:
            return sum(1 for e in self._entries if e.get("type") == "lap")
