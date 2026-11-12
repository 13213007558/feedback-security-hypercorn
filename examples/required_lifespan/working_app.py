"""ASGI app that initialises and tears down cleanly via the lifespan protocol."""


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                # E.g. open the revocation list store / connection pool here.
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", b"2")],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})
