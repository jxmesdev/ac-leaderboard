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

# Create two drivers via the text-input validate callback.
mock_ac.validate(app._app.in_newuser, "James")
mock_ac.validate(app._app.in_newuser, "Alex")
print("driver buttons:", driver_button_texts())

# Click James's button (slot 0) to select him.
mock_ac.click(app._app.driver_btns[0])
print("selected:", app._app.selected)

# Auto-capture: a valid best lap appears, then improves.
mock_ac.STATE.best_lap = 82500
app.acUpdate(0.6)
dump("after auto PB 1:22.500")
mock_ac.STATE.best_lap = 81200
app.acUpdate(0.6)
dump("after auto PB 1:21.200")

# A slower session best is impossible in AC; a non-improving value is ignored.
mock_ac.STATE.best_lap = 81900
app.acUpdate(0.6)
dump("after (ignored) 1:21.900")

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
