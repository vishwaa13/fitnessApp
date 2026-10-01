"""Read notes from Google Keep (unofficial API via gkeepapi).

Needs GOOGLE_EMAIL and GOOGLE_KEEP_MASTER_TOKEN. See README for how to get the
master token once with scripts/keep_token.py.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class KeepSource:
    def __init__(self, email: str | None = None, master_token: str | None = None):
        self.email = email or os.getenv("GOOGLE_EMAIL")
        self.master_token = master_token or os.getenv("GOOGLE_KEEP_MASTER_TOKEN")
        self._keep = None

    @property
    def configured(self) -> bool:
        return bool(self.email and self.master_token)

    def _client(self):
        if self._keep is None:
            import gkeepapi

            keep = gkeepapi.Keep()
            keep.authenticate(self.email, self.master_token)
            self._keep = keep
        return self._keep

    def notes_text(self, title: str) -> str:
        """Text of every note whose title contains ``title`` (case-insensitive),
        oldest note first, so "Gym logs 2025" and "Gym logs" both count."""
        keep = self._client()
        wanted = title.strip().lower()
        notes = [n for n in keep.all()
                 if not n.trashed and wanted in (n.title or "").strip().lower()]
        notes.sort(key=lambda n: getattr(n.timestamps, "created", None) or 0)
        log.info("Keep: %d note(s) match %r", len(notes), title)
        return "\n\n".join(n.text or "" for n in notes)
