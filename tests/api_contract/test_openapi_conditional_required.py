from __future__ import annotations

"""Issue #203: cross-field ("conditional required") request constraints.

``delete-plan`` / ``recover`` / ``resubmit`` enforce extra rules in
``model_validator``s that pydantic cannot project into JSON Schema.  They are
published as *reviewed merge refinements*: a JSON-Schema ``if``/``then`` (plus
``else`` when the other branch forbids the fields) appended to the derived body
node.  These tests pin

- the exact published node (so a reviewer sees what the client will read);
- the merge-refinement guard: only constraint-composition keys may be appended,
  and a merge may never invent or restate a property;
- fail-closed behaviour for an unregistered merge refinement;
- the 400/404 answer of the real route for the same body, so the projection
  cannot drift away from the validator that actually runs.
"""

from typing import Any

import pytest

from apps.migu_orca_web import openapi_gen
from apps.migu_orca_web.openapi_gen import (
    _ENDPOINTS,
    generate_openapi,
)
from apps.migu_orca_web.schemas import SavedTrackingPlanDeleteInput

DELETE_PLAN = "/api/v1/tracking/items/{tracking_id}/delete-plan"
RECOVER = "/api/v1/tracking/items/{tracking_id}/recover"
RESUBMIT = "/api/v1/tracking/items/{tracking_id}/resubmit"
REF = "11111111-1111-4111-8111-111111111111"
OP_ID = "op_abc123"
TRACKING_ID = "trk-203"
CONDITIONAL_KEYS = ("if", "then", "else")


def _body_schema(path: str, method: str = "post") -> dict[str, Any]:
    doc = generate_openapi()
    return doc["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]


def _conditional_fragment(path: str) -> dict[str, Any]:
    schema = _body_schema(path)
    return {key: schema[key] for key in CONDITIONAL_KEYS if key in schema}


def _satisfies(node: Any, body: Any) -> bool:
    """Evaluate the conditional keywords used by the #203 refinements.

    Deliberately small: it understands ``if``/``then``/``else``, ``required``,
    ``properties``, ``const``, ``enum``, ``not``, ``anyOf`` and ``allOf`` — i.e.
    exactly the vocabulary the reviewed fragments use.  Types/minimum are out of
    scope (they come from the model and are not part of the projection under
    test).
    """
    if not isinstance(node, dict):
        return True
    if "if" in node:
        branch = "then" if _satisfies(node["if"], body) else "else"
        if branch in node:
            return _satisfies(node[branch], body)
        return True
    if "const" in node and body != node["const"]:
        return False
    if "enum" in node and body not in node["enum"]:
        return False
    if "required" in node and (
        not isinstance(body, dict) or any(name not in body for name in node["required"])
    ):
        return False
    if "properties" in node:
        if not isinstance(body, dict):
            return False
        for name, child in node["properties"].items():
            if name in body and not _satisfies(child, body[name]):
                return False
    if "not" in node and _satisfies(node["not"], body):
        return False
    if "anyOf" in node and not any(_satisfies(branch, body) for branch in node["anyOf"]):
        return False
    return not (
        "allOf" in node and not all(_satisfies(item, body) for item in node["allOf"])
    )


# ---------------------------------------------------------------------------
# Published shape (what the generated client and the reviewer read)
# ---------------------------------------------------------------------------


def test_delete_plan_documents_when_the_connection_is_required() -> None:
    """``delete_external=true`` needs the saved connection; ``false`` never forbids it."""
    schema = _body_schema(DELETE_PLAN)
    assert schema["if"] == {
        "properties": {"delete_external": {"const": True}},
        "required": ["delete_external"],
    }
    assert schema["then"] == {"required": ["connection_ref", "configuration_revision"]}
    # The model keeps both fields optional when the delete stays local, so an
    # ``else`` here would publish a constraint the validator does not enforce.
    assert "else" not in schema
    # The derived base is untouched: path param dropped, model required kept.
    assert schema["required"] == ["confirm", "idempotency_key"]
    assert set(schema["properties"]) == {
        "confirm",
        "delete_external",
        "idempotency_key",
        "connection_ref",
        "configuration_revision",
        "storage_dir",
    }


def test_recover_documents_both_branches() -> None:
    """``VERIFY_EXTERNAL`` requires the connection; every other action forbids it."""
    schema = _body_schema(RECOVER)
    assert schema["if"] == {
        "properties": {"action": {"const": "VERIFY_EXTERNAL"}},
        "required": ["action"],
    }
    assert schema["then"] == {"required": ["connection_ref", "configuration_revision"]}
    assert schema["else"] == {
        "not": {
            "anyOf": [
                {"required": ["connection_ref"]},
                {"required": ["configuration_revision"]},
            ]
        }
    }


def test_resubmit_documents_both_branches() -> None:
    """``confirm=true`` requires the published binding; the read-only stage forbids it."""
    schema = _body_schema(RESUBMIT)
    assert schema["if"] == {
        "properties": {"confirm": {"const": True}},
        "required": ["confirm"],
    }
    assert schema["then"] == {"required": ["previous_operation_id", "connection_ref"]}
    assert schema["else"] == {
        "not": {
            "anyOf": [
                {"required": ["previous_operation_id"]},
                {"required": ["connection_ref"]},
            ]
        }
    }


def test_conditional_rules_do_not_change_the_generated_types() -> None:
    """The projection is documentation: ``properties``/``required`` stay model-derived."""

    def structural(node: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in node.items() if key not in {"description", "example"}}

    assert structural(_body_schema(DELETE_PLAN)["properties"]["connection_ref"]) == {
        "type": ["string", "null"],
        "format": "uuid",
    }
    assert structural(_body_schema(RECOVER)["properties"]["configuration_revision"]) == {
        "type": ["integer", "null"],
        "minimum": 0,
    }
    assert structural(_body_schema(RESUBMIT)["properties"]["previous_operation_id"]) == {
        "type": ["string", "null"]
    }


# ---------------------------------------------------------------------------
# Runtime comparison: the documented verdict must equal the route's 400 answer
# ---------------------------------------------------------------------------


def _request_path(openapi_path: str) -> str:
    return openapi_path.replace("{tracking_id}", TRACKING_ID)


_RUNTIME_CASES = [
    pytest.param(
        DELETE_PLAN,
        {"confirm": True, "delete_external": True, "idempotency_key": "k-1"},
        id="delete-plan-external-without-connection",
    ),
    pytest.param(
        DELETE_PLAN,
        {
            "confirm": True,
            "delete_external": True,
            "idempotency_key": "k-1",
            "connection_ref": REF,
            "configuration_revision": 1,
        },
        id="delete-plan-external-with-connection",
    ),
    pytest.param(
        DELETE_PLAN,
        {"confirm": True, "delete_external": False, "idempotency_key": "k-1"},
        id="delete-plan-local-only",
    ),
    pytest.param(
        DELETE_PLAN,
        {
            "confirm": True,
            "delete_external": False,
            "idempotency_key": "k-1",
            "connection_ref": REF,
            "configuration_revision": 1,
        },
        id="delete-plan-local-carrying-connection",
    ),
    pytest.param(
        RECOVER,
        {"expected_revision": 1, "action": "VERIFY_EXTERNAL"},
        id="recover-verify-external-without-connection",
    ),
    pytest.param(
        RECOVER,
        {
            "expected_revision": 1,
            "action": "VERIFY_EXTERNAL",
            "connection_ref": REF,
            "configuration_revision": 1,
        },
        id="recover-verify-external-with-connection",
    ),
    pytest.param(RECOVER, {"expected_revision": 1, "action": "AUTO"}, id="recover-local"),
    pytest.param(
        RECOVER,
        {"expected_revision": 1, "action": "AUTO", "connection_ref": REF},
        id="recover-local-carrying-connection-ref",
    ),
    pytest.param(
        RECOVER,
        {"expected_revision": 1, "action": "AUTO", "configuration_revision": 1},
        id="recover-local-carrying-configuration-revision",
    ),
    pytest.param(
        RESUBMIT, {"expected_revision": 1, "confirm": False}, id="resubmit-read-only"
    ),
    pytest.param(
        RESUBMIT,
        {"expected_revision": 1, "confirm": False, "previous_operation_id": OP_ID},
        id="resubmit-read-only-carrying-operation-id",
    ),
    pytest.param(
        RESUBMIT,
        {"expected_revision": 1, "confirm": False, "connection_ref": REF},
        id="resubmit-read-only-carrying-connection",
    ),
    pytest.param(
        RESUBMIT,
        {"expected_revision": 1, "confirm": True},
        id="resubmit-confirm-without-binding",
    ),
    pytest.param(
        RESUBMIT,
        {
            "expected_revision": 1,
            "confirm": True,
            "previous_operation_id": OP_ID,
            "connection_ref": REF,
        },
        id="resubmit-confirm-with-binding",
    ),
]


@pytest.mark.parametrize("openapi_path, body", _RUNTIME_CASES)
def test_documented_condition_matches_the_running_validator(
    client: Any, openapi_path: str, body: dict[str, Any]
) -> None:
    """Same body: documented verdict == (route did not answer 400).

    A satisfied body reaches the service and fails later on the missing record
    (404); a violated body is rejected by the validator (400).
    """
    response = client.post(_request_path(openapi_path), json=body)
    assert response.status_code in {400, 404}, response.get_json()
    documented_ok = _satisfies(_conditional_fragment(openapi_path), body)
    runtime_ok = response.status_code != 400
    assert documented_ok == runtime_ok, (
        f"{openapi_path} {body}: documented_ok={documented_ok} but runtime={response.status_code}"
    )


#: ``required`` only sees whether a key exists, while the validators compare the
#: *value* to ``None``.  JSON Schema cannot express "present and non-null"
#: without restating property structure, which #203 forbids in a merge
#: refinement; the divergence is frozen here and explained in ADR-0003.
_NULL_DIVERGENCE_CASES = [
    pytest.param(
        RECOVER,
        {"expected_revision": 1, "action": "AUTO", "configuration_revision": None},
        404,
        id="recover-local-configuration-revision-null",
    ),
    pytest.param(
        RECOVER,
        {"expected_revision": 1, "action": "AUTO", "connection_ref": None},
        404,
        id="recover-local-connection-ref-null",
    ),
    pytest.param(
        RECOVER,
        {
            "expected_revision": 1,
            "action": "VERIFY_EXTERNAL",
            "connection_ref": None,
            "configuration_revision": 1,
        },
        400,
        id="recover-verify-external-connection-ref-null",
    ),
    pytest.param(
        DELETE_PLAN,
        {
            "confirm": True,
            "delete_external": True,
            "idempotency_key": "k-1",
            "connection_ref": REF,
            "configuration_revision": None,
        },
        400,
        id="delete-plan-external-configuration-revision-null",
    ),
    pytest.param(
        RESUBMIT,
        {
            "expected_revision": 1,
            "confirm": True,
            "previous_operation_id": OP_ID,
            "connection_ref": None,
        },
        400,
        id="resubmit-confirm-connection-ref-null",
    ),
    pytest.param(
        RESUBMIT,
        {
            "expected_revision": 1,
            "confirm": True,
            "previous_operation_id": None,
            "connection_ref": REF,
        },
        400,
        id="resubmit-confirm-previous-operation-id-null",
    ),
    pytest.param(
        RESUBMIT,
        {"expected_revision": 1, "confirm": False, "previous_operation_id": None},
        404,
        id="resubmit-read-only-previous-operation-id-null",
    ),
]


@pytest.mark.parametrize("openapi_path, body, expected_status", _NULL_DIVERGENCE_CASES)
def test_explicit_null_is_a_frozen_documented_divergence(
    client: Any, openapi_path: str, body: dict[str, Any], expected_status: int
) -> None:
    """Explicit ``null`` vs "absent" is the one place the projection is inexact.

    A ``null`` value satisfies ``required`` (the key exists) but the validator
    compares the value to ``None``.  This pins a *representative* direction for
    each endpoint family instead of silently pretending the document is exact;
    the remaining null shapes are listed in ADR-0003 as known and unfrozen.
    """
    response = client.post(_request_path(openapi_path), json=body)
    assert response.status_code == expected_status, response.get_json()
    documented_ok = _satisfies(_conditional_fragment(openapi_path), body)
    assert documented_ok != (expected_status != 400)


# ---------------------------------------------------------------------------
# Merge refinement guard
# ---------------------------------------------------------------------------


def test_merge_refinement_accepts_constraint_composition_keys() -> None:
    openapi_gen._merge_refinement(
        {"properties": {"confirm": {"type": "boolean"}}},
        "",
        {
            "allOf": [{"not": {"required": ["confirm"]}}],
        },
        endpoint="TEST",
    )


@pytest.mark.parametrize(
    "fragment",
    [
        {"properties": {"confirm": {"const": True}}},
        {"required": ["confirm"]},
        {"type": "object"},
        {"enum": [True]},
        {"title": "手写标题"},
        {"description": "手写描述"},
    ],
)
def test_merge_refinement_rejects_structural_and_unknown_keys(fragment: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="merge refinement"):
        openapi_gen._validate_merge_fragment(
            fragment, allowed_names={"confirm", "connection_ref"}
        )


def test_merge_refinement_rejects_invented_property_names() -> None:
    fragment = {
        "if": {"properties": {"mystery": {"const": True}}, "required": ["mystery"]},
        "then": {"required": ["connection_ref"]},
    }
    with pytest.raises(ValueError, match="not a model field"):
        openapi_gen._validate_merge_fragment(
            fragment, allowed_names={"delete_external", "connection_ref"}
        )


def test_merge_refinement_rejects_property_structure_restatement() -> None:
    fragment = {
        "if": {
            "properties": {"delete_external": {"const": True}},
            "required": ["delete_external"],
        },
        "then": {"properties": {"connection_ref": {"type": "integer"}}},
    }
    with pytest.raises(ValueError, match="predicate"):
        openapi_gen._validate_merge_fragment(
            fragment, allowed_names={"delete_external", "connection_ref"}
        )


def test_merge_refinement_appends_instead_of_overwriting() -> None:
    first = {"not": {"required": ["confirm"]}}
    second = {"not": {"required": ["connection_ref"]}}
    root = {
        "type": "object",
        "properties": {"confirm": {}, "connection_ref": {}},
        "allOf": [first],
    }
    openapi_gen._merge_refinement(root, "", {"allOf": [second]}, endpoint="TEST")
    assert root["allOf"] == [first, second]
    # Two ``if`` constraints merge recursively; a scalar collision is an
    # overwrite, not an append.
    conditional = {"properties": {"confirm": {}}, "if": {"const": True}}
    openapi_gen._merge_refinement(
        conditional, "", {"if": {"not": {"required": ["confirm"]}}}, endpoint="TEST"
    )
    assert conditional["if"] == {"const": True, "not": {"required": ["confirm"]}}
    with pytest.raises(ValueError, match="overwrite"):
        openapi_gen._merge_refinement(
            {"if": {"const": True}}, "", {"if": {"const": False}}, endpoint="TEST"
        )


@pytest.mark.parametrize(
    "fragment",
    [
        {"allOf": {"required": ["confirm"]}},
        {"not": ["confirm"]},
        {"then": ["required"]},
    ],
)
def test_merge_refinement_rejects_malformed_composition_values(
    fragment: dict[str, Any],
) -> None:
    """A composition keyword with the wrong value shape would emit invalid JSON Schema."""
    with pytest.raises(ValueError, match="merge refinement"):
        openapi_gen._validate_merge_fragment(fragment, allowed_names=_CONDITION_NAMES)


#: Property names used by the negative guard cases below. They mirror the
#: derived ``delete-plan`` body so the failures are about the fragment, not the
#: allowed set.
_CONDITION_NAMES = {
    "confirm",
    "delete_external",
    "idempotency_key",
    "connection_ref",
    "configuration_revision",
    "storage_dir",
}


@pytest.mark.parametrize(
    "fragment",
    [
        # A condition subtree may not smuggle an unknown property name.
        {"then": {"required": ["mystery"]}},
        # ... nor a structural keyword the model already owns.
        {"then": {"type": "object"}},
        {"then": {"additionalProperties": False}},
        {"then": {"minProperties": 1}},
        {"allOf": [{"type": "object"}]},
    ],
)
def test_merge_refinement_rejects_loose_condition_subtrees(fragment: dict[str, Any]) -> None:
    """``then``/``if``/``else`` are constraint subtrees, not a structure escape.

    Before the tightened guard these fragments were accepted: an unknown
    ``required`` name, or ``type``/``additionalProperties``/``minProperties``
    passed straight through into the published schema — exactly the second
    structure source issue #171 removed.
    """
    with pytest.raises(ValueError, match="merge refinement"):
        openapi_gen._validate_merge_fragment(fragment, allowed_names=_CONDITION_NAMES)


def test_merge_refinement_rejects_invented_required_name_in_a_condition() -> None:
    with pytest.raises(ValueError, match="not a model field"):
        openapi_gen._validate_merge_fragment(
            {"then": {"required": ["mystery"]}}, allowed_names=_CONDITION_NAMES
        )
    with pytest.raises(ValueError, match="not a model field"):
        openapi_gen._validate_merge_fragment(
            {"else": {"not": {"anyOf": [{"required": ["invented"]}]}}},
            allowed_names=_CONDITION_NAMES,
        )


def test_merge_refinement_rejects_a_non_mapping_properties_node() -> None:
    """``properties: "not-a-dict"`` would publish a schema-invalid node."""
    with pytest.raises(ValueError, match="'properties' must be a mapping"):
        openapi_gen._validate_merge_fragment(
            {"if": {"properties": "not-a-dict"}}, allowed_names=_CONDITION_NAMES
        )


def test_registered_conditional_refinements_pass_the_tightened_guard() -> None:
    """The three published merges stay valid, unchanged, under the new guard."""
    for openapi_path, condition in (
        (DELETE_PLAN, openapi_gen._DELETE_PLAN_CONDITION),
        (RECOVER, openapi_gen._RECOVER_CONDITION),
        (RESUBMIT, openapi_gen._RESUBMIT_CONDITION),
    ):
        openapi_gen._validate_merge_fragment(
            condition, allowed_names=set(_body_schema(openapi_path)["properties"])
        )


def test_reviewed_merge_refinements_are_registered() -> None:
    """Every published conditional refinement is on the reviewed allowlist."""
    declared = frozenset(
        name
        for key, entry in _ENDPOINTS.items()
        if entry.get("requestBody") is not None
        for name in openapi_gen.refinement_keys(key, entry["requestBody"])
    )
    assert {
        f"POST {DELETE_PLAN.replace('{tracking_id}', '<path:tracking_id>')}|merge:",
        f"POST {RECOVER.replace('{tracking_id}', '<path:tracking_id>')}|merge:",
        f"POST {RESUBMIT.replace('{tracking_id}', '<path:tracking_id>')}|merge:",
    } <= declared
    assert declared == openapi_gen._REFINEMENT_ALLOWLIST


def test_unregistered_merge_refinement_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge refinement nobody reviewed aborts generation."""
    spec = openapi_gen._rb(
        SavedTrackingPlanDeleteInput,
        merge={"": {"allOf": [{"not": {"required": ["confirm"]}}]}},
    )
    with pytest.raises(ValueError, match="unreviewed request-body refinement"):
        openapi_gen._assert_reviewed_refinements("POST /api/v1/requests", spec)
    check_key = "POST /api/v1/tracking/items/<path:tracking_id>/check"
    entry = dict(_ENDPOINTS[check_key])
    entry["requestBody"] = spec
    monkeypatch.setitem(_ENDPOINTS, check_key, entry)
    with pytest.raises(ValueError, match="unreviewed request-body refinement"):
        generate_openapi()
