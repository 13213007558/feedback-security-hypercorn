Reading client TLS certificates
================================

Hypercorn exposes information about the negotiated TLS transport in the
ASGI ``tls`` extension, following the `ASGI TLS extension
<https://github.com/django/asgiref/blob/main/docs/asgi/extensions.rst#tls-extension>`_
convention. For every HTTP and WebSocket request the value is available at
``scope["extensions"]["tls"]``. On an HTTP/2 connection every stream (request)
receives the same connection-level value.

The data is read from the actual TLS transport, never from request headers,
so a client cannot influence or override it by sending a header with a
matching name. This makes it suitable as the basis for client certificate
authentication, unlike proxy-supplied headers such as
``X-SSL-Client-Cert``.

Configuring client certificates
-------------------------------

Hypercorn verifies client certificates against the configured chain of
trust. Point ``ca_certs`` at the trust store and choose a ``verify_mode``,

.. code-block:: python

    import ssl
    from hypercorn.config import Config

    config = Config()
    config.certfile = "server.pem"
    config.keyfile = "server.key"
    config.ca_certs = "ca.pem"
    # Request but do not require a client certificate, so the app can decide.
    config.verify_mode = ssl.CERT_OPTIONAL

Use ``ssl.CERT_REQUIRED`` to reject the TLS handshake entirely when the
client does not present a certificate trusted by ``ca_certs``. With
``ssl.CERT_NONE`` no verification happens and Hypercorn cannot vouch for any
certificate the client sends.

The observable states
---------------------

``scope["extensions"]["tls"]["tls"]`` is always present and reports whether
the connection is actually TLS:

* **No TLS** (plaintext listener): ``{"tls": False}``.
* **TLS, no usable client certificate**: ``{"tls": True}``, with
  ``client_cert_error`` set to ``"No client certificate"`` when the server
  requested one (``CERT_OPTIONAL``). Under ``CERT_NONE`` no error is added
  because no certificate was requested.
* **TLS, verified client certificate**: ``{"tls": True}`` with
  ``client_cert`` (the DER encoded certificate as ``bytes``) and
  ``client_cert_name`` (the RFC 4514 subject, e.g.
  ``"CN=client-001,O=Example,C=UK"``).

When verification is disabled, Python's TLS stack does not expose the
offered certificate at all, so an unverified certificate can never appear
in ``client_cert``. A handshake presenting a certificate that fails the
configured chain of trust is rejected during the handshake under
``CERT_OPTIONAL`` and ``CERT_REQUIRED``.

Making an authentication decision
---------------------------------

Treat a populated ``client_cert`` as the transport's statement that the
certificate passed verification, then apply your own authorization rules,

.. code-block:: python

    async def app(scope, receive, send):
        tls = scope.get("extensions", {}).get("tls")
        if not tls or not tls.get("tls") or not tls.get("client_cert"):
            status = 401  # No TLS, or no verified client certificate.
        else:
            name = tls["client_cert_name"]
            status = 200 if is_known_client(name) else 403

        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

What must not be used on its own
--------------------------------

* **Headers** such as ``X-Forwarded-*`` or ``X-SSL-Client-*`` are set by a
  peer and can be forged unless a trusted proxy strips and rewrites them.
  They are not evidence of a verified client certificate.
* **``client_cert_name``** is only a human readable rendering of the
  certificate subject. The subject is self-asserted by the certificate; it
  is meaningful only together with a present, verified ``client_cert`` and
  an allow-list check. Do not authenticate on the name alone.
* **The presence of the ``tls`` extension or ``tls == True``** only proves a
  TLS connection, not that the client authenticated. Inspect
  ``client_cert`` (or ``client_cert_error``) for that.
* **``scheme`` / ``wss``** describe the transport scheme, not client
  authentication.

For richer checks (validity dates, SANs, extensions, revocation), parse the
DER ``client_cert`` yourself, for example with the ``cryptography``
package's ``x509.load_der_x509_certificate``.
