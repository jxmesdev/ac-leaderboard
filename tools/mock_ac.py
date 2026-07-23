"""A minimal fake `ac` / `acsys` for exercising the in-game glue off-car.

This is a DEV/TEST aid only -- it is never shipped into Assetto Corsa.
It records widget creation and lets tests drive telemetry + fire callbacks.
"""

import sys
import types


class _State(object):
    def __init__(self):
        self.next_id = 1
        self.widgets = {}          # id -> dict(kind, text, clicked_cb, validate_cb)
        self.track = ""
        self.track_config = ""
        self.car = ""
        self.driver_name = "TestDriver"
        self.best_lap = 0
        self.last_lap = 0
        self.lap_count = 0
        self.lap_invalidated = 0
        self.splits = []          # last lap's sector times (ms)
        self.logs = []
        # live telemetry channels
        self.gas = 0.0
        self.brake = 0.0
        self.gear = 0
        self.steer = 0.0          # radians
        self.speed_kmh = 0.0
        self.nsp = 0.0
        self.world = (0.0, 0.0, 0.0)


STATE = _State()


def _new(kind, text=""):
    wid = STATE.next_id
    STATE.next_id += 1
    STATE.widgets[wid] = {"kind": kind, "text": text,
                          "clicked_cb": None, "validate_cb": None}
    return wid


# -- widget creation -------------------------------------------------------
def newApp(name):
    return _new("app", name)


def addLabel(app, text):
    return _new("label", text)


def addButton(app, text):
    return _new("button", text)


def addTextInput(app, name):
    return _new("input", "")


# -- widget mutation -------------------------------------------------------
def setSize(*a):
    return 1


def setPosition(wid, x, y):
    if wid in STATE.widgets:
        STATE.widgets[wid]["pos"] = (x, y)
    return 1


def setFontSize(*a):
    return 1


def setTitle(*a):
    return 1


def setBackgroundOpacity(*a):
    return 1


def drawBorder(*a):
    return 1


def setText(wid, text):
    if wid in STATE.widgets:
        STATE.widgets[wid]["text"] = text
    return 1


def getText(wid):
    return STATE.widgets.get(wid, {}).get("text", "")


def addOnClickedListener(wid, cb):
    STATE.widgets[wid]["clicked_cb"] = cb
    return 1


def addOnValidateListener(wid, cb):
    STATE.widgets[wid]["validate_cb"] = cb
    return 1


# -- telemetry -------------------------------------------------------------
def getTrackName(car_id):
    return STATE.track


def getTrackConfiguration(car_id):
    return STATE.track_config


def getCarName(car_id):
    return STATE.car


def getDriverName(car_id):
    return STATE.driver_name


def getLastSplits(car_id):
    return list(STATE.splits)


def getCarState(car_id, which, *rest):
    if which == _CS.BestLap:
        return STATE.best_lap
    if which == _CS.LastLap:
        return STATE.last_lap
    if which == _CS.LapCount:
        return STATE.lap_count
    if which == _CS.LapInvalidated:
        return STATE.lap_invalidated
    if which == _CS.Gas:
        return STATE.gas
    if which == _CS.Brake:
        return STATE.brake
    if which == _CS.Gear:
        return STATE.gear
    if which == _CS.Steer:
        return STATE.steer
    if which == _CS.SpeedKMH:
        return STATE.speed_kmh
    if which == _CS.NormalizedSplinePosition:
        return STATE.nsp
    if which == _CS.WorldPosition:
        return STATE.world
    return 0


def log(msg):
    STATE.logs.append(str(msg))


def console(msg):
    STATE.logs.append(str(msg))


# -- acsys.CS enum ---------------------------------------------------------
class _CS(object):
    LapTime = "LapTime"
    LastLap = "LastLap"
    BestLap = "BestLap"
    LapCount = "LapCount"
    LapInvalidated = "LapInvalidated"
    NormalizedSplinePosition = "NSP"
    Gas = "Gas"
    Brake = "Brake"
    Gear = "Gear"
    Steer = "Steer"
    SpeedKMH = "SpeedKMH"
    WorldPosition = "WorldPosition"


# -- test-driver helpers ---------------------------------------------------
def click(wid):
    cb = STATE.widgets[wid]["clicked_cb"]
    if cb:
        cb(0, 0)


def validate(wid, text):
    cb = STATE.widgets[wid]["validate_cb"]
    if cb:
        cb(text)


def install():
    """Register fake `ac` and `acsys` modules; return the ac module."""
    ac_mod = sys.modules[__name__]
    acsys_mod = types.ModuleType("acsys")
    acsys_mod.CS = _CS
    sys.modules["ac"] = ac_mod
    sys.modules["acsys"] = acsys_mod
    return ac_mod
