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

    Each driver's MAX_PER_KEY fastest laps per (track, config, car, user) are
    kept, so the files stay small and are exactly the leaderboard payload for
    GitHub Pages.
    """

    RECORDS_FILE = "records.json"
    USERS_FILE = "users.json"
    MAX_PER_KEY = 3

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
        """The FASTEST stored record for this combo+user (or None)."""
        recs = self.records_for(track, config, car, user)
        return recs[0] if recs else None

    def records_for(self, track, config, car, user):
        """All stored records for this combo+user, fastest first."""
        key = (norm(track), norm(config), norm(car), norm(user))
        out = [r for r in self.records if record_key(r) == key]
        out.sort(key=lambda r: r.get("time_ms", 1 << 62))
        return out

    def upsert_record(self, rec):
        """Insert a record, keeping each driver's MAX_PER_KEY fastest laps
        per (track, config, car, user).

        Returns a (result, dropped) tuple:
          result:  "pb"      -- new personal best (including first ever lap)
                   "top3"    -- entered the driver's top MAX_PER_KEY, not best
                   "ignored" -- slower than (or equal to) their existing laps
          dropped: the record that fell out of the top MAX_PER_KEY, or None.
        A lap whose time EQUALS an already-stored lap is "ignored" (a new lap
        never replaces an equal existing one). Also registers the user.
        """
        self._remember_user(rec.get("user"))
        new_ms = rec.get("time_ms")
        if new_ms is None:
            return ("ignored", None)
        existing = self.records_for(rec.get("track"), rec.get("config"),
                                    rec.get("car"), rec.get("user"))
        for r in existing:
            if r.get("time_ms") == new_ms:
                return ("ignored", None)
        if len(existing) >= self.MAX_PER_KEY and \
                new_ms > existing[self.MAX_PER_KEY - 1].get("time_ms", 1 << 62):
            return ("ignored", None)

        best = existing[0].get("time_ms", 1 << 62) if existing else None
        self.records.append(rec)
        dropped = None
        kept = existing + [rec]
        kept.sort(key=lambda r: r.get("time_ms", 1 << 62))
        if len(kept) > self.MAX_PER_KEY:
            dropped = kept[self.MAX_PER_KEY]
            self.records.remove(dropped)
        result = "pb" if (best is None or new_ms < best) else "top3"
        return (result, dropped)
