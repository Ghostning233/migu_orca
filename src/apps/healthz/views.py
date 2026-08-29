from __future__ import annotations

"""Liveness and readiness probes (US-195).

- ``/healthz`` (liveness): the Flask process is up and serving. It performs
  no storage or external-service work, so it is safe for load balancers and
  container orchestrators to poll frequently.
- ``/readiness`` (readiness): the process is up **and** the server-side Web
  storage root is available (creatable/writable). It only touches the local
  storage layout — it never probes or writes to real MiKan, AutoBangumi,
  qBittorrent or any other external system.
"""

from flask import Blueprint, jsonify

from shared.errors import Stage1Error
from storage_engine.controllers.storage_config import (
    ensure_storage_layout,
    load_storage_config,
)

blueprint = Blueprint("healthz", __name__)


@blueprint.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "result": "ok"}


@blueprint.get("/readiness")
def readiness():
    """Report whether the app is ready to serve requests.

    The app is ready when the server-side Web storage root can be created /
    written (the default local storage directory or the deployment override).
    Failures return 503 with a stable ``{ok: false, result}`` envelope so
    orchestrators can distinguish "starting / degraded" from "down".
    """
    from apps.migu_orca_web.services import _web_storage_root

    try:
        ensure_storage_layout(load_storage_config(_web_storage_root()))
    except Stage1Error:
        return jsonify({"ok": False, "result": "storage_unavailable"}), 503
    return jsonify({"ok": True, "result": "ok"})
