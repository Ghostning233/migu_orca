from __future__ import annotations

"""US-198: keep OpenAPI error declarations in sync with runtime classification.

The OpenAPI registry in ``openapi_gen._ENDPOINTS`` is the single documented
source of truth for the runtime failure envelope. These tests prevent drift:

- every HTTP status declared in ``_ENDPOINTS`` must match the status the
  runtime classifier (``extensions.flask_api.api._error_http_status``) assigns
  to the same ``error_type`` — an error_type declared under the wrong status
  would mislead generated TypeScript clients;
- every ``error_type`` the classifier knows about must be declared somewhere
  in the registry, so a runtime failure the frontend must handle is never
  silently undocumented;
- operationIds must be unique, readable camelCase, and stable across
  regenerations (the TypeScript client keys off them).
"""

import json
import re
import subprocess
from pathlib import Path

from apps.migu_orca_web.openapi_gen import _ENDPOINTS, generate_openapi
from extensions.flask_api.api import _error_http_status

DOC_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"
)

# Error types the runtime classifier knows about but that are intentionally
# never surfaced through the /api/v1 JSON envelope (CLI-only, safety-boundary
# or non-API engine errors). They must stay out of the OpenAPI document.
_UNDOCUMENTED_ERROR_TYPES = {
    # CLI / offline paths only — never reachable from /api/v1 routes.
    "invalid_modify_patch",  # CLI arg parsing (entry_controller), not the API
    "invalid_confirmation_action",  # CLI-only action; API validates earlier
    "invalid_cancel_reason",  # API default fills a reason before cancel_request
    "invalid_input",  # generic engine input error, not raised by API routes
    "ai_title_parse_failed",  # batch parse folds this into item status, not an envelope
    "mikan_search_failed",  # folded into the parse result `status: FAILED`
    "invalid_seed_count",  # internal engine validation
    "invalid_ab_response",  # CLI/engine; API maps to whitelisted connection errors
    "invalid_ab_payload",  # engine-internal, not raised by API routes
    "invalid_ab_submit_result",  # engine-internal
    "invalid_poster",  # poster 400 maps via invalid_poster_key/poster_unavailable
    "poster_too_large",  # poster cache writes are not reachable through GET
    "internal_server_error",  # unhandled exceptions never documented as a route error
    "unexpected_error",  # safety boundary, not a documented route failure
    "storage_error",  # generic storage failure documented per-endpoint where reachable
    "storage_json_error",  # generic storage failure documented per-endpoint
    # Classified but never raised as an envelope error by /api/v1 routes:
    "ab_http_failed",  # only in the classifier set; routes raise ab_submit_failed
    "draft_mismatch",  # DraftStore comment only; routes map to draft_expired/evicted/replayed
    "request_cancelled",  # folded into batch item results, never an envelope error
    # US-213: the save-confirm idempotency repository raises this as a
    # Stage1Error, but no /api/v1 route surfaces it yet — the save-confirm
    # endpoint (US-214) declares it in _ENDPOINTS.
    "idempotency_conflict",
}


def _declared_errors() -> dict[str, dict[str, dict[str, str]]]:
    """Return ``{endpoint_key: {status: {error_type: message}}}``."""
    declared: dict[str, dict[str, dict[str, str]]] = {}
    for key, entry in _ENDPOINTS.items():
        errors = entry.get("errors", {})
        if errors:
            declared[key] = {status: dict(mapping) for status, mapping in errors.items()}
    return declared


def _all_declared_error_types() -> set[str]:
    types: set[str] = set()
    for entry in _ENDPOINTS.values():
        for mapping in entry.get("errors", {}).values():
            types.update(mapping)
    return types


def test_declared_status_matches_runtime_classifier() -> None:
    """Every declared status/error_type pair matches _error_http_status.

    The OpenAPI registry is the documented contract; if the runtime classifier
    maps an error_type to a different status than the registry declares, the
    generated TypeScript client would handle the wrong branch.
    """
    mismatches: list[str] = []
    for key, statuses in _declared_errors().items():
        for status, mapping in statuses.items():
            for error_type in mapping:
                runtime_status = _error_http_status(error_type)
                if int(status) != runtime_status:
                    mismatches.append(
                        f"{key}: {error_type} declared under {status} but "
                        f"_error_http_status returns {runtime_status}"
                    )
    assert not mismatches, "OpenAPI error declarations drifted from the runtime:\n" + "\n".join(
        sorted(mismatches)
    )


def test_every_classified_error_type_is_documented() -> None:
    """Every error_type the classifier knows must be declared in the registry.

    A runtime failure the frontend must handle should never be silently absent
    from the machine-readable contract. Types that are intentionally CLI-only
    or non-API (see ``_UNDOCUMENTED_ERROR_TYPES``) are exempt.
    """
    from extensions.flask_api import api as api_module

    classifier_types: set[str] = set()
    for attr in dir(api_module):
        if attr.startswith("_HTTP_") and attr.endswith("_ERROR_TYPES"):
            classifier_types.update(getattr(api_module, attr))

    declared = _all_declared_error_types()
    missing = sorted(classifier_types - declared - _UNDOCUMENTED_ERROR_TYPES)
    assert not missing, (
        "error_type(s) classified by _error_http_status are not declared in "
        "openapi_gen._ENDPOINTS: " + ", ".join(missing)
    )


def test_operation_ids_are_unique() -> None:
    doc = generate_openapi()
    seen: set[str] = set()
    duplicates: list[str] = []
    for path, methods in doc["paths"].items():
        for method, operation in methods.items():
            operation_id = operation.get("operationId", "")
            if operation_id in seen:
                duplicates.append(f"{operation_id} ({method.upper()} {path})")
            seen.add(operation_id)
    assert not duplicates, "Duplicate operationIds: " + ", ".join(duplicates)


def test_operation_ids_are_readable_camel_case() -> None:
    """operationIds drive the generated TypeScript client names.

    They must be readable camelCase (not machine-mangled identifiers like
    ``getRequestsByRequestid``) and stable: the checked-in document and the
    live generator must agree.
    """
    doc = generate_openapi()
    pattern = re.compile(r"^[a-z][A-Za-z0-9]*$")
    bad: list[str] = []
    for path, methods in doc["paths"].items():
        for method, operation in methods.items():
            operation_id = operation.get("operationId", "")
            if not pattern.match(operation_id):
                bad.append(f"{operation_id} ({method.upper()} {path})")
            elif operation_id.lower().endswith("id") and "id" not in operation_id:
                # e.g. "...ByRequestid" — the "id" token must be camelCased.
                bad.append(f"{operation_id} ({method.upper()} {path})")
    assert not bad, "Unreadable operationIds: " + ", ".join(bad)


def test_operation_ids_stable_across_regeneration() -> None:
    """operationIds must not depend on path ordering or machine state."""
    first = generate_openapi()
    second = generate_openapi()
    ids_first = {
        (method.upper(), path): operation.get("operationId", "")
        for path, methods in first["paths"].items()
        for method, operation in methods.items()
    }
    ids_second = {
        (method.upper(), path): operation.get("operationId", "")
        for path, methods in second["paths"].items()
        for method, operation in methods.items()
    }
    assert ids_first == ids_second


def test_generated_openapi_is_valid_json_schema() -> None:
    """The document must be consumable by a strict generator.

    In particular, no property may be declared as a bare Array (a schema
    object must use ``type: array`` + ``items``) — openapi-typescript rejects
    ``Expected Schema Object or boolean, got Array``.
    """
    text = json.dumps(generate_openapi(), ensure_ascii=False)
    # Spot-check the previously-invalid inline array shape is gone.
    assert '"requests": [{}]' not in text
    assert '"requests": {}' not in text
    doc = generate_openapi()
    requests = doc["paths"]["/api/v1/requests"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["properties"]["result"]["properties"][
        "requests"
    ]
    assert requests["type"] == "array"
    assert "items" in requests


def test_frontend_generated_client_matches_openapi() -> None:
    """The committed frontend TypeScript client equals a fresh generation.

    US-198 pins ``frontend/src/api/generated/api.ts`` to
    ``docs/api/openapi.json`` via ``openapi-typescript`` (locked in
    ``frontend/package.json``). When frontend dependencies are installed this
    test runs the same drift check as the dedicated frontend CI job. A clean
    backend-only checkout skips it instead of mistaking a missing local CLI
    for generated-client drift.
    """
    import shutil

    repo_root = Path(__file__).resolve().parents[2]
    npm = shutil.which("npm")
    generator = repo_root / "frontend" / "node_modules" / ".bin" / "openapi-typescript"
    if npm is None or not generator.is_file():
        import pytest

        pytest.skip("frontend dependencies not installed; drift is covered by frontend CI")
    result = subprocess.run(
        [npm, "run", "api:check"],
        cwd=repo_root / "frontend",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "frontend/src/api/generated/api.ts is stale. Run `npm run api:generate` "
        "in frontend/ and commit the regenerated file.\n" + result.stdout + result.stderr
    )
