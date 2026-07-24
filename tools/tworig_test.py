"""Two-rig sync integration test.

Simulates BOTH rigs sharing one GitHub repo: a bare remote plus two clones,
each with its own Outbox + GitSync, driven through the exact scenarios that
broke the old commit-then-pull design (interleaved laps, stale stores,
stranded commits, shared-driver pruning, offline queues). Run:

    python3 tools/tworig_test.py /path/to/scratch/dir
"""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from acl_core import storage
from acl_core.git_sync import GitSync
from acl_core.outbox import Outbox

DATA_SUB = "docs/data"


def sh(cwd, *args):
    p = subprocess.Popen(list(args), cwd=cwd, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    out, _ = p.communicate()
    if p.returncode != 0:
        raise RuntimeError("cmd failed: %s\n%s" % (" ".join(args), out))
    return out


class Rig(object):
    """A clone + outbox + sync engine, mimicking the in-game glue."""

    def __init__(self, name, clone_dir):
        self.name = name
        self.dir = clone_dir
        self.data_dir = os.path.join(clone_dir, *DATA_SUB.split("/"))
        self.outbox = Outbox(os.path.join(clone_dir, "_localdata"))
        self.git = GitSync(clone_dir, DATA_SUB, self.outbox,
                           view_dir=os.path.join(clone_dir, "_localdata",
                                                 "view"),
                           author_name=name, author_email=name + "@test",
                           logger=None)
        self.reloads = 0
        self._seen_version = 0

    def record_lap(self, user, ms, track="spa", car="gt3"):
        rec = storage.make_record(track, "", car, user, ms, "auto")
        rec["splits"] = [ms // 2, ms - ms // 2]
        fname = "%s____%s__%s__%d.json" % (track, car,
                                           user.lower().replace(" ", "_"), ms)
        rec["telemetry"] = "telemetry/" + fname
        payload = json.dumps({"fake": True, "driver": user, "time_ms": ms})
        self.outbox.add_lap(rec, payload)

    def add_driver(self, name):
        self.outbox.add_user(name)

    def sync(self):
        ok, detail = self.git._sync_once()
        if self.git.data_version != self._seen_version:
            self._seen_version = self.git.data_version
            self.reloads += 1
        return ok, detail

    def records(self):
        p = os.path.join(self.data_dir, "records.json")
        return json.load(open(p)) if os.path.exists(p) else []

    def users(self):
        p = os.path.join(self.data_dir, "users.json")
        return json.load(open(p)) if os.path.exists(p) else []


def remote_records(bare):
    return json.loads(sh(bare, "git", "show", "main:" + DATA_SUB + "/records.json"))


def remote_users(bare):
    return json.loads(sh(bare, "git", "show", "main:" + DATA_SUB + "/users.json"))


def remote_has_file(bare, rel):
    p = subprocess.Popen(["git", "cat-file", "-e", "main:" + rel], cwd=bare,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.communicate()
    return p.returncode == 0


def main():
    scratch = os.path.abspath(sys.argv[1])
    if os.path.isdir(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)

    bare = os.path.join(scratch, "remote.git")
    sh(scratch, "git", "clone", "-q", "--bare", ROOT, bare)
    a_dir = os.path.join(scratch, "rigA")
    b_dir = os.path.join(scratch, "rigB")
    sh(scratch, "git", "clone", "-q", bare, a_dir)
    sh(scratch, "git", "clone", "-q", bare, b_dir)
    base_records = len(remote_records(bare))

    A = Rig("rigA", a_dir)
    B = Rig("rigB", b_dir)

    print("== 1. simple lap from A reaches the remote and then B ==")
    A.record_lap("James", 81200)
    ok, d = A.sync()
    assert ok, d
    assert A.outbox.count() == 0
    ids = [(r["user"], r["time_ms"]) for r in remote_records(bare)]
    assert ("James", 81200) in ids
    ok, d = B.sync()
    assert ok, d
    assert ("James", 81200) in [(r["user"], r["time_ms"]) for r in B.records()]
    assert B.reloads == 1, "B must signal a board reload after pulling A's lap"
    print("   ok (B reloaded, remote has the lap)")

    print("== 2. interleaved laps on BOTH rigs (the old conflict killer) ==")
    A.record_lap("James", 80900)
    B.record_lap("Dad", 82500)          # both queued before either syncs
    ok, d = A.sync()
    assert ok, d
    ok, d = B.sync()                    # B replays onto A's fresh push
    assert ok, d
    ok, d = A.sync()                    # A picks up B's lap
    assert ok, d
    ids = [(r["user"], r["time_ms"]) for r in remote_records(bare)]
    assert ("James", 80900) in ids and ("Dad", 82500) in ids, ids
    for rig in (A, B):
        got = [(r["user"], r["time_ms"]) for r in rig.records()]
        assert ("James", 80900) in got and ("Dad", 82500) in got, (rig.name, got)
        assert rig.outbox.count() == 0
    assert remote_has_file(bare, DATA_SUB + "/telemetry/spa____gt3__dad__82500.json")
    print("   ok (no conflict, both laps everywhere, telemetry present)")

    print("== 3. stranded old-style local commit gets salvaged ==")
    # B commits a lap the OLD way (working-tree write + commit), then the
    # remote moves under it -> push rejected -> salvage -> replay.
    st = storage.Store(B.data_dir).load()
    rec = storage.make_record("spa", "", "gt3", "Dad", 82100, "auto")
    st.upsert_record(rec)
    st.save()
    sh(b_dir, "git", "add", "-A", "--", DATA_SUB)
    sh(b_dir, "git", "-c", "user.name=old", "-c", "user.email=o@x",
       "commit", "-q", "-m", "old-style lap")
    A.record_lap("James", 80800)
    ok, d = A.sync()
    assert ok, d
    ok, d = B.sync()
    assert ok, d
    ids = [(r["user"], r["time_ms"]) for r in remote_records(bare)]
    assert ("Dad", 82100) in ids and ("James", 80800) in ids, ids
    out = sh(b_dir, "git", "status", "--porcelain", "--", DATA_SUB)
    assert out.strip() == "", "B's tree must be clean: " + out
    print("   ok (salvaged lap on remote, tree clean)")

    print("== 4. same driver+combo on both rigs: top-3 pruning converges ==")
    A.record_lap("Shared", 90100)
    A.record_lap("Shared", 90200)
    B.record_lap("Shared", 90050)
    B.record_lap("Shared", 90300)
    ok, d = A.sync()
    assert ok, d
    ok, d = B.sync()
    assert ok, d
    ok, d = A.sync()
    assert ok, d
    shared = sorted(r["time_ms"] for r in remote_records(bare)
                    if r["user"] == "Shared")
    assert shared == [90050, 90100, 90200], shared
    # dropped lap's telemetry must be gone; kept laps' files must exist
    assert not remote_has_file(bare, DATA_SUB + "/telemetry/spa____gt3__shared__90300.json")
    for ms in shared:
        assert remote_has_file(bare, DATA_SUB + "/telemetry/spa____gt3__shared__%d.json" % ms)
    print("   ok (exactly top-3 kept, dropped telemetry deleted)")

    print("== 5. drivers added on both rigs, case-variant dedupe ==")
    A.add_driver("Alpha")
    B.add_driver("Beta")
    B.add_driver("alpha")               # case-variant duplicate
    ok, d = A.sync()
    assert ok, d
    ok, d = B.sync()
    assert ok, d
    users = remote_users(bare)
    lows = [u.lower() for u in users]
    assert "alpha" in lows and "beta" in lows
    assert lows.count("alpha") == 1, users
    print("   ok (both drivers, no case duplicate)")

    print("== 6. offline: laps queue, then flush when the remote returns ==")
    sh(b_dir, "git", "remote", "set-url", "origin",
       os.path.join(scratch, "nowhere.git"))
    B.record_lap("Dad", 82000)
    ok, d = B.sync()
    assert not ok and "offline" in d, d
    assert B.outbox.lap_count() == 1
    sh(b_dir, "git", "remote", "set-url", "origin", bare)
    ok, d = B.sync()
    assert ok, d
    assert B.outbox.count() == 0
    assert ("Dad", 82000) in [(r["user"], r["time_ms"])
                              for r in remote_records(bare)]
    print("   ok (queued while offline, flushed on reconnect)")

    print("== 7. corrupt local records.json self-heals from the remote ==")
    with open(os.path.join(B.data_dir, "records.json"), "w") as f:
        f.write("{ not json !!!")
    ok, d = B.sync()
    assert ok, d
    assert len(B.records()) >= base_records, "reset must restore the file"
    assert B.reloads >= 2, "repairing the file must signal a board reload"
    print("   ok (reset restored origin's file, reload signalled)")

    print("== 8. UNCOMMITTED lap data (old-design crash) is salvaged ==")
    st = storage.Store(B.data_dir).load()
    st.upsert_record(storage.make_record("spa", "", "gt3", "Dad", 81900, "auto"))
    st.save()                            # dirty working tree, NO commit
    ok, d = B.sync()
    assert ok, d
    assert ("Dad", 81900) in [(r["user"], r["time_ms"])
                              for r in remote_records(bare)]
    print("   ok (dirty-tree lap reached the remote)")

    print("== 9. local commits OUTSIDE docs/data pause the sync (no nuking) ==")
    marker = os.path.join(b_dir, "README.md")
    with open(marker, "a") as f:
        f.write("\nlocal dev experiment\n")
    sh(b_dir, "git", "add", "README.md")
    sh(b_dir, "git", "-c", "user.name=dev", "-c", "user.email=d@x",
       "commit", "-q", "-m", "WIP code change")
    B.record_lap("Dad", 81800)
    ok, d = B.sync()
    assert not ok and "paused" in d, d
    out = sh(b_dir, "git", "log", "--oneline", "-1")
    assert "WIP code change" in out, "foreign commit must survive untouched"
    assert B.outbox.lap_count() == 1, "lap must stay queued"
    ids = [(r["user"], r["time_ms"]) for r in remote_records(bare)]
    assert ("Dad", 81800) not in ids
    sh(b_dir, "git", "reset", "--hard", "origin/main")   # human resolves
    ok, d = B.sync()
    assert ok, d
    assert ("Dad", 81800) in [(r["user"], r["time_ms"])
                              for r in remote_records(bare)]
    print("   ok (paused with WIP intact, flushed after manual resolve)")

    print("== 10. rejected pushes: bounded retries, NO outbox duplication ==")
    hooks = os.path.join(bare, "hooks")
    hook = os.path.join(hooks, "pre-receive")
    with open(hook, "w") as f:
        f.write("#!/bin/sh\necho rejected by test hook >&2\nexit 1\n")
    os.chmod(hook, 0o755)
    A.record_lap("James", 80700)
    ok, d = A.sync()
    assert not ok, "push must fail against the rejecting hook"
    assert A.outbox.lap_count() == 1, \
        "retries must not duplicate outbox entries: %d" % A.outbox.lap_count()
    os.remove(hook)
    ok, d = A.sync()
    assert ok, d
    assert A.outbox.count() == 0
    times = [r["time_ms"] for r in remote_records(bare) if r["user"] == "James"]
    assert times.count(80700) == 1, times
    print("   ok (entries survived, exactly one record after recovery)")

    print("== 11. wrong checked-out branch refuses to sync ==")
    sh(b_dir, "git", "checkout", "-q", "-b", "feature")
    B.record_lap("Dad", 81700)
    ok, d = B.sync()
    assert not ok and "branch" in d, d
    sh(b_dir, "git", "checkout", "-q", "main")
    ok, d = B.sync()
    assert ok, d
    assert ("Dad", 81700) in [(r["user"], r["time_ms"])
                              for r in remote_records(bare)]
    print("   ok (refused on feature branch, synced after checkout main)")

    print("== 12. view snapshot mirrors the data files after a cycle ==")
    view = os.path.join(b_dir, "_localdata", "view", "records.json")
    assert os.path.isfile(view), "view snapshot must exist"
    assert json.load(open(view)) == B.records(), "view must match data dir"
    print("   ok")

    print("== 13. no-git mode still lands laps in the local data files ==")
    plain = os.path.join(scratch, "plain")
    os.makedirs(os.path.join(plain, "docs", "data"))
    pbox = Outbox(os.path.join(plain, "_localdata"))
    peng = GitSync(plain, DATA_SUB, pbox,
                   view_dir=os.path.join(plain, "_localdata", "view"))
    rec = storage.make_record("spa", "", "gt3", "Solo", 99000, "auto")
    pbox.add_lap(rec, None)
    peng.apply_outbox_locally()
    got = json.load(open(os.path.join(plain, "docs", "data", "records.json")))
    assert [(r["user"], r["time_ms"]) for r in got] == [("Solo", 99000)]
    assert pbox.count() == 0
    print("   ok")

    total = len(remote_records(bare))
    print("\nALL TWO-RIG SCENARIOS PASS -- remote has {0} records ({1} new)"
          .format(total, total - base_records))


if __name__ == "__main__":
    main()
