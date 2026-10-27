"""The static site's own files: every icon the page or manifest points at exists."""

import json
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


def test_icons_and_manifest_exist():
    html = (SITE / "index.html").read_text()
    linked = re.findall(r'<link rel="(?:icon|apple-touch-icon|manifest)" href="([^"]+)"', html)
    assert {"icons/favicon.svg", "icons/apple-touch-icon.png", "manifest.webmanifest"} <= set(linked)
    for href in linked:
        assert (SITE / href).is_file(), href
    manifest = json.loads((SITE / "manifest.webmanifest").read_text())
    assert {"any", "maskable"} <= {i["purpose"] for i in manifest["icons"]}
    for icon in manifest["icons"]:
        assert (SITE / icon["src"]).is_file(), icon["src"]
