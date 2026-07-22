"""End-to-end smoke test of the in-game glue using the fake `ac` module.

Drives the app exactly as Assetto Corsa would: acMain -> acUpdate (telemetry)
-> driver actions -> acShutdown, then verifies JSON + git push. Run:

    python3 tools/smoke_ingame.py /path/to/git/clone
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import mock_ac
ac = mock_ac.install()          # registers fake `ac` + `acsys`

repo = sys.argv[1]
cfg_path = os.path.join(repo, "_smoke_config.json")
with open(cfg_path, "w") as f:
    json.dump({
        "repo_path": repo,
        "data_subdir": "docs/data",
        "git_branch": "main",
        "auto_push": True,
        "auto_capture": True,
        "leaderboard_rows": 5,
    }, f)
os.environ["ACL_CONFIG"] = cfg_path

import ac_leaderboard as app


def dump(title):
    recs = os.path.join(repo, "docs", "data", "records.json")
    data = json.load(open(recs)) if os.path.exists(recs) else []
    print("--", title, "-> records:", len(data))
    for r in data:
        print("   ", r["user"], r["track"], r["car"], r["time_ms"], r["source"])


def driver_button_texts():
    return [mock_ac.STATE.widgets[b]["text"] for b in app._app.driver_btns
            if mock_ac.STATE.widgets[b]["text"].strip()]


print("== acMain ==")
app.acMain(1.0)

app.acUpdate(0.6)                      # menus, no track yet

# Load a session: Spa + Ferrari.
mock_ac.STATE.track = "spa"
mock_ac.STATE.car = "ferrari_488_gt3"
app.acUpdate(0.6)
print("track label:", mock_ac.STATE.widgets[app._app.l_track]["text"])
print("car label:  ", mock_ac.STATE.widgets[app._app.l_car]["text"])

# Add a driver by typing + Enter: validate() stashes the name, and the next
# acUpdate applies it (the crash-safe deferred path). Then one via users.json
# style, and confirm "+ Add me" (AC profile name) works too.
mock_ac.validate(app._app.in_newuser, "James")
app.acUpdate(1 / 60.0)                    # processes the pending name
assert app._app.in_newuser is None or mock_ac.STATE.widgets[app._app.in_newuser]["text"] == ""
app._app._add_driver("Alex")
mock_ac.STATE.driver_name = "James"
mock_ac.click(app._app.b_addme)          # + Add me -> getDriverName -> James (dup)
print("driver buttons:", driver_button_texts())

# Click James's button (slot 0) to select him.
mock_ac.click(app._app.driver_btns[0])
print("selected:", app._app.selected)


def drive_lap(seconds=5.0, fps=60.0):
    """Simulate driving one lap: nsp 0->~1 with plausible telemetry."""
    import math
    dt = 1.0 / fps
    frames = int(seconds * fps)
    for i in range(frames):
        frac = i / float(frames)
        mock_ac.STATE.nsp = min(frac, 0.9999)
        mock_ac.STATE.gas = 1.0 if (i % 90) < 65 else 0.0
        mock_ac.STATE.brake = 0.0 if mock_ac.STATE.gas > 0 else 0.85
        mock_ac.STATE.speed_kmh = 190.0 if mock_ac.STATE.gas > 0 else 95.0
        mock_ac.STATE.gear = 5 if mock_ac.STATE.gas > 0 else 3
        mock_ac.STATE.steer = 0.25 * math.sin(frac * 10 * math.pi)
        mock_ac.STATE.world = (120.0 * math.cos(frac * 2 * math.pi),
                               0.0,
                               80.0 * math.sin(frac * 2 * math.pi))
        app.acUpdate(dt)


# Drive a full lap for James (accumulates telemetry samples)...
drive_lap(5.0)
# ...cross start/finish so the recorder finalizes the lap...
mock_ac.STATE.nsp = 0.0
app.acUpdate(1 / 60.0)
# ...then AC reports it as the new best -> save record + flush telemetry.
mock_ac.STATE.best_lap = 81200
for _ in range(40):
    app.acUpdate(1 / 60.0)
dump("after driven PB 1:21.200")

tel_path = os.path.join(repo, "docs", "data", "telemetry",
                        "spa____ferrari_488_gt3__james.json")
print("telemetry file written:", os.path.isfile(tel_path))
if os.path.isfile(tel_path):
    tel = json.load(open(tel_path))
    print("  samples:", tel["n"], "| channels:",
          [k for k in ("nsp", "thr", "brk", "spd", "gear", "str", "x", "z") if k in tel],
          "| len(m):", tel["track_len_m"])
rec = json.load(open(os.path.join(repo, "docs", "data", "records.json")))[0]
print("record telemetry link:", rec.get("telemetry"))

# Let the background git worker finish.
time.sleep(3)
print("git status:", app._app.git.last_status)

app.acShutdown()

from acl_core.leaderboard import leaderboard_for
from acl_core import storage
st = storage.Store(os.path.join(repo, "docs", "data")).load()
rows = leaderboard_for(st.records, "spa", "", "ferrari_488_gt3")
print("== leaderboard ==")
for r in rows:
    print("  {0}. {1:10s} {2} {3}".format(r["rank"], r["user"], r["time_str"], r["gap_str"]))

os.remove(cfg_path)
print("OK" if app._app.git.last_status == "synced" else "GIT NOT SYNCED")
