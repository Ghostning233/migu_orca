from __future__ import annotations

"""Stage 27 (US-197): serve the Vue SPA at ``/app/``.

The new frontend builds to ``frontend/dist/`` and is served same-origin by
Flask at ``/app/``. Vite's production ``base`` is ``/app/``, so the built
asset URLs (e.g. ``/app/assets/index-<hash>.js``) resolve under the same
origin without a Node runtime.

Fallback scope (critical): the SPA shell route at ``/app/`` and the SPA
client-side routes under ``/app/*`` must return the shell, but the fallback
must **never** capture:

- ``/api/v1/*`` (JSON API), ``/migu-orca-static/*`` (legacy static assets),
  ``/healthz``, ``/readiness`` (probes),
- the legacy Flask pages ``/index``, ``/settings`` and any other registered
  Flask route (they keep serving during the migration window; US-208 flips
  the default entry and US-209 removes them).

The ``/app/<path:subpath>`` route only matches paths under ``/app/``; every
other route is registered separately and takes precedence in Flask's URL map,
so it is never intercepted here. Real files inside the Vite build are served
as-is; anything else under ``/app/`` returns the SPA shell (client-side
routing handles the rest).
"""

from pathlib import Path

from flask import Blueprint, abort, render_template, send_from_directory
from werkzeug.exceptions import NotFound

# Absolute path of the Vite production build directory. Resolved once at
# import time; production deployments build the frontend before starting the
# app, so the directory exists. Tests monkeypatch ``_dist_dir`` to point at a
# fixture build or assert the placeholder path when no build is present.
_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

app_blueprint = Blueprint("migu_orca_app", __name__)


def _dist_dir() -> Path:
    """Return the frontend build directory (overridable for tests)."""
    return _FRONTEND_DIST


def _index_html() -> str:
    """Return the built ``index.html`` or a dependency-free placeholder."""
    index = _dist_dir() / "index.html"
    if index.is_file():
        return index.read_text(encoding="utf-8")
    # No production build present (bare checkout without `npm run build`).
    # A stable placeholder keeps the route meaningful and lets tests assert
    # the mount point without a Node build.
    return render_template("migu_orca_web/app_placeholder.html")


@app_blueprint.get("/app/")
def app_shell() -> str:
    """Serve the SPA shell at the exact ``/app/`` mount point."""
    return _index_html()


@app_blueprint.get("/app/<path:subpath>")
def app_fallback(subpath: str) -> str:
    """Serve a real build file or fall back to the SPA shell under ``/app/``.

    Files that exist inside the Vite build (hashed JS/CSS chunks, favicons)
    are served verbatim; all other ``/app/*`` paths are client-side routes
    and return the shell ``index.html``. Path traversal is blocked by the
    containment check plus ``send_from_directory``'s own guard.
    """
    dist = _dist_dir()
    candidate = (dist / subpath).resolve()
    try:
        candidate.relative_to(dist.resolve())
    except ValueError:
        abort(404)
    if candidate.is_file():
        try:
            return send_from_directory(dist, subpath)
        except NotFound:
            abort(404)
    return _index_html()
