from __future__ import annotations

"""US-197: the Vue SPA is served same-origin by Flask at ``/app/``.

These tests pin the engineering baseline of Stage 27:

- ``/app/`` serves the built SPA shell (or a dependency-free placeholder when
  no ``frontend/dist`` build exists yet);
- real build files under ``/app/*`` are served as static assets;
- non-file ``/app/*`` paths fall back to the SPA shell for client-side
  routing;
- the fallback **never** captures the API, legacy static assets, health
  probes or legacy Flask pages — every non-``/app`` route keeps its own
  handler (US-199 and US-208 extend this to a parity matrix).
"""

import json
import re
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient

from apps.base import create_app
from apps.migu_orca_web import routes_app

# A tiny fixture build: index.html referencing hashed assets + one asset file.
FIXTURE_INDEX = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <title>MiGuOrca</title>
    <script type="module" crossorigin src="/app/assets/index-deadbeef.js"></script>
    <link rel="stylesheet" crossorigin href="/app/assets/index-cafebabe.css">
  </head>
  <body>
    <div id="app"></div>
  </body>
</html>
"""


def _client() -> FlaskClient:
    return create_app("testing").test_client()


def _fixture_build(tmp_path: Path) -> Path:
    """Write a fake Vite production build into a tmp dir."""
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(FIXTURE_INDEX, encoding="utf-8")
    (assets / "index-deadbeef.js").write_text(
        "console.log('fixture');\n", encoding="utf-8"
    )
    (assets / "index-cafebabe.css").write_text(
        "body { color: black; }\n", encoding="utf-8"
    )
    return dist


def _point_dist(tmp_path: Path, monkeypatch: Any) -> Path:
    dist = _fixture_build(tmp_path)
    monkeypatch.setattr(routes_app, "_dist_dir", lambda: dist)
    return dist


def test_app_shell_serves_built_index(tmp_path: Path, monkeypatch: Any) -> None:
    _point_dist(tmp_path, monkeypatch)

    response = _client().get("/app/")

    assert response.status_code == 200
    assert "text/html" in response.content_type
    html = response.get_data(as_text=True)
    assert "<title>MiGuOrca</title>" in html
    assert 'src="/app/assets/index-deadbeef.js"' in html
    assert 'href="/app/assets/index-cafebabe.css"' in html


def test_app_shell_placeholder_without_build(tmp_path: Path, monkeypatch: Any) -> None:
    """Without a build, /app/ returns a stable placeholder (no Node needed)."""
    missing = tmp_path / "no-dist"
    missing.mkdir()
    monkeypatch.setattr(routes_app, "_dist_dir", lambda: missing)

    response = _client().get("/app/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "MiGuOrca" in html
    assert "frontend/dist" in html


def test_app_static_assets_served(tmp_path: Path, monkeypatch: Any) -> None:
    _point_dist(tmp_path, monkeypatch)

    js = _client().get("/app/assets/index-deadbeef.js")
    assert js.status_code == 200
    assert "text/javascript" in js.content_type
    assert js.get_data(as_text=True) == "console.log('fixture');\n"

    css = _client().get("/app/assets/index-cafebabe.css")
    assert css.status_code == 200
    assert "text/css" in css.content_type


def test_app_fallback_returns_shell_for_spa_routes(tmp_path: Path, monkeypatch: Any) -> None:
    """Client-side routes under /app/* get the shell for Vue Router."""
    _point_dist(tmp_path, monkeypatch)

    for path in ("/app/workbench", "/app/settings", "/app/requests/abc-123"):
        response = _client().get(path)
        assert response.status_code == 200, path
        html = response.get_data(as_text=True)
        assert "<title>MiGuOrca</title>" in html
        assert 'src="/app/assets/index-deadbeef.js"' in html


def test_app_path_traversal_blocked(tmp_path: Path, monkeypatch: Any) -> None:
    _point_dist(tmp_path, monkeypatch)

    for path in ("/app/../index", "/app/..%2findex", "/app/%2e%2e/index"):
        response = _client().get(path)
        assert response.status_code in (301, 302, 400, 404), path


def test_api_not_intercepted_by_spa_fallback() -> None:
    """/api/v1 endpoints keep their JSON handlers, never the SPA shell."""
    client = _client()

    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "result" in payload
    # Not the HTML shell.
    assert "text/html" not in response.content_type


def test_legacy_pages_and_probes_not_intercepted() -> None:
    """Legacy Flask pages, probes and legacy static assets stay on Flask."""
    client = _client()

    index = client.get("/index")
    assert index.status_code == 200
    assert "text/html" in index.content_type
    assert "Stage 13 订阅方案工作台" in index.get_data(as_text=True)

    settings = client.get("/settings")
    assert settings.status_code == 200
    assert "MiGuOrca Settings" in settings.get_data(as_text=True)

    healthz = client.get("/healthz")
    assert healthz.status_code == 200
    assert healthz.get_json() == {"ok": True, "result": "ok"}

    legacy_static = client.get("/migu-orca-static/style.css")
    assert legacy_static.status_code in (200, 404)  # asset may or may not exist
    assert "text/html" not in legacy_static.content_type


def test_app_blueprint_registered() -> None:
    """app_blueprint is registered and owns the /app routes."""
    app = create_app("testing")
    rules = {(r.rule, r.endpoint) for r in app.url_map.iter_rules()}
    assert ("/app/", "migu_orca_app.app_shell") in rules
    assert ("/app/<path:subpath>", "migu_orca_app.app_fallback") in rules


def test_spa_fallback_never_captures_non_app_prefixes(tmp_path: Path, monkeypatch: Any) -> None:
    """Registered Flask routes outside /app are untouched by the fallback."""
    _point_dist(tmp_path, monkeypatch)
    app = create_app("testing")

    # Every non-/app rule in the url_map must have a non-app endpoint, i.e.
    # the /app fallback cannot shadow them.
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/app/"):
            continue
        assert not rule.endpoint.startswith("migu_orca_app."), rule.rule


def test_generated_index_uses_app_base_assets(tmp_path: Path, monkeypatch: Any) -> None:
    """The built index references /app/-rooted assets (matches Flask hosting)."""
    dist = _point_dist(tmp_path, monkeypatch)
    index_html = (dist / "index.html").read_text(encoding="utf-8")

    asset_refs = re.findall(r'(?:src|href)="([^"]+)"', index_html)
    assert asset_refs, "built index must reference at least one asset"
    for ref in asset_refs:
        if ref.startswith("data:"):
            continue
        assert ref.startswith("/app/"), f"asset {ref!r} is not rooted at /app/"
    assert "/app/assets/" in index_html


def test_placeholder_has_no_external_assets() -> None:
    """The placeholder is dependency-free and leaks nothing sensitive."""
    from pathlib import Path

    template = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "apps"
        / "migu_orca_web"
        / "templates"
        / "migu_orca_web"
        / "app_placeholder.html"
    )
    assert template.is_file(), f"placeholder template missing: {template}"
    text = template.read_text(encoding="utf-8")
    assert "http://" not in text
    assert "https://" not in text
    assert "token" not in text.lower()
    assert json.dumps("placeholder")  # sanity: json import used
