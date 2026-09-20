"""Every console template must be offline-safe: no script or link tag may
load anything over http(s) or a protocol-relative URL.  This pins the CDN
removal (the two legacy templates used to pull htmx from unpkg.com)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path("python/mql5bot/api/templates")

# src/href attribute of a <script> or <link> tag, whatever the quote style
_SCRIPT_SRC = re.compile(r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]",
                         re.IGNORECASE)
_LINK_HREF = re.compile(r"<link\b[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"]",
                        re.IGNORECASE)
_EXTERNAL = re.compile(r"^\s*(https?:)?//", re.IGNORECASE)


def _templates() -> list[Path]:
    found = sorted(TEMPLATES_DIR.glob("*.html"))
    assert found, f"no templates found under {TEMPLATES_DIR}"
    return found


@pytest.mark.parametrize("template", _templates(),
                         ids=lambda p: p.name)
def test_template_loads_nothing_external(template: Path):
    text = template.read_text(encoding="utf-8")
    urls = _SCRIPT_SRC.findall(text) + _LINK_HREF.findall(text)
    external = [u for u in urls if _EXTERNAL.match(u)]
    assert not external, (
        f"{template.name} loads external resource(s): {external} — "
        f"the console must render with no network access")
