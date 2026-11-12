"""ASGI app whose revocation list fails to load during lifespan startup.

The HTTP handler records every request it receives into a module level
counter. Under the ``required`` lifespan mode the worker must exit before the
serving sockets are opened, therefore this counter must stay at zero.
"""

request_count = 0


async def app(scope, receive, send):
    global request_count

    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                # Simulate the revocation list loader raising during startup.
                raise RuntimeError("failed to load revocation list")
            if message["type"] == "lifespan.shutdown":
                return

    request_count += 1
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", b"2")],
        }
    )
    await send({"type": "http.response.body", "body": b"ok"})
