# Session conditions from AC's shared memory. Python 3.3 compatible.
#
# The in-game python API exposes no weather, so air/road temperature, track
# grip and wind come straight from the simulator's shared-memory pages
# (the same mechanism every AC telemetry tool uses). Struct layouts are
# copied verbatim from the community-standard sim_info.py for AC 1.16+;
# only the fields up to the ones we read are declared (a shorter mapping
# of the same page is safe). Windows-only by nature -- on any other OS or
# with AC not running, read_conditions() just returns None. Never raises.
#
# AC's embedded interpreter ships a STRIPPED stdlib: ctypes or mmap may be
# missing entirely, and this module must never take the app down with it
# (proven on-rig: a bare `import ctypes` here killed the app at load).
# IMPORT_ERROR carries the reason for the debug log.

IMPORT_ERROR = None
try:
    import ctypes
    import mmap
    from ctypes import c_float, c_int32, c_wchar
except Exception as _exc:
    IMPORT_ERROR = str(_exc)
    ctypes = None
    mmap = None

_PhysicsHead = None
_Graphics = None

if ctypes is not None:

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
        """SPageFileGraphic through windDirection (grip + wind at the end)."""
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


_SESSIONS = {0: "practice", 1: "qualify", 2: "race", 3: "hotlap",
             4: "time attack", 5: "drift", 6: "drag"}


def read_conditions():
    """Snapshot of session conditions at lap time, or None.

    {"air","road","grip","wind_kmh","wind_deg","tyres","fuel","session"}.
    None when ctypes/mmap are unavailable (stripped interpreter), AC's
    pages aren't mapped (not Windows, sim not running), or the values
    look like a dead page. Never raises.
    """
    if ctypes is None:
        return None
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
            "tyres": str(gr.tyreCompound).strip(),
            "fuel": round(float(ph.fuel), 1),
            "session": _SESSIONS.get(int(gr.session), "unknown"),
        }
    except Exception:
        return None
    # an all-zero page means the sim isn't live (temps and grip are never
    # simultaneously zero in a real session)
    if not (out["air"] or out["road"] or out["grip"]):
        return None
    return out
