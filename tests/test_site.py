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


def test_page_only_runs_its_own_scripts_and_talks_to_github():
    # The page holds the passphrase and, for food sync, a GitHub token.
    html = (SITE / "index.html").read_text()
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    rules = dict(r.strip().split(" ", 1) for r in csp.split(";") if r.strip())
    assert rules["script-src"] == "'self'"
    assert rules["connect-src"] == "'self' https://api.github.com"
    assert re.findall(r"<script[^>]*>", html) == ['<script src="charts.js">', '<script src="app.js">']
