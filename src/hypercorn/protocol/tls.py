from __future__ import annotations

from ssl import CERT_OPTIONAL, CERT_REQUIRED, SSLObject
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..typing import TLSExtension

CLIENT_CERT_NO_CERT = "No client certificate"

# RFC 4514 short names for the attribute types Python's :meth:`getpeercert`
# renders with their long OpenSSL name. Unknown types keep their long name.
_RDN_SHORT_NAMES = {
    "businessCategory": "businessCategory",
    "commonName": "CN",
    "countryName": "C",
    "dc": "DC",
    "domainComponent": "DC",
    "emailAddress": "emailAddress",
    "generationQualifier": "generationQualifier",
    "givenName": "GN",
    "initials": "initials",
    "localityName": "L",
    "organizationalUnitName": "OU",
    "organizationName": "O",
    "postalCode": "postalCode",
    "serialNumber": "serialNumber",
    "stateOrProvinceName": "ST",
    "streetAddress": "street",
    "surname": "SN",
    "title": "title",
    "userID": "UID",
    "userid": "UID",
}


def _build_distinguished_name(subject: tuple[tuple[tuple[str, str], ...], ...]) -> str:
    # The subject is a sequence of relative distinguished names, each a
    # sequence of attribute type and value pairs. Reversing the order renders
    # the name as the RFC 4514 string representation, e.g. ``CN=…,O=…,C=…``.
    return ",".join(
        f"{_RDN_SHORT_NAMES.get(attribute_type, attribute_type)}={attribute_value}"
        for relative_name in reversed(subject)
        for attribute_type, attribute_value in relative_name
    )


def build_tls_extension(ssl_object: SSLObject) -> TLSExtension:
    """Build the ASGI ``tls`` extension value from an active TLS transport.

    The data is taken directly from the negotiated :class:`~ssl.SSLObject`,
    never from request headers, so it cannot be spoofed by the client. The
    observable states are:

    * plain TLS without a usable client certificate, optionally annotated with
      ``client_cert_error`` when the server requested one,
    * a client certificate verified against the configured chain of trust,
      exposed as DER bytes in ``client_cert`` with its RFC 4514 subject name.

    Python's :meth:`~ssl.SSLObject.getpeercert` only returns a populated
    dictionary once OpenSSL has verified the peer certificate; with
    verification disabled it returns ``None`` even if the client sent bytes.
    An unverified certificate is therefore never placed in ``client_cert``, so
    a non-empty ``client_cert`` is always backed by a successful verification.
    """
    extension: TLSExtension = {"tls": True}
    peer_cert = ssl_object.getpeercert()

    if not peer_cert:
        # Either no certificate was offered, or verification is disabled so
        # the transport cannot vouch for any offered bytes.
        if ssl_object.context.verify_mode in {CERT_OPTIONAL, CERT_REQUIRED}:
            extension["client_cert_error"] = CLIENT_CERT_NO_CERT
        return extension

    # A populated peer certificate dict implies the chain was verified.
    extension["client_cert"] = ssl_object.getpeercert(binary_form=True)
    extension["client_cert_name"] = _build_distinguished_name(peer_cert["subject"])
    return extension


def no_tls_extension() -> TLSExtension:
    return {"tls": False}
