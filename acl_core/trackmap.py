# Grab a track's minimap (map.png + data/map.ini) from the AC install so the web
# lap viewer can draw the real circuit outline under the racing lines.
# Python 3.3 compatible. Pure file I/O -- no `ac` import, so it is unit-testable.
#
# AC world position -> map.png pixel (per AC's own Track Map apps):
#     px = worldX * SCALE_FACTOR + X_OFFSET
#     py = worldZ * SCALE_FACTOR + Z_OFFSET
# The viewer stores {scale, xoff, zoff} and applies the same formula to the
# recorded x/z, so the line sits on the track regardless of overall orientation.

import io
import os
import shutil

from acl_core.telemetry import slug


def find_ac_root(app_dir):
    """Given the installed app dir (.../assettocorsa/apps/python/ac_leaderboard),
    return the assettocorsa root if it looks right, else None."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(app_dir)))
    if os.path.isdir(os.path.join(root, "content", "tracks")):
        return root
    return None


def _candidates(ac_root, track, config):
    """(map.png, map.ini) paths to try: layout sub-folder first, then track root."""
    base = os.path.join(ac_root, "content", "tracks", track)
    out = []
    if config:
        out.append((os.path.join(base, config, "map.png"),
                    os.path.join(base, config, "data", "map.ini")))
    out.append((os.path.join(base, "map.png"),
                os.path.join(base, "data", "map.ini")))
    return out


def parse_map_ini(path):
    """Return {scale, xoff, zoff, width, height} from a map.ini, or None."""
    if not os.path.isfile(path):
        return None
    vals = {}
    try:
        with io.open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(";") or line.startswith("["):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    vals[k.strip().upper()] = v.strip()
    except (IOError, OSError):
        return None

    def num(key):
        try:
            return float(vals.get(key))
        except (TypeError, ValueError):
            return None

    scale, xoff, zoff = num("SCALE_FACTOR"), num("X_OFFSET"), num("Z_OFFSET")
    if scale is None or xoff is None or zoff is None:
        return None
    return {"scale": scale, "xoff": xoff, "zoff": zoff,
            "width": num("WIDTH"), "height": num("HEIGHT")}


def grab(ac_root, track, config, data_dir):
    """Copy the track's map.png into data_dir/trackmaps/ and return
    (trackmap_dict, copied_png_path) or None if it can't be found/parsed.

    trackmap_dict = {"url", "scale", "xoff", "zoff"} (plus w/h if known).
    """
    if not ac_root:
        return None
    for png, ini in _candidates(ac_root, track, config):
        if not (os.path.isfile(png) and os.path.isfile(ini)):
            continue
        params = parse_map_ini(ini)
        if not params:
            continue
        name = slug(track) + "__" + slug(config) + ".png"
        dst_dir = os.path.join(data_dir, "trackmaps")
        if not os.path.isdir(dst_dir):
            os.makedirs(dst_dir)
        dst = os.path.join(dst_dir, name)
        try:
            shutil.copyfile(png, dst)
        except (IOError, OSError):
            return None
        tm = {"url": "trackmaps/" + name,
              "scale": params["scale"],
              "xoff": params["xoff"],
              "zoff": params["zoff"]}
        if params.get("width"):
            tm["w"] = params["width"]
        if params.get("height"):
            tm["h"] = params["height"]
        return tm, dst
    return None
