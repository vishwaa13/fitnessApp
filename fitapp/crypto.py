"""Passphrase encryption that the browser can undo with WebCrypto.

PBKDF2-SHA256 derives an AES-256-GCM key from the passphrase. The envelope is
plain JSON with base64 fields; ``site/app.js`` reverses it with
``crypto.subtle``. The GitHub repo is public, so every byte of personal data
that leaves the Actions runner goes through here first.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 310_000


def _key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_json(obj: Any, passphrase: str, iterations: int = ITERATIONS) -> dict[str, Any]:
    salt = os.urandom(16)
    iv = os.urandom(12)
    plaintext = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_key(passphrase, salt, iterations)).encrypt(iv, plaintext, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iterations,
            "salt": b64(salt), "iv": b64(iv), "ct": b64(ciphertext)}


def decrypt_json(envelope: dict[str, Any], passphrase: str) -> Any:
    salt = base64.b64decode(envelope["salt"])
    iv = base64.b64decode(envelope["iv"])
    ciphertext = base64.b64decode(envelope["ct"])
    key = _key(passphrase, salt, int(envelope["iter"]))
    return json.loads(AESGCM(key).decrypt(iv, ciphertext, None))
