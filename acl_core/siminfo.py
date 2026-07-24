# Session conditions from AC's shared memory. Python 3.3 compatible.
#
# The in-game python API exposes no weather, so air/road temperature, track
# grip and wind come straight from the simulator's shared-memory pages
# (the same mechanism every AC telemetry tool uses). Struct layouts are
# copied verbatim from the community-standard sim_info.py for AC 1.16+;
# only the fields up to the ones we read are declared (a shorter mapping
# of the same page is safe). Windows-only by nature -- on any other OS or
# with AC not running, read_conditions() just returns None. Never raises.

import ctypes
import mmap
from ctypes import c_float, c_int32, c_wchar


class _PhysicsHead(ctypes.Structure):
    """SPageFilePhysics up to roadTemp (all we need)."""
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int32),
        ("gas", c_float),
        ("brake", c_float),
        ("fuel", c_float),
        ("gear", c_int32),
        ("rpms", c_int32),
        ("steerAngle", c_float),
        ("speedKmh", c_float),
        ("velocity", c_float * 3),
        ("accG", c_float * 3),
        ("wheelSlip", c_float * 4),
        ("wheelLoad", c_float * 4),
        ("wheelsPressure", c_float * 4),
        ("wheelAngularSpeed", c_float * 4),
        ("tyreWear", c_float * 4),
        ("tyreDirtyLevel", c_float * 4),
        ("tyreCoreTemperature", c_float * 4),
        ("camberRAD", c_float * 4),
        ("suspensionTravel", c_float * 4),
        ("drs", c_float),
        ("tc", c_float),
        ("heading", c_float),
        ("pitch", c_float),
        ("roll", c_float),
        ("cgHeight", c_float),
        ("carDamage", c_float * 5),
        ("numberOfTyresOut", c_int32),
        ("pitLimiterOn", c_int32),
        ("abs", c_float),
        ("kersCharge", c_float),
        ("kersInput", c_float),
        ("autoShifterOn", c_int32),
        ("rideHeight", c_float * 2),
        ("turboBoost", c_float),
        ("ballast", c_float),
        ("airDensity", c_float),
        ("airTemp", c_float),
        ("roadTemp", c_float),
    ]


class _Graphics(ctypes.Structure):
    """SPageFileGraphic through windDirection (grip + wind live at the end)."""
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int32),
        ("status", c_int32),
        ("session", c_int32),
        ("currentTime", c_wchar * 15),
        ("lastTime", c_wchar * 15),
        ("bestTime", c_wchar * 15),
        ("split", c_wchar * 15),
        ("completedLaps", c_int32),
        ("position", c_int32),
        ("iCurrentTime", c_int32),
        ("iLastTime", c_int32),
        ("iBestTime", c_int32),
        ("sessionTimeLeft", c_float),
        ("distanceTraveled", c_float),
        ("isInPit", c_int32),
        ("currentSectorIndex", c_int32),
        ("lastSectorTime", c_int32),
        ("numberOfLaps", c_int32),
        ("tyreCompound", c_wchar * 33),
        ("replayTimeMultiplier", c_float),
        ("normalizedCarPosition", c_float),
        ("carCoordinates", c_float * 3),
        ("penaltyTime", c_float),
        ("flag", c_int32),
        ("idealLineOn", c_int32),
        ("isInPitLane", c_int32),
        ("surfaceGrip", c_float),
        ("mandatoryPitDone", c_int32),
        ("windSpeed", c_float),
        ("windDirection", c_float),
    ]


def _read_page(tag, struct_cls):
    try:
        m = mmap.mmap(0, ctypes.sizeof(struct_cls), tag)
        try:
            return struct_cls.from_buffer_copy(m.read(ctypes.sizeof(struct_cls)))
        finally:
            m.close()
    except Exception:
        return None


def read_conditions():
    """Snapshot {"air","road","grip","wind_kmh","wind_deg"} or None.

    None when AC's pages aren't mapped (not Windows, sim not running) or
    the values look like a dead page. Never raises.
    """
    ph = _read_page("acpmf_physics", _PhysicsHead)
    gr = _read_page("acpmf_graphics", _Graphics)
    if ph is None or gr is None:
        return None
    try:
        out = {
            "air": round(float(ph.airTemp), 1),
            "road": round(float(ph.roadTemp), 1),
            "grip": round(float(gr.surfaceGrip), 4),
            "wind_kmh": round(float(gr.windSpeed), 1),
            "wind_deg": int(round(float(gr.windDirection))) % 360,
        }
    except Exception:
        return None
    # an all-zero page means the sim isn't live (temps and grip are never
    # simultaneously zero in a real session)
    if not (out["air"] or out["road"] or out["grip"]):
        return None
    return out
