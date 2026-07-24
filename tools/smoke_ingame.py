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


def records():
    recs = os.path.join(repo, "docs", "data", "records.json")
    return json.load(open(recs)) if os.path.exists(recs) else []


def dump(title):
    data = records()
    print("--", title, "-> records:", len(data))
    for r in data:
        print("   ", r["user"], r["track"], r["car"], r["time_ms"],
              r["source"], "splits=" + str(r.get("splits")))


def driver_button_texts():
    return [mock_ac.STATE.widgets[b]["text"] for b in app._app.driver_btns
            if mock_ac.STATE.widgets[b]["text"].strip()]


print("== acMain ==")
app.acMain(1.0)

app.acUpdate(0.6)                      # menus, no track yet

# Load a session: Spa + Ferrari. NOTHING is auto-selected or auto-created --
# drivers exist only by typing a new name or clicking an existing button.
mock_ac.STATE.track = "spa"
mock_ac.STATE.car = "ferrari_488_gt3"
app.acUpdate(0.6)                         # session start
print("track label:", mock_ac.STATE.widgets[app._app.l_track]["text"])
print("car label:  ", mock_ac.STATE.widgets[app._app.l_car]["text"])
assert app._app.selected is None, "nothing should be auto-selected"

# Add drivers by typing + Enter (validate -> stash -> acUpdate applies it).
mock_ac.validate(app._app.in_newuser, "James")
app.acUpdate(1 / 60.0)
mock_ac.validate(app._app.in_newuser, "Alex")
app.acUpdate(1 / 60.0)
print("driver buttons:", driver_button_texts())

# Typing an existing name is an error and does NOT switch.
mock_ac.validate(app._app.in_newuser, "james")
app.acUpdate(1 / 60.0)
assert app._app.selected == "Alex", "duplicate typing must not switch"
assert "already exists" in app._app.status_text, app._app.status_text
print("duplicate entry ->", app._app.status_text)

# The Add button: click stashes a flag; the NEXT acUpdate reads the field via
# ac.getText (deferred -- calling it inside the click handler crashes AC).
mock_ac.setText(app._app.in_newuser, "Dave")
mock_ac.click(app._app.btn_add)
app.acUpdate(1 / 60.0)
assert "Dave" in app._app.users, app._app.users
assert app._app.selected == "Dave", app._app.selected
assert mock_ac.getText(app._app.in_newuser) == "", "field must clear on Add"
print("Add button ->", driver_button_texts())

# Add with an empty field is a friendly error, not a crash.
mock_ac.click(app._app.btn_add)
app.acUpdate(1 / 60.0)
assert "type a name" in app._app.status_text, app._app.status_text

# Add with a duplicate name errors and does not switch.
mock_ac.setText(app._app.in_newuser, "ALEX")
mock_ac.click(app._app.btn_add)
app.acUpdate(1 / 60.0)
assert "already exists" in app._app.status_text, app._app.status_text
assert app._app.selected == "Dave", "duplicate Add must not switch"
mock_ac.setText(app._app.in_newuser, "")
print("Add-button edge cases OK")

# Regression check: a newly-added driver's button must be ON-SCREEN, not parked
# at (-500, -500). (Bug: slots hidden as empty were never restored on add.)
for i, name in enumerate(app._app.users):
    pos = mock_ac.STATE.widgets[app._app.driver_btns[i]].get("pos")
    assert pos != (-500, -500), "driver %s button is off-screen!" % name
print("driver button positions on-screen:",
      [mock_ac.STATE.widgets[app._app.driver_btns[i]]["pos"] for i in range(len(app._app.users))])

# Select James (slot 0) for the lap. Clicks stash the slot index (plain
# module-level callback); the next acUpdate tick applies it.
mock_ac.click(app._app.driver_btns[0])
app.acUpdate(1 / 60.0)
assert app._app.selected == "James", app._app.selected
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
        mock_ac.STATE.steer = 15.0 * math.sin(frac * 10 * math.pi)   # degrees
        mock_ac.STATE.world = (120.0 * math.cos(frac * 2 * math.pi),
                               0.0,
                               80.0 * math.sin(frac * 2 * math.pi))
        app.acUpdate(dt)


# Drive a full lap for James (accumulates telemetry samples)...
drive_lap(5.0)
# ...cross start/finish so the recorder finalizes the lap...
mock_ac.STATE.nsp = 0.0
app.acUpdate(1 / 60.0)
# ...then AC's lap counter ticks over with the completed lap's time and its
# sector splits -> save record + flush telemetry (judged against James's OWN
# record). Splits must sum to (about) the lap time to be accepted.
mock_ac.STATE.lap_count += 1
mock_ac.STATE.last_lap = 81200
mock_ac.STATE.splits = [27000, 27100, 27100]     # sums to 81200
for _ in range(40):
    app.acUpdate(1 / 60.0)
dump("after driven PB 1:21.200")
# (the async git worker may have already overwritten the status with "git: ...")
assert app._app.status_text == "PB for James: 1:21.200" or \
    app._app.status_text.startswith("git:"), app._app.status_text

# Each stored lap now has its OWN telemetry file, keyed by lap time.
tel_path = os.path.join(repo, "docs", "data", "telemetry",
                        "spa____ferrari_488_gt3__james__81200.json")
print("telemetry file written:", os.path.isfile(tel_path))
assert os.path.isfile(tel_path), "per-lap telemetry file missing"
tel = json.load(open(tel_path))
print("  samples:", tel["n"], "| channels:",
      [k for k in ("nsp", "thr", "brk", "spd", "gear", "str", "x", "z") if k in tel],
      "| len(m):", tel["track_len_m"], "| splits:", tel.get("splits"))
# Splits round-trip into BOTH the record and the telemetry payload.
assert tel.get("splits") == [27000, 27100, 27100], tel.get("splits")


def james_spa_records():
    """The smoke's own records (the clone may carry pre-existing live data)."""
    return [r for r in records()
            if r["user"] == "James" and r["track"] == "spa"]


rec = james_spa_records()[0]
print("record telemetry link:", rec.get("telemetry"))
assert rec.get("splits") == [27000, 27100, 27100], rec.get("splits")
assert rec.get("telemetry") == \
    "telemetry/spa____ferrari_488_gt3__james__81200.json", rec.get("telemetry")

# A SECOND, slower lap for the same driver -> a second record (top3) with its
# own telemetry file (up to each driver's 3 fastest laps are kept).
drive_lap(5.0)
mock_ac.STATE.nsp = 0.0
app.acUpdate(1 / 60.0)
mock_ac.STATE.lap_count += 1
mock_ac.STATE.last_lap = 82500
mock_ac.STATE.splits = [27500, 27400, 27600]     # sums to 82500
for _ in range(40):
    app.acUpdate(1 / 60.0)
dump("after slower lap 1:22.500 (top-3)")
assert app._app.status_text == "top-3 lap for James: 1:22.500" or \
    app._app.status_text.startswith("git:"), app._app.status_text

james_recs = james_spa_records()
assert len(james_recs) == 2, "expected 2 James records, got %d" % len(james_recs)
assert sorted(r["time_ms"] for r in james_recs) == [81200, 82500]
tel_path2 = os.path.join(repo, "docs", "data", "telemetry",
                         "spa____ferrari_488_gt3__james__82500.json")
assert os.path.isfile(tel_path2), "second lap's telemetry file missing"
by_ms = dict((r["time_ms"], r) for r in james_recs)
assert by_ms[82500].get("telemetry") == \
    "telemetry/spa____ferrari_488_gt3__james__82500.json"
assert by_ms[82500].get("splits") == [27500, 27400, 27600]
assert json.load(open(tel_path2)).get("splits") == [27500, 27400, 27600]
print("second (top-3) lap stored with its own telemetry + splits")

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
