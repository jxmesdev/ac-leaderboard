# Minimal Assetto Corsa text-input test #2 -- NOT part of the leaderboard app.
#
# Test #1 (text field alone) WORKED on this rig. This version adds the ONE thing
# the leaderboard does that the minimal test didn't: it reads live car telemetry
# via ac.getCarState EVERY FRAME (gas/brake/speed/gear/steer/position), exactly
# like the lap recorder. Everything else is identical to test #1.
#
# Install: copy this "textbox_test" folder into
#   ...\steamapps\common\assettocorsa\apps\python\textbox_test\
# (overwrite the old one), enable it, open it IN A SESSION (on track, so
# getCarState returns data), click the field, type a word, press Enter.
#   - If AC CRASHES  -> per-frame getCarState while the field has focus is the
#                       culprit; the fix is to gate that sampling.
#   - If it WORKS    -> telemetry sampling is innocent; I'll test the next suspect.
#
# Steps + the validate event are logged to Documents\Assetto Corsa\logs\py_log.txt.

import ac
import acsys

_app = None
_label = None
_input = None
_typed = ""
_frames = 0


def _log(msg):
    try:
        ac.log("[tbtest2] " + str(msg))
        ac.console("[tbtest2] " + str(msg))
    except Exception:
        pass


def _on_validate(value):
    global _typed
    _typed = value
    _log("validate fired -> " + repr(value))


def acMain(version):
    global _app, _label, _input
    _log("acMain start")
    _app = ac.newApp("Textbox Test 2")
    ac.setSize(_app, 340, 130)
    _label = ac.addLabel(_app, "On track: type a word, press Enter")
    ac.setPosition(_label, 10, 30)
    ac.setFontSize(_label, 13)
    _input = ac.addTextInput(_app, "")
    ac.setPosition(_input, 10, 60)
    ac.setSize(_input, 320, 26)
    ac.addOnValidateListener(_input, _on_validate)
    _log("built ok (input + validate + per-frame getCarState)")
    return "Textbox Test 2"


def acUpdate(deltaT):
    global _frames
    _frames += 1
    # Mimic the lap recorder: read several car-state channels every frame.
    try:
        ac.getCarState(0, acsys.CS.Gas)
        ac.getCarState(0, acsys.CS.Brake)
        ac.getCarState(0, acsys.CS.SpeedKMH)
        ac.getCarState(0, acsys.CS.Gear)
        ac.getCarState(0, acsys.CS.Steer)
        ac.getCarState(0, acsys.CS.NormalizedSplinePosition)
        ac.getCarState(0, acsys.CS.WorldPosition)
    except Exception:
        pass
    if _label is not None:
        try:
            if _typed:
                ac.setText(_label, "You typed: " + _typed + "  (frame " + str(_frames) + ")")
            else:
                ac.setText(_label, "On track: type a word, press Enter  (frame " + str(_frames) + ")")
        except Exception:
            pass


def acShutdown():
    pass
