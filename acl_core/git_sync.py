# Background git commit + push. Python 3.3 compatible.
#
# Runs git as a subprocess on a worker thread so the game is never blocked.
# Requests are coalesced: if a push is already running, at most one more run is
# queued, and it picks up whatever is on disk at the time.

import os
import subprocess
import threading


# On Windows, prevent a console window from flashing for each git call.
_CREATE_NO_WINDOW = 0x08000000
_IS_WINDOWS = (os.name == "nt")


def _popen_kwargs():
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.PIPE,
        "universal_newlines": True,
    }
    if _IS_WINDOWS:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


class GitSync(object):
    def __init__(self, repo_path, branch="main", remote="origin",
                 author_name="AC Leaderboard", author_email="ac-leaderboard@local",
                 git_exe="git", on_status=None, logger=None):
        self.repo_path = repo_path
        self.branch = branch
        self.remote = remote
        self.author_name = author_name
        self.author_email = author_email
        self.git_exe = git_exe
        self.on_status = on_status
        self.logger = logger

        self.last_status = "idle"
        self._lock = threading.Lock()
        self._worker = None
        self._pending = None  # (paths, message) or None

    # -- public API -------------------------------------------------------
    def available(self):
        """True if repo_path looks like a git working tree."""
        if not self.repo_path or not os.path.isdir(self.repo_path):
            return False
        return os.path.isdir(os.path.join(self.repo_path, ".git")) or \
            self._run(["rev-parse", "--is-inside-work-tree"])[0] == 0

    def request_push(self, paths, message):
        """Queue a commit+push of `paths`. Non-blocking; returns immediately."""
        with self._lock:
            self._pending = (list(paths), message)
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._drain,
                                            name="acl-gitsync")
            self._worker.daemon = True
            self._worker.start()

    # -- worker -----------------------------------------------------------
    def _drain(self):
        while True:
            with self._lock:
                job = self._pending
                self._pending = None
                if job is None:
                    return
            paths, message = job
            self._set_status("syncing")
            ok, detail = self._commit_and_push(paths, message)
            self._set_status("synced" if ok else ("error: " + detail))

    def _dbg(self, msg):
        if self.logger:
            try:
                self.logger("gitsync: " + msg)
            except Exception:
                pass

    def _commit_and_push(self, paths, message):
        if not self.available():
            return False, "repo not found: " + str(self.repo_path)

        self._dbg("add start")
        add_args = ["add", "--"] + [self._rel(p) for p in paths]
        rc, out, err = self._run(add_args)
        self._dbg("add rc=" + str(rc))
        if rc != 0:
            return False, ("git add failed: " + (err or out)).strip()

        # Nothing staged? Still try to push in case earlier commits are unpushed.
        staged_rc = self._run(["diff", "--cached", "--quiet"])[0]
        if staged_rc != 0:
            commit_args = [
                "-c", "user.name=" + self.author_name,
                "-c", "user.email=" + self.author_email,
                "commit", "-m", message,
            ]
            self._dbg("commit start")
            rc, out, err = self._run(commit_args)
            self._dbg("commit rc=" + str(rc))
            if rc != 0:
                return False, ("git commit failed: " + (err or out)).strip()

        self._dbg("push start")
        rc, out, err = self._run(["push", self.remote, "HEAD:" + self.branch])
        self._dbg("push rc=" + str(rc))
        if rc != 0:
            return False, ("git push failed: " + (err or out)).strip()
        return True, "ok"

    # -- helpers ----------------------------------------------------------
    def _rel(self, path):
        """Prefer a repo-relative path so `git add` behaves predictably."""
        try:
            return os.path.relpath(path, self.repo_path)
        except ValueError:
            return path

    def _run(self, args):
        cmd = [self.git_exe, "-C", self.repo_path] + args
        try:
            p = subprocess.Popen(cmd, **_popen_kwargs())
            out, err = p.communicate()
            return p.returncode, out or "", err or ""
        except (OSError, ValueError) as exc:
            return 1, "", str(exc)

    def _set_status(self, status):
        self.last_status = status
        if self.logger:
            try:
                self.logger("git: " + status)
            except Exception:
                pass
        if self.on_status:
            try:
                self.on_status(status)
            except Exception:
                pass
