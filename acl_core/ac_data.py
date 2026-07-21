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


def get_best_lap_ms():
    """Best VALID lap of the current session in ms (0 if none yet).

    AC only records a BestLap for laps that were not invalidated (off-track,
    cutting, etc.), which is exactly what we want for a clean leaderboard.
    """
    if not _HAVE_AC:
        return 0
    return _car_state_int(acsys.CS.BestLap)


def get_last_lap_ms():
    if not _HAVE_AC:
        return 0
    return _car_state_int(acsys.CS.LastLap)
