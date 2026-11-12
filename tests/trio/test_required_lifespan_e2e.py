from __future__ import annotations

import socket
from functools import partial

import pytest
import trio

from hypercorn.app_wrappers import ASGIWrapper
from hypercorn.config import Config
from hypercorn.trio.run import worker_serve
from hypercorn.utils import LifespanFailureError, LifespanUnsupportedError
from ..helpers import (
    early_return_lifespan_app,
    raising_lifespan_app,
    startup_failed_lifespan_app,
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


def _required_config() -> Config:
    config = Config()
    config.lifespan = "required"
    config.bind = ["127.0.0.1:59998"]
    config.errorlog = None
    config.accesslog = None
    return config


@pytest.mark.trio
@pytest.mark.parametrize(
    "app, expected",
    [
        (raising_lifespan_app, LifespanUnsupportedError),
        (early_return_lifespan_app, (LifespanUnsupportedError, trio.ClosedResourceError)),
        (startup_failed_lifespan_app, LifespanFailureError),
    ],
)
async def test_required_lifespan_failure_never_serves(app, expected) -> None:
    config = _required_config()

    with pytest.raises(BaseException) as exc_info:
        await worker_serve(ASGIWrapper(app), config)

    error = exc_info.value
    assert _contains(error, expected)

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert probe.connect_ex(("127.0.0.1", 59998)) != 0
    finally:
        probe.close()


def _contains(
    error: BaseException, expected: type[BaseException] | tuple[type[BaseException], ...]
) -> bool:
    if isinstance(error, ExceptionGroup):
        return error.subgroup(expected) is not None
    return isinstance(error, expected)


@requires_binding
@pytest.mark.trio
async def test_required_lifespan_success_serves_and_shuts_down() -> None:
    from ..helpers import WorkingLifespanFramework

    config = _required_config()
    framework = WorkingLifespanFramework()
    shutdown = trio.Event()

    async def _stop_soon() -> None:
        with trio.move_on_after(5):
            while True:
                try:
                    await trio.open_tcp_stream("127.0.0.1", 59998)
                except OSError:
                    await trio.sleep(0.05)
                else:
                    break
        shutdown.set()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(
            partial(worker_serve, ASGIWrapper(framework), config, shutdown_trigger=shutdown.wait)
        )
        nursery.start_soon(_stop_soon)

    assert framework.started and framework.shutdown
