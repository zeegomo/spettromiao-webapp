"""Self-update from GitHub: pull the webapp and kat checkouts, then restart.

The webapp is served from its own git checkout, so updating means fast-forwarding
that checkout (and the kat checkout the backend imports) to their upstream
branches, reinstalling Python dependencies if they changed, and restarting the
backend so the new code is loaded. Under gunicorn the worker just exits and the
gunicorn master starts a fresh one, which imports the updated code from disk.
"""

import importlib.util
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
GIT_TIMEOUT_S = 60
DEPS_TIMEOUT_S = 30 * 60

# Identifies this server process, so the browser can tell when a restart finished
STARTED_AT = time.time()

# Never wait for a username/password: fail fast instead (the private kat repo
# needs stored credentials or an SSH key to be updated)
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


# English fallbacks for blocker codes (the frontend shows translated ones)
BLOCKER_TEXT = {
    "check_failed": "could not check GitHub",
    "local_changes": "local changes to",
    "local_commits": "local commits not on GitHub",
}


class UpdateError(Exception):
    """An update step failed."""


def _git(repo: Path, *args: str, timeout: float = GIT_TIMEOUT_S) -> str:
    """Run a git command in `repo` and return its stdout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, env=GIT_ENV,
        )
    except subprocess.TimeoutExpired:
        raise UpdateError(f"git {args[0]} timed out in {repo}")
    except OSError as e:
        raise UpdateError(f"cannot run git: {e}")
    if result.returncode != 0:
        raise UpdateError(result.stderr.strip() or f"git {args[0]} failed in {repo}")
    return result.stdout.strip()


def find_kat_dir() -> Optional[Path]:
    """Locate the git checkout the kat package is imported from."""
    candidates = []
    spec = importlib.util.find_spec("kat")
    if spec and spec.submodule_search_locations:
        candidates.append(Path(list(spec.submodule_search_locations)[0]).parent)
    candidates.append(Path(os.environ.get("KAT_DIR", "~/kat")).expanduser())

    for path in candidates:
        try:
            return Path(_git(path, "rev-parse", "--show-toplevel"))
        except UpdateError:
            continue
    return None


def repo_status(path: Path, fetch: bool = True) -> dict:
    """Fetch a checkout and describe how it relates to its upstream branch."""
    status = {"path": str(path), "error": None, "behind": 0, "ahead": 0, "dirty": [], "head": None}
    try:
        if fetch:
            _git(path, "fetch", "--quiet")
        status["head"] = _git(path, "rev-parse", "HEAD")
        _git(path, "rev-parse", "--abbrev-ref", "@{upstream}")
        status["behind"] = int(_git(path, "rev-list", "--count", "HEAD..@{upstream}"))
        status["ahead"] = int(_git(path, "rev-list", "--count", "@{upstream}..HEAD"))
        # Staged or unstaged changes to tracked files (untracked ones, e.g. .venv, don't matter)
        status["dirty"] = _git(path, "diff", "--name-only", "HEAD").splitlines()
    except UpdateError as e:
        status["error"] = str(e)
    return status


def _problems(status: dict) -> list:
    """Reasons a checkout can't be fast-forwarded, as {code, detail} dicts."""
    if status["error"]:
        return [{"code": "check_failed", "detail": status["error"]}]
    problems = []
    if status["dirty"]:
        problems.append({"code": "local_changes", "detail": ", ".join(status["dirty"])})
    if status["ahead"]:
        problems.append({"code": "local_commits", "detail": str(status["ahead"])})
    return problems


def check(fetch: bool = True) -> dict:
    """
    Check GitHub for updates to the webapp and kat.

    Problems with the webapp checkout block the update; problems with kat only
    mean kat is skipped (reported as warnings).
    """
    webapp = repo_status(APP_DIR, fetch)
    current_version = (APP_DIR / "version.txt").read_text().strip()
    latest_version = None
    if not webapp["error"]:
        try:
            latest_version = _git(APP_DIR, "show", "@{upstream}:version.txt")
        except UpdateError:
            pass

    kat_dir = find_kat_dir()
    kat = repo_status(kat_dir, fetch) if kat_dir else None
    if kat is None:
        warnings = [{"code": "kat_not_found", "detail": ""}]
    else:
        warnings = [{**p, "code": "kat_" + p["code"]} for p in _problems(kat)]
    kat_updatable = kat is not None and not warnings

    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "webapp": webapp,
        "kat": kat,
        "kat_updatable": kat_updatable,
        "update_available": webapp["behind"] > 0 or (kat_updatable and kat["behind"] > 0),
        "blockers": _problems(webapp),
        "warnings": warnings,
    }


def _under_gunicorn() -> bool:
    return "gunicorn" in sys.modules


class Updater:
    """Runs one update at a time in a background thread and reports progress."""

    def __init__(self, capture_lock: threading.Lock, camera) -> None:
        self._capture_lock = capture_lock
        self._camera = camera
        self._lock = threading.Lock()
        self._state = {"state": "idle", "step": None, "error": None, "notices": []}

    def status(self) -> dict:
        with self._lock:
            return {**self._state, "notices": list(self._state["notices"]), "started_at": STARTED_AT}

    def is_running(self) -> bool:
        with self._lock:
            return self._state["state"] in ("running", "restarting")

    def start(self) -> bool:
        """Start an update unless one is already running."""
        with self._lock:
            if self._state["state"] in ("running", "restarting"):
                return False
            self._state = {"state": "running", "step": "waiting", "error": None, "notices": []}
        threading.Thread(target=self._run, name="updater", daemon=True).start()
        return True

    def _set(self, **changes) -> None:
        with self._lock:
            self._state.update(changes)

    def _notice(self, code: str, detail: str = "") -> None:
        with self._lock:
            self._state["notices"].append({"code": code, "detail": detail})

    def _run(self) -> None:
        # Wait for any capture in progress; captures are refused while updating
        with self._capture_lock:
            try:
                self._camera.stop_preview()
            except Exception:
                pass
            try:
                restart = self._update()
            except Exception as e:
                logger.exception("Update failed")
                self._set(state="failed", step=None, error=str(e))
                return

        if not restart:
            return
        if _under_gunicorn():
            logger.info("Update installed, restarting the worker")
            self._set(state="restarting", step="restarting")
            # Give the browser a moment to see "restarting" before the worker exits
            threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM)).start()
        else:
            self._notice("restart_manually")
            self._set(state="done", step=None)

    def _update(self) -> bool:
        """Pull, reinstall dependencies if needed. Returns whether a restart is needed."""
        self._set(step="checking")
        info = check()
        if info["blockers"]:
            raise UpdateError("; ".join(
                f"{BLOCKER_TEXT[b['code']]}: {b['detail']}" for b in info["blockers"]))
        for warning in info["warnings"]:
            self._notice(warning["code"], warning["detail"])
        if not info["update_available"]:
            self._set(state="done", step=None)
            return False

        repos = [("webapp", APP_DIR, info["webapp"])]
        if info["kat_updatable"]:
            repos.append(("kat", Path(info["kat"]["path"]), info["kat"]))

        self._set(step="pulling")
        pulled = []  # (path, previous HEAD) for rollback
        changed = {}
        try:
            for name, path, status in repos:
                if not status["behind"]:
                    continue
                logger.info("Updating %s at %s", name, path)
                _git(path, "merge", "--ff-only", "@{upstream}")
                pulled.append((path, status["head"]))
                changed[name] = _git(path, "diff", "--name-only", status["head"], "HEAD").splitlines()

            deps_changed = (
                "backend/requirements.txt" in changed.get("webapp", [])
                or "pyproject.toml" in changed.get("kat", [])
            )
            if deps_changed:
                self._set(step="installing")
                self._install_deps(info["kat"]["path"] if info["kat"] else None)
        except Exception:
            # Put the code on disk back to what this process is running
            for path, head in pulled:
                try:
                    _git(path, "reset", "--keep", head)
                except UpdateError as e:
                    logger.error("Rollback of %s failed: %s", path, e)
            raise

        if "setup-pi.sh" in changed.get("webapp", []):
            self._notice("setup_changed")
        return True

    def _install_deps(self, kat_dir: Optional[str]) -> None:
        env = dict(os.environ)
        if kat_dir:
            env["KAT_DIR"] = kat_dir
        try:
            result = subprocess.run(
                [str(APP_DIR / "setup-pi.sh"), "--deps-only"],
                capture_output=True, text=True, timeout=DEPS_TIMEOUT_S, env=env,
            )
        except subprocess.TimeoutExpired:
            raise UpdateError("dependency install timed out")
        if result.returncode != 0:
            tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-10:])
            raise UpdateError(f"dependency install failed:\n{tail}")
