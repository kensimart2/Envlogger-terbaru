from __future__ import annotations

import os
import runpy
import signal
import sys
import time
import traceback
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEPS_DIR = BASE_DIR / "deps"
if DEPS_DIR.exists() and str(DEPS_DIR) not in sys.path:
    sys.path.insert(0, str(DEPS_DIR))

BOT_FILE = BASE_DIR / "bot.py"
MIN_BACKOFF = 2
MAX_BACKOFF = 60


def load_local_environment() -> None:
    """Load only missing values from the local runtime environment file.

    This keeps externally injected values authoritative and never logs secrets.
    """
    env_path = BASE_DIR / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
import fcntl
import socket
import sys
import tempfile

_SUPERVISOR_LOCK_HANDLE = None
_SUPERVISOR_MUTEX_SOCKET = None


def ensure_single_instance() -> None:
    """Ensure only one supervisor/bot instance runs at any time.

    If an instance is already running, exit immediately without interfering.
    """
    global _SUPERVISOR_LOCK_HANDLE, _SUPERVISOR_MUTEX_SOCKET

    _SUPERVISOR_MUTEX_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _SUPERVISOR_MUTEX_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        _SUPERVISOR_MUTEX_SOCKET.bind(("127.0.0.1", 48290))
        _SUPERVISOR_MUTEX_SOCKET.listen(1)
    except OSError:
        print("[supervisor] Another supervisor instance is already active (port 48290 in use). Exiting duplicate.", flush=True)
        sys.exit(0)

    pid_file = Path(tempfile.gettempdir()) / "kenv1_supervisor.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    lock_file = Path(tempfile.gettempdir()) / "kenv1_supervisor.lock"
    _SUPERVISOR_LOCK_HANDLE = open(lock_file, "w")
    try:
        fcntl.flock(_SUPERVISOR_LOCK_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        pass


def main() -> None:
    ensure_single_instance()
    load_local_environment()
    if os.environ.get("PORT") == "8080":
        os.environ["PORT"] = "3000"
    else:
        os.environ.setdefault("PORT", "3000")

    import keep_alive

    keep_alive.keep_alive()
    keep_alive.set_bot_alive(True)
    shutdown_requested = False

    def request_shutdown(_signal: int, _frame: object) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True
        keep_alive.set_bot_alive(False)

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    backoff = MIN_BACKOFF
    while not shutdown_requested:
        started = time.monotonic()
        try:
            runpy.run_path(str(BOT_FILE), run_name="__main__")
            if shutdown_requested:
                break
            print("[supervisor] bot stopped cleanly.", flush=True)
            break
        except KeyboardInterrupt:
            break
        except SystemExit as exc:
            if shutdown_requested:
                break
            code = exc.code if isinstance(exc.code, int) else 0
            if code in (0, 99):
                print(f"[supervisor] bot yielded to existing instance (code {code}). Stopping supervisor.", flush=True)
                break
            print(f"[supervisor] bot exited with code {code}; restarting", flush=True)
        except Exception:
            if shutdown_requested:
                break
            print("[supervisor] bot crashed:", flush=True)
            traceback.print_exc()
        finally:
            keep_alive.set_bot_alive(False)

        if shutdown_requested:
            break
        if time.monotonic() - started > 60:
            backoff = MIN_BACKOFF
        else:
            backoff = min(backoff * 2, MAX_BACKOFF)
        print(f"[supervisor] waiting {backoff}s before restart", flush=True)
        for _ in range(backoff):
            if shutdown_requested:
                break
            time.sleep(1)

    keep_alive.stop_all()


if __name__ == "__main__":
    main()
