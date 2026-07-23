# Thin, crash-proof wrappers around the in-game `ac`/`acsys` telemetry API.
# Python 3.3 compatible.
#
# Import is guarded so this module is safe to import on a dev machine (macOS)
# where `ac`/`acsys` do not exist -- every getter simply returns a neutral value.

try:
    import ac
    import acsys
    _HAVE_AC = True
except Exception:  # not running inside Assetto Corsa
    ac = None
    acsys = None
    _HAVE_AC = False

PLAYER = 0  # car id of the local player


def have_ac():
    return _HAVE_AC


def get_track():
    if not _HAVE_AC:
        return ""
    try:
        return (ac.getTrackName(PLAYER) or "").strip()
    except Exception:
        return ""


def get_track_config():
    if not _HAVE_AC:
        return ""
    try:
        return (ac.getTrackConfiguration(PLAYER) or "").strip()
    except Exception:
        return ""


def get_car():
    if not _HAVE_AC:
        return ""
    try:
        return (ac.getCarName(PLAYER) or "").strip()
    except Exception:
        return ""


def get_driver_name():
    """The local player's AC profile/driver name ("" if unavailable)."""
    if not _HAVE_AC:
        return ""
    try:
        return (ac.getDriverName(PLAYER) or "").strip()
    except Exception:
        return ""


def _car_state_int(which):
    if not _HAVE_AC:
        return 0
    try:
        val = ac.getCarState(PLAYER, which)
        if val is None:
            return 0
        return int(val)
    except Exception:
        return 0


def _car_state_float(which):
    if not _HAVE_AC:
        return 0.0
    try:
        val = ac.getCarState(PLAYER, which)
        if val is None:
            return 0.0
        return float(val)
    except Exception:
        return 0.0


# -- live telemetry channels (for the lap recorder) -----------------------
def get_nsp():
    """Normalized spline position, 0..1 around the lap (None if unavailable)."""
    if not _HAVE_AC:
        return None
    try:
        return float(ac.getCarState(PLAYER, acsys.CS.NormalizedSplinePosition))
    except Exception:
        return None


def get_gas():
    return _car_state_float(acsys.CS.Gas) if _HAVE_AC else 0.0


def get_brake():
    return _car_state_float(acsys.CS.Brake) if _HAVE_AC else 0.0


def get_speed_kmh():
    return _car_state_float(acsys.CS.SpeedKMH) if _HAVE_AC else 0.0


def get_gear():
    return _car_state_int(acsys.CS.Gear) if _HAVE_AC else 0


def get_steer_deg():
    """Steering wheel rotation in DEGREES (acsys.CS.Steer is degrees)."""
    return _car_state_float(acsys.CS.Steer) if _HAVE_AC else 0.0


def get_world_xz():
    """Top-down car position (x, z) in world metres; (0, 0) if unavailable."""
    if not _HAVE_AC:
        return (0.0, 0.0)
    try:
        wp = ac.getCarState(PLAYER, acsys.CS.WorldPosition)
        return (float(wp[0]), float(wp[2]))
    except Exception:
        return (0.0, 0.0)


def get_best_lap_ms():
    """Best VALID lap of the current session in ms (0 if none yet).

    NOTE: this is AC's SESSION best -- shared across driver swaps on one rig,
    so the leaderboard no longer uses it for capture. Kept for reference.
    """
    if not _HAVE_AC:
        return 0
    return _car_state_int(acsys.CS.BestLap)


def get_last_lap_ms():
    """Time of the most recently COMPLETED lap in ms (0 if none). Unlike
    BestLap this reports every lap, so each completed lap can be judged
    against the current driver's own record."""
    if not _HAVE_AC:
        return 0
    return _car_state_int(acsys.CS.LastLap)


def get_last_splits():
    """Sector times (ms) of the most recently completed lap, as a list of
    ints. [] when unavailable (no lap yet, API missing, or bad values)."""
    if not _HAVE_AC:
        return []
    try:
        splits = ac.getLastSplits(PLAYER)
        if not splits:
            return []
        return [int(s) for s in splits]
    except Exception:
        return []


def get_lap_count():
    """Completed-lap count for the session (0 at the start)."""
    if not _HAVE_AC:
        return 0
    return _car_state_int(acsys.CS.LapCount)


def get_lap_invalidated():
    """True if the CURRENT lap has been invalidated (cut/off-track).

    Falls back to False if this build's acsys lacks the enum, in which case
    every completed lap counts.
    """
    if not _HAVE_AC:
        return False
    which = getattr(acsys.CS, "LapInvalidated", None)
    if which is None:
        return False
    return _car_state_int(which) != 0
