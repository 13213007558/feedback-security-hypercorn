from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

import pytest
import trio

from hypercorn.app_wrappers import ASGIWrapper
from hypercorn.config import Config
from hypercorn.trio.lifespan import Lifespan
from hypercorn.typing import ASGIReceiveCallable, ASGISendCallable, Scope
from hypercorn.utils import LifespanFailureError, LifespanTimeoutError, LifespanUnsupportedError
from ..helpers import (
    early_return_lifespan_app,
    raising_lifespan_app,
    SlowLifespanFramework,
    SlowStartupLifespanFramework,
    startup_failed_lifespan_app,
    WorkingLifespanFramework,
)


@pytest.mark.trio
async def test_startup_timeout_error(nursery: trio._core._run.Nursery) -> None:
    config = Config()
    config.startup_timeout = 0.01
    lifespan = Lifespan(ASGIWrapper(SlowLifespanFramework(0.02, trio.sleep)), config, {})
    nursery.start_soon(lifespan.handle_lifespan)
    with pytest.raises(LifespanTimeoutError) as exc_info:
        await lifespan.wait_for_startup()
    assert str(exc_info.value).startswith("Timeout whilst awaiting startup")


async def _lifespan_failure(
    scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
) -> None:
    async with trio.open_nursery():
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.failed", "message": "Failure"})
            break


@pytest.mark.trio
async def test_startup_failure() -> None:
    lifespan = Lifespan(ASGIWrapper(_lifespan_failure), Config(), {})
    try:
        async with trio.open_nursery() as lifespan_nursery:
            await lifespan_nursery.start(lifespan.handle_lifespan)
            await lifespan.wait_for_startup()
    except ExceptionGroup as error:
        assert error.subgroup(LifespanFailureError) is not None


def _required_config() -> Config:
    config = Config()
    config.lifespan = "required"
    return config


def _assert_contains(exc: BaseException, expected: type[BaseException]) -> None:
    if isinstance(exc, ExceptionGroup):
        assert exc.subgroup(expected) is not None
    else:
        assert isinstance(exc, expected)


@pytest.mark.trio
async def test_required_rejects_unsupported_app() -> None:
    lifespan = Lifespan(ASGIWrapper(raising_lifespan_app), _required_config(), {})
    with pytest.raises(BaseException) as exc_info:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(lifespan.handle_lifespan)
            await lifespan.wait_for_startup()
    _assert_contains(exc_info.value, LifespanUnsupportedError)


@pytest.mark.trio
async def test_required_rejects_early_return() -> None:
    lifespan = Lifespan(ASGIWrapper(early_return_lifespan_app), _required_config(), {})
    with pytest.raises(BaseException) as exc_info:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(lifespan.handle_lifespan)
            await lifespan.wait_for_startup()
    _assert_contains(exc_info.value, LifespanUnsupportedError)


@pytest.mark.trio
async def test_required_rejects_startup_failed() -> None:
    lifespan = Lifespan(ASGIWrapper(startup_failed_lifespan_app), _required_config(), {})
    with pytest.raises(BaseException) as exc_info:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(lifespan.handle_lifespan)
            await lifespan.wait_for_startup()
    _assert_contains(exc_info.value, LifespanFailureError)


@pytest.mark.trio
async def test_required_rejects_startup_timeout() -> None:
    config = _required_config()
    config.startup_timeout = 0.01
    lifespan = Lifespan(
        ASGIWrapper(SlowStartupLifespanFramework(0.02, trio.sleep)), config, {}
    )
    with pytest.raises(BaseException) as exc_info:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(lifespan.handle_lifespan)
            await lifespan.wait_for_startup()
    _assert_contains(exc_info.value, LifespanTimeoutError)


@pytest.mark.trio
async def test_required_allows_supported_app() -> None:
    framework = WorkingLifespanFramework()
    lifespan = Lifespan(ASGIWrapper(framework), _required_config(), {})
    async with trio.open_nursery() as nursery:
        nursery.start_soon(lifespan.handle_lifespan)
        await lifespan.wait_for_startup()
        assert framework.started
        await lifespan.wait_for_shutdown()
        assert framework.shutdown


@pytest.mark.trio
async def test_auto_still_continues_without_lifespan() -> None:
    lifespan = Lifespan(ASGIWrapper(raising_lifespan_app), Config(), {})
    async with trio.open_nursery() as nursery:
        nursery.start_soon(lifespan.handle_lifespan)
        await lifespan.wait_for_startup()
        await lifespan.wait_for_shutdown()
    assert not lifespan.supported
