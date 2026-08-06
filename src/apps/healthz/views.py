from __future__ import annotations

from flask import Blueprint

blueprint = Blueprint("healthz", __name__)


@blueprint.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "result": "ok"}


@blueprint.get("/readiness")
def readiness() -> dict[str, object]:
    return {"ok": True, "result": "ok"}
