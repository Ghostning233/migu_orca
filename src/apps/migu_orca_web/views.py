from __future__ import annotations

"""Page routes and Blueprint assembly for the Web app (US-191 split).

After the US-191 split, ``views.py`` keeps only the Jinja page routes and the
blueprint registration: it imports the domain route modules (which register
their endpoints on ``api_blueprint``) and re-exports the blueprints for the app
registry. Request schemas live in ``schemas.py``, response serializers in
``serializers.py``, orchestration in ``services.py``, short-lived contexts in
``contexts.py``, and Blueprint objects in ``blueprints.py``.

``CandidateSelectionContextStore`` and ``candidate_selection_contexts`` are
re-exported here for backward compatibility (pre-split consumers imported them
from ``apps.migu_orca_web.views``); the canonical home is ``contexts.py``.
"""

from flask import redirect, render_template, url_for

# Importing the route modules registers their endpoints on api_blueprint; the
# import side effect is intentional. Order matters only for readability, not
# for URL resolution.
from apps.migu_orca_web import (  # noqa: F401
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


@web_blueprint.get("/")
def index_redirect() -> object:
    return redirect(url_for("migu_orca_web.index"))


@web_blueprint.get("/index")
def index() -> str:
    return render_template("migu_orca_web/index.html", active_page="index")


@web_blueprint.get("/Settings")
def settings_case_redirect() -> object:
    return redirect(url_for("migu_orca_web.settings"))


@web_blueprint.get("/settings")
def settings() -> str:
    return render_template("migu_orca_web/settings.html", active_page="settings")
