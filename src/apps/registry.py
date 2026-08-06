from __future__ import annotations

from apps.healthz import blueprints as healthz_blueprints
from apps.migu_orca_web import blueprints as migu_orca_web_blueprints

ALL_BLUEPRINTS = [
    *healthz_blueprints,
    *migu_orca_web_blueprints,
]
