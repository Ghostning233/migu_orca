from __future__ import annotations

from apps.migu_orca_web.routes_app import app_blueprint
from apps.migu_orca_web.views import api_blueprint, web_blueprint

blueprints = [web_blueprint, api_blueprint, app_blueprint]
