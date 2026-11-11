from __future__ import annotations

import ssl
from typing import cast
from unittest.mock import AsyncMock

import pytest
import trio

from hypercorn.app_wrappers import ASGIWrapper
from hypercorn.config import Config
from hypercorn.protocol.tls import build_tls_extension
from hypercorn.trio.tcp_server import TCPServer
from hypercorn.trio.worker_context import WorkerContext
from hypercorn.typing import ASGIReceiveCallable, ASGISendCallable, Scope
from tests.helpers import MockSocket
from tests.protocol.tls_helpers import (
    CLIENT_CERT,
    CLIENT_KEY,
    client_ssl_context,
    memory_bio_handshake,
    server_ssl_context,
)

captured: list[Scope] = []


async def _capturing_app(
    scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
) -> None:
    captured.append(scope)
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})


class _FakeTransport:
    socket = MockSocket()


@pytest.mark.trio
async def test_trio_scope_uses_verified_transport_certificate(
    nursery: trio._core._run.Nursery,
) -> None:
    ssl_object = memory_bio_handshake(
        server_ssl_context(ssl.CERT_REQUIRED),
        client_ssl_context(CLIENT_CERT, CLIENT_KEY),
    )
    expected = build_tls_extension(ssl_object)

    client_stream, server_stream = trio.testing.memory_stream_pair()
    server_stream = cast("trio.SSLStream[trio.SocketStream]", server_stream)
    server_stream.do_handshake = AsyncMock()  # type: ignore[method-assign]
    server_stream.selected_alpn_protocol = lambda: "http/1.1"  # type: ignore[method-assign]
    server_stream.ssl_object = ssl_object  # type: ignore[attr-defined]
    server_stream.transport_stream = _FakeTransport()  # type: ignore[attr-defined]

    server = TCPServer(
        ASGIWrapper(_capturing_app), Config(), WorkerContext(None), {}, server_stream
    )
    nursery.start_soon(server.run)

    await client_stream.send_all(b"GET / HTTP/1.1\r\nHost: hypercorn\r\n\r\n")
    await client_stream.aclose()
    await trio.testing.wait_all_tasks_blocked()

    assert len(captured) == 1
    scope = captured[0]
    assert scope["type"] == "http"
    assert scope["scheme"] == "https"
    assert scope["extensions"]["tls"] == expected
    assert scope["extensions"]["tls"]["client_cert"] == ssl_object.getpeercert(
        binary_form=True
    )
    assert scope["extensions"]["tls"]["client_cert_name"] == (
        "CN=client-001,O=Hypercorn Clients,C=UK"
    )
    captured.clear()
