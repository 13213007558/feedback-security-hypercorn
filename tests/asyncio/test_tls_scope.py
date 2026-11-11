from __future__ import annotations

import asyncio
import ssl
from collections.abc import Callable

import pytest

from hypercorn.app_wrappers import ASGIWrapper
from hypercorn.asyncio.tcp_server import TCPServer
from hypercorn.asyncio.worker_context import WorkerContext
from hypercorn.config import Config
from hypercorn.protocol.tls import build_tls_extension
from hypercorn.typing import ASGIReceiveCallable, ASGISendCallable, Scope
from tests.asyncio.helpers import MemoryReader, MemoryWriter
from tests.helpers import MockSocket
from tests.protocol.tls_helpers import (
    CLIENT_CERT,
    CLIENT_KEY,
    client_ssl_context,
    memory_bio_handshake,
    server_ssl_context,
)


class VerifiedWriter(MemoryWriter):
    def __init__(self, ssl_object: ssl.SSLObject) -> None:
        super().__init__(http2=False)
        self._ssl_object = ssl_object

    def get_extra_info(self, name: str) -> object:
        if name == "socket":
            return MockSocket()
        if name == "ssl_object":
            return self._ssl_object
        return None


async def _capturing_app(
    scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
) -> None:
    captured.append(scope)  # type: ignore[name-defined]
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})


captured: list[Scope] = []


@pytest.mark.asyncio
async def test_asyncio_scope_uses_verified_transport_certificate() -> None:
    event_loop = asyncio.get_running_loop()
    ssl_object = memory_bio_handshake(
        server_ssl_context(ssl.CERT_REQUIRED),
        client_ssl_context(CLIENT_CERT, CLIENT_KEY),
    )
    expected = build_tls_extension(ssl_object)

    reader = MemoryReader()
    writer = VerifiedWriter(ssl_object)
    server = TCPServer(
        ASGIWrapper(_capturing_app),
        event_loop,
        Config(),
        WorkerContext(None),
        {},
        reader,  # type: ignore[arg-type]
        writer,  # type: ignore[arg-type]
    )
    task = event_loop.create_task(server.run())
    await reader.send(b"GET / HTTP/1.1\r\nHost: hypercorn\r\n\r\n")
    reader.close()
    await task

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
