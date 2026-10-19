"""Serving the built frontend, the production headers and the client-IP diagnostics."""

import logging

import httpx
import pytest

from app.core.clientip import CHECKED_REQUESTS, mask_ip
from app.core.settings import Settings
from app.main import create_app
from tests.conftest import MOCK_AGENTS, demo_factory


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "showcase").mkdir()
    (root / "index.html").write_text("<!doctype html><title>Tribunal</title>", encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (root / "showcase" / "index.json").write_text('{"format": 1}', encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the build", encoding="utf-8")
    return root


@pytest.fixture
async def web(tmp_path, dist):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'web.db'}",
        agents_config=MOCK_AGENTS,
        frontend_dist=dist,
        _env_file=None,
    )
    app = create_app(settings, demo_factory())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_index_and_spa_fallback_for_shared_links(web):
    for path in ("/", "/history", "/debate/abc-123", "/showcase/some-slug"):
        r = await web.get(path)
        assert r.status_code == 200 and "<title>Tribunal</title>" in r.text, path
        assert r.headers["cache-control"] == "no-cache"


async def test_built_files_are_served_with_the_right_caching(web):
    hashed = await web.get("/assets/index-abc123.js")
    assert hashed.status_code == 200 and "immutable" in hashed.headers["cache-control"]
    showcase = await web.get("/showcase/index.json")  # static data shipped in the image
    assert showcase.json() == {"format": 1}
    assert showcase.headers["cache-control"] == "no-cache"


async def test_missing_files_and_unknown_api_paths_are_404_not_the_html_shell(web):
    for path in ("/assets/nope.js", "/favicon.ico", "/api/nope", "/api/debates/x/y/z"):
        r = await web.get(path)
        assert r.status_code == 404 and "<title>" not in r.text, path
    assert (await web.get("/api/nope")).json() == {"detail": "not found"}


async def test_api_routes_still_win_over_the_fallback(web):
    assert (await web.get("/api/health")).json() == {"status": "ok"}
    assert (await web.get("/api/debates")).json() == []
    assert (await web.get("/api/debates/does-not-exist")).status_code == 404


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/..%2fsecret.txt"]
)
async def test_path_traversal_cannot_leave_the_build_folder(web, path):
    r = await web.get(path)
    assert "outside the build" not in r.text


async def test_security_headers_on_pages_and_api(web):
    for path in ("/", "/api/health", "/assets/index-abc123.js", "/api/nope"):
        h = (await web.get(path)).headers
        assert h["x-content-type-options"] == "nosniff", path
        assert h["referrer-policy"] == "same-origin", path
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
        assert "object-src 'none'" in csp
        # Vite inlines small fonts as data: URIs; found by loading the built app in a browser.
        assert "font-src 'self' data:" in csp
        # The Space page frames the app; nothing else may.
        assert "frame-ancestors 'self' https://huggingface.co https://*.hf.space" in csp
        assert "x-frame-options" not in h
        assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


async def test_no_cors_headers_even_for_a_cross_origin_request(web):
    r = await web.get("/api/health", headers={"origin": "https://evil.example"})
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]
    pre = await web.options(
        "/api/debates",
        headers={"origin": "https://evil.example", "access-control-request-method": "POST"},
    )
    assert not [h for h in pre.headers if h.lower().startswith("access-control-")]


async def test_no_frontend_is_served_when_there_is_no_build(make_client):
    async with make_client() as (client, _):  # the shared fixture has no frontend_dist
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/api/health")).status_code == 200


# --- client-IP diagnostics ---


def test_mask_ip_keeps_enough_to_tell_devices_apart_but_not_the_address():
    assert mask_ip("203.0.113.77") == "203.0.113.0"
    assert mask_ip("2001:db8:85a3:8d3:1319:8a2e:370:7348") == "2001:0db8:85a3::"
    assert mask_ip(None) == "-" and mask_ip("not an ip") == "<invalid>"


async def test_client_ip_probe_logs_the_first_requests_masked_then_stops(tmp_path, dist, caplog):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'ip.db'}",
        agents_config=MOCK_AGENTS,
        frontend_dist=dist,
        trusted_proxy=1,
        _env_file=None,
    )
    app = create_app(settings, demo_factory())
    caplog.set_level(logging.INFO, logger="app.clientip")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("10.20.30.40", 5555))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/health")  # the health check is never counted
            for _ in range(CHECKED_REQUESTS + 3):
                await client.get("/", headers={"x-forwarded-for": "198.51.100.9, 10.1.2.3"})
    records = [r for r in caplog.records if r.name == "app.clientip"]
    assert len(records) == CHECKED_REQUESTS
    first = records[0]
    assert first.peer == "10.20.30.0" and first.xff_entries == 2
    assert first.xff == ["198.51.100.0", "10.1.2.0"]
    assert first.trusted_proxy == 1 and first.resolved == "10.1.2.0"  # the Nth entry from the right
    logged = " ".join(str(vars(r)) for r in records)
    assert "198.51.100.9" not in logged and "10.20.30.40" not in logged
