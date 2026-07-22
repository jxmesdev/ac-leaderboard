# Assetto Corsa text-input test #6 -- NOT part of the leaderboard app.
#
# Tests #1-5 all worked, but they had ~15 widgets. The real leaderboard builds
# ~60 (10 driver buttons + 4 headers + 40 row labels + more) and repaints the
# rows every tick. In the real app the text field stopped responding (Enter did
# nothing) and a button click crashed. This test reproduces that widget load.
#
# Install: copy this folder over the old one in ...\apps\python\textbox_test\
# Enable it, open it in a session, click the field, type "abc", press ENTER,
# then click the [NO-OP] button. Tell me: does Enter register? does it crash?
# Push py_log.txt (and the crash report if it crashes).

import ac
import acsys

_app = None
_status = None
_input = None
_rows = []
_frames = 0


def _log(msg):
    try:
        ac.log("[tb6] " + str(msg))
        ac.console("[tb6] " + str(msg))
    except Exception:
        pass


def _on_validate(value):
    _log("validate fired -> " + repr(value))
    if _status is not None:
        try:
            ac.setText(_status, "validate fired: " + str(value))
        except Exception:
            pass


def _on_noop(x, y):
    _log("no-op clicked")
    if _status is not None:
        try:
            ac.setText(_status, "no-op clicked")
        except Exception:
            pass


def acMain(version):
    global _app, _status, _input
    _log("acMain start")
    _app = ac.newApp("Textbox Test 6")
    ac.setSize(_app, 380, 640)

    # 10 buttons (driver grid) with colours + click listeners
    for i in range(10):
        b = ac.addButton(_app, "Driver " + str(i + 1))
        ac.setPosition(b, 10 + (i % 2) * 185, 30 + (i // 2) * 26)
        ac.setSize(b, 175, 22)
        ac.addOnClickedListener(b, (lambda a, c, n=i: _log("grid " + str(n))))
        try:
            ac.setFontColor(b, 0.96, 0.65, 0.14, 1.0)
        except Exception:
            pass

    _input = ac.addTextInput(_app, "")
    ac.setPosition(_input, 10, 175)
    ac.setSize(_input, 360, 26)
    ac.addOnValidateListener(_input, _on_validate)

    bn = ac.addButton(_app, "NO-OP")
    ac.setPosition(bn, 10, 208)
    ac.setSize(bn, 175, 24)
    ac.addOnClickedListener(bn, _on_noop)

    _status = ac.addLabel(_app, "type abc + Enter, then click NO-OP")
    ac.setPosition(_status, 10, 240)
    ac.setFontSize(_status, 13)

    # ~44 leaderboard-style labels (4 header + 40 rows), like the real board
    y = 270
    for r in range(44):
        lab = ac.addLabel(_app, "row " + str(r))
        ac.setPosition(lab, 10 + (r % 4) * 90, y + (r // 4) * 22)
        try:
            ac.setFontSize(lab, 12)
        except Exception:
            pass
        _rows.append(lab)

    _log("built ok (~58 widgets: 10 buttons + field + 44 labels + status)")
    return "Textbox Test 6"


def acUpdate(deltaT):
    global _frames
    _frames += 1
    try:
        ac.getCarState(0, acsys.CS.Gas)
        ac.getCarState(0, acsys.CS.SpeedKMH)
        ac.getCarState(0, acsys.CS.NormalizedSplinePosition)
        ac.getCarState(0, acsys.CS.WorldPosition)
    except Exception:
        pass
    # repaint the "leaderboard" rows every ~0.5s like _refresh_board (setText +
    # setFontColor on many labels)
    if _frames % 30 == 0:
        for i, lab in enumerate(_rows):
            try:
                ac.setText(lab, "r" + str(i) + ":" + str(_frames))
                ac.setFontColor(lab, 1.0, 1.0, 1.0, 1.0)
            except Exception:
                pass


def acShutdown():
    pass
