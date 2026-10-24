from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date

import pytest

from wellness import pipeline, site, warehouse
from wellness.generate import GenerateConfig, write_landing


@pytest.fixture
def built(tmp_path):
    con = warehouse.connect(tmp_path / "wh.duckdb")
    write_landing(GenerateConfig(start=date(2026, 1, 1), days=60), tmp_path / "landing")
    pipeline.run(con, tmp_path / "landing")
    yield con
    con.close()


def embedded(html: str) -> dict:
    match = re.search(r"const D = (.*?);\n", html)
    assert match, "data payload not found"
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_export_writes_a_self_contained_page(built, tmp_path):
    index = site.export_site(built, tmp_path / "site")
    html = index.read_text()
    assert (tmp_path / "site" / ".nojekyll").exists()
    assert site.PLACEHOLDER not in html
    assert "<script src=" not in html  # no external scripts
    data = embedded(html)
    assert len(data["daily"]) == 60
    assert data["daily"][0][0] == "2026-01-01"
    assert len(data["checks"]) == 13 and all(c["passed"] for c in data["checks"])
    # checks carry plain-English titles, not internal names
    assert all("_" not in c["title"] for c in data["checks"])


def test_payload_cannot_close_the_script_tag():
    html = site.render({"daily": [], "note": "</script><script>alert(1)</script>"})
    assert "</script><script>alert(1)" not in html
    assert embedded(html)["note"] == "</script><script>alert(1)</script>"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_script_is_valid_javascript(built, tmp_path):
    html = site.export_site(built, tmp_path / "site").read_text()
    script = re.search(r'<script>\n"use strict";(.*?)</script>', html, re.S).group(1)
    js = tmp_path / "page.js"
    js.write_text(script)
    subprocess.run(["node", "--check", str(js)], check=True)
