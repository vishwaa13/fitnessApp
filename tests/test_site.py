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


def test_page_only_runs_its_own_scripts_and_talks_to_the_food_sheet():
    # The page holds the passphrase: only its own scripts run, and it talks only to the food sheet.
    html = (SITE / "index.html").read_text()
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    rules = dict(r.strip().split(" ", 1) for r in csp.split(";") if r.strip())
    assert rules["script-src"] == "'self'"
    assert rules["connect-src"] == "'self' https://script.google.com https://script.googleusercontent.com"
    assert re.findall(r"<script[^>]*>", html) == ['<script src="charts.js">', '<script src="lift-search.js">', '<script src="app.js">']


def test_deploy_stamps_every_local_asset_with_its_version(tmp_path):
    import shutil
    from fitapp.stamp import stamp
    site = tmp_path / "site"
    shutil.copytree(SITE, site, ignore=shutil.ignore_patterns("data"))
    stamp(site, "abc123def456")
    html = (site / "index.html").read_text()
    local = re.findall(r'(?:src|href)="((?!https?:)[^"]+\.(?:js|css)[^"]*)"', html)
    assert local and all(u.endswith("?v=abc123def456") for u in local), local
    assert 'href="https://fonts.googleapis.com/css2?family=Barlow' in html          # outside links untouched
    assert '<meta name="site-version" content="abc123def456">' in html
    assert json.loads((site / "version.json").read_text()) == {"version": "abc123def456"}
    stamp(site, "next")                                                              # a second stamp replaces, not stacks
    html = (site / "index.html").read_text()
    assert html.count('name="site-version"') == 1 and '<meta name="site-version" content="next">' in html
    assert 'src="app.js?v=next"' in html and "abc123def456" not in html
