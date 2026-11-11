from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import pytest
from h2.connection import H2Connection
from h2.events import DataReceived, InformationalResponseReceived, ResponseReceived, StreamEnded

from hypercorn.app_wrappers import ASGIWrapper
from hypercorn.asyncio.tcp_server import TCPServer
from hypercorn.asyncio.worker_context import WorkerContext
from hypercorn.config import Config
from hypercorn.typing import ASGIReceiveCallable, ASGISendCallable, Scope
from .helpers import MemoryReader, MemoryWriter

VALID_LINK = b'  </style.css>; rel="preload"; as="style"\t'
STRIPPED_LINK = b'</style.css>; rel="preload"; as="style"'
MALICIOUS_LINKS = [
    b'</style.css>; rel="preload"\r\nx-evil: injected',
    b'</style.css>; rel="preload"\rx-evil: injected',
    b'</style.css>; rel="preload"\nx-evil: injected',
    b'</style.css>; rel="preload"\x00x-evil',
]


def early_hint_framework(link: bytes) -> Callable:
    async def framework(
        scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                break
            elif event["type"] == "http.request" and not event.get("more_body", False):
                if scope["path"] == "/hint":  # type: ignore
                    await send({"type": "http.response.early_hint", "links": [link]})
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-length", b"2")],
                    }
                )
                await send({"type": "http.response.body", "body": b"ok", "more_body": False})
                break

    return framework


@asynccontextmanager
async def serve(app: Callable, http2: bool) -> AsyncGenerator[TCPServer, None]:
    event_loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    config = Config()
    config.keep_alive_timeout = 0.01
    server = TCPServer(
        ASGIWrapper(app),
        event_loop,
        config,
        WorkerContext(None),
        {},
        MemoryReader(),  # type: ignore
        MemoryWriter(http2=http2),  # type: ignore
    )
    task = event_loop.create_task(server.run())
    yield server
    server.reader.close()  # type: ignore
    await task


async def h2_request(
    client: H2Connection, server: TCPServer, stream_id: int, path: str
) -> tuple[list, bytes]:
    client.send_headers(
        stream_id,
        [
            (":method", "GET"),
            (":path", path),
            (":authority", "hypercorn"),
            (":scheme", "https"),
        ],
        end_stream=True,
    )
    await server.reader.send(client.data_to_send())  # type: ignore
    events, raw = [], b""
    while not any(
        isinstance(event, StreamEnded) and event.stream_id == stream_id for event in events
    ):
        data = await asyncio.wait_for(server.writer.receive(), 1)  # type: ignore
        raw += data
        events.extend(client.receive_data(data))
        outbound = client.data_to_send()
        if outbound:
            await server.reader.send(outbound)  # type: ignore
    return events, raw


@pytest.mark.asyncio
@pytest.mark.parametrize("link", MALICIOUS_LINKS)
async def test_h2_malicious_early_hint_is_rejected(link: bytes) -> None:
    async with serve(early_hint_framework(link), http2=True) as server:
        client = H2Connection()
        client.initiate_connection()
        await server.reader.send(client.data_to_send())  # type: ignore

        events, raw = await h2_request(client, server, 1, "/hint")
        # No informational response nor injected bytes may reach the wire
        assert not any(isinstance(event, InformationalResponseReceived) for event in events)
        assert b"x-evil" not in raw.lower()
        responses = [event for event in events if isinstance(event, ResponseReceived)]
        assert len(responses) == 1
        assert (b":status", b"500") in responses[0].headers

        # The connection must stay usable, with unambiguous later responses
        events, raw = await h2_request(client, server, 3, "/")
        responses = [event for event in events if isinstance(event, ResponseReceived)]
        assert len(responses) == 1
        assert (b":status", b"200") in responses[0].headers
        body = b"".join(event.data for event in events if isinstance(event, DataReceived))
        assert body == b"ok"


@pytest.mark.asyncio
async def test_h2_early_hint_legal_whitespace() -> None:
    async with serve(early_hint_framework(VALID_LINK), http2=True) as server:
        client = H2Connection()
        client.initiate_connection()
        await server.reader.send(client.data_to_send())  # type: ignore

        events, _ = await h2_request(client, server, 1, "/hint")
        hints = [event for event in events if isinstance(event, InformationalResponseReceived)]
        assert len(hints) == 1
        assert (b":status", b"103") in hints[0].headers
        assert (b"link", STRIPPED_LINK) in hints[0].headers
        responses = [event for event in events if isinstance(event, ResponseReceived)]
        assert len(responses) == 1
        assert (b":status", b"200") in responses[0].headers
        body = b"".join(event.data for event in events if isinstance(event, DataReceived))
        assert body == b"ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", MALICIOUS_LINKS)
async def test_h11_malicious_early_hint_is_rejected(link: bytes) -> None:
    async with serve(early_hint_framework(link), http2=False) as server:
        await server.reader.send(  # type: ignore
            b"GET /hint HTTP/1.1\r\nHost: hypercorn\r\nConnection: keep-alive\r\n\r\n"
        )
        raw = b""
        while True:
            chunk = await asyncio.wait_for(server.writer.receive(), 1)  # type: ignore
            if chunk == b"":
                break
            raw += chunk
        # No 103 response nor injected bytes may reach the wire
        assert raw.startswith(b"HTTP/1.1 500")
        assert b"103" not in raw.split(b"\r\n", 1)[0]
        assert b"x-evil" not in raw.lower()
        # The connection must be closed, not left in an ambiguous state
        assert server.writer.is_closed  # type: ignore
