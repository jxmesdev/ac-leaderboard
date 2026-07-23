# Best-effort capture of the car setup used for a lap. Python 3.3 compatible.
#
# AC's python API does not expose WHICH setup the player loaded, so we record
# the most recently SAVED setup file for this car (track folder or generic)
# at the moment the lap is stored, and label it as such. Setups live in
# Documents/Assetto Corsa/setups/<car>/<track_folder>/*.ini (layouts share
# the base track folder).

import io
import os

MAX_SETUP_BYTES = 64 * 1024     # setup inis are a few KB; refuse anything odd


def default_setups_dir():
    return os.path.join(os.path.expanduser("~"), "Documents",
                        "Assetto Corsa", "setups")


def find_latest_setup(setups_dir, car, track):
    """Newest .ini for this car under the track's folder or generic/.

    Returns {"name", "ini", "folder"} or None. `folder` is the subdirectory
    it came from ("<track>" or "generic") -- kept so the viewer can offer to
    save it back to the right place.
    """
    if not (setups_dir and car):
        return None
    car_dir = os.path.join(setups_dir, car)
    best = None          # (mtime, folder, name, path)
    for folder in (track, "generic"):
        if not folder:
            continue
        d = os.path.join(car_dir, folder)
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith(".ini"):
                continue
            p = os.path.join(d, n)
            try:
                mt = os.path.getmtime(p)
                if os.path.getsize(p) > MAX_SETUP_BYTES:
                    continue
            except OSError:
                continue
            if best is None or mt > best[0]:
                best = (mt, folder, n, p)
    if best is None:
        return None
    try:
        with io.open(best[3], "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except (IOError, OSError):
        return None
    if "VALUE" not in text:
        return None          # not an AC setup file
    return {"name": best[2], "ini": text, "folder": best[1]}
