from __future__ import annotations

"""Web/API Blueprint definitions (US-191 split).

Owning the Blueprint objects in their own module lets every domain route module
register endpoints on ``api_blueprint`` without importing ``views``, avoiding a
circular import between ``views`` (page routes + registration) and the route
modules. Blueprint names, static/template folders and registration order are
identical to the pre-split ``views.py`` so URL maps and endpoint names are
byte-for-byte compatible.
"""

from flask import Blueprint

api_blueprint = Blueprint("migu_orca_web_api", __name__)

# US-209: the legacy Jinja frontend (app.js/style.css under ``static/``) was
# removed with the Stage 27 closeout, so ``web_blueprint`` no longer serves a
# static folder or templates — the SPA is served by ``app_blueprint`` at
# ``/app/`` and the web blueprint only owns the entry redirects in views.py.
web_blueprint = Blueprint("migu_orca_web", __name__)
