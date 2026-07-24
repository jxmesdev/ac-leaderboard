# Bradford Leaderboard

An in-game [Assetto Corsa](https://www.assettocorsa.net/) python app that records
each driver's **3 fastest valid laps** for every **track + car** combination, stores
them as JSON with full lap telemetry, and syncs them through this git repo so a
**GitHub Pages** site can display them. Multiple rigs can share one leaderboard —
even racing at the same time.

- **Repo:** https://github.com/jxmesdev/ac-leaderboard
- **Live board:** https://jxmesdev.github.io/ac-leaderboard/

Features:

- **Per-lap capture** — every completed clean lap is judged against the selected
  driver's own record; their 3 fastest laps per combo are kept, with official AC
  sector splits. Cut/invalid laps and laps with no driver selected are discarded.
- **Clickable driver grid** — type a name + Enter (or the **Add** button) to add a
  driver, click a name to switch. No auto-select, no auto-create.
- **Multi-rig sync** — every lap queues in a local outbox and a background worker
  replays it onto the remote's latest state (fetch → reset → replay → push). Two
  rigs racing simultaneously never conflict; each rig pulls periodically so the
  other rig's laps appear in-game within about a minute.
- **Lap telemetry** — throttle / brake / speed / gear / steering / position at
  ~30 Hz for every stored lap, plus the running car **setup** captured live via a
  CSP Lua companion (auto-installed). The Pages site has a MoTeC-style viewer
  (track map with true boundaries + corner names, stacked traces, sector focus,
  setup comparison) that overlays any set of laps.

## Install on a gaming PC (no files to move)

The repo root **is** the AC app: clone it straight into AC's python-apps folder.
Updates are just `git pull`.

### 1. Requirements
- **[Git for Windows](https://git-scm.com/download/win)** installed and on `PATH`.
- **A GitHub login with push access to this repo**, cached so pushes never prompt
  (see step 3 — the app pushes headless mid-game and cannot answer a prompt).
- **CSP (Custom Shaders Patch)** for live setup capture (optional — everything
  else works without it; setups fall back to the most recently saved file).
- **No Python packages** — only the standard library inside AC's interpreter.

### 2. Clone it *as the app folder*
The folder name **must** be `ac_leaderboard` (underscore!). A bare `git clone`
defaults to `ac-leaderboard`, which AC silently refuses to load:

```powershell
cd "C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\python"
git clone https://github.com/jxmesdev/ac-leaderboard.git ac_leaderboard
```

You should now have `…\apps\python\ac_leaderboard\ac_leaderboard.py`.

### 3. Cache credentials with one manual push
From the cloned folder, prove a headless push works **before** starting AC:

```powershell
cd "…\apps\python\ac_leaderboard"
git commit --allow-empty -m "credential test" ; git push ; git pull --rebase
```

Sign in when the Git Credential Manager pops up; after this the app can push
silently. (If `git push` still prompts, the in-game sync will time out instead
of hanging — fix the credentials and it retries by itself.)

### 4. Enable it in-game
- **Content Manager / AC → Settings → General → UI Modules**: tick
  **Bradford Leaderboard**.
- Join a session and open the app from the right-hand app bar.
- If CSP is installed, also enable the auto-installed **BL Setup Capture** Lua
  app once (it appears after the first session).

### Adding a second rig
Follow the same four steps on the other PC. Recommended: give each rig its own
identity in `config.json` (copy `config.example.json`) so commits are tellable
apart when debugging:

```json
{ "author_name": "Dads rig", "author_email": "dad@rig.local" }
```

Both rigs can record at once — laps merge by design (see *How syncing works*).
Keep track/car **mods identical** on both PCs: combos are keyed by AC's folder
names, so differing mod versions split the board (Kunos content always matches).

### Updating later
```powershell
cd "…\apps\python\ac_leaderboard"
git pull
```
(Do this with AC closed. The app also fast-forwards itself to the remote during
play; code changes take effect at the next AC restart.)

## Configuration (optional)

Copy `config.example.json` → `config.json` (git-ignored) and edit:

| Key | Default | Meaning |
|---|---|---|
| `repo_path` | `""` → the app folder | Only set if the clone lives elsewhere. |
| `data_subdir` | `docs/data` | Where the JSON lives (must be under `docs/` for Pages). |
| `auto_push` | `true` | Sync automatically (laps still queue locally if off). |
| `sync_interval_s` | `60` | Seconds between background pulls (and push retries). |
| `git_branch` | `main` | Branch to sync. |
| `author_name` / `author_email` | `AC Leaderboard` | Per-rig commit identity. |
| `leaderboard_rows` | `10` | Rows shown in-game. |
| `record_telemetry` | `true` | Record per-lap telemetry for the viewer. |
| `telemetry_hz` | `30` | Telemetry sample rate. |
| `ac_root` | `""` → auto | AC install path (track map/edges/sections grabs). |
| `setups_dir` | `""` → Documents | Override if OneDrive redirects Documents. |
| `web_url` | Pages URL | Opened by the in-game **Open web leaderboard** button. |

## Using it in-game

| Action | How |
|---|---|
| Add a driver | Type the name, then **Enter** or the **Add** button |
| Pick the driver at the wheel | Click their name in the grid |
| Save a lap | Just drive — every clean lap beats-or-not their own top 3 |
| See the other rig's laps | Automatic — the board refreshes after each background pull |
| Open the website | **Open web leaderboard** button (bottom of the window) |

The status line shows what happened (`PB for James: 1:21.200`, `top-3 lap for
Dad: 1:22.010`, `git: synced`, `git: error: … 2 lap(s) queued, will retry`, …).

## How syncing works (and why two rigs can't corrupt it)

```
lap finished ──► outbox (_localdata/, git-ignored, crash-safe)
                    │
        background worker, every lap + every sync_interval_s:
                    │
   fetch ► salvage stranded commits ► reset --hard to origin ► replay
   outbox onto origin's files (dedupe + top-3 prune) ► commit ► push
                    │                                    │ rejected? retry
                    └── data changed? bump version ──► in-game board reloads
```

The main thread **never writes** `docs/data`; the worker rebuilds it from the
remote's truth plus the outbox every cycle. So concurrent laps from two rigs
merge instead of conflicting, a lost push race just replays, laps queue locally
while offline, and a corrupt or diverged clone self-heals from origin. Pruning
(top-3 per driver+combo) re-runs deterministically on the merged data, deleting
dropped laps' telemetry with the same commit.

`send_debug.bat` writes a per-PC `debug_report_<COMPUTERNAME>.txt`, so support
snapshots from two rigs never collide either.

## Lap viewer (on the Pages site)

Click any leaderboard row to open the **lap viewer** (`lap.html`): true-boundary
track map with AC's own corner/straight names and sector lines, stacked traces
(throttle/brake/speed/gear/steering + delta) with sector focus, per-lap colours,
an At-cursor readout, sector table with gaps, and a setup comparison table with
per-lap downloads. Laps are shareable via the `?show=` URL.

## Repository layout

```
ac_leaderboard/                  ← repo root == the AC app (clone here)
├── ac_leaderboard.py            ← in-game entry point + UI (the "glue")
├── _ctypes.pyd                  ← from official CPython 3.3.5 amd64 (AC's
│                                  stripped stdlib lacks it; conditions
│                                  capture needs ctypes for shared memory)
├── config.example.json          ← optional; copy to config.json to tweak
├── send_debug.bat               ← one-click debug snapshot → GitHub
├── acl_core/                    ← pure-Python, unit-tested logic (no `ac` import)
│   ├── config.py  storage.py  leaderboard.py  outbox.py  git_sync.py
│   ├── timefmt.py ac_data.py  telemetry.py  trackmap.py  ailine.py
│   ├── setups.py  luainstall.py
├── lua/acl_setup/               ← CSP Lua companion (live setup capture)
├── docs/                        ← GitHub Pages site (Pages serves from /docs)
│   ├── index.html               ← leaderboard
│   ├── lap.html                 ← lap viewer + overlays
│   └── data/…                   ← records/users JSON, telemetry, trackmaps
├── tests/                       ← run on any machine (no AC needed)
└── tools/                       ← mock `ac`, smoke test, two-rig sync test
```

## Develop / test on macOS (no Assetto Corsa needed)

```bash
python3 -m unittest discover -s tests        # unit tests
python3 tools/smoke_ingame.py /path/to/clone # full in-game flow vs a fake `ac`
python3 tools/tworig_test.py /tmp/tworig     # two rigs sharing one remote
cd docs && python3 -m http.server 8777       # preview the Pages site
```

## Data format

`docs/data/records.json` — up to 3 laps per driver per combo:
```json
[
  { "track": "spa", "config": "", "car": "ferrari_488_gt3",
    "user": "James", "time_ms": 81200, "splits": [27000, 27100, 27100],
    "date": "2026-07-21T22:14:26Z", "source": "auto",
    "telemetry": "telemetry/spa____ferrari_488_gt3__james__81200.json" }
]
```
`docs/data/users.json` — every driver ever created. Telemetry files are columnar
arrays (`nsp` is the alignment axis; `t` cumulative ms; `x`/`z` world metres;
`str` degrees; embedded `setup` ini) — immutable, since the filename carries the
lap time.

## Notes & limitations

- **Embedded interpreter.** All in-game code targets AC's Python 3.3.5 — no
  f-strings, `pathlib`, or modern typing. Every `ac.*` listener callback must be
  a plain module-level function, and nothing heavy may run inside one.
- **Driver grid** shows the first 10 drivers.
- **Track/car IDs** are AC's folder names; the site prettifies them.
