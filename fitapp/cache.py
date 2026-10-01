"""Encrypted state carried between GitHub Actions runs (via actions/cache).

Holds fetched Garmin history, rotated Garmin tokens, and what the app already
did (uploaded workouts, calendar swaps), so each run only fetches what changed.
It is encrypted with the dashboard passphrase because Actions caches on a
public repo can be read by workflows from forks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .crypto import decrypt_json, encrypt_json

log = logging.getLogger(__name__)


def load(path: Path, passphrase: str) -> dict:
    if not path.exists():
        return {}
    try:
        return decrypt_json(json.loads(path.read_text()), passphrase)
    except Exception:  # noqa: BLE001 - a bad cache just means a full refetch
        log.warning("Cache could not be decrypted (passphrase changed?); starting fresh")
        return {}


def save(path: Path, state: dict, passphrase: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encrypt_json(state, passphrase, iterations=100_000)))
