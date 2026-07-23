# Auto-install the CSP Lua companion app (lua/acl_setup in this repo) into
# the AC install's apps/lua/ folder. Python 3.3 compatible; pure file I/O.
#
# The companion writes the currently running setup (a CSP-Lua-only API) to a
# file the python app reads at lap time. Copying happens at session start:
# missing or outdated files are refreshed, matching files are left alone, so
# a `git pull` on the rig also updates the Lua side automatically.

import io
import os

APP_ID = "acl_setup"


def _read(path):
    try:
        with io.open(path, "rb") as f:
            return f.read()
    except (IOError, OSError):
        return None


def install(ac_root, repo_dir):
    """Copy lua/acl_setup/* into <ac_root>/apps/lua/acl_setup/.

    Returns "installed", "updated", "current", or None (no root / no source /
    copy failed). Never raises.
    """
    try:
        src_dir = os.path.join(repo_dir, "lua", APP_ID)
        if not (ac_root and os.path.isdir(src_dir)):
            return None
        dst_dir = os.path.join(ac_root, "apps", "lua", APP_ID)
        existed = os.path.isdir(dst_dir)
        if not existed:
            os.makedirs(dst_dir)
        changed = False
        for name in sorted(os.listdir(src_dir)):
            sp = os.path.join(src_dir, name)
            if not os.path.isfile(sp):
                continue
            data = _read(sp)
            if data is None:
                continue
            dp = os.path.join(dst_dir, name)
            if _read(dp) == data:
                continue
            with io.open(dp, "wb") as f:
                f.write(data)
            changed = True
        if not changed:
            return "current"
        return "updated" if existed else "installed"
    except Exception:
        return None
