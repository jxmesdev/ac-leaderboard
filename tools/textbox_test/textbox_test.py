# Minimal Assetto Corsa text-input test #3 -- NOT part of the leaderboard app.
#
# Tests #1 (bare field) and #2 (field + per-frame getCarState) both WORKED.
# This version adds the next difference: a BACKGROUND THREAD that repeatedly
# launches `git` via subprocess.Popen -- exactly how the leaderboard's git push
# works. Everything else is the same bare text field.
#
# Install: copy this "textbox_test" folder over the old one in
#   ...\steamapps\common\assettocorsa\apps\python\textbox_test\
# Enable it, open it in a session, click the field, type a word, press Enter.
#   - If AC CRASHES  -> launching git via subprocess on a thread is the culprit;
#                       fix = change how/when the push runs.
#   - If it WORKS    -> I'll test the last suspect (many widgets + setFontColor).
#
# The worker runs `git --version` back-to-back so a subprocess is almost always
# in flight when you press Enter. Steps are logged to py_log.txt.

import os
import subprocess
import threading

import ac

_app = None
_label = None
_input = None
_typed = ""
_runs = 0
_stop = False

_IS_WINDOWS = (os.name == "nt")
_CREATE_NO_WINDOW = 0x08000000


def _log(msg):
    try:
        ac.log("[tbtest3] " + str(msg))
        ac.console("[tbtest3] " + str(msg))
    except Exception:
        pass


def _on_validate(value):
    global _typed
    _typed = value
    _log("validate fired -> " + repr(value))


def _worker():
    global _runs
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
              "stdin": subprocess.PIPE, "universal_newlines": True}
    if _IS_WINDOWS:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    while not _stop:
        try:
            p = subprocess.Popen(["git", "--version"], **kwargs)
            p.communicate()
            _runs += 1
        except Exception as exc:
            _log("subprocess error: " + str(exc))
        # tiny pause so we're not pegging a core, but still nearly continuous
        for _ in range(3):
            if _stop:
                break


def acMain(version):
    global _app, _label, _input
    _log("acMain start")
    _app = ac.newApp("Textbox Test 3")
    ac.setSize(_app, 340, 130)
    _label = ac.addLabel(_app, "type a word, press Enter (git thread running)")
    ac.setPosition(_label, 10, 30)
    ac.setFontSize(_label, 13)
    _input = ac.addTextInput(_app, "")
    ac.setPosition(_input, 10, 60)
    ac.setSize(_input, 320, 26)
    ac.addOnValidateListener(_input, _on_validate)
    t = threading.Thread(target=_worker, name="tbtest3-git")
    t.daemon = True
    t.start()
    _log("built ok (input + background git subprocess thread)")
    return "Textbox Test 3"


def acUpdate(deltaT):
    if _label is not None:
        try:
            base = ("You typed: " + _typed) if _typed else "type a word, press Enter"
            ac.setText(_label, base + "  (git runs: " + str(_runs) + ")")
        except Exception:
            pass


def acShutdown():
    global _stop
    _stop = True
