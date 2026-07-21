# AC Leaderboard -- in-game Assetto Corsa python app.
#
# Records the fastest VALID lap per driver for each track+car combination,
# stores them as JSON, and pushes them to the git repo this app was cloned from
# (for a GitHub Pages site). Python 3.3 compatible -- runs under AC's embedded
# interpreter.
#
# This file is the thin "glue" between AC's `ac`/`acsys` API and the
# pure-Python logic in the acl_core package (which is unit-tested off-car).

import os
import sys
import traceback

# Make sibling packages importable under AC's embedded interpreter.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import ac  # provided by Assetto Corsa

from acl_core import ac_data, config, storage
from acl_core.git_sync import GitSync
from acl_core.leaderboard import leaderboard_for
from acl_core.timefmt import format_ms

APP_NAME = "AC Leaderboard"

# Layout constants (pixels).
WIN_W = 380
MARGIN = 10
MAX_DRIVERS = 10          # clickable driver slots (2 columns)
DRIVER_COLS = 2
ROW_H = 22

ACCENT = (0.96, 0.65, 0.14, 1.0)   # selected / leader highlight
WHITE = (1.0, 1.0, 1.0, 1.0)
MUTED = (0.60, 0.65, 0.70, 1.0)


def log(msg):
    try:
        ac.log("[ac_leaderboard] " + str(msg))
    except Exception:
        pass


class LeaderboardApp(object):
    def __init__(self):
        self.window = None
        self.cfg = config.load(APP_DIR)
        self.store = storage.Store(self.cfg.data_dir).load()
        self.git = GitSync(
            self.cfg.repo_path,
            branch=self.cfg.get("git_branch"),
            remote=self.cfg.get("git_remote"),
            author_name=self.cfg.get("author_name"),
            author_email=self.cfg.get("author_email"),
            git_exe=self.cfg.get("git_exe"),
            on_status=self._on_git_status,
            logger=log,
        )

        # session state
        self.track = ""
        self.track_config = ""
        self.car = ""
        self.users = self.store.all_users()
        self.selected = None           # display name of active driver
        self.last_seen_best = 0        # for auto-capture edge detection
        self.auto_capture = bool(self.cfg.get("auto_capture"))
        self.status_text = ""
        self._accum = 0.0
        self._rows = int(self.cfg.get("leaderboard_rows") or 10)

        # widget ids
        self.l_track = None
        self.l_car = None
        self.driver_btns = []          # MAX_DRIVERS button ids
        self.in_newuser = None
        self.l_status = None
        self.b_auto = None
        self.row_pos = []
        self.row_user = []
        self.row_time = []
        self.row_gap = []
        self.cx_pos = MARGIN
        self.cx_user = MARGIN + 28
        self.cx_time = WIN_W - 150
        self.cx_gap = WIN_W - 70

    # -- construction -----------------------------------------------------
    def build(self):
        driver_grid_rows = (MAX_DRIVERS + DRIVER_COLS - 1) // DRIVER_COLS
        win_h = 150 + driver_grid_rows * 26 + 120 + self._rows * ROW_H
        self.window = ac.newApp(APP_NAME)
        ac.setSize(self.window, WIN_W, win_h)
        try:
            ac.setTitle(self.window, APP_NAME)
            ac.setBackgroundOpacity(self.window, 0.85)
            ac.drawBorder(self.window, 0)
        except Exception:
            pass

        y = 32
        self.l_track = self._label("Track: -", MARGIN, y, 13)
        y += 18
        self.l_car = self._label("Car: -", MARGIN, y, 13)
        y += 26

        self._label("Driver  (click to select):", MARGIN, y, 13)
        y += 20

        # Clickable driver grid (2 columns). Empty slots are parked off-screen.
        col_w = (WIN_W - (DRIVER_COLS + 1) * MARGIN) // DRIVER_COLS
        grid_y0 = y
        for i in range(MAX_DRIVERS):
            col = i % DRIVER_COLS
            row = i // DRIVER_COLS
            bx = MARGIN + col * (col_w + MARGIN)
            by = grid_y0 + row * 26
            bid = ac.addButton(self.window, "")
            ac.setPosition(bid, bx, by)
            ac.setSize(bid, col_w, 22)
            ac.addOnClickedListener(bid, self._make_pick_cb(i))
            try:
                ac.setFontSize(bid, 13)
            except Exception:
                pass
            self.driver_btns.append(bid)
        y = grid_y0 + driver_grid_rows * 26 + 6

        # Create driver: type a name and press Enter.
        # NOTE: AC/CSP only hands us the typed text via this Enter/validate
        # callback. Reading a text field on demand (ac.getText) crashes AC at
        # the native level, so there is deliberately no "Add" button here.
        self._label("New driver (type name, press Enter):", MARGIN, y, 12)
        y += 16
        self.in_newuser = self._text_input(MARGIN, y, WIN_W - 2 * MARGIN, 22,
                                           self.on_create_user)
        y += 30

        # Controls: auto-capture toggle.
        self.b_auto = self._button(self._auto_label(), MARGIN, y, 150, 22,
                                   self.on_toggle_auto)
        y += 28

        # Status line.
        self.l_status = self._label("", MARGIN, y, 12)
        y += 22

        # Leaderboard header + rows (4 aligned columns).
        self._label("#", self.cx_pos, y, 13)
        self._label("Driver", self.cx_user, y, 13)
        self._label("Time", self.cx_time, y, 13)
        self._label("Gap", self.cx_gap, y, 13)
        y += ROW_H
        for _ in range(self._rows):
            self.row_pos.append(self._label("", self.cx_pos, y, 13))
            self.row_user.append(self._label("", self.cx_user, y, 13))
            self.row_time.append(self._label("", self.cx_time, y, 13))
            self.row_gap.append(self._label("", self.cx_gap, y, 13))
            y += ROW_H

        if not self.cfg.repo_configured():
            self._set_status("not a git clone -- times save locally, no push")
        else:
            self._set_status("ready")

        self._render_driver_grid()
        self._refresh_board()
        return self

    # -- widget helpers ---------------------------------------------------
    def _label(self, text, x, y, size):
        lid = ac.addLabel(self.window, text)
        ac.setPosition(lid, x, y)
        try:
            ac.setFontSize(lid, size)
        except Exception:
            pass
        return lid

    def _button(self, text, x, y, w, h, cb):
        bid = ac.addButton(self.window, text)
        ac.setPosition(bid, x, y)
        ac.setSize(bid, w, h)
        ac.addOnClickedListener(bid, cb)
        try:
            ac.setFontSize(bid, 13)
        except Exception:
            pass
        return bid

    def _text_input(self, x, y, w, h, cb):
        """Create a text input if the AC build supports it; else None."""
        try:
            tid = ac.addTextInput(self.window, "")
            ac.setPosition(tid, x, y)
            ac.setSize(tid, w, h)
            ac.addOnValidateListener(tid, cb)
            return tid
        except Exception:
            log("addTextInput unavailable; add drivers by editing users.json")
            self._label("(add drivers by editing docs/data/users.json)", x, y, 11)
            return None

    def _color(self, lid, rgba):
        try:
            ac.setFontColor(lid, rgba[0], rgba[1], rgba[2], rgba[3])
        except Exception:
            pass

    # -- driver selection -------------------------------------------------
    def current_user(self):
        return self.selected

    def _make_pick_cb(self, index):
        def cb(x, y):
            self.on_pick(index)
        return cb

    def on_pick(self, index):
        if index < 0 or index >= len(self.users):
            return
        self.selected = self.users[index]
        self.last_seen_best = 0        # allow capturing the current best for them
        self._render_driver_grid()
        self._refresh_board()
        self._set_status("driver: " + self.selected)

    def _render_driver_grid(self):
        """Label active slots with driver names; park empties off-screen."""
        for i, bid in enumerate(self.driver_btns):
            if i < len(self.users):
                name = self.users[i]
                mark = "> " if name == self.selected else "  "
                self._set(bid, mark + name)
                self._color(bid, ACCENT if name == self.selected else WHITE)
            else:
                self._set(bid, "")
                try:
                    ac.setPosition(bid, -500, -500)   # hide unused slot
                except Exception:
                    pass

    def on_create_user(self, name):
        name = (name or "").strip()
        if not name:
            return
        if len(self.users) >= MAX_DRIVERS and name not in self.users:
            self._set_status("driver limit reached (" + str(MAX_DRIVERS) + ")")
            self._clear_input(self.in_newuser)
            return
        added = self.store.add_user(name)
        self.users = self.store.all_users()
        self.selected = name
        self.last_seen_best = 0
        self._render_driver_grid()
        self._refresh_board()
        if added:
            self.store.save()
            self._set_status("created driver: " + name)
            self._publish("Add driver " + name)
        else:
            self._set_status("selected: " + name)
        self._clear_input(self.in_newuser)

    # -- recording --------------------------------------------------------
    def _record(self, user, ms):
        track, cfg, car = self.track, self.track_config, self.car
        if not track or not car:
            return
        rec = storage.make_record(track, cfg, car, user, ms, "auto")
        result = self.store.upsert_record(rec)
        if result in ("new", "improved"):
            self.store.save()
            self._refresh_board()
            verb = "PB" if result == "improved" else "time"
            self._set_status("{0} for {1}: {2}".format(verb, user, format_ms(ms)))
            self._publish("{0} {1} {2} {3}".format(user, track, car, format_ms(ms)))
        else:
            self._set_status("{0}: {1} not faster than current".format(user, format_ms(ms)))

    # -- controls ---------------------------------------------------------
    def _auto_label(self):
        return "Auto-capture: " + ("ON" if self.auto_capture else "OFF")

    def on_toggle_auto(self, *args):
        self.auto_capture = not self.auto_capture
        self._set(self.b_auto, self._auto_label())

    def _publish(self, message, force=False):
        if not self.cfg.repo_configured():
            self._set_status("not a git clone -- cannot push")
            return
        if not (self.cfg.get("auto_push") or force):
            return
        self.git.request_push(self.store.data_paths(), message)

    def _on_git_status(self, status):
        # Called from the git worker thread; only touches a simple string.
        self.status_text = "git: " + status

    # -- rendering --------------------------------------------------------
    def _set_status(self, text):
        self.status_text = text

    def _apply_status(self):
        self._set(self.l_status, self.status_text)

    def _refresh_board(self):
        rows = leaderboard_for(self.store.records, self.track,
                               self.track_config, self.car)
        for i in range(self._rows):
            if i < len(rows):
                r = rows[i]
                is_me = (self.selected is not None and
                         r["user"].lower() == self.selected.lower())
                self._set(self.row_pos[i], str(r["rank"]))
                self._set(self.row_user[i], ("> " if is_me else "") + r["user"])
                self._set(self.row_time[i], r["time_str"])
                self._set(self.row_gap[i], r["gap_str"])
                pos_col = ACCENT if (is_me or r["rank"] == 1) else WHITE
                self._color(self.row_pos[i], pos_col)
                self._color(self.row_user[i], ACCENT if is_me else WHITE)
                self._color(self.row_gap[i], MUTED)
            else:
                self._set(self.row_pos[i], "")
                self._set(self.row_user[i], "")
                self._set(self.row_time[i], "")
                self._set(self.row_gap[i], "")

    def _set(self, lid, text):
        try:
            ac.setText(lid, text)
        except Exception:
            pass

    def _clear_input(self, tid):
        if tid is None:
            return
        try:
            ac.setText(tid, "")
        except Exception:
            pass

    # -- per-frame update -------------------------------------------------
    def update(self, dt):
        self._accum += dt
        if self._accum < 0.5:
            return
        self._accum = 0.0

        track = ac_data.get_track()
        cfg = ac_data.get_track_config()
        car = ac_data.get_car()
        if (track, cfg, car) != (self.track, self.track_config, self.car):
            self.track, self.track_config, self.car = track, cfg, car
            self.last_seen_best = 0
            self._set(self.l_track, "Track: " + self._combo_name(track, cfg))
            self._set(self.l_car, "Car: " + (car or "-"))
            self._refresh_board()

        if self.auto_capture:
            self._poll_best_lap()

        self._apply_status()

    def _combo_name(self, track, cfg):
        if not track:
            return "-"
        return track + ((" / " + cfg) if cfg else "")

    def _poll_best_lap(self):
        best = ac_data.get_best_lap_ms()
        if best <= 0:
            self.last_seen_best = 0
            return
        if self.last_seen_best != 0 and best >= self.last_seen_best:
            return  # nothing new since last poll
        user = self.current_user()
        if user is None:
            # Keep prompting so the lap is still captured once a driver is picked.
            self._set_status("new best " + format_ms(best) + " -- pick your driver to save it")
            return
        self.last_seen_best = best
        self._record(user, best)


# -- module-level AC entry points -----------------------------------------
_app = None


def acMain(ac_version):
    global _app
    try:
        _app = LeaderboardApp().build()
    except Exception:
        log("acMain error:\n" + traceback.format_exc())
    return APP_NAME


def acUpdate(deltaT):
    if _app is None:
        return
    try:
        _app.update(deltaT)
    except Exception:
        log("acUpdate error:\n" + traceback.format_exc())


def acShutdown():
    if _app is None:
        return
    try:
        _app.store.save()
    except Exception:
        log("acShutdown error:\n" + traceback.format_exc())
