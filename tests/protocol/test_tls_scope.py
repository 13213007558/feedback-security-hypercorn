from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hypercorn.asyncio.worker_context import WorkerContext
from hypercorn.config import Config
from hypercorn.protocol.events import Request
from hypercorn.protocol.http_stream import HTTPStream
from hypercorn.protocol.ws_stream import WSStream
from hypercorn.typing import ConnectionState, TLSExtension

VERIFIED_TLS: TLSExtension = {
    "tls": True,
    "client_cert": b"0\x82\x03\x01der-bytes",
    "client_cert_name": "CN=client-001,O=Hypercorn Clients,C=UK",
}


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        stream_id=1,
        http_version="1.1",
        headers=headers or [],
        raw_path=b"/?a=b",
        method="GET",
        state=ConnectionState({}),
    )


@pytest.mark.asyncio
async def test_http_scope_carries_tls_extension() -> None:
    stream = HTTPStream(
        AsyncMock(),
        Config(),
        WorkerContext(None),
        AsyncMock(),
        True,
        None,
        None,
        AsyncMock(),
        1,
        VERIFIED_TLS,
    )
    stream.app_put = AsyncMock()
    await stream.handle(_request())
    scope = stream.task_group.spawn_app.call_args[0][2]
    assert scope["extensions"]["tls"] == VERIFIED_TLS


@pytest.mark.asyncio
async def test_http_request_header_cannot_override_tls_extension() -> None:
    stream = HTTPStream(
        AsyncMock(),
        Config(),
        WorkerContext(None),
        AsyncMock(),
        True,
        None,
        None,
        AsyncMock(),
        1,
        VERIFIED_TLS,
    )
    stream.app_put = AsyncMock()
    # A client trying to forge client certificate material via a header.
    await stream.handle(
        _request([(b"x-ssl-client-cert", b"CN=forged"), (b"x-forwarded-proto", b"http")])
    )
    scope = stream.task_group.spawn_app.call_args[0][2]
    # The transport-derived extension is untouched by any request header.
    assert scope["extensions"]["tls"] == VERIFIED_TLS
    # And the scheme remains the transport-derived value, not the header's.
    assert scope["scheme"] == "https"


@pytest.mark.asyncio
async def test_ws_scope_carries_tls_extension() -> None:
    stream = WSStream(
        AsyncMock(),
        Config(),
        WorkerContext(None),
        AsyncMock(),
        True,
        None,
        None,
        AsyncMock(),
        1,
        VERIFIED_TLS,
    )
    stream.app_put = AsyncMock()
    await stream.handle(
        _request(
            [
                (b"connection", b"upgrade"),
                (b"upgrade", b"websocket"),
                (b"sec-websocket-version", b"13"),
                (b"sec-websocket-key", b"UnQ3lpJAH6j2PslA993iKQ=="),
            ]
        )
    )
    scope = stream.task_group.spawn_app.call_args[0][2]
    assert scope["extensions"]["tls"] == VERIFIED_TLS
    assert scope["scheme"] == "wss"
