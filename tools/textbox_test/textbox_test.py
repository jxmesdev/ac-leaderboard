# Assetto Corsa text-input test #5 -- NOT part of the leaderboard app.
#
# In the full app: (1) typing a name + Enter did NOT fire the validate callback,
# and (2) clicking the "+ Add me" button (which calls ac.getDriverName) CRASHED.
# This test isolates both, in a realistic layout (buttons created BEFORE the
# field, like the driver grid), with per-frame getCarState like the recorder.
#
# Install: copy this folder over the old one in
#   ...\apps\python\textbox_test\   then enable it and open it IN A SESSION.
#
# Do these THREE things, and tell me which (if any) crash + push py_log.txt:
#   A) Click the field, type "abc", press ENTER.   (does validate fire?)
#   B) Click the field, type "xyz", then click the [NO-OP] button.  (focus+click)
#   C) Click the field, type "def", then click the [READ NAME] button. (getDriverName)
#
# Each action logs to Documents\Assetto Corsa\logs\py_log.txt.

import ac
import acsys

_app = None
_status = None
_input = None
_last = ""


def _log(msg):
    try:
        ac.log("[tb5] " + str(msg))
        ac.console("[tb5] " + str(msg))
    except Exception:
        pass


def _set_status(text):
    global _last
    _last = text
    if _status is not None:
        try:
            ac.setText(_status, text)
        except Exception:
            pass


def _on_validate(value):
    _log("A: validate fired -> " + repr(value))
    _set_status("validate fired: " + str(value))


def _on_noop(x, y):
    _log("B: no-op button clicked (field may have had focus)")
    _set_status("no-op clicked")


def _on_read(x, y):
    _log("C: read button clicked -- calling getDriverName")
    try:
        name = ac.getDriverName(0)
        _log("C: getDriverName returned -> " + repr(name))
        _set_status("driver name: " + str(name))
    except Exception as exc:
        _log("C: getDriverName raised: " + str(exc))


def acMain(version):
    global _app, _status, _input
    _log("acMain start")
    _app = ac.newApp("Textbox Test 5")
    ac.setSize(_app, 360, 300)

    # 10 buttons FIRST, like the driver grid (created before the text field).
    for i in range(10):
        b = ac.addButton(_app, "Driver " + str(i + 1))
        ac.setPosition(b, 10 + (i % 2) * 175, 30 + (i // 2) * 26)
        ac.setSize(b, 165, 22)
        ac.addOnClickedListener(b, (lambda a, c, n=i: _log("grid button " + str(n))))
        try:
            ac.setFontColor(b, 0.96, 0.65, 0.14, 1.0)
        except Exception:
            pass

    _lab = ac.addLabel(_app, "A: type + Enter | B: NO-OP | C: READ NAME")
    ac.setPosition(_lab, 10, 168)
    ac.setFontSize(_lab, 12)

    _input = ac.addTextInput(_app, "")
    ac.setPosition(_input, 10, 190)
    ac.setSize(_input, 340, 26)
    ac.addOnValidateListener(_input, _on_validate)

    bn = ac.addButton(_app, "NO-OP")
    ac.setPosition(bn, 10, 224)
    ac.setSize(bn, 165, 24)
    ac.addOnClickedListener(bn, _on_noop)

    br = ac.addButton(_app, "READ NAME")
    ac.setPosition(br, 185, 224)
    ac.setSize(br, 165, 24)
    ac.addOnClickedListener(br, _on_read)

    _status = ac.addLabel(_app, "(status)")
    ac.setPosition(_status, 10, 258)
    ac.setFontSize(_status, 13)

    _log("built ok (10 grid buttons + field + NO-OP + READ NAME)")
    return "Textbox Test 5"


def acUpdate(deltaT):
    # per-frame getCarState like the recorder
    try:
        ac.getCarState(0, acsys.CS.Gas)
        ac.getCarState(0, acsys.CS.SpeedKMH)
        ac.getCarState(0, acsys.CS.NormalizedSplinePosition)
        ac.getCarState(0, acsys.CS.WorldPosition)
    except Exception:
        pass


def acShutdown():
    pass
