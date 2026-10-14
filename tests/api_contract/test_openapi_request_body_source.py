from __future__ import annotations

"""Issue #171: every request body has exactly one source — ``schemas.py``.

The OpenAPI request bodies used to be a handwritten copy of the pydantic models
that actually validate them, with no test comparing the two.  These tests pin
the derived pipeline:

- every documented request body declares the model its route validates with;
- the registry contributes documentation only (a ``description``/``example``/
  ``x-*`` overlay) — never a property name, type or constraint;
- the few structural refinements pydantic cannot project are frozen in
  ``_REFINEMENT_ALLOWLIST``, so handwriting a second structure source (or a new
  one) turns red.
"""

from typing import Any

import pytest

from apps.base import create_app
from apps.migu_orca_web import openapi_gen
from apps.migu_orca_web.openapi_gen import (
    _ENDPOINTS,
    _REFINEMENT_ALLOWLIST,
    _normalized_path,
    _path_parameters,
    _request_body_schema,
    _RequestBodySpec,
    refinement_keys,
)


def _request_body_endpoints() -> list[tuple[str, dict[str, Any]]]:
    return [
        (key, entry)
        for key, entry in _ENDPOINTS.items()
        if entry.get("requestBody") is not None
    ]


def _view_for(app, method: str, rule: str) -> type:
    for candidate in app.url_map.iter_rules():
        if candidate.rule != rule or method not in candidate.methods:
            continue
        return app.view_functions[candidate.endpoint].view_class
    raise AssertionError(f"{method} {rule} is not registered")


def test_every_request_body_declares_the_model_its_route_validates() -> None:
    """The registry can only point at the executable validator (schemas.py)."""
    app = create_app("testing")
    checked = 0
    for key, entry in _request_body_endpoints():
        spec = entry["requestBody"]
        assert isinstance(spec, _RequestBodySpec), (
            f"{key} declares a handwritten request body; use _rb(<model>)"
        )
        assert spec.model.__module__ == "apps.migu_orca_web.schemas", (
            f"{key} must derive from a schemas.py model, got {spec.model.__module__}"
        )
        method, rule = key.split(" ", 1)
        view = _view_for(app, method, rule)
        declared = getattr(view, "request_validator_model", None)
        # Most views declare the model on the class; three tracking writes
        # (submit/retry/delete-plan) validate it inside ``save()`` because they
        # inject the URL tracking_id. Either way the route must reference the
        # same class object the registry points at.
        referenced = {
            name: view.save.__globals__.get(name)
            for name in view.save.__code__.co_names
        }
        assert declared is spec.model or spec.model in referenced.values(), (
            f"{key} derives from {spec.model.__name__} but its route validates "
            f"with {getattr(declared, '__name__', None) or 'an unreferenced model'}"
        )
        checked += 1
    assert checked == 29, f"expected 29 documented request bodies, found {checked}"


def test_request_body_overlay_rejects_structural_keys() -> None:
    """A structural key in the overlay would be a second source: fail closed.

    The real overlays are exercised by every test that generates the document
    (``test_openapi_generation.py``); this pins the guard's behaviour, including
    the field-name exception inside a ``properties`` map.
    """
    target = {"properties": {"title": {"type": "string"}}}
    with pytest.raises(ValueError, match="is not documentation"):
        openapi_gen._merge_overlay(target, {"properties": {"title": {"type": "object"}}})
    with pytest.raises(ValueError, match="is not documentation"):
        openapi_gen._merge_overlay(target, {"required": ["title"]})
    # Documentation keys and field names merge without complaint.
    openapi_gen._merge_overlay(
        target, {"properties": {"title": {"description": "番剧名称（必填）。"}}}
    )
    assert target["properties"]["title"]["description"] == "番剧名称（必填）。"
    assert target["properties"]["title"]["type"] == "string"


def test_request_body_overlay_never_invents_a_field() -> None:
    """Every overlay property must already exist in the model-derived schema."""
    for key, entry in _request_body_endpoints():
        spec = entry["requestBody"]
        method, rule = key.split(" ", 1)
        path = _normalized_path(rule)
        path_parameters = _path_parameters(path)
        with_overlay = _request_body_schema(spec, path_parameters)
        without_overlay = _request_body_schema(
            openapi_gen._rb(
                spec.model, replace=spec.replace, required_extra=spec.required_extra
            ),
            path_parameters,
        )
        assert _property_paths(with_overlay) == _property_paths(without_overlay), (
            f"{key}: the documentation overlay must not add or drop a property"
        )


def test_structural_refinements_are_frozen_and_all_used() -> None:
    """Adding (or dropping) a refinement requires a reviewed allowlist edit."""
    declared = frozenset(
        sorted(
            name
            for key, entry in _request_body_endpoints()
            for name in refinement_keys(key, entry["requestBody"])
        )
    )
    assert declared == _REFINEMENT_ALLOWLIST


def test_structural_refinements_reuse_model_declared_field_names() -> None:
    """A refinement may re-encode a rule, never invent a field."""
    known = (
        set(openapi_gen.RequestPreviewModifyPayload.model_fields)
        | set(openapi_gen.TrackingDeleteExternalPayload.model_fields)
        | set(openapi_gen.TrackingSubscriptionPatch.model_fields)
        | set(openapi_gen.TrackingRssPatch.model_fields)
        | set(openapi_gen.TrackingFilterRulePatch.model_fields)
        | set(openapi_gen.AutoBangumiConfigPayload.model_fields)
        | {"patch"}
    )
    for key, entry in _request_body_endpoints():
        spec = entry["requestBody"]
        for path, node in spec.replace.items():
            if spec.model is openapi_gen.RequestPreviewModifyPayload:
                # The service, not the model, owns this editable subset; it is
                # frozen by test_preview_modify_patch_refinement_is_frozen.
                continue
            invented = _top_level_properties(node) - known
            assert not invented, f"{key}|{path} invents field(s): {sorted(invented)}"


def test_preview_modify_patch_refinement_is_frozen() -> None:
    """The service-owned editable subset is frozen here, not left implicit."""
    assert _property_paths(openapi_gen._PREVIEW_MODIFY_PATCH) == {
        "selected_subtitle_group",
        "filter_rule",
        "filter_rule.must_contain",
        "filter_rule.must_not_contain",
        "filter_rule.use_regex",
        "filter_rule.case_sensitive",
        "expected_folder_name",
    }


@pytest.mark.parametrize(
    "replace_path",
    ["properties.title", ""],
)
def test_unreviewed_refinement_fails_closed(replace_path: str) -> None:
    """A structural override that is not on the allowlist aborts generation."""
    spec = openapi_gen._rb(
        openapi_gen.RequestCreatePayload,
        replace={replace_path: {"type": "object"}},
    )
    with pytest.raises(ValueError, match="unreviewed request-body refinement"):
        openapi_gen._assert_reviewed_refinements("POST /api/v1/requests", spec)


def _top_level_properties(schema: Any) -> set[str]:
    """Field names declared in every ``properties``/``allOf`` node of ``schema``."""
    names: set[str] = set()
    if isinstance(schema, dict):
        names |= set(schema.get("properties", {}))
        for key in ("allOf", "oneOf", "anyOf", "items"):
            value = schema.get(key)
            if isinstance(value, dict):
                names |= _top_level_properties(value)
            elif isinstance(value, list):
                for item in value:
                    names |= _top_level_properties(item)
    return names


def _property_paths(schema: Any, path: str = "") -> set[str]:
    """Dotted paths of every ``properties`` name reachable from ``schema``."""
    found: set[str] = set()
    if isinstance(schema, dict):
        for name, child in schema.get("properties", {}).items():
            here = f"{path}.{name}" if path else name
            found.add(here)
            found |= _property_paths(child, here)
        for name in ("items", "anyOf", "oneOf", "allOf"):
            value = schema.get(name)
            if isinstance(value, dict):
                found |= _property_paths(value, path)
            elif isinstance(value, list):
                for item in value:
                    found |= _property_paths(item, path)
    return found
