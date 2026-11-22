"""Serving the SPA under any mount prefix (technical-findings §7, ADR-0009)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from oneadmin import AdminSite
from oneadmin.ui.spa import STATIC_DIR, mount_ui

# What Vite emits with `base: "./"` (see frontend/vite.config.ts).
VITE_INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Admin</title>
    <script type="module" crossorigin src="./assets/index-abc123.js"></script>
  </head>
  <body><div id="root"></div></body>
</html>"""


@pytest.fixture
def static(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(VITE_INDEX)
    (tmp_path / "assets" / "index-abc123.js").write_text("export {};")
    return tmp_path


def make_app(
    static: Path, prefix: str, *, title: str = "Shop", builtin_auth: bool = True
) -> FastAPI:
    ui = FastAPI()
    mount_ui(ui, title=title, builtin_auth=builtin_auth, static_dir=static)
    host = FastAPI()
    host.mount(prefix, ui)
    return host


async def get(app: FastAPI, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as c:
        return await c.get(path)


def config_of(page: str) -> dict[str, str]:
    match = re.search(r'<script type="application/json" id="oneadmin-config">(.*?)</script>', page)
    assert match, page
    data: dict[str, str] = json.loads(match.group(1))
    return data


@pytest.mark.parametrize("prefix", ["/admin", "/back/office"])
async def test_index_is_served_for_deep_links_with_base_and_config(
    static: Path, prefix: str
) -> None:
    app = make_app(static, prefix)
    for path in ("/", "/m/orders", "/m/orders/r/42?sort=-id"):
        r = await get(app, prefix + path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache"
        assert f'<base href="{prefix}/">' in r.text
        assert config_of(r.text) == {
            "basePath": prefix,
            "apiBase": f"{prefix}/api/v1",
            "title": "Shop",
            "auth": "builtin",
            "dev": False,
        }
        assert "<title>Shop</title>" in r.text


async def test_relative_assets_resolve_under_the_prefix_and_are_immutable(static: Path) -> None:
    app = make_app(static, "/admin")
    page = (await get(app, "/admin/m/x")).text
    src = re.search(r'src="\./(assets/[^"]+)"', page)
    assert src
    asset = await get(app, f"/admin/{src.group(1)}")  # how the browser resolves it via <base>
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert (await get(app, "/admin/assets/missing.js")).status_code == 404


async def test_config_values_cannot_break_out_of_the_script_element(static: Path) -> None:
    evil = "</script><script>alert(1)</script><title>x</title>"
    page = (await get(make_app(static, "/admin", title=evil), "/admin/")).text
    assert "<script>alert(1)" not in page
    assert config_of(page)["title"] == evil
    assert "<title>&lt;/script&gt;" in page


async def test_unknown_api_paths_are_json_404_not_the_spa(static: Path) -> None:
    r = await get(make_app(static, "/admin"), "/admin/api/v2/whatever")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_external_auth_mode_is_passed_to_the_ui(static: Path) -> None:
    page = (await get(make_app(static, "/admin", builtin_auth=False), "/admin/")).text
    assert config_of(page)["auth"] == "external"


async def test_missing_bundle_serves_an_explanatory_page(tmp_path: Path) -> None:
    r = await get(make_app(tmp_path, "/admin", title="<b>Shop</b>"), "/admin/")
    assert r.status_code == 200
    assert "UI bundle is missing" in r.text
    assert "&lt;b&gt;Shop&lt;/b&gt;" in r.text


@pytest.mark.skipif(not (STATIC_DIR / "index.html").is_file(), reason="frontend not built")
async def test_the_real_bundle_is_csp_clean_and_its_assets_resolve() -> None:
    """With the built UI: no inline script/style (CSP blocks them) and every asset loads."""
    site = AdminSite(session_factory=async_sessionmaker(), secret_key="k" * 32)
    host = FastAPI()
    site.mount(host, "/admin")
    r = await get(host, "/admin/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    without_config = re.sub(r'<script type="application/json"[^>]*>.*?</script>', "", r.text)
    for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script>", without_config, re.S):
        assert "src=" in attrs, "inline script would be blocked by the CSP"
        assert not body.strip(), "inline script would be blocked by the CSP"
    assert "<style" not in r.text
    refs = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', r.text)
    assert refs, "index.html references no assets"
    for ref in refs:
        assert (await get(host, f"/admin/{ref}")).status_code == 200, ref
