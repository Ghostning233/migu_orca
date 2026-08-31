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

from flask import Blueprint, Response, abort, render_template, send_from_directory
from werkzeug.exceptions import NotFound

# Absolute path of the Vite production build directory. Resolved once at
# import time; production deployments build the frontend before starting the
# app, so the directory exists. Tests monkeypatch ``_dist_dir`` to point at a
# fixture build or assert the placeholder path when no build is present.
_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

# Hashed Vite build assets under /app/assets/* (US-207). Vite emits content
# hashes in the filename (e.g. index-<hash>.js), so these are immutable:
# the browser may cache them indefinitely and a redeploy simply references a
# new URL. The SPA shell must never be cached (a stale index.html would pin
# old hashes), so it is served with no-cache. Only assets inside this folder
# are treated as immutable — every other /app/* path is a client-side route
# and gets the no-cache shell.
_APP_ASSETS_PREFIX = "/app/assets/"

# Cache-Control for /app/assets/* files. max-age=31536000 (1 year) matches
# the Vite recommendation for content-hashed assets; the `immutable` flag
# tells browsers/proxies the bytes never change for that URL.
_ASSETS_CACHE_CONTROL = "public, max-age=31536000, immutable"

# Cache-Control for the SPA shell and any other /app/* fallback response.
# Must revalidate so a deploy that changes the hashed asset URLs is picked up.
_SHELL_CACHE_CONTROL = "no-cache"

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
def app_shell() -> Response:
    """Serve the SPA shell at the exact ``/app/`` mount point.

    The shell is never cached (``no-cache``) so a redeploy that changes the
    hashed asset URLs is picked up immediately; the hashed assets themselves
    are served with an immutable cache header (see ``app_fallback``).
    """
    return Response(_index_html(), headers={"Cache-Control": _SHELL_CACHE_CONTROL})


@app_blueprint.get("/app/<path:subpath>")
def app_fallback(subpath: str) -> Response:
    """Serve a real build file or fall back to the SPA shell under ``/app/``.

    Files that exist inside the Vite build (hashed JS/CSS chunks, favicons)
    are served verbatim; all other ``/app/*`` paths are client-side routes
    and return the shell ``index.html``. Path traversal is blocked by the
    containment check plus ``send_from_directory``'s own guard.

    Cache headers (US-207): hashed assets under ``/app/assets/`` are
    immutable (``public, max-age=31536000, immutable``); the shell fallback
    and any other non-asset path are served with ``no-cache``.
    """
    dist = _dist_dir()
    candidate = (dist / subpath).resolve()
    try:
        candidate.relative_to(dist.resolve())
    except ValueError:
        abort(404)
    if candidate.is_file():
        try:
            response = send_from_directory(dist, subpath)
            # subpath is relative to /app/ (e.g. "assets/index-<hash>.js");
            # hashed assets under /app/assets/ are immutable, everything else
            # (any other real file) is treated like the shell (no-cache).
            request_path = f"/app/{subpath}"
            if request_path.startswith(_APP_ASSETS_PREFIX):
                response.headers["Cache-Control"] = _ASSETS_CACHE_CONTROL
            else:
                response.headers["Cache-Control"] = _SHELL_CACHE_CONTROL
            return response
        except NotFound:
            abort(404)
    return Response(_index_html(), headers={"Cache-Control": _SHELL_CACHE_CONTROL})
