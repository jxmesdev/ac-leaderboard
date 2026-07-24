# Background git sync engine. Python 3.3 compatible.
#
# Two rigs share one repo, so the naive commit-then-pull flow conflicts (both
# rewrite the same JSON tail) or silently deletes the other rig's laps (a
# stale in-memory list re-saved over pulled data). This engine avoids both by
# never trusting local state:
#
#   fetch -> salvage local-only data into the outbox -> reset --hard to
#   origin -> replay the outbox onto the remote's files -> commit -> push
#   (rejected? start over, bounded retries)
#
# Safety first: reset --hard is destructive, so every cycle preflights that
# repo_path IS the repo toplevel, that the checked-out branch is the sync
# branch, and that nothing outside data_subdir would be touched -- a rig is
# always clean there, and anything else (a dev checkout, local experiments)
# makes the engine refuse rather than destroy.
#
# Runs on a worker thread; never calls ac.*; reports via plain strings
# (on_status) and a data_version counter the UI polls to reload. The UI
# reads a snapshot COPY of the data files (view dir) so a mid-cycle git
# write can never be half-read.

import hashlib
import io
import json
import os
import subprocess
import threading
import time

from acl_core import storage

_CREATE_NO_WINDOW = 0x08000000
_IS_WINDOWS = (os.name == "nt")
GIT_TIMEOUT_S = 90       # a hung push (credential prompt, dead net) must not
                         # wedge the worker for the whole session
PUSH_ATTEMPTS = 3        # re-fetch/replay rounds when the remote moves under us
STALE_LOCK_S = 300       # a .git/index.lock older than this is from a dead git

DATA_FILES = ("records.json", "users.json")


def _popen_kwargs():
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.PIPE,
    }
    if _IS_WINDOWS:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"    # fail fast, never prompt headless
    env["GCM_INTERACTIVE"] = "never"
    kwargs["env"] = env
    return kwargs


class GitSync(object):
    """Outbox-replay git sync. See module docstring for the model."""

    def __init__(self, repo_path, data_subdir, outbox, view_dir=None,
                 branch="main", remote="origin",
                 author_name="AC Leaderboard",
                 author_email="ac-leaderboard@local", git_exe="git",
                 on_status=None, logger=None):
        self.repo_path = repo_path
        self.data_subdir = (data_subdir or "").replace("\\", "/").strip("/")
        self.outbox = outbox
        # Where the UI-facing copy of records/users.json is published after
        # each cycle (atomic replace -- safe to read any time).
        self.view_dir = view_dir
        self.branch = branch
        self.remote = remote
        self.author_name = author_name
        self.author_email = author_email
        self.git_exe = git_exe
        self.on_status = on_status
        self.logger = logger

        self.last_status = "idle"
        # Bumped whenever a cycle actually changed the data files (remote
        # laps arrived, or a repair/replay rewrote them). The main thread
        # polls it and reloads its in-memory store + UI when it moves.
        self.data_version = 0
        self._lock = threading.Lock()
        self._worker = None
        self._requested = False

    # -- public API -------------------------------------------------------
    def available(self):
        if not self.repo_path or not os.path.isdir(self.repo_path):
            return False
        return os.path.isdir(os.path.join(self.repo_path, ".git")) or \
            self._run(["rev-parse", "--is-inside-work-tree"])[0] == 0

    def request_sync(self):
        """Ask for a sync cycle. Non-blocking; coalesces bursts."""
        with self._lock:
            self._requested = True
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._drain,
                                            name="acl-gitsync")
            self._worker.daemon = True
            self._worker.start()

    def apply_outbox_locally(self):
        """No-git mode: replay the outbox straight into the data files.

        Runs on the CALLER's thread (there is no worker without git). Used
        when the install is not a clone or auto_push is off, so laps still
        land in docs/data like the old design did.
        """
        entries = self.outbox.snapshot()
        if not entries:
            return
        fp0 = self._data_fingerprint()
        try:
            self._replay(entries)
        except Exception as exc:
            self._set_status("error: local save failed: " + str(exc))
            return
        self.outbox.remove([e.get("id") for e in entries])
        self._publish_view()
        if self._data_fingerprint() != fp0:
            self.data_version += 1
        self._set_status("saved locally (no git)")

    # -- worker -----------------------------------------------------------
    def _drain(self):
        while True:
            with self._lock:
                if not self._requested:
                    # decide-and-die atomically: request_sync spawns a new
                    # worker when _worker is None, so a request that lands
                    # after this block starts a thread instead of being lost
                    self._worker = None
                    return
                self._requested = False
            self._set_status("syncing")
            try:
                ok, detail = self._sync_once()
            except Exception as exc:
                ok, detail = False, "internal: " + str(exc)
            if ok:
                self._set_status("synced")
            else:
                queued = self.outbox.lap_count()
                if queued:
                    self._set_status("error: {0} -- {1} lap(s) queued, "
                                     "will retry".format(detail, queued))
                else:
                    self._set_status("error: " + detail)

    def _dbg(self, msg):
        if self.logger:
            try:
                self.logger("gitsync: " + msg)
            except Exception:
                pass

    # -- the sync cycle ---------------------------------------------------
    def _sync_once(self):
        if not self.available():
            return False, "repo not found: " + str(self.repo_path)
        ok, why = self._preflight()
        if not ok:
            return False, why
        self._clear_stale_lock()

        fp0 = self._data_fingerprint()
        for attempt in range(PUSH_ATTEMPTS):
            self._dbg("cycle {0} start".format(attempt + 1))
            # Clear any wedge (mid-rebase from the old design or a debug
            # bat) FIRST, so the dirtiness checks below see a sane tree.
            self._run(["rebase", "--abort"])
            rc, out, err = self._run(["fetch", self.remote, self.branch])
            if rc != 0:
                return False, "offline (fetch failed): " + _first_line(err or out)

            # Prefer the per-ref remote-tracking head; FETCH_HEAD is a
            # last-writer-wins file another git process could repoint.
            remote_head = self._rev(self.remote + "/" + self.branch) or \
                self._rev("FETCH_HEAD")
            local_head = self._rev("HEAD")
            if remote_head is None:
                return False, "cannot resolve remote head"

            # SAFETY: anything local outside data_subdir (commits or
            # uncommitted tracked changes) means this is not a plain rig
            # checkout -- refuse to touch the repo rather than destroy it.
            foreign = self._foreign_changes(remote_head)
            if foreign:
                self._salvage_local_data(remote_head)
                return False, ("local changes outside {0} ({1}) -- sync "
                               "paused, resolve by hand".format(
                                   self.data_subdir, foreign))

            # Local-only DATA (stranded commits from the old design, or
            # uncommitted edits): pull the laps/users into the outbox
            # before reset --hard discards them. Replay recreates them on
            # top of the remote; identical laps dedupe in upsert.
            if (local_head != remote_head and
                    self._ahead_of(remote_head) > 0) or self._data_dirty():
                n = self._salvage_local_data(remote_head)
                if n:
                    self._dbg("salvaged {0} local-only item(s)".format(n))

            rc, out, err = self._run(["reset", "--hard", remote_head])
            if rc != 0:
                return False, "reset failed: " + _first_line(err or out)

            entries = self.outbox.snapshot()
            if entries:
                try:
                    self._replay(entries)
                except Exception as exc:
                    return False, "replay failed: " + str(exc)

            if os.path.isdir(self._data_dir()):
                rc, out, err = self._run(["add", "-A", "--",
                                          self.data_subdir])
                if rc != 0:
                    return False, "add failed: " + _first_line(err or out)

            if self._run(["diff", "--cached", "--quiet"])[0] != 0:
                msg = self._commit_message(entries)
                rc, out, err = self._run([
                    "-c", "user.name=" + self.author_name,
                    "-c", "user.email=" + self.author_email,
                    "commit", "-m", msg,
                ])
                if rc != 0:
                    return False, "commit failed: " + _first_line(err or out)
                rc, out, err = self._run(["push", self.remote,
                                          "HEAD:" + self.branch])
                if rc != 0:
                    # remote moved (the other rig pushed): replay onto the
                    # new state and try again
                    self._dbg("push rejected, retrying: " +
                              _first_line(err or out))
                    continue

            self.outbox.remove([e.get("id") for e in entries])
            self._publish_view()
            if self._data_fingerprint() != fp0:
                self.data_version += 1
                self._dbg("data changed -> version " + str(self.data_version))
            self._dbg("cycle ok")
            return True, "ok"

        return False, "push kept losing the race -- will retry"

    # -- safety preflight -------------------------------------------------
    def _preflight(self):
        """Refuse to run destructive git ops unless this looks like a rig
        checkout: repo_path is the repo TOPLEVEL and the sync branch is
        checked out. Protects a dev machine or a misconfigured repo_path
        (e.g. a subfolder of some other repo) from reset --hard."""
        if not self.data_subdir:
            return False, "data_subdir is not set -- refusing to sync"
        rc, out, _ = self._run(["rev-parse", "--show-toplevel"])
        if rc != 0 or not out.strip():
            return False, "not a git work tree"
        top = os.path.normcase(os.path.realpath(out.strip()))
        here = os.path.normcase(os.path.realpath(self.repo_path))
        if top != here:
            return False, "repo_path is not the repo root (" + top + ")"
        rc, out, _ = self._run(["symbolic-ref", "--short", "HEAD"])
        if rc != 0 or out.strip() != self.branch:
            return False, "checked-out branch is '{0}', expected '{1}'".format(
                out.strip() or "?", self.branch)
        return True, "ok"

    def _clear_stale_lock(self):
        """A git killed mid-run (timeout, AC exit) leaves .git/index.lock
        behind and poisons every later command. Old locks are safe to
        remove; a live git would have refreshed it recently."""
        lock = os.path.join(self.repo_path, ".git", "index.lock")
        try:
            if os.path.isfile(lock) and \
                    time.time() - os.path.getmtime(lock) > STALE_LOCK_S:
                os.remove(lock)
                self._dbg("removed stale index.lock")
        except (IOError, OSError):
            pass

    def _foreign_changes(self, remote_head):
        """A path outside data_subdir that local commits or tracked edits
        touch (None when clean). Untracked files never count, and neither
        do the per-rig debug snapshots (regenerable logs the send_debug
        bat rewrites; losing them to reset --hard is harmless)."""
        if self._ahead_of(remote_head) > 0:
            rc, out, _ = self._run(["diff", "--name-only",
                                    remote_head + "..HEAD"])
            if rc == 0:
                for line in out.splitlines():
                    p = self._clean_path(line.strip())
                    if p and self._is_foreign(p):
                        return p
        rc, out, _ = self._run(["status", "--porcelain"])
        if rc == 0:
            for line in out.splitlines():
                if len(line) < 4 or line.startswith("??"):
                    continue
                p = self._clean_path(line[3:].strip())
                if p and self._is_foreign(p):
                    return p
        return None

    @staticmethod
    def _clean_path(p):
        p = p.replace("\\", "/")
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        return p

    def _is_foreign(self, path):
        if path.startswith(self.data_subdir + "/"):
            return False
        base = path.rsplit("/", 1)[-1]
        if base.startswith("debug_report_") or base == "debug.log":
            return False
        return True

    def _data_dirty(self):
        rc, out, _ = self._run(["status", "--porcelain", "--",
                                self.data_subdir])
        if rc != 0:
            return False
        for line in out.splitlines():
            if line.strip() and not line.startswith("??"):
                return True
        return False

    # -- replay + salvage -------------------------------------------------
    def _data_dir(self):
        return os.path.join(self.repo_path, *self.data_subdir.split("/"))

    def _replay(self, entries):
        """Apply outbox entries onto the (freshly reset) working tree."""
        data_dir = self._data_dir()
        store = storage.Store(data_dir).load()
        dirty = False
        for e in entries:
            kind = e.get("type")
            if kind == "user":
                if store.add_user(e.get("name")):
                    dirty = True
            elif kind == "lap":
                rec = dict(e.get("record") or {})
                rel = rec.get("telemetry")
                if rel and not os.path.isfile(self.outbox.staged_path(rel)):
                    # payload lost (cleaned _localdata?): store the lap
                    # without a link rather than publish a dead one
                    self._dbg("no staged telemetry for " + rel +
                              " -- storing lap without it")
                    del rec["telemetry"]
                    rel = None
                result, dropped = store.upsert_record(rec)
                if result == "ignored":
                    continue
                dirty = True
                if rel:
                    self._install_asset(data_dir, rel)
                if dropped and dropped.get("telemetry"):
                    dpath = os.path.join(data_dir, dropped["telemetry"])
                    try:
                        if os.path.isfile(dpath):
                            os.remove(dpath)
                    except (IOError, OSError):
                        pass
            elif kind == "asset":
                rel = e.get("rel")
                if rel and self._install_asset(data_dir, rel):
                    dirty = True
        if dirty:
            store.save()

    def _install_asset(self, data_dir, rel):
        """Copy a staged outbox file into the data dir. True if it changed."""
        src = self.outbox.staged_path(rel)
        try:
            with io.open(src, "rb") as f:
                data = f.read()
        except (IOError, OSError):
            self._dbg("staged file missing: " + rel)
            return False
        dst = os.path.join(data_dir, *rel.replace("\\", "/").split("/"))
        try:
            with io.open(dst, "rb") as f:
                if f.read() == data:
                    return False
        except (IOError, OSError):
            pass
        parent = os.path.dirname(dst)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        tmp = dst + ".tmp"
        with io.open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
        return True

    def _salvage_local_data(self, remote_head):
        """Queue records/users that exist locally but not on the remote.

        Runs before reset --hard discards local state. Reads BOTH the
        working tree and HEAD (a crash can corrupt one but not the other),
        skips laps already queued in the outbox (a retried cycle must not
        duplicate), and drops telemetry links whose payload is unreadable.
        Trackmap assets are skipped -- they regenerate at session start.
        """
        base = self.data_subdir + "/" if self.data_subdir else ""
        candidates = []
        seen = set()
        for recs in (self._read_working_json(base + "records.json", []),
                     self._read_git_json("HEAD", base + "records.json", [])):
            for r in recs:
                if isinstance(r, dict) and _rec_identity(r) not in seen:
                    seen.add(_rec_identity(r))
                    candidates.append(r)
        remote_ids = set(_rec_identity(r) for r in
                         self._read_git_json(remote_head,
                                             base + "records.json", [])
                         if isinstance(r, dict))
        queued_ids = set(_rec_identity(e.get("record") or {})
                         for e in self.outbox.snapshot()
                         if e.get("type") == "lap")
        n = 0
        for r in candidates:
            ident = _rec_identity(r)
            if ident in remote_ids or ident in queued_ids:
                continue
            rec = dict(r)
            payload = None
            rel = rec.get("telemetry")
            if rel:
                tpath = os.path.join(self.repo_path,
                                     *(base + rel).split("/"))
                try:
                    with io.open(tpath, "r", encoding="utf-8") as f:
                        payload = f.read()
                except (IOError, OSError):
                    payload = None
                if payload is None:
                    del rec["telemetry"]     # never publish a dead link
            self.outbox.add_lap(rec, payload)
            n += 1
        local_users = []
        seen_u = set()
        for users in (self._read_working_json(base + "users.json", []),
                      self._read_git_json("HEAD", base + "users.json", [])):
            for u in users:
                if storage.norm(u) not in seen_u:
                    seen_u.add(storage.norm(u))
                    local_users.append(u)
        remote_users = set(storage.norm(u) for u in
                           self._read_git_json(remote_head,
                                               base + "users.json", []))
        queued_users = set(storage.norm(e.get("name"))
                           for e in self.outbox.snapshot()
                           if e.get("type") == "user")
        for u in local_users:
            if storage.norm(u) not in remote_users and \
                    storage.norm(u) not in queued_users:
                self.outbox.add_user(u)
                n += 1
        return n

    # -- UI view snapshot + change detection ------------------------------
    def _publish_view(self):
        """Atomic copy of the data files for the UI to read. git rewrites
        docs/data in place mid-cycle; the view dir only ever moves whole
        files, so the main thread can load it at any moment."""
        if not self.view_dir:
            return
        data_dir = self._data_dir()
        for name in DATA_FILES:
            src = os.path.join(data_dir, name)
            try:
                with io.open(src, "rb") as f:
                    data = f.read()
            except (IOError, OSError):
                continue
            if not os.path.isdir(self.view_dir):
                os.makedirs(self.view_dir)
            tmp = os.path.join(self.view_dir, name + ".tmp")
            with io.open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, os.path.join(self.view_dir, name))

    def _data_fingerprint(self):
        h = hashlib.md5()
        data_dir = self._data_dir()
        for name in DATA_FILES:
            try:
                with io.open(os.path.join(data_dir, name), "rb") as f:
                    h.update(f.read())
            except (IOError, OSError):
                h.update(b"missing")
            h.update(b"|")
        return h.hexdigest()

    def _read_working_json(self, relpath, default):
        path = os.path.join(self.repo_path, *relpath.split("/"))
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, OSError, ValueError):
            return default

    def _read_git_json(self, rev, relpath, default):
        rc, out, err = self._run(["show", rev + ":" + relpath])
        if rc != 0:
            return default
        try:
            return json.loads(out)
        except ValueError:
            return default

    def _commit_message(self, entries):
        laps = [e for e in entries if e.get("type") == "lap"]
        if len(laps) == 1:
            r = laps[0].get("record") or {}
            return "{0} {1} {2} {3}ms".format(
                r.get("user", "?"), r.get("track", "?"),
                r.get("car", "?"), r.get("time_ms", "?"))
        if laps:
            return "Sync {0} laps".format(len(laps))
        users = [e for e in entries if e.get("type") == "user"]
        if users:
            return "Add driver " + ", ".join(
                str(u.get("name")) for u in users)
        return "Track data"

    # -- git helpers ------------------------------------------------------
    def _rev(self, ref):
        rc, out, _ = self._run(["rev-parse", "--verify", ref])
        return out.strip() if rc == 0 and out.strip() else None

    def _ahead_of(self, remote_head):
        rc, out, _ = self._run(["rev-list", "--count",
                                remote_head + "..HEAD"])
        try:
            return int(out.strip()) if rc == 0 else 0
        except ValueError:
            return 0

    def _run(self, args):
        cmd = [self.git_exe, "-C", self.repo_path] + args
        try:
            p = subprocess.Popen(cmd, **_popen_kwargs())
            try:
                out, err = p.communicate(timeout=GIT_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                p.kill()
                try:
                    # bounded: a credential-helper grandchild can keep the
                    # pipes open on Windows; give up rather than block
                    p.communicate(timeout=5)
                except Exception:
                    pass
                return 1, "", "git timed out: " + " ".join(args[:2])
            # decode ourselves: universal_newlines would use the locale
            # codec on Windows and mangle non-ASCII driver names in
            # `git show` output
            return (p.returncode,
                    _decode(out), _decode(err))
        except (OSError, ValueError) as exc:
            return 1, "", str(exc)

    def _set_status(self, status):
        self.last_status = status
        if self.logger:
            try:
                self.logger("git: " + status)
            except Exception:
                pass
        if self.on_status:
            try:
                self.on_status(status)
            except Exception:
                pass


def _decode(b):
    if b is None:
        return ""
    if isinstance(b, str):
        return b
    return b.decode("utf-8", "replace")


def _first_line(s):
    s = (s or "").strip()
    return s.splitlines()[0] if s else "unknown error"


def _rec_identity(r):
    return (storage.norm(r.get("track")), storage.norm(r.get("config")),
            storage.norm(r.get("car")), storage.norm(r.get("user")),
            r.get("time_ms"))
