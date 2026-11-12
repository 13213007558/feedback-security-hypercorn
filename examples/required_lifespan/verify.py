"""Local verification for the ``required`` lifespan mode.

Run from the repository root with the project virtualenv::

    python examples/required_lifespan/verify.py            # asyncio worker
    python examples/required_lifespan/verify.py trio       # trio worker

Checks performed:

1. A deliberately failing app makes the worker exit non-zero before it can
   serve, and no business request is ever processed.
2. A correctly initialising app starts, answers a request, and shuts down
   cleanly with exit code zero.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def _hypercorn_cmd(worker_class: str, app_module: str, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "hypercorn",
        f"{app_module}:app",
        "--worker-class",
        worker_class,
        "--lifespan",
        "required",
        "--bind",
        f"127.0.0.1:{port}",
        "--error-logfile",
        "-",
    ]


def _request(port: int) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            return True, response.read().decode()
    except OSError as error:
        return False, str(error)


def check_failing_app(worker_class: str) -> None:
    port = _free_port()
    proc = subprocess.Popen(
        _hypercorn_cmd(worker_class, "failing_app", port),
        cwd=APP_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Give the worker a moment to fail startup, then probe the port.
        time.sleep(1.5)
        served, detail = _request(port)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    stderr = proc.stderr.read() if proc.stderr else ""

    assert proc.returncode != 0, "worker was expected to exit non-zero"
    assert not served, f"failing app served a request: {detail}"
    print(
        f"[{worker_class}] failing app: worker exited {proc.returncode}, "
        "no request served, revocation-list failure aborts startup"
    )
    print("  captured error:", _first_error_line(stderr))


def check_working_app(worker_class: str) -> None:
    port = _free_port()
    proc = subprocess.Popen(
        _hypercorn_cmd(worker_class, "working_app", port),
        cwd=APP_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if not _wait_for_port(port):
            proc.kill()
            raise AssertionError("working app never opened the serving socket")
        served, body = _request(port)
        assert served and body == "ok", f"unexpected response: {body}"
        proc.terminate()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    stderr = proc.stderr.read() if proc.stderr else ""

    assert proc.returncode == 0, f"clean shutdown expected, got {proc.returncode}"
    print(f"[{worker_class}] working app: started, served request, shut down cleanly")


def _first_error_line(stderr: str) -> str:
    for line in stderr.splitlines():
        if "RuntimeError" in line or "Lifespan" in line or "revocation" in line:
            return line.strip()
    return stderr.strip().splitlines()[-1] if stderr.strip() else "(no stderr)"


def main() -> int:
    worker_class = sys.argv[1] if len(sys.argv) > 1 else "asyncio"
    if worker_class not in {"asyncio", "trio"}:
        print(f"unknown worker class: {worker_class}", file=sys.stderr)
        return 2

    check_failing_app(worker_class)
    check_working_app(worker_class)
    print(f"[{worker_class}] all required-lifespan checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
