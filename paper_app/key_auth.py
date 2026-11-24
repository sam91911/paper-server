"""Validate the wire format shared by human and AI Ed25519 sign-in."""

import base64
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import accounts

CHALLENGE_SECONDS = 120


def decode_field(data, name, size):
    value = data.get(name)
    length = (size * 8 + 5) // 6
    if isinstance(value, str) and re.fullmatch(f"[A-Za-z0-9_-]{{{length}}}", value):
        decoded = base64.urlsafe_b64decode(value + "=" * (-length % 4))
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") == value:
            return decoded
    raise ValueError(f"Enter a valid base64url {name}.")


def verify(public_key, data, message):
    signature = decode_field(data, "signature", 64)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message.encode("ascii"))
    except InvalidSignature:
        raise accounts.SignInRequired from None
