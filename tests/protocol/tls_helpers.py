from __future__ import annotations

import os
import ssl

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "tls")


def _path(name: str) -> str:
    return os.path.abspath(os.path.join(ASSETS, name))


CA_CERT = _path("ca.pem")
SERVER_CERT = _path("server.pem")
SERVER_KEY = _path("server.key")
CLIENT_CERT = _path("client.pem")
CLIENT_KEY = _path("client.key")
ROGUE_CERT = _path("rogue.pem")
ROGUE_KEY = _path("rogue.key")


def server_ssl_context(verify_mode: ssl.VerifyMode) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(SERVER_CERT, SERVER_KEY)
    context.load_verify_locations(CA_CERT)
    context.verify_mode = verify_mode
    return context


def client_ssl_context(
    cert: str | None = None, key: str | None = None
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # The server certificate is validated separately; the focus here is the
    # server's view of the client certificate.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    if cert is not None and key is not None:
        context.load_cert_chain(cert, key)
    return context


def memory_bio_handshake(
    server_context: ssl.SSLContext, client_context: ssl.SSLContext
) -> ssl.SSLObject:
    """Drive a real TLS handshake over in-memory BIOs and return the server.

    Avoids binding a network socket, so it works without network permissions.
    """
    server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    server = server_context.wrap_bio(server_in, server_out, server_side=True)
    client = client_context.wrap_bio(client_in, client_out, server_hostname="localhost")

    def _pump(source: ssl.MemoryBIO, destination: ssl.MemoryBIO) -> None:
        try:
            data = source.read()
        except ssl.SSLWantReadError:
            return
        if data:
            destination.write(data)

    for _ in range(20):
        client_done = server_done = False
        try:
            client.do_handshake()
            client_done = True
        except ssl.SSLWantReadError:
            pass
        _pump(client_out, server_in)
        try:
            server.do_handshake()
            server_done = True
        except ssl.SSLWantReadError:
            pass
        _pump(server_out, client_in)
        if client_done and server_done:
            return server

    raise RuntimeError("TLS handshake did not complete")
