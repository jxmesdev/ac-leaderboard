# JSON-backed storage for leaderboard records and the global user list.
# Python 3.3 compatible. No dependency on the in-game `ac` module.

import datetime
import io
import json
import os


def make_record(track, config, car, user, time_ms, source="manual", date=None):
    """Build a leaderboard record dict with a UTC timestamp."""
    if date is None:
        date = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "track": (track or "").strip(),
        "config": (config or "").strip(),
        "car": (car or "").strip(),
        "user": (user or "").strip(),
        "time_ms": int(time_ms),
        "date": date,
        "source": source,
    }


def norm(s):
    """Normalise a key component for case-insensitive matching."""
    if s is None:
        return ""
    return str(s).strip().lower()


def combo_key(track, config, car):
    return (norm(track), norm(config), norm(car))


def record_key(rec):
    return (norm(rec.get("track")), norm(rec.get("config")),
            norm(rec.get("car")), norm(rec.get("user")))


def _atomic_write_json(path, data):
    """Write JSON to `path` atomically (temp file + os.replace)."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        f.write(text)
        f.write("\n")
    os.replace(tmp, path)


def _read_json(path, default):
    if not os.path.isfile(path):
        return default
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, IOError, OSError):
        return default


class Store(object):
    """Reads/writes records.json and users.json in a data directory.

    Only the best (lowest) time per (track, config, car, user) is kept, so the
    files stay small and are exactly the leaderboard payload for GitHub Pages.
    """

    RECORDS_FILE = "records.json"
    USERS_FILE = "users.json"

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.records = []       # list of record dicts
        self.users = []         # list of display names (order preserved)

    # -- paths ------------------------------------------------------------
    @property
    def records_path(self):
        return os.path.join(self.data_dir, self.RECORDS_FILE)

    @property
    def users_path(self):
        return os.path.join(self.data_dir, self.USERS_FILE)

    def data_paths(self):
        return [self.records_path, self.users_path]

    # -- loading ----------------------------------------------------------
    def load(self):
        recs = _read_json(self.records_path, [])
        if not isinstance(recs, list):
            recs = []
        self.records = [r for r in recs if isinstance(r, dict)]

        users = _read_json(self.users_path, [])
        if not isinstance(users, list):
            users = []
        self.users = []
        for u in users:
            self._remember_user(u)
        return self

    # -- persistence ------------------------------------------------------
    def save(self):
        _atomic_write_json(self.records_path, self.records)
        _atomic_write_json(self.users_path, self.users)

    # -- users ------------------------------------------------------------
    def _remember_user(self, name):
        """Add a display name if not already present (case-insensitive)."""
        if name is None:
            return False
        name = str(name).strip()
        if not name:
            return False
        for existing in self.users:
            if norm(existing) == norm(name):
                return False
        self.users.append(name)
        return True

    def add_user(self, name):
        """Public: create a user. Returns True if newly added."""
        return self._remember_user(name)

    def all_users(self):
        """Every user ever seen: the users list plus any user in a record."""
        out = list(self.users)
        seen = set(norm(u) for u in out)
        for r in self.records:
            u = r.get("user")
            if u is None:
                continue
            u = str(u).strip()
            if u and norm(u) not in seen:
                out.append(u)
                seen.add(norm(u))
        return out

    # -- records ----------------------------------------------------------
    def find_record(self, track, config, car, user):
        key = (norm(track), norm(config), norm(car), norm(user))
        for r in self.records:
            if record_key(r) == key:
                return r
        return None

    def upsert_record(self, rec):
        """Insert or update a record, keeping only the best time per key.

        Returns "new" (first time for this combo/user), "improved" (beat the
        previous best), or "ignored" (existing time was as good or better).
        Also registers the user in the users list.
        """
        self._remember_user(rec.get("user"))
        existing = self.find_record(rec.get("track"), rec.get("config"),
                                    rec.get("car"), rec.get("user"))
        new_ms = rec.get("time_ms")
        if existing is None:
            self.records.append(rec)
            return "new"
        if new_ms is not None and new_ms < existing.get("time_ms", 1 << 62):
            existing.update(rec)
            return "improved"
        return "ignored"
