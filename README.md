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
- **Create driver** — type a name + Enter (or pre-seed `docs/data/users.json`).
- **Auto-publish** — every saved time is committed and `git push`ed on a background
  thread, so it never stutters the game.

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

## Using it in-game

| Action | How |
|---|---|
| Pick your driver | Click your name in the driver grid |
| Create a driver | Type a name in **New driver**, press **Enter** |
| Save a PB | Just drive — a new clean best lap is saved for the selected driver |
| Toggle auto-capture | **Auto-capture: ON/OFF** button |
| Force a push | **Publish now** button |

The status line shows what happened (`PB for James: 1:21.200`, `git: synced`, …).

> **Text field note:** AC's native text widget is used for *create driver*. If your
> AC build lacks it, that field says so — add drivers by editing
> `docs/data/users.json` (a JSON list of names); the app loads it next session.

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
│   ├── timefmt.py git_sync.py  ac_data.py
├── docs/                        ← GitHub Pages site (Pages serves from /docs)
│   ├── index.html               ← reads data/*.json and renders leaderboards
│   └── data/{records,users}.json
├── tests/test_core.py           ← run on any machine (no AC needed)
└── tools/                       ← mock `ac` + off-car smoke test
```

## Develop / test on macOS (no Assetto Corsa needed)

The `acl_core` package never imports `ac`/`acsys`, so it runs anywhere.

```bash
python3 tests/test_core.py                       # unit tests
python3 tools/smoke_ingame.py /path/to/a/clone   # full flow vs a fake `ac` + real git push
cd docs && python3 -m http.server 8777           # preview the Pages site
```

## Data format

`docs/data/records.json` — one entry per driver per combo (best kept):
```json
[
  { "track": "spa", "config": "", "car": "ferrari_488_gt3",
    "user": "James", "time_ms": 81200,
    "date": "2026-07-21T22:14:26Z", "source": "auto" }
]
```
`docs/data/users.json` — every driver ever created:
```json
["James", "Alex"]
```

## Notes & limitations

- **Single PC.** One machine pushes to the repo; there's no merge handling. A rejected
  `git push` (remote diverged) is reported, not auto-resolved.
- **Track/car IDs** are AC's folder names (`spa`, `ferrari_488_gt3`); the Pages site
  prettifies them.
- **Embedded interpreter.** All in-game code targets AC's Python 3.3.5 — no f-strings,
  `pathlib`, or modern typing.
- **Driver limit** in the in-game grid is 10 (plenty for a friend group); more can be
  added to `users.json` and still appear on the Pages board.
