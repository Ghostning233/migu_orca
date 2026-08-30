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

web_blueprint = Blueprint(
    "migu_orca_web",
    __name__,
    static_folder="static",
    static_url_path="/migu-orca-static",
    template_folder="templates",
)
