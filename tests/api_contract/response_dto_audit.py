from __future__ import annotations

"""Test-time response DTO audit for ``/api/v1`` success envelopes (issue #204).

This module productizes the throwaway audit plugin from
``docs/api/response-dto-runtime-audit-172.md`` (附录 A) into the permanent
contract suite. ``tests/api_contract/conftest.py`` installs the hook for every
test in this package; the hook validates each real, route-produced JSON success
envelope (``ok is True``) against the DTO that ``openapi_gen._ENDPOINTS``
declares for that operation — i.e. it performs the ``ok_result(result, dto)``
step that no production route performs.

The response DTO whitelist deliberately never runs in production (ADR-0004), so
this hook is the only place that compares a real response with its declared
DTO. ``tests/api_contract/test_zz_response_dto_audit.py`` is the fail-closed
coverage assertion and must run after every other test of this package.
"""

from dataclasses import dataclass, field
from typing import Any

import flask
import pytest
from pydantic import BaseModel, ValidationError

from apps.migu_orca_web.openapi_gen import _ENDPOINTS


def declared_success_dtos() -> dict[str, type[BaseModel]]:
    """Return ``{endpoint key: declared success DTO}`` for the whole registry.

    Endpoints that declare ``success=None`` (the binary poster view) or a value
    that is not a pydantic model are deliberately absent: they have no JSON
    envelope contract to validate. They are not silently ignored —
    :func:`unregistered_success_declarations` proves each one either carries a
    typed DTO or an explicit ``responses`` mapping.
    """
    declared: dict[str, type[BaseModel]] = {}
    for key, entry in _ENDPOINTS.items():
        success = entry.get("success")
        if isinstance(success, type) and issubclass(success, BaseModel):
            declared[key] = success
    return declared


def unregistered_success_declarations(
    endpoints: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Return the ``_ENDPOINTS`` keys whose success shape is declared nowhere.

    A success shape is accounted for structurally: either ``success`` is a
    pydantic model, or the entry explicitly declares a non-empty ``responses``
    mapping (the binary poster shape). A bare ``success=None`` — or a non-model
    class such as ``dict`` — is unregistered, so adding one while removing a DTO
    can never keep the DTO count looking correct.
    """
    registry = _ENDPOINTS if endpoints is None else endpoints
    unregistered: list[str] = []
    for key, entry in registry.items():
        success = entry.get("success")
        if isinstance(success, type) and issubclass(success, BaseModel):
            continue
        responses = entry.get("responses")
        if success is None and isinstance(responses, dict) and responses:
            continue
        unregistered.append(key)
    return sorted(unregistered)


def _render_errors(exc: ValidationError) -> list[str]:
    rendered: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<result>"
        rendered.append(f"{location}: {error['msg']} [{error['type']}]")
    return rendered


@dataclass
class EndpointObservation:
    """What one declared endpoint produced during the audited run."""

    dto: str
    runs: int = 0
    failures: list[str] = field(default_factory=list)


class ResponseDtoAudit:
    """Accumulated per-endpoint result of the test-time DTO audit."""

    def __init__(self) -> None:
        self.declared: dict[str, type[BaseModel]] = declared_success_dtos()
        self.observations: dict[str, EndpointObservation] = {}
        #: ``/api/v1`` JSON success envelopes for keys _ENDPOINTS does not type.
        self.undeclared: dict[str, list[str]] = {}
        #: Registry keys whose success shape is declared nowhere (fail closed).
        self.unregistered: list[str] = unregistered_success_declarations()
        #: Exceptions raised inside the hook itself (never swallowed silently).
        self.hook_errors: list[str] = []

    # -- recording ---------------------------------------------------------
    def observe(self, key: str, result: Any, *, method: str, path: str) -> None:
        """Validate one real success ``result`` against its declared DTO."""
        dto = self.declared.get(key)
        if dto is None:
            self.undeclared.setdefault(key, []).append(f"{method} {path}")
            return
        observation = self.observations.setdefault(
            key, EndpointObservation(dto=dto.__name__)
        )
        observation.runs += 1
        try:
            dto.model_validate(result)
        except ValidationError as exc:
            for line in _render_errors(exc):
                if line not in observation.failures:
                    observation.failures.append(line)

    # -- fail-closed coverage ---------------------------------------------
    @property
    def missing(self) -> list[str]:
        """Declared endpoints that produced no JSON success envelope at all."""
        return sorted(set(self.declared) - set(self.observations))

    @property
    def failures(self) -> dict[str, list[str]]:
        """Declared endpoints that produced at least one invalid success result."""
        return {
            key: observation.failures
            for key, observation in sorted(self.observations.items())
            if observation.failures
        }

    def report(self) -> str:
        """A human-readable summary used as the coverage assertion message."""
        lines = [
            f"declared success DTO endpoints: {len(self.declared)}",
            f"observed: {len(self.observations)}",
        ]
        if self.unregistered:
            lines.append("endpoints whose success shape is declared nowhere:")
            lines.extend(f"  - {key}" for key in self.unregistered)
        if self.missing:
            lines.append("unobserved endpoints (fail closed):")
            lines.extend(f"  - {key}" for key in self.missing)
        for key, failures in self.failures.items():
            lines.append(f"invalid success result: {key}")
            lines.extend(f"  - {failure}" for failure in failures)
        if self.undeclared:
            lines.append("JSON success envelopes without a declared success DTO:")
            for key, occurrences in sorted(self.undeclared.items()):
                lines.append(f"  - {key} ({len(occurrences)}x, e.g. {occurrences[0]})")
        if self.hook_errors:
            lines.append("audit hook errors:")
            lines.extend(f"  - {error}" for error in self.hook_errors)
        return "\n".join(lines)


#: Process-wide recorder shared by the conftest hook and the coverage assertion.
RESPONSE_DTO_AUDIT = ResponseDtoAudit()


def install_response_dto_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the audit hook on ``Flask.process_response`` for one test.

    ``monkeypatch`` restores whatever ``process_response`` was installed before
    (normally the pristine Flask implementation), so the hook's scope is
    exactly the tests of this package — it can never leak into another suite
    running later in the same pytest session.
    """
    previous = flask.Flask.process_response

    def audited_process_response(self: flask.Flask, response: flask.Response) -> flask.Response:
        _record_response(response)
        return previous(self, response)

    monkeypatch.setattr(flask.Flask, "process_response", audited_process_response)


def _record_response(response: flask.Response) -> None:
    """Validate a ``/api/v1`` JSON success envelope; never raise."""
    try:
        rule = flask.request.url_rule
        if rule is None or not rule.rule.startswith("/api/v1/"):
            return
        payload = response.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return
        RESPONSE_DTO_AUDIT.observe(
            f"{flask.request.method} {rule.rule}",
            payload.get("result"),
            method=flask.request.method,
            path=flask.request.path,
        )
    except Exception as exc:  # never break an unrelated test; reported as fail-closed
        try:
            location = flask.request.path
        except Exception:  # no request context: report the failure without it
            location = "<no request context>"
        RESPONSE_DTO_AUDIT.hook_errors.append(f"{location}: {exc!r}")


__all__ = [
    "EndpointObservation",
    "RESPONSE_DTO_AUDIT",
    "ResponseDtoAudit",
    "declared_success_dtos",
    "install_response_dto_audit",
    "unregistered_success_declarations",
]
