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

Stage 27 closeout (US-209): the legacy Jinja pages (``/index``, ``/settings``)
were removed together with the old ``app.js`` frontend. The default entry
routes now always redirect to the SPA — ``/`` and ``/index`` go to
``/app/add`` (preserving only ``batch_id``), ``/Settings`` and ``/settings``
go to ``/app/settings`` (preserving only ``request_id``). The
``MIGU_ORCA_WEB_ENTRY_LEGACY`` rollback switch from US-208 is gone with the
legacy pages it served.

``CandidateSelectionContextStore`` and ``candidate_selection_contexts`` are
re-exported here for backward compatibility (pre-split consumers imported them
from ``apps.migu_orca_web.views``); the canonical home is ``contexts.py``.
"""

import re

from flask import redirect

# Importing the route modules registers their endpoints on api_blueprint; the
# import side effect is intentional. Order matters only for readability, not
# for URL resolution.
from apps.migu_orca_web import (  # noqa: F401
    routes_app,
    routes_batches,
    routes_mikan,
    routes_requests,
    routes_settings,
    routes_tracking,
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
# Default Web entry (US-209)
# ---------------------------------------------------------------------------
# The legacy Jinja pages are gone; every entry route redirects to the SPA.
# Only the two public, already-saved identifiers are forwarded to the SPA —
# never credentials, endpoints or storage paths (US-193/199 boundaries).

_INDEX_SPA_PATH = "/app/add"
_SETTINGS_SPA_PATH = "/app/settings"
_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _preserved_entry_query(key: str) -> str:
    """Return one non-empty scalar public identifier from the entry query.

    Each destination owns exactly one public locator. Duplicate values are
    rejected rather than silently interpreted differently by Flask and Vue.
    """
    from urllib.parse import urlencode

    from flask import request

    values = request.args.getlist(key)
    if len(values) != 1:
        return ""
    value = values[0].strip()
    return f"?{urlencode({key: value})}" if _PUBLIC_IDENTIFIER.fullmatch(value) else ""


@web_blueprint.get("/")
def index_redirect() -> object:
    # The root entry is as bookmarkable as /index and must preserve the same
    # public identifiers while dropping every sensitive query value.
    return redirect(f"{_INDEX_SPA_PATH}{_preserved_entry_query('batch_id')}")


@web_blueprint.get("/index")
def index() -> object:
    # Preserve only the batch locator consumed by the add workbench.
    return redirect(f"{_INDEX_SPA_PATH}{_preserved_entry_query('batch_id')}")


@web_blueprint.get("/Settings")
def settings_case_redirect() -> object:
    return redirect(f"{_SETTINGS_SPA_PATH}{_preserved_entry_query('request_id')}")


@web_blueprint.get("/settings")
def settings() -> object:
    # The legacy /settings?request_id=<id>#auto-bangumi entry maps to the SPA
    # Settings route; the SPA reads request_id from the URL query and renders
    # the AB panel on the same page (the #auto-bangumi anchor is a no-op).
    return redirect(f"{_SETTINGS_SPA_PATH}{_preserved_entry_query('request_id')}")
