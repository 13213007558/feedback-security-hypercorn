from __future__ import annotations

import asyncio
import socket
import urllib.request

import pytest

from hypercorn.app_wrappers import ASGIWrapper
from hypercorn.asyncio.run import worker_serve
from hypercorn.config import Config
from hypercorn.utils import LifespanFailureError, LifespanUnsupportedError
from ..helpers import (
    early_return_lifespan_app,
    raising_lifespan_app,
    startup_failed_lifespan_app,
    WorkingLifespanFramework,
)


def _can_bind() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
    except OSError:
        return False
    else:
        sock.close()
        return True


requires_binding = pytest.mark.skipif(not _can_bind(), reason="local socket binding is disabled")


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _required_config(port: int) -> Config:
    config = Config()
    config.lifespan = "required"
    config.bind = [f"127.0.0.1:{port}"]
    config.errorlog = None
    config.accesslog = None
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app, expected",
    [
        (raising_lifespan_app, LifespanUnsupportedError),
        (early_return_lifespan_app, LifespanUnsupportedError),
        (startup_failed_lifespan_app, LifespanFailureError),
    ],
)
async def test_required_lifespan_failure_never_serves(app, expected) -> None:
    # The worker must raise before create_sockets, so no real port is needed.
    port = 59999
    config = _required_config(port)
    shutdown = asyncio.Event()

    with pytest.raises(expected):
        await worker_serve(
            ASGIWrapper(app), config, shutdown_trigger=shutdown.wait
        )

    # The worker raised before create_sockets, so nothing is listening.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        probe.close()


@requires_binding
@pytest.mark.asyncio
async def test_required_lifespan_success_serves_and_shuts_down() -> None:
    port = _free_port()
    config = _required_config(port)
    shutdown = asyncio.Event()

    async def _stop_soon() -> None:
        # Wait until the socket accepts a connection, then request shutdown.
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
            except OSError:
                await asyncio.sleep(0.05)
            else:
                writer.close()
                await writer.wait_closed()
                reader.feed_eof()
                break
        shutdown.set()

    framework = WorkingLifespanFramework()
    await asyncio.gather(
        worker_serve(ASGIWrapper(framework), config, shutdown_trigger=shutdown.wait),
        _stop_soon(),
    )
    assert framework.started and framework.shutdown

    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
