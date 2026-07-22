# Minimal Assetto Corsa text-input test #4 -- NOT part of the leaderboard app.
#
# Tests #1-3 all WORKED (bare field; +per-frame getCarState; +git subprocess
# thread). The one thing none of them had, but the leaderboard does: BUTTONS
# (with click listeners) and colored labels in the SAME window as the text
# field -- the driver grid + leaderboard. Your live app has buttons but no
# field (works); the tests had a field but no buttons (work). This tests the
# combination.
#
# Install: copy this "textbox_test" folder over the old one in
#   ...\steamapps\common\assettocorsa\apps\python\textbox_test\
# Enable it, open it in a session, click the field, type a word, press Enter.
#   - If AC CRASHES  -> a text field + buttons/colored labels together is the
#                       trigger; I'll split buttons vs setFontColor next, then fix.
#   - If it WORKS    -> I'll replicate the full app build to find the combo.
#
# Steps + the validate event are logged to py_log.txt.

import ac

_app = None
_label = None
_input = None
_typed = ""
_btns = []
_rows = []


def _log(msg):
    try:
        ac.log("[tbtest4] " + str(msg))
        ac.console("[tbtest4] " + str(msg))
    except Exception:
        pass


def _on_validate(value):
    global _typed
    _typed = value
    _log("validate fired -> " + repr(value))


def _make_cb(i):
    def cb(x, y):
        _log("button " + str(i) + " clicked")
    return cb


def acMain(version):
    global _app, _label, _input
    _log("acMain start")
    _app = ac.newApp("Textbox Test 4")
    ac.setSize(_app, 360, 320)

    _label = ac.addLabel(_app, "type a word, press Enter")
    ac.setPosition(_label, 10, 28)
    ac.setFontSize(_label, 13)

    _input = ac.addTextInput(_app, "")
    ac.setPosition(_input, 10, 50)
    ac.setSize(_input, 340, 26)
    ac.addOnValidateListener(_input, _on_validate)

    # 10 buttons with click listeners + font colours (like the driver grid).
    for i in range(10):
        b = ac.addButton(_app, "Driver " + str(i + 1))
        ac.setPosition(b, 10 + (i % 2) * 175, 85 + (i // 2) * 26)
        ac.setSize(b, 165, 22)
        ac.addOnClickedListener(b, _make_cb(i))
        try:
            ac.setFontSize(b, 13)
            ac.setFontColor(b, 0.96, 0.65, 0.14, 1.0)
        except Exception:
            pass
        _btns.append(b)

    # a few coloured labels (like the leaderboard rows)
    for r in range(4):
        lab = ac.addLabel(_app, "row " + str(r))
        ac.setPosition(lab, 10, 220 + r * 22)
        try:
            ac.setFontSize(lab, 13)
            ac.setFontColor(lab, 1.0, 1.0, 1.0, 1.0)
        except Exception:
            pass
        _rows.append(lab)

    _log("built ok (input + 10 buttons + coloured labels)")
    return "Textbox Test 4"


def acUpdate(deltaT):
    if _label is not None and _typed:
        try:
            ac.setText(_label, "You typed: " + _typed)
        except Exception:
            pass


def acShutdown():
    pass
