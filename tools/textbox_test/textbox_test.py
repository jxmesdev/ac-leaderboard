# Minimal Assetto Corsa text-input test -- NOT part of the leaderboard app.
#
# Purpose: find out whether AC/CSP's text field crashes on its own on this rig,
# or only because the leaderboard app does other work around it. This app does
# NOTHING except show a text field and echo what you type. No telemetry, no git,
# no getText, no threads -- just addTextInput + a validate listener.
#
# Install: copy this "textbox_test" folder into
#   ...\steamapps\common\assettocorsa\apps\python\textbox_test\
# Enable "textbox_test" in Content Manager, open it in a session, click the
# field, type a word, and press Enter.
#   - If AC CRASHES  -> the text widget itself can't run on your CSP build.
#   - If it WORKS    -> the leaderboard app was interfering; that's fixable.
#
# Every step logs to Documents\Assetto Corsa\logs\py_log.txt so we can see how
# far it got (in particular whether the validate callback fired before any crash).

import ac

_app = None
_label = None
_input = None
_typed = ""


def _log(msg):
    try:
        ac.log("[tbtest] " + str(msg))
        ac.console("[tbtest] " + str(msg))
    except Exception:
        pass


def _on_validate(value):
    # This runs when you press Enter. It ONLY stores/logs the text.
    global _typed
    _typed = value
    _log("validate fired -> " + repr(value))


def acMain(version):
    global _app, _label, _input
    _log("acMain start")
    _app = ac.newApp("Textbox Test")
    ac.setSize(_app, 320, 130)
    _label = ac.addLabel(_app, "Click below, type a word, press Enter")
    ac.setPosition(_label, 10, 30)
    ac.setFontSize(_label, 14)
    _input = ac.addTextInput(_app, "")
    ac.setPosition(_input, 10, 60)
    ac.setSize(_input, 300, 26)
    ac.addOnValidateListener(_input, _on_validate)
    _log("built ok (input + validate listener)")
    return "Textbox Test"


def acUpdate(deltaT):
    # Deliberately does almost nothing (no getCarState, no shared memory).
    if _label is not None and _typed:
        try:
            ac.setText(_label, "You typed: " + _typed)
        except Exception:
            pass


def acShutdown():
    pass
