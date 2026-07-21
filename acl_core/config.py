# App configuration. Python 3.3 compatible.
#
# On the Windows gaming PC the AC app folder lives inside
#   assettocorsa/apps/python/ac_leaderboard/
# but the leaderboard DATA is written into a local clone of your GitHub Pages
# repo. config.json tells the app where that clone is.

import io
import json
import os

DEFAULTS = {
    # Absolute path to the local clone of the git repo that GitHub Pages serves.
    # Leave "" to auto-detect: the app folder itself IS the clone (you cloned
    # this repo straight into assettocorsa/apps/python/ as `ac_leaderboard`).
    "repo_path": "",
    # Sub-directory inside the repo where records.json/users.json are written.
    "data_subdir": "docs/data",
    "git_remote": "origin",
    "git_branch": "main",
    "git_exe": "git",
    "author_name": "AC Leaderboard",
    "author_email": "ac-leaderboard@local",
    # Push automatically whenever a record is saved.
    "auto_push": True,
    # Automatically capture your best lap from AC's shared memory.
    "auto_capture": True,
    # Number of leaderboard rows to render in-game.
    "leaderboard_rows": 10,
}


class Config(object):
    def __init__(self, values, path, app_dir):
        self.values = values
        self.path = path
        self.app_dir = app_dir

    def get(self, key, fallback=None):
        return self.values.get(key, DEFAULTS.get(key, fallback))

    @property
    def repo_path(self):
        # Auto-detect: the installed app folder is itself the git clone.
        return self.get("repo_path") or self.app_dir

    @property
    def data_dir(self):
        """Absolute path to the directory holding records.json/users.json."""
        sub = self.get("data_subdir") or ""
        return os.path.normpath(os.path.join(self.repo_path, sub))

    def repo_configured(self):
        """True if repo_path is a git working tree we can push from."""
        repo = self.repo_path
        return bool(repo) and os.path.isdir(os.path.join(repo, ".git"))


def load(app_dir):
    """Load config.json, creating it from defaults if missing.

    Honours the ACL_CONFIG environment variable (path to a config.json) so the
    app can be pointed at an alternate config for testing without touching the
    installed app folder.
    """
    path = os.environ.get("ACL_CONFIG") or os.path.join(app_dir, "config.json")
    values = dict(DEFAULTS)
    if os.path.isfile(path):
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                values.update(loaded)
        except (ValueError, IOError, OSError):
            pass
    else:
        # Write a starter config so the user has something to edit.
        try:
            with io.open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(DEFAULTS, ensure_ascii=False, indent=2,
                                   sort_keys=True))
                f.write("\n")
        except (IOError, OSError):
            pass
    return Config(values, path, app_dir)
