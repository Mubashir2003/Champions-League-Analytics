"""Static checks on the frontend: UI restrictions, secrets, JS syntax."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
TEXT_FILES = [p for p in FRONTEND.rglob("*") if p.suffix in {".html", ".js", ".css"}]
HTML = {p.name: p.read_text(encoding="utf-8") for p in FRONTEND.glob("*.html")}

FORBIDDEN = [
    "stadium", "referee", "source: pitchapi", "not yet verified", "score: not available",
    "result verification", "data connections", "pitchapi", "strikerapi", "api docs",
    "not affiliated with or endorsed by uefa", "fixtures and post-match statistics from",
    "predictions come from an experimental statistical model",
]


def test_no_forbidden_or_technical_text_in_ui():
    for path in TEXT_FILES:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in text, f"'{phrase}' found in {path.name}"


def test_no_credentials_in_frontend():
    pattern = re.compile(r"(api[_-]?key|x-api-key|pk_live|pk_test|sk_test|STRIKERAPI|PITCHAPI)", re.I)
    for path in TEXT_FILES:
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_navigation_has_exactly_three_items_and_no_predictions_page():
    for name, html in HTML.items():
        nav = re.search(r'<nav class="main-nav".*?</nav>', html, re.S).group(0)
        labels = re.findall(r">([^<]+)</a>", nav)
        assert labels == ["Overview", "Fixtures", "Standings"], name
    assert not (FRONTEND / "predictions.html").exists()


def test_overview_copy_and_buttons():
    html = HTML["index.html"]
    assert re.search(r"<h1>Champions League<span class=\"dot\">·</span><span class=\"accent\">Analytics</span></h1>", html)
    assert '<p class="subtitle">Match intelligence for Europe\'s elite club competition.</p>' in html
    assert '<p class="tagline">Get Analytical view of Europe\'s Biggest Competition all in one place.</p>' in html
    assert html.count('href="/fixtures.html?view=upcoming">View Upcoming Fixtures') == 2
    assert 'href="/fixtures.html?view=completed">View Completed Results' in html
    css = (FRONTEND / "css" / "style.css").read_text()
    assert re.search(r"\.hero \.subtitle \{[^}]*font-style: italic;[^}]*font-weight: 400", css)
    assert re.search(r"\.hero \.tagline \{[^}]*font-style: italic;[^}]*font-weight: 400", css)
    assert "MAX_RECENT = 5" in (FRONTEND / "js" / "overview.js").read_text()


def test_all_internal_links_resolve():
    targets = set()
    for html in HTML.values():
        targets.update(re.findall(r'(?:href|src)="(/[^"?#]*)', html))
    for t in targets:
        if t == "/":
            continue
        assert (FRONTEND / t.lstrip("/")).exists(), t


def test_theme_persistence_wired_on_every_page():
    for name, html in HTML.items():
        assert 'localStorage.getItem("ucl-theme")' in html, name
        assert 'class="theme-toggle"' in html, name
    app = (FRONTEND / "js" / "app.js").read_text()
    assert "localStorage.setItem(THEME_KEY" in app


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_javascript_syntax():
    for js in (FRONTEND / "js").glob("*.js"):
        result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert result.returncode == 0, f"{js.name}: {result.stderr}"
