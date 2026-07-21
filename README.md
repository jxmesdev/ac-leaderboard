# AC Leaderboard

An in-game [Assetto Corsa](https://www.assettocorsa.net/) python app that records
the **fastest valid lap per driver** for each **track + car** combination, stores
them as JSON, and pushes them to a local git clone so a **GitHub Pages** site can
display them.

- **Auto-capture** — reads AC's best (valid) lap from the sim and saves a driver's
  personal best automatically.
- **Manual entry** — type a time (e.g. `1:23.456`) for the selected driver.
- **Driver selector** — cycle drivers with `<` / `>` (defaults to *select user*);
  the list contains every driver ever entered on any track/car.
- **Create driver** — type a name + Enter.
- **Auto-publish** — every saved time is committed and `git push`ed on a background
  thread, so it never stutters the game.

## Repository layout

```
ac-leaderboard/
├── apps/python/ac_leaderboard/      ← the AC app (copy this into AC on Windows)
│   ├── ac_leaderboard.py            ← in-game entry point + UI (the "glue")
│   ├── config.example.json          ← copy to config.json and edit
│   └── acl_core/                    ← pure-Python, unit-tested logic (no `ac` import)
│       ├── config.py  storage.py  leaderboard.py
│       ├── timefmt.py git_sync.py  ac_data.py
├── docs/                            ← GitHub Pages site (serve Pages from /docs)
│   ├── index.html                   ← reads data/*.json and renders leaderboards
│   └── data/
│       ├── records.json             ← written by the app (the payload)
│       └── users.json
├── tests/test_core.py               ← run on any machine (no AC needed)
└── tools/                           ← mock `ac` + off-car smoke test
```

The **app** lives inside your AC install; the **data** lives in this repo. `config.json`
tells the app where this repo is checked out so it can write JSON and push.

## How it works

```
Assetto Corsa ──► ac_leaderboard.py ──► acl_core (storage/leaderboard)
   telemetry         (UI + glue)              │
                                              ├─► docs/data/records.json + users.json
                                              └─► git_sync ──► git commit + push (background)
                                                                    │
                                              GitHub ──► Pages (docs/index.html)
```

Auto-capture uses `ac.getCarState(0, acsys.CS.BestLap)`, which AC only sets for laps
that were **not invalidated** (no cutting / off-tracks) — so the leaderboard stays clean.
Only the single best time per `(track, config, car, driver)` is kept, so the JSON stays
small and is exactly the leaderboard payload.

## Setup (Windows gaming PC)

### 1. Prepare the GitHub repo
1. Push this project to a GitHub repo (e.g. `ac-leaderboard`).
2. In the repo: **Settings → Pages → Build from a branch → `main` / `/docs`**.
   Your board will be live at `https://<you>.github.io/ac-leaderboard/`.

### 2. Clone it on the gaming PC
```powershell
git clone https://github.com/<you>/ac-leaderboard.git C:\Users\James\Code\ac-leaderboard
```
Make sure `git push` works **without prompting** (use a credential helper, SSH key, or
a cached PAT). The app pushes non-interactively; if git blocks on a password the push
just fails and is reported in the status line.

### 3. Install the app into Assetto Corsa
Copy the app folder into your AC install:
```
…\steamapps\common\assettocorsa\apps\python\ac_leaderboard\
```
(Copy the **contents** of `apps/python/ac_leaderboard/` — i.e. `ac_leaderboard.py`
and the `acl_core/` folder — into that directory.)

### 4. Configure it
In the installed `ac_leaderboard` folder, copy `config.example.json` → `config.json`
and set `repo_path` to your clone:
```json
{
  "repo_path": "C:\\Users\\James\\Code\\ac-leaderboard",
  "data_subdir": "docs/data",
  "git_branch": "main",
  "auto_push": true,
  "auto_capture": true,
  "leaderboard_rows": 10
}
```
(If you skip this, the app still runs and stores times in a local `_localdata/` folder,
but nothing is pushed.)

### 5. Enable it in-game
- **Content Manager / AC → Settings → Assetto Corsa → General → UI Modules**: tick
  **AC Leaderboard**.
- Join a session; open the app from the right-hand app bar.

## Using it in-game

| Action | How |
|---|---|
| Pick your driver | `<` / `>` buttons (starts on *select user*) |
| Create a driver | Type a name in **New user**, press **Enter** |
| Auto-save a PB | Just drive — a new clean best lap is saved for the selected driver |
| Add a time by hand | Type e.g. `1:23.456` in **Add time**, press **Enter** |
| Toggle auto-capture | **Auto-capture: ON/OFF** button |
| Force a push | **Publish now** button |

The status line shows what happened (`PB for James: 1:21.200`, `git: synced`, etc.).

> **Note on text fields:** AC's native text-input widget is used for *create driver*
> and *add time*. If your AC build lacks it, those fields show
> *"text input unsupported"* — in that case add drivers by editing
> `docs/data/users.json` (the app reloads it on the next session) and rely on
> auto-capture for times.

## Develop / test on macOS (no Assetto Corsa needed)

The `acl_core` package never imports `ac`/`acsys`, so it runs anywhere.

```bash
# unit tests (storage, leaderboard, time parsing, config)
python3 tests/test_core.py

# full in-game flow against a fake `ac` module + a throwaway git repo
#   (creates users, manual + auto times, and a real git push)
python3 tools/smoke_ingame.py /path/to/a/git/clone

# preview the Pages site locally
cd docs && python3 -m http.server 8777   # then open http://localhost:8777
```

## Data format

`docs/data/records.json` — one entry per driver per combo (best kept):
```json
[
  {
    "track": "spa", "config": "", "car": "ferrari_488_gt3",
    "user": "James", "time_ms": 81200,
    "date": "2026-07-21T22:14:26Z", "source": "auto"
  }
]
```
`docs/data/users.json` — every driver ever created (drives the in-game selector and
the site's driver filter):
```json
["James", "Alex"]
```

## Notes & limitations

- **Single PC.** The design assumes one machine pushing to the repo; there's no merge
  handling. A `git push` that's rejected (remote diverged) is reported, not auto-resolved.
- **Track/car IDs** are AC's folder names (`spa`, `ferrari_488_gt3`). The Pages site
  prettifies them for display.
- **Embedded interpreter.** All in-game code targets AC's Python 3.3.5, so it avoids
  f-strings / `pathlib` / modern typing.
