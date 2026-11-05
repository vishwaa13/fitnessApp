"""Stamp a deploy's version into the site, so browsers don't keep old files.

GitHub Pages lets browsers reuse a file for 10 minutes. Without this, opening
the dashboard right after a deploy can show the old page, or the new page with
an old script. This adds ``?v=<version>`` to every local script and stylesheet
link in index.html, records the version in a ``site-version`` meta tag, and
writes ``version.json``, which the page fetches uncached on load: if it's
newer than the page, the page reloads itself once at a fresh address.

    python -m fitapp.stamp site <version>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def stamp(site: Path, version: str) -> None:
    version = re.sub(r"[^A-Za-z0-9._-]", "", version)[:40]
    if not version:
        raise ValueError("empty version")
    index = site / "index.html"
    html = index.read_text()
    html = re.sub(r'(<(?:script|link)\b[^>]*?\b(?:src|href)=")((?!https?:|//|data:)[^"?#]+\.(?:js|css))(?:\?v=[^"]*)?(")',
                  lambda m: f"{m[1]}{m[2]}?v={version}{m[3]}", html)
    meta = f'<meta name="site-version" content="{version}">'
    html = re.sub(r'<meta name="site-version" content="[^"]*">', meta, html) if "site-version" in html \
        else html.replace("<meta charset=\"utf-8\">", "<meta charset=\"utf-8\">\n  " + meta, 1)
    index.write_text(html)
    (site / "version.json").write_text(json.dumps({"version": version}))


if __name__ == "__main__":
    stamp(Path(sys.argv[1]), sys.argv[2])
