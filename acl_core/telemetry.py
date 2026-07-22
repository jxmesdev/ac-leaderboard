# Per-lap telemetry recording. Python 3.3 compatible. No `ac` import.
#
# A LapRecorder is fed one sample per frame via tick(); it buffers the current
# lap, detects the start/finish crossing from the normalized spline position,
# and hands back the just-completed lap when asked. The in-game app flushes that
# lap to a compact columnar JSON file only when the driver sets a new best, so
# only best-lap telemetry is ever stored (mirroring the leaderboard).

import io
import json
import os
import re

RAD_TO_DEG = 57.295779513

# Per-sample channels stored, in columnar form.
CHANNELS = ("nsp", "t", "thr", "brk", "spd", "gear", "str", "x", "z")

MIN_SAMPLES = 20   # ignore tiny partial "laps" (out-lap fragments, resets)


def slug(s):
    """Filesystem-safe token: lowercase, non-alphanumerics -> single '_'."""
    s = "" if s is None else str(s).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def telemetry_filename(track, config, car, driver):
    return "__".join([slug(track), slug(config), slug(car), slug(driver)]) + ".json"


class LapRecorder(object):
    def __init__(self, hz=30):
        self.hz = hz
        self.dt_target = 1.0 / float(hz)
        self.last_lap = None       # dict of finished lap once available
        self._reset_current()
        self._prev_nsp = None

    # -- lifecycle --------------------------------------------------------
    def reset(self):
        """Drop everything (call on track/car change)."""
        self._reset_current()
        self._prev_nsp = None
        self.last_lap = None

    def _reset_current(self):
        self._cur = dict((c, []) for c in CHANNELS)
        self._accum = self.dt_target      # sample immediately on first tick
        self._dist_m = 0.0                # integrated distance this lap
        self._lap_t = 0.0                 # elapsed time this lap (s)

    # -- feeding ----------------------------------------------------------
    def tick(self, dt, nsp, gas, brake, speed_kmh, gear, steer_rad, x, z):
        """Feed one frame of telemetry. Safe to call every frame."""
        if nsp is None:
            return
        try:
            nsp = float(nsp)
        except (TypeError, ValueError):
            return

        # Start/finish crossing = normalized position wraps 1.0 -> 0.0.
        if self._prev_nsp is not None and (self._prev_nsp - nsp) > 0.5:
            self._finalize()
        self._prev_nsp = nsp

        speed_kmh = _f(speed_kmh)
        self._dist_m += max(0.0, speed_kmh) / 3.6 * dt
        self._lap_t += dt

        # Down-sample to the target rate.
        self._accum += dt
        if self._accum + 1e-9 < self.dt_target:
            return
        self._accum = 0.0

        cur = self._cur
        cur["nsp"].append(round(nsp, 4))
        cur["t"].append(int(round(self._lap_t * 1000)))
        cur["thr"].append(_clamp_pct(_f(gas) * 100.0))
        cur["brk"].append(_clamp_pct(_f(brake) * 100.0))
        cur["spd"].append(round(speed_kmh, 1))
        cur["gear"].append(int(_f(gear)))
        cur["str"].append(round(_f(steer_rad) * RAD_TO_DEG, 1))
        cur["x"].append(round(_f(x), 1))
        cur["z"].append(round(_f(z), 1))

    def _finalize(self):
        cur = self._cur
        if len(cur["nsp"]) >= MIN_SAMPLES:
            lap = dict((c, cur[c]) for c in CHANNELS)
            lap["_len_m"] = round(self._dist_m, 1)
            lap["_dur_ms"] = int(round(self._lap_t * 1000))
            self.last_lap = lap
        self._reset_current()

    # -- output -----------------------------------------------------------
    def take_last_lap(self):
        """Return (and clear) the most recently completed lap, or None."""
        lap = self.last_lap
        self.last_lap = None
        return lap


def build_payload(lap, track, config, car, driver, time_ms, date, hz):
    """Assemble the on-disk telemetry dict from a finished lap + metadata."""
    payload = {
        "track": track or "",
        "config": config or "",
        "car": car or "",
        "driver": driver or "",
        "time_ms": int(time_ms),
        "date": date or "",
        "hz": hz,
        "track_len_m": lap.get("_len_m", 0.0),
        "n": len(lap.get("nsp", [])),
    }
    for c in CHANNELS:
        payload[c] = lap.get(c, [])
    return payload


def write_telemetry(data_dir, payload):
    """Write a telemetry payload compactly; return its path relative to data_dir."""
    filename = telemetry_filename(payload.get("track"), payload.get("config"),
                                  payload.get("car"), payload.get("driver"))
    tel_dir = os.path.join(data_dir, "telemetry")
    if not os.path.isdir(tel_dir):
        os.makedirs(tel_dir)
    path = os.path.join(tel_dir, filename)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")))
        f.write("\n")
    os.replace(tmp, path)
    return "telemetry/" + filename


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _clamp_pct(v):
    iv = int(round(v))
    if iv < 0:
        return 0
    if iv > 100:
        return 100
    return iv
