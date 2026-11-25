"""Export a Paper Library human or agent Ed25519 key in OpenSSH format."""

import argparse
import base64
import binascii
import json
import os
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def raw_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValueError("Expected a Paper Library Ed25519 key.")
    return base64.urlsafe_b64decode(value + "=")


def load_key(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a Paper Library identity file.")
    jwk = data.get("key")
    if isinstance(jwk, dict) and jwk.get("kty") == "OKP" and jwk.get("crv") == "Ed25519":
        private = Ed25519PrivateKey.from_private_bytes(raw_key(jwk.get("d")))
        if private.public_key().public_bytes_raw() != raw_key(jwk.get("x")):
            raise ValueError("The private and public fields in this identity do not match.")
        return private
    return Ed25519PrivateKey.from_private_bytes(raw_key(data.get("private_key")))


def export(source, destination):
    private = load_key(source)
    output = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                   serialization.NoEncryption())
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identity", type=Path, help="Downloaded human key or local agent identity")
    parser.add_argument("--out", required=True, type=Path, help="New private key file")
    args = parser.parse_args()
    try:
        export(args.identity.expanduser(), args.out.expanduser())
        print(f"Saved OpenSSH key to {args.out}")
    except (ValueError, OSError, binascii.Error) as error:
        parser.exit(1, f"Paper Library SSH key: {error}\n")


if __name__ == "__main__":
    main()
