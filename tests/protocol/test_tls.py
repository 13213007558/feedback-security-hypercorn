from __future__ import annotations

import ssl

import pytest

from hypercorn.protocol.tls import (
    CLIENT_CERT_NO_CERT,
    build_tls_extension,
    no_tls_extension,
)
from tests.protocol.tls_helpers import (
    CLIENT_CERT,
    CLIENT_KEY,
    ROGUE_CERT,
    ROGUE_KEY,
    client_ssl_context,
    memory_bio_handshake,
    server_ssl_context,
)


def test_no_tls_extension_marks_plaintext() -> None:
    assert no_tls_extension() == {"tls": False}


def test_tls_without_client_cert_and_verification_disabled() -> None:
    # CERT_NONE, no client cert: TLS is present but nothing was requested.
    server = memory_bio_handshake(
        server_ssl_context(ssl.CERT_NONE), client_ssl_context()
    )
    extension = build_tls_extension(server)
    assert extension == {"tls": True}
    assert "client_cert" not in extension
    assert "client_cert_error" not in extension


def test_tls_without_client_cert_optional_reports_error() -> None:
    # Under CERT_OPTIONAL the handshake succeeds without a client cert, and
    # the absence is surfaced rather than silently treated as authenticated.
    server = memory_bio_handshake(
        server_ssl_context(ssl.CERT_OPTIONAL), client_ssl_context()
    )
    extension = build_tls_extension(server)
    assert extension["tls"] is True
    assert extension.get("client_cert") is None
    assert extension["client_cert_error"] == CLIENT_CERT_NO_CERT


def test_tls_without_client_cert_required_rejects_handshake() -> None:
    with pytest.raises(ssl.SSLError):
        memory_bio_handshake(
            server_ssl_context(ssl.CERT_REQUIRED), client_ssl_context()
        )


def test_cert_offered_with_verification_disabled_is_not_exposed() -> None:
    # With verification disabled getpeercert() returns None even though the
    # client sent a certificate. The offered, unverified bytes must never be
    # surfaced as client_cert, which would look like a successful auth.
    server = memory_bio_handshake(
        server_ssl_context(ssl.CERT_NONE),
        client_ssl_context(CLIENT_CERT, CLIENT_KEY),
    )
    extension = build_tls_extension(server)
    assert extension == {"tls": True}
    assert "client_cert" not in extension
    assert "client_cert_name" not in extension
    assert "client_cert_error" not in extension
    assert server.getpeercert(binary_form=True) is None


@pytest.mark.parametrize("verify_mode", [ssl.CERT_OPTIONAL, ssl.CERT_REQUIRED])
def test_verified_client_cert_is_exposed(verify_mode: ssl.VerifyMode) -> None:
    server = memory_bio_handshake(
        server_ssl_context(verify_mode),
        client_ssl_context(CLIENT_CERT, CLIENT_KEY),
    )
    extension = build_tls_extension(server)
    assert extension["tls"] is True
    assert isinstance(extension["client_cert"], bytes) and extension["client_cert"]
    # DER encoded certificates start with the SEQUENCE tag.
    assert extension["client_cert"][0] == 0x30
    assert "client_cert_error" not in extension
    # RFC 4514 ordering, most specific RDN first.
    assert extension["client_cert_name"] == "CN=client-001,O=Hypercorn Clients,C=UK"


def test_verified_cert_matches_wire_der() -> None:
    server = memory_bio_handshake(
        server_ssl_context(ssl.CERT_REQUIRED),
        client_ssl_context(CLIENT_CERT, CLIENT_KEY),
    )
    extension = build_tls_extension(server)
    assert extension["client_cert"] == server.getpeercert(binary_form=True)


def test_rogue_cert_fails_handshake_under_required() -> None:
    # An untrusted cert never reaches the app under CERT_REQUIRED; the
    # handshake itself is rejected by the configured chain of trust.
    with pytest.raises(ssl.SSLError):
        memory_bio_handshake(
            server_ssl_context(ssl.CERT_REQUIRED),
            client_ssl_context(ROGUE_CERT, ROGUE_KEY),
        )


def test_rogue_cert_optional_handshake_rejected() -> None:
    with pytest.raises(ssl.SSLError):
        memory_bio_handshake(
            server_ssl_context(ssl.CERT_OPTIONAL),
            client_ssl_context(ROGUE_CERT, ROGUE_KEY),
        )
