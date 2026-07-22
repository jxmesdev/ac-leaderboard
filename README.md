# AC Leaderboard

An in-game [Assetto Corsa](https://www.assettocorsa.net/) python app that records
the **fastest valid lap per driver** for each **track + car** combination, stores
them as JSON, and pushes them to this git repo so a **GitHub Pages** site can
display them.

- **Repo:** https://github.com/jxmesdev/ac-leaderboard
- **Live board:** https://jxmesdev.github.io/ac-leaderboard/

Features:

- **Auto-capture** — reads AC's best *valid* lap and saves a driver's personal best
  automatically. Only the fastest lap per driver is kept; a quicker lap overwrites it.
- **Clickable driver list** — every driver ever entered shows as a button; click to
  pick who's at the wheel. The selected driver and the leader are highlighted.
- **Create driver** — type a name and press **Enter**, or pre-seed
  `docs/data/users.json`.
- **Auto-publish** — every time a driver beats their best, it's committed and
  `git push`ed on a background thread, so it never stutters the game.
- **Lap telemetry** — the best lap's throttle / brake / speed / gear / steering and
  track position are recorded (~30 Hz) and saved alongside the record. The Pages site
  has a **MoTeC-style lap viewer** (track map + stacked traces) where you can **overlay
  every other driver's lap** on the same track+car and compare with a synced cursor.

## Install on the gaming PC (no files to move)

The repo root **is** the AC app, so you clone it straight into AC's python-apps
folder and it works. There is nothing to copy around, and updates are just `git pull`.

### 1. Requirements
- **[Git for Windows](https://git-scm.com/download/win)** installed and on `PATH`
  (the app shells out to `git`). Make sure `git push` works **without prompting**
  (sign in once via the Git Credential Manager, or use an SSH key / cached PAT).
- **No Python packages** — the app uses only the standard library that ships inside
  Assetto Corsa's embedded interpreter.

### 2. Clone it *as the app folder*
Clone into AC's python apps directory, naming the folder `ac_leaderboard`
(underscore — AC uses the folder name as the module name, so no hyphen):

```powershell
cd "C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\python"
git clone https://github.com/jxmesdev/ac-leaderboard.git ac_leaderboard
```

You should now have `…\apps\python\ac_leaderboard\ac_leaderboard.py`.

### 3. Enable it in-game
- **Content Manager / AC → Settings → Assetto Corsa → General → UI Modules**: tick
  **AC Leaderboard**.
- Join a session and open the app from the right-hand app bar.

That's it. No config file is required — see below only if you want to tweak things.

### Updating later
```powershell
cd "…\apps\python\ac_leaderboard"
git pull
```
(Do this with AC closed.) Your recorded times live in the same repo and are pushed
to GitHub, so nothing is lost.

## Configuration (optional)

`repo_path` **auto-detects** to the app folder itself (which is this clone), so you
normally don't set anything. To change behaviour, copy `config.example.json` →
`config.json` (it's git-ignored) and edit:

| Key | Default | Meaning |
|---|---|---|
| `repo_path` | `""` → the app folder | Only set this if you keep the clone somewhere else. |
| `data_subdir` | `docs/data` | Where `records.json` / `users.json` are written (must be under `docs/` for Pages). |
| `auto_capture` | `true` | Save your best valid lap automatically. |
| `auto_push` | `true` | Commit + push each saved time. |
| `git_branch` | `main` | Branch to push. |
| `leaderboard_rows` | `10` | Rows shown in-game. |
| `record_telemetry` | `true` | Record best-lap telemetry for the lap viewer. |
| `telemetry_hz` | `30` | Telemetry sample rate. |

## Using it in-game

| Action | How |
|---|---|
| Pick your driver | Click your name in the driver grid |
| Create a driver | Type a name in **New driver** and press **Enter** |
| Save a PB | Just drive — a new clean best lap is saved and pushed for the selected driver |
| Toggle auto-capture | **Auto-capture: ON/OFF** button |

The status line shows what happened (`PB for James: 1:21.200`, `git: synced`, …).
Every time a driver beats their best on the current combo, the new time is committed
and pushed to GitHub automatically (slower laps are ignored, so no push).

> **Text field note:** typing a driver name needs a working text field, which comes
> from **Custom Shaders Patch (CSP)** — installed by default with most Content Manager
> setups. Submit with **Enter**: that's the only way AC hands the typed text to the
> app. (Reading a field on demand via `ac.getText` crashes AC natively, so there is
> intentionally no "Add" button.) On vanilla AC without CSP there's no text input at
> all — add drivers by editing `docs/data/users.json` (a JSON list of names) and the
> app loads them next session.

## Lap viewer (on the Pages site)

On the leaderboard, any driver with recorded telemetry shows a 📈 next to their name.
Click it to open the **lap viewer** (`lap.html`):

- A **track map** drawn from the car's world position, with the racing line highlighted.
- Stacked **traces vs distance**: throttle, brake, speed, gear, steering.
- A **Laps** panel listing every driver's lap for that same track + car — tick any of
  them to **overlay** their lap on the map and all traces, each in its own colour.
- Hover the traces or map for a **synced cursor**: a readout shows every lap's values
  at that point, plus **Δ** (the time gained/lost versus the primary lap there).

Telemetry is recorded for the **best** lap only and overwritten when it's beaten, so
the map/traces always reflect each driver's fastest lap.

## How it works

```
Assetto Corsa ──► ac_leaderboard.py ──► acl_core (storage / leaderboard / telemetry)
   telemetry         (UI + glue)              │
                                              ├─► docs/data/records.json + users.json
                                              ├─► docs/data/telemetry/<combo>__<driver>.json
                                              └─► git_sync ──► git commit + push (background)
                                                                    │
                                              GitHub ──► Pages (index.html + lap.html)
```

Auto-capture uses `ac.getCarState(0, acsys.CS.BestLap)`, which AC only sets for laps
that were **not invalidated** (no cutting / off-tracks) — so the board stays clean.
Only the single best time per `(track, config, car, driver)` is kept, so the JSON
stays small and is exactly the leaderboard payload.

## Repository layout

```
ac_leaderboard/                  ← repo root == the AC app (clone here)
├── ac_leaderboard.py            ← in-game entry point + UI (the "glue")
├── config.example.json          ← optional; copy to config.json to tweak
├── acl_core/                    ← pure-Python, unit-tested logic (no `ac` import)
│   ├── config.py  storage.py  leaderboard.py
│   ├── timefmt.py git_sync.py  ac_data.py  telemetry.py
├── docs/                        ← GitHub Pages site (Pages serves from /docs)
│   ├── index.html               ← leaderboards (links to the lap viewer)
│   ├── lap.html                 ← MoTeC-style lap viewer + overlay
│   └── data/{records,users}.json, data/telemetry/*.json
├── tests/{test_core,test_telemetry}.py   ← run on any machine (no AC needed)
└── tools/                       ← mock `ac` + off-car smoke test
```

## Develop / test on macOS (no Assetto Corsa needed)

The `acl_core` package never imports `ac`/`acsys`, so it runs anywhere.

```bash
python3 tests/test_core.py                       # leaderboard/storage unit tests
python3 tests/test_telemetry.py                  # telemetry recorder unit tests
python3 tools/smoke_ingame.py /path/to/a/clone   # full flow (incl. a driven lap) vs a fake `ac`
cd docs && python3 -m http.server 8777           # preview the Pages site + lap viewer
```

## Data format

`docs/data/records.json` — one entry per driver per combo (best kept):
```json
[
  { "track": "spa", "config": "", "car": "ferrari_488_gt3",
    "user": "James", "time_ms": 81200,
    "date": "2026-07-21T22:14:26Z", "source": "auto",
    "telemetry": "telemetry/spa____ferrari_488_gt3__james.json" }
]
```
`docs/data/users.json` — every driver ever created:
```json
["James", "Alex"]
```
`docs/data/telemetry/<combo>__<driver>.json` — best-lap telemetry, columnar arrays
(one value per ~1/30 s sample) so the viewer can index one cursor across all channels:
```json
{ "track":"spa","car":"ferrari_488_gt3","driver":"James","time_ms":81200,
  "hz":30,"track_len_m":7004,"n":4100,
  "nsp":[…], "t":[…], "thr":[…], "brk":[…], "spd":[…],
  "gear":[…], "str":[…], "x":[…], "z":[…] }
```
`nsp` (0–1 lap fraction) is the alignment axis for overlays; `x`/`z` are world metres
for the map; `str` is degrees. A ~90 s lap ≈ 80–120 KB (much less over the wire).

## Notes & limitations

- **Single PC.** One machine pushes to the repo; there's no merge handling. A rejected
  `git push` (remote diverged) is reported, not auto-resolved.
- **Track/car IDs** are AC's folder names (`spa`, `ferrari_488_gt3`); the Pages site
  prettifies them.
- **Embedded interpreter.** All in-game code targets AC's Python 3.3.5 — no f-strings,
  `pathlib`, or modern typing.
- **Driver limit** in the in-game grid is 10 (plenty for a friend group); more can be
  added to `users.json` and still appear on the Pages board.
