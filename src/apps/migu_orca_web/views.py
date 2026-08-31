from __future__ import annotations

"""Page routes and Blueprint assembly for the Web app (US-191 split).

After the US-191 split, ``views.py`` keeps only the Jinja page routes and the
blueprint registration: it imports the domain route modules (which register
their endpoints on ``api_blueprint``) and re-exports the blueprints for the app
registry. Request schemas live in ``schemas.py``, response serializers in
``serializers.py``, orchestration in ``services.py``, short-lived contexts in
``contexts.py``, and Blueprint objects in ``blueprints.py``.

Stage 27 (US-197) adds the Vue SPA shell: ``routes_app.py`` owns the
``app_blueprint`` (``/app/`` shell + scoped SPA fallback) and is imported
here alongside the API route modules so its endpoints register on app
creation. The blueprint list in ``apps.migu_orca_web.__init__`` includes it.

``CandidateSelectionContextStore`` and ``candidate_selection_contexts`` are
re-exported here for backward compatibility (pre-split consumers imported them
from ``apps.migu_orca_web.views``); the canonical home is ``contexts.py``.
"""

import os

from flask import redirect, render_template, url_for

# Importing the route modules registers their endpoints on api_blueprint; the
# import side effect is intentional. Order matters only for readability, not
# for URL resolution.
from apps.migu_orca_web import (  # noqa: F401
    routes_app,
    routes_batches,
    routes_connections,
    routes_mikan,
    routes_requests,
    routes_settings,
)
from apps.migu_orca_web.blueprints import (  # noqa: F401 - api_blueprint is re-exported for apps.migu_orca_web.__init__
    api_blueprint,
    web_blueprint,
)
from apps.migu_orca_web.contexts import (  # noqa: F401
    CandidateSelectionContextStore,
    candidate_selection_contexts,
)
from apps.migu_orca_web.routes_app import app_blueprint  # noqa: F401

# ---------------------------------------------------------------------------
# Default Web entry (US-208)
# ---------------------------------------------------------------------------
# Stage 27 flips the default Web entry from the legacy Jinja pages to the Vue
# SPA at /app/. The legacy /index and /settings routes stay registered for the
# whole migration window (US-209 removes them); this flag only decides which
# page the *default* entry points serve:
#
#   - ``spa`` (default): GET / and GET /index redirect to /app/workbench (the
#     request_id/batch_id query params are preserved), GET /Settings and
#     GET /settings redirect to /app/settings. This is the production default
#     after US-208; the SPA reads request_id/batch_id from the URL itself.
#   - ``legacy``: the old behavior — GET / redirects to /index, /index and
#     /settings render the legacy Jinja pages. Used by the legacy regression
#     browser suites and by the rollback rehearsal.
#
# The switch is deployment-level (server environment only) and mirrors the
# ``MIGU_ORCA_WEB_STORAGE_ROOT`` pattern: the browser never controls it. The
# rollback rehearsal flips this flag back to ``legacy`` to prove only the page
# routes/assets change — the API and storage are untouched either way.
_LEGACY_ENTRY_ENV = "MIGU_ORCA_WEB_ENTRY_LEGACY"
_SPA_ENTRY_ENV = "MIGU_ORCA_WEB_ENTRY_SPA"


def web_entry_mode() -> str:
    """Return the active Web entry mode: ``"spa"`` (default) or ``"legacy"``.

    ``MIGU_ORCA_WEB_ENTRY_LEGACY=1`` forces the legacy Jinja entry (used by
    the legacy regression browser suites and the rollback rehearsal);
    ``MIGU_ORCA_WEB_ENTRY_SPA=1`` forces the SPA entry (default when neither
    is set). The value is read at request time so a running server can flip
    the entry without a restart (the rehearsal exercises this).
    """
    if os.environ.get(_SPA_ENTRY_ENV) == "1":
        return "spa"
    if os.environ.get(_LEGACY_ENTRY_ENV) == "1":
        return "legacy"
    return "spa"


def _index_spa_path() -> str:
    """The SPA route that replaces the legacy /index entry (US-208)."""
    return "/app/workbench"


def _settings_spa_path() -> str:
    """The SPA route that replaces the legacy /settings entry (US-208)."""
    return "/app/settings"


@web_blueprint.get("/")
def index_redirect() -> object:
    if web_entry_mode() == "legacy":
        return redirect(url_for("migu_orca_web.index"))
    return redirect(_index_spa_path())


@web_blueprint.get("/index")
def index() -> object:
    if web_entry_mode() == "legacy":
        return render_template("migu_orca_web/index.html", active_page="index")
    # SPA default entry: preserve the public request_id/batch_id query params
    # so bookmarks from the legacy UI keep working (the SPA reads them from
    # the URL query itself — RequestsView/QueueView/BatchWorkbenchView).
    return redirect(f"{_index_spa_path()}{_preserved_entry_query()}")


@web_blueprint.get("/Settings")
def settings_case_redirect() -> object:
    if web_entry_mode() == "legacy":
        return redirect(url_for("migu_orca_web.settings"))
    return redirect(_settings_spa_path())


@web_blueprint.get("/settings")
def settings() -> object:
    if web_entry_mode() == "legacy":
        return render_template("migu_orca_web/settings.html", active_page="settings")
    # The legacy /settings?request_id=<id>#auto-bangumi entry maps to the SPA
    # Settings route; the SPA reads request_id from the URL query and renders
    # the AB panel on the same page (the #auto-bangumi anchor is a no-op).
    return redirect(f"{_settings_spa_path()}{_preserved_entry_query()}")


def _preserved_entry_query() -> str:
    """Return ``?request_id=...&batch_id=...`` from the current request query.

    Only the two public, already-saved identifiers are forwarded to the SPA —
    never credentials, endpoints or storage paths (US-193/199 boundaries).
    """
    from urllib.parse import urlencode

    from flask import request

    forwarded: dict[str, str] = {}
    for key in ("request_id", "batch_id"):
        value = request.args.get(key, "").strip()
        if value:
            forwarded[key] = value
    return f"?{urlencode(forwarded)}" if forwarded else ""
