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

from acl_core import ac_data, config, storage, telemetry, trackmap
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
RED = (1.0, 0.25, 0.25, 1.0)       # error status text


# Crash-proof breadcrumb log: written with flush+fsync so nothing is lost when
# AC crashes (unlike ac.log, which buffers). Safe to call from any thread (pure
# file I/O, no ac.*). Lives in the app folder as debug.log.
_DBG_PATH = os.path.join(APP_DIR, "debug.log")


def dbg(msg):
    try:
        f = open(_DBG_PATH, "a")
        f.write(str(msg) + "\n")
        f.flush()
        os.fsync(f.fileno())
        f.close()
    except Exception:
        pass


def dbg_reset():
    try:
        open(_DBG_PATH, "w").close()
    except Exception:
        pass


def log(msg):
    dbg(msg)   # crash-proof file first
    try:
        ac.log("[ac_leaderboard] " + str(msg))
    except Exception:
        pass


# =============================================================================
# EVERY ac.* listener callback MUST be a PLAIN MODULE-LEVEL FUNCTION.
# Closures and bound methods crash AC natively or silently fail to fire
# (proven on-rig: the validate closure crashed on Enter before its body ran;
# the driver-grid click closures crashed or did nothing). The handlers below
# only stash into module globals; the update loop consumes them next tick,
# outside AC's input event handler.
# =============================================================================
_typed_name = None
_pending_pick = None
_auto_clicked = False


def _on_validate_typed(value):
    global _typed_name
    _typed_name = value
    dbg("validate fired: " + repr(value))


def _consume_typed_name():
    global _typed_name
    v = _typed_name
    _typed_name = None
    return v


def _stash_pick(i):
    global _pending_pick
    _pending_pick = i
    dbg("pick fired: " + str(i))


# One named module-level function per driver slot (closures are banned, and a
# module function is the only way to bind the slot index safely).
def _pick_0(x, y): _stash_pick(0)
def _pick_1(x, y): _stash_pick(1)
def _pick_2(x, y): _stash_pick(2)
def _pick_3(x, y): _stash_pick(3)
def _pick_4(x, y): _stash_pick(4)
def _pick_5(x, y): _stash_pick(5)
def _pick_6(x, y): _stash_pick(6)
def _pick_7(x, y): _stash_pick(7)
def _pick_8(x, y): _stash_pick(8)
def _pick_9(x, y): _stash_pick(9)


_PICK_CBS = (_pick_0, _pick_1, _pick_2, _pick_3, _pick_4,
             _pick_5, _pick_6, _pick_7, _pick_8, _pick_9)


def _consume_pick():
    global _pending_pick
    v = _pending_pick
    _pending_pick = None
    return v


def _on_auto_clicked(x, y):
    global _auto_clicked
    _auto_clicked = True
    dbg("auto toggle fired")


def _consume_auto_clicked():
    global _auto_clicked
    v = _auto_clicked
    _auto_clicked = False
    return v


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
            logger=dbg,   # file-only logger: safe to call from the git thread
        )
        self._last_git_log = ""

        # session state
        self.track = ""
        self.track_config = ""
        self.car = ""
        self.users = self.store.all_users()
        self.selected = None           # display name of active driver
        self.last_seen_best = 0        # for auto-capture edge detection
        self.auto_capture = bool(self.cfg.get("auto_capture"))
        self.status_text = ""
        self.status_error = False
        self._accum = 0.0
        # True only while the car is moving. Checked at the slow cadence so that
        # while parked/typing there are ZERO per-frame ac.* reads (which crash
        # AC's keyboard input on Enter).
        self._moving = False
        self._rows = int(self.cfg.get("leaderboard_rows") or 10)

        # telemetry recording
        self.record_telemetry = bool(self.cfg.get("record_telemetry"))
        self.recorder = telemetry.LapRecorder(hz=int(self.cfg.get("telemetry_hz") or 30))

        # widget ids
        self.l_track = None
        self.l_car = None
        self.driver_btns = []          # MAX_DRIVERS button ids
        self.driver_btn_pos = []       # each button's on-screen (x, y)
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
        win_h = 150 + driver_grid_rows * 26 + 140 + self._rows * ROW_H
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
            ac.addOnClickedListener(bid, _PICK_CBS[i])
            try:
                ac.setFontSize(bid, 13)
            except Exception:
                pass
            self.driver_btns.append(bid)
            self.driver_btn_pos.append((bx, by))
        y = grid_y0 + driver_grid_rows * 26 + 6

        # Add a driver: type a name + Enter. (No "+ Add me" button -- it triggered
        # a native crash on this rig; typing is the single, reliable path.)
        self._label("New driver (type + Enter):", MARGIN, y, 12)
        y += 16
        self.in_newuser = self._text_input(MARGIN, y, WIN_W - 2 * MARGIN, 22,
                                           _on_validate_typed)
        y += 28

        # Status line (above the auto-capture button; red when it's an error).
        self.l_status = self._label("", MARGIN, y, 12)
        y += 22

        self.b_auto = self._button(self._auto_label(), MARGIN, y, 150, 22,
                                   _on_auto_clicked)
        y += 28

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
        # cb MUST be a plain module-level function (closures/bound methods
        # crash AC or silently fail -- see the listener block at the top).
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
        try:
            tid = ac.addTextInput(self.window, "")
            ac.setPosition(tid, x, y)
            ac.setSize(tid, w, h)
            ac.addOnValidateListener(tid, cb)
            return tid
        except Exception:
            log("addTextInput unavailable")
            return None

    def _color(self, lid, rgba):
        try:
            ac.setFontColor(lid, rgba[0], rgba[1], rgba[2], rgba[3])
        except Exception:
            pass

    # -- driver selection -------------------------------------------------
    def current_user(self):
        return self.selected

    def on_pick(self, index):
        if index < 0 or index >= len(self.users):
            return
        self.selected = self.users[index]
        # NB: last_seen_best is NOT reset -- a lap driven before this switch is
        # never credited to the newly picked driver. Only a best set AFTER
        # selection (i.e. beating the session best) records.
        self._render_driver_grid()
        self._refresh_board()
        self._set_status("driver: " + self.selected)

    def _render_driver_grid(self):
        """Label active slots with driver names; park empties off-screen."""
        for i, bid in enumerate(self.driver_btns):
            if i < len(self.users):
                name = self.users[i]
                mark = "> " if name == self.selected else "  "
                # Restore the on-screen position: a slot that was previously
                # empty is parked off-screen, so a newly-added driver must be
                # moved back or its button stays hidden.
                bx, by = self.driver_btn_pos[i]
                try:
                    ac.setPosition(bid, bx, by)
                except Exception:
                    pass
                self._set(bid, mark + name)
                self._color(bid, ACCENT if name == self.selected else WHITE)
            else:
                self._set(bid, "")
                try:
                    ac.setPosition(bid, -500, -500)   # hide unused slot
                except Exception:
                    pass

    def _add_driver(self, name):
        """Add a NEW driver (typed + Enter) and select them.

        Typing an existing name is an error and does NOT switch -- use the
        driver buttons to switch. There is no auto-select/auto-create from the
        AC profile name; typing and clicking are the only two paths.
        """
        log("add_driver: start " + repr(name))
        name = (name or "").strip()
        if not name:
            return
        # Existing driver (case-insensitive)?
        for u in self.users:
            if storage.norm(u) == storage.norm(name):
                self._set_status("'" + u + "' already exists -- "
                                 "click their name to switch", error=True)
                log("add_driver: done (existing)")
                return
        if len(self.users) >= MAX_DRIVERS:
            self._set_status("driver limit reached (" + str(MAX_DRIVERS) + ")",
                             error=True)
            return
        self.store.add_user(name)
        self.users = self.store.all_users()
        self.selected = name
        # last_seen_best NOT reset (see on_pick): earlier laps stay unattributed.
        self._render_driver_grid()
        self._refresh_board()
        self.store.save()
        self._set_status("added driver: " + name)
        self._publish("Add driver " + name)
        log("add_driver: done")

    # -- recording --------------------------------------------------------
    def _record(self, user, ms):
        track, cfg, car = self.track, self.track_config, self.car
        if not track or not car:
            return
        rec = storage.make_record(track, cfg, car, user, ms, "auto")
        result = self.store.upsert_record(rec)
        if result not in ("new", "improved"):
            self._set_status("{0}: {1} not faster than current".format(user, format_ms(ms)))
            return
        extra = self._save_telemetry(track, cfg, car, user, ms, rec.get("date"))
        self.store.save()
        self._refresh_board()
        verb = "PB" if result == "improved" else "time"
        self._set_status("{0} for {1}: {2}".format(verb, user, format_ms(ms)))
        self._publish("{0} {1} {2} {3}".format(user, track, car, format_ms(ms)),
                      extra_paths=extra)

    def _save_telemetry(self, track, cfg, car, user, ms, date):
        """Write best-lap telemetry and link it to the stored record.

        Returns a list of extra file paths to include in the git push.
        """
        if not self.record_telemetry:
            return []
        lap = self.recorder.take_last_lap()
        if not lap:
            return []
        extra = []
        try:
            payload = telemetry.build_payload(lap, track, cfg, car, user, ms,
                                              date, self.recorder.hz)
            tm = self._grab_trackmap(track, cfg)
            if tm is not None:
                payload["trackmap"] = tm[0]
                extra.append(tm[1])
            relpath = telemetry.write_telemetry(self.cfg.data_dir, payload)
        except Exception:
            log("telemetry write failed:\n" + traceback.format_exc())
            return []
        stored = self.store.find_record(track, cfg, car, user)
        if stored is not None:
            stored["telemetry"] = relpath
        return [os.path.join(self.cfg.data_dir, relpath)] + extra

    def _grab_trackmap(self, track, cfg):
        """Best-effort copy of the AC track's map.png for the web viewer."""
        try:
            ac_root = self.cfg.get("ac_root") or trackmap.find_ac_root(APP_DIR)
            return trackmap.grab(ac_root, track, cfg, self.cfg.data_dir)
        except Exception:
            log("trackmap grab failed:\n" + traceback.format_exc())
            return None

    # -- controls ---------------------------------------------------------
    def _auto_label(self):
        return "Auto-capture: " + ("ON" if self.auto_capture else "OFF")

    def on_toggle_auto(self, *args):
        self.auto_capture = not self.auto_capture
        self._set(self.b_auto, self._auto_label())

    def _publish(self, message, force=False, extra_paths=None):
        if not self.cfg.repo_configured():
            self._set_status("not a git clone -- cannot push", error=True)
            return
        if not (self.cfg.get("auto_push") or force):
            return
        paths = self.store.data_paths()
        if extra_paths:
            paths = paths + list(extra_paths)
        self.git.request_push(paths, message)

    def _on_git_status(self, status):
        # Called from the git worker thread; only touches simple values.
        self.status_error = status.startswith("error")
        self.status_text = "git: " + status

    # -- rendering --------------------------------------------------------
    def _set_status(self, text, error=False):
        self.status_text = text
        self.status_error = error

    def _apply_status(self):
        self._set(self.l_status, self.status_text)
        self._color(self.l_status, RED if self.status_error else MUTED)

    def _refresh_board(self):
        if not self.row_pos:
            return   # board labels not built (defensive)
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

    # -- per-frame update -------------------------------------------------
    def update(self, dt):
        # A typed name (Enter) stashes into the module-level _typed_name (the
        # validate handler must be a plain module function); apply it here,
        # outside the input's event handler.
        pending = _consume_typed_name()
        if pending is not None:
            name = (pending or "").strip()
            log("update: pending driver " + repr(name))
            if name:
                self._add_driver(name)
            if self.in_newuser is not None:
                log("update: clearing input")
                self._set(self.in_newuser, "")
            log("update: pending handled")

        # A clicked driver button stashes its slot index; apply it here,
        # outside the click event handler. Same for the auto-capture toggle.
        pick = _consume_pick()
        if pick is not None:
            log("update: pick " + str(pick))
            self.on_pick(pick)
        if _consume_auto_clicked():
            self.on_toggle_auto()

        # Mirror git status to the log from the MAIN thread (the worker thread
        # must never call ac.*). Cheap string compare each frame.
        if self.git.last_status != self._last_git_log:
            self._last_git_log = self.git.last_status
            log("git status -> " + self.git.last_status)

        # High-rate telemetry sampling -- only while MOVING. self._moving is set
        # at the slow cadence below, so while parked/typing there are ZERO
        # per-frame ac.* reads on the input path (belt-and-braces robustness;
        # you never type while driving anyway).
        if self._moving and self.record_telemetry \
                and self.auto_capture and self.track and self.car:
            self._sample_telemetry(dt)

        # Everything else (UI, best-lap poll) runs at a relaxed cadence.
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
            self.recorder.reset()
            self._set(self.l_track, "Track: " + self._combo_name(track, cfg))
            self._set(self.l_car, "Car: " + (car or "-"))
            self._refresh_board()

        # Decide (at this slow cadence) whether we're moving, so the per-frame
        # telemetry sampling above does no ac.* work while parked.
        self._moving = ac_data.get_speed_kmh() >= 3.0

        if self.auto_capture:
            self._poll_best_lap()

        self._apply_status()

    def _sample_telemetry(self, dt):
        # Gated by self._moving in update(), so this only runs while driving.
        nsp = ac_data.get_nsp()
        if nsp is None:
            return
        x, z = ac_data.get_world_xz()
        self.recorder.tick(dt, nsp, ac_data.get_gas(), ac_data.get_brake(),
                           ac_data.get_speed_kmh(), ac_data.get_gear(),
                           ac_data.get_steer_rad(), x, z)

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
        # Mark the lap as seen FIRST: with no driver selected it is discarded,
        # not held for whoever gets picked later (they didn't drive it).
        self.last_seen_best = best
        user = self.current_user()
        if user is None:
            self._set_status("lap " + format_ms(best) +
                             " not saved -- no driver selected", error=True)
            return
        self._record(user, best)


# -- module-level AC entry points -----------------------------------------
_app = None


def acMain(ac_version):
    global _app
    dbg_reset()
    dbg("acMain: start")
    try:
        _app = LeaderboardApp().build()
        dbg("acMain: build ok")
    except Exception:
        dbg("acMain error:\n" + traceback.format_exc())
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
