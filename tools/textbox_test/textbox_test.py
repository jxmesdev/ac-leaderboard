# Assetto Corsa text-input RELIABILITY test -- NOT part of the leaderboard app.
#
# Question: does AC's text field crash INTERMITTENTLY on this rig, or only in the
# full leaderboard app? This is a bare window + text field (no imports beyond ac,
# no objects, no getCarState) -- identical to the very first test that "worked".
#
# HOW TO USE: install (copy this folder to ...\apps\python\textbox_test\), enable
# it, open it in a session. Click the field, type any letter, press ENTER.
# REPEAT ~15-20 times. Restart AC and do another ~15. The label shows a running
# count. Tell me: did it EVER crash, and roughly after how many Enters?
#
#   - Crashes at least once  -> AC's text field is unreliable on your CSP build,
#                               regardless of our app. We stop using it.
#   - Survives 30+ Enters    -> the field is fine; the leaderboard app's imports/
#                               objects are the cause, and I strip those.
#
# Each Enter is logged (with its number) to py_log.txt via ac.log.

import ac

_app = None
_label = None
_input = None
_count = 0


def _on_validate(value):
    global _count
    _count += 1
    try:
        ac.log("[reliability] enter #" + str(_count) + " -> " + repr(value))
        ac.console("[reliability] enter #" + str(_count))
    except Exception:
        pass
    if _label is not None:
        try:
            ac.setText(_label, "Enters survived: " + str(_count) + "  (keep going)")
        except Exception:
            pass


def acMain(version):
    global _app, _label, _input
    _app = ac.newApp("Reliability Test")
    ac.setSize(_app, 340, 120)
    _label = ac.addLabel(_app, "Type a letter + Enter, repeat ~15x")
    ac.setPosition(_label, 10, 30)
    ac.setFontSize(_label, 14)
    _input = ac.addTextInput(_app, "")
    ac.setPosition(_input, 10, 58)
    ac.setSize(_input, 320, 26)
    ac.addOnValidateListener(_input, _on_validate)
    return "Reliability Test"


def acUpdate(deltaT):
    pass


def acShutdown():
    pass
