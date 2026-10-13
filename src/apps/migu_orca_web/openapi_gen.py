from __future__ import annotations

"""Deterministic OpenAPI 3.1 generation for the /api/v1 Web API (US-190).

The generated document is the machine-readable contract for Stage 27's
TypeScript client generation. It is produced by a pure function over the
registered Flask ``url_map`` plus explicit per-endpoint schemas in
``_ENDPOINTS``, so:

- it covers every /api/v1 JSON endpoint automatically (an undocumented new
  endpoint still needs an explicit schema entry, which the drift test
  enforces);
- it never reflects runtime configuration, storage paths, credentials or
  example values from the live process;
- examples use only fictional, desensitized values (all values below are
  placeholders; ``example.invalid`` is reserved for documentation);
- running the generator twice yields byte-identical output (no timestamps,
  no random ids, no machine paths).

Security rules applied here:

- ``storage_dir`` (a server-constrained relative profile; see US-193) is marked
  ``writeOnly``/request-only; it never appears in example responses.
- Credential fields (``password``/``token``) are flagged
  ``x-request-scoped: true`` and their examples use only placeholders.
- The poster binary endpoint declares its content types and error responses
  explicitly (it is a function view outside the JSON envelope).
"""

import json
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from apps.base import create_app
from apps.migu_orca_web.api_contract import (
    ApiErrorEnvelope,
    AutoBangumiCapabilitiesDTO,
    AutoBangumiConnectionSummaryDTO,
    AutoBangumiConnectionTestResultDTO,
    BatchParseResultDTO,
    BatchSaveConfirmResultDTO,
    CorrectionsResultDTO,
    MikanCandidateResultDTO,
    PreferenceResultDTO,
    RequestActionResultDTO,
    RequestCreateResultDTO,
    RequestDeleteResultDTO,
    RequestDetailResultDTO,
    RequestListResultDTO,
    RequestPreviewModifyResultDTO,
    RequestSafeInfoResultDTO,
    RequestSaveConfirmResultDTO,
    TrackingBatchSubmitResultDTO,
    TrackingCheckResultDTO,
    TrackingDetailResultDTO,
    TrackingItemListResultDTO,
    TrackingManagementResultDTO,
    TrackingPlanDeleteResultDTO,
    TrackingRecoverResultDTO,
    TrackingResubmitResultDTO,
    TrackingRevalidateResultDTO,
    TrackingSubmitResultDTO,
    TrackingSyncResultDTO,
)
from apps.migu_orca_web.endpoint_lifecycle import lifecycle_for
from apps.migu_orca_web.schemas import (
    AutoBangumiConfigDeletePayload,
    AutoBangumiConfigPayload,
    AutoBangumiConfigSavePayload,
    AutoBangumiConnectionTestPayload,
    BatchParsePayload,
    BatchSaveConfirmPayload,
    CorrectionSavePayload,
    MikanCandidateSearchPayload,
    PreferenceSavePayload,
    RequestActionPayload,
    RequestCancelPayload,
    RequestCreatePayload,
    RequestModifyPayload,
    RequestPreviewModifyPayload,
    RequestSaveConfirmPayload,
    SavedAutoBangumiProbePayload,
    SavedTrackingBatchSubmitInput,
    SavedTrackingPlanDeleteInput,
    SavedTrackingSubmitInput,
    TrackingCheckPayload,
    TrackingDeleteExternalPayload,
    TrackingFilterRulePatch,
    TrackingModifyPayload,
    TrackingRecoverPayload,
    TrackingRefreshRssPayload,
    TrackingResubmitPayload,
    TrackingRevalidatePayload,
    TrackingRssPatch,
    TrackingSetEnabledPayload,
    TrackingSubscriptionPatch,
    TrackingSyncPayload,
)
from shared.management_contract import (
    MANAGEMENT_ERROR_MESSAGES,
    management_error_names_for_status,
)

OPENAPI_VERSION = "3.1.0"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"

# US-193: every endpoint that accepts ``storage_dir`` rejects absolute paths /
# traversal / symlink escapes with the same stable 400 error.
_STORAGE_DIR_ERRORS: dict[str, dict[str, str]] = {
    "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
}

def _schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the JSON Schema for a pydantic model (dereferenced, no $defs)."""
    schema = model.model_json_schema()
    return _dereference(schema)


def _dereference(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline ``$ref``/``$defs`` so the emitted OpenAPI has no local refs.

    Pydantic emits sibling ``$defs`` with ``$ref`` properties; a standalone
    OpenAPI document is easier for client generators to consume without a
    resolver, and inlining keeps the output deterministic and self-contained.
    """
    defs = schema.get("$defs", {})
    if not defs:
        return schema

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.split("/")[-1]
                if name in defs:
                    return resolve(defs[name])
            return {key: resolve(item) for key, item in value.items() if key != "$defs"}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    return resolve(schema)


def _normalize_property(value: Any) -> Any:
    """Normalize a raw result-shape property value into a JSON Schema.

    Supported values:

    - a pydantic model class → its full dereferenced JSON Schema;
    - a list ``[item]`` → ``{"type": "array", "items": <item schema>}`` where
      the single element may itself be a model class or a plain dict;
    - a plain dict → an inline JSON Schema (used for nested objects);
    - ``None`` → ``{}`` (any value).
    """
    if isinstance(value, type) and issubclass(value, BaseModel):
        return _schema(value)
    if isinstance(value, list):
        item = value[0] if value else {}
        return {"type": "array", "items": _normalize_property(item)}
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                key: _normalize_property(item) for key, item in value.items()
            },
        }
    if value is None:
        return {}
    return value


def _envelope(model: type[BaseModel] | dict[str, Any] | None) -> dict[str, Any]:
    """Build a JSON Schema for ``{ok: true, result: <model>}``.

    ``model`` may be a pydantic DTO (full JSON Schema) or a raw result-shape
    dict (used for the small number of endpoints whose result is a plain
    inline object, e.g. the request list). Raw result-shape dict values must
    be valid JSON Schema properties (a property whose value is a bare list is
    a schema-invalid ``Array`` — use ``[item]`` so it becomes an object with
    ``type: array``).
    """
    if isinstance(model, dict):
        result_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                key: _normalize_property(item) for key, item in model.items()
            },
        }
    elif model is not None:
        result_schema = _schema(model)
    else:
        result_schema = {}
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["ok", "result"],
        "properties": {
            "ok": {"type": "boolean", "const": True},
            "result": result_schema,
        },
    }
    return schema


def _error_envelope() -> dict[str, Any]:
    """Build the shared failure envelope JSON Schema."""
    return _schema(ApiErrorEnvelope)


def _request_body(schema: dict[str, Any], *, description: str) -> dict[str, Any]:
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": schema,
                "example": _example_from_schema(schema),
            }
        },
        "description": description,
    }


def _example_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Derive a fictional, desensitized example from a JSON Schema.

    Every value is a placeholder; ``example.invalid`` is the reserved
    documentation-only domain. Sensitive fields (``password``/``token`` and
    anything flagged ``x-request-scoped``) are always placeholders.
    """
    examples: dict[str, Any] = {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    for key, prop in properties.items():
        if key in {"storage_dir"} or prop.get("x-request-scoped"):
            continue
        examples[key] = _example_value(prop, required=key in required)
    return examples


def _example_value(prop: dict[str, Any], *, required: bool) -> Any:
    if "example" in prop:
        return prop["example"]
    if "const" in prop:
        return prop["const"]
    if "default" in prop:
        return prop["default"]
    prop_type = prop.get("type")
    if isinstance(prop_type, list):
        # ``type: [T, "null"]`` (issue #171): exemplify the non-null branch.
        prop_type = next((item for item in prop_type if item != "null"), None)
    if prop_type == "boolean":
        return bool(required)
    if prop_type == "number":
        return 1
    if prop_type == "integer":
        return 1
    if prop_type == "array":
        items = prop.get("items", {})
        if items.get("type") == "object":
            return [_example_value(items, required=False)]
        return []
    if prop_type == "object":
        sub = prop.get("properties")
        if sub:
            return {
                key: _example_value(item, required=key in prop.get("required", []))
                for key, item in sub.items()
                if key != "storage_dir" and not item.get("x-request-scoped")
            }
        return {}
    # anyOf (e.g. optional dict fields) — use the first non-null variant.
    any_of = prop.get("anyOf")
    if any_of:
        for variant in any_of:
            if variant.get("type") != "null":
                return _example_value(variant, required=required)
        return None
    return "示例" if required else None


def _make_storage_dir_nullable(value: Any) -> None:
    """Keep the generated request contract aligned with the nullable input."""
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("storage_dir"), dict):
            storage_dir = properties["storage_dir"]
            if storage_dir.get("type") == "string":
                storage_dir["type"] = ["string", "null"]
        for child in value.values():
            _make_storage_dir_nullable(child)
    elif isinstance(value, list):
        for child in value:
            _make_storage_dir_nullable(child)


# ---------------------------------------------------------------------------
# Endpoint schema registry
# ---------------------------------------------------------------------------
# Keys are ``<METHOD> <path>`` (path with ``<param>`` placeholders, matching
# the url_map form). Each entry declares the request body (issue #171: derived
# from the ``schemas.py`` model that actually validates it), the success result
# DTO, and explicit error responses.
#
# Request bodies are never restated here. A ``requestBody`` value is a
# ``_RequestBodySpec`` carrying only:
#
# - the documentation overlay (Chinese ``description``/``example`` plus the
#   ``x-request-scoped``/``x-legacy`` security markers) that reaches the
#   generated client's JSDoc;
# - the reviewed structural refinements in ``_REFINEMENT_ALLOWLIST`` — the few
#   constraints a ``model_validator`` enforces but pydantic cannot project into
#   JSON Schema.
#
# Property names, types, required lists, enums, defaults and
# ``additionalProperties`` all come from the pydantic model.

#: Documentation-only keys a request-body overlay may carry.
_OVERLAY_KEYS = frozenset(
    {
        "description",
        "example",
        "deprecated",
        "readOnly",
        "writeOnly",
        "x-request-scoped",
        "x-legacy",
    }
)

#: Pydantic JSON-Schema metadata that is not part of the published contract.
#: ``description`` is dropped too: the pydantic model docstrings are developer
#: notes, and the published documentation is the registry overlay's job.
_DROPPED_SCHEMA_KEYS = frozenset({"title", "description"})

#: ``type`` values whose ``T | None`` union is published as ``[T, "null"]``.
_NULLABLE_UNION_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})
_MISSING = object()


@dataclass(frozen=True)
class _RequestBodySpec:
    """One request body derived from a pydantic model plus reviewed overlays."""

    model: type[BaseModel]
    overlay: dict[str, Any] = field(default_factory=dict)
    #: ``path`` -> replacement node for constraints pydantic cannot project.
    replace: dict[str, Any] = field(default_factory=dict)
    #: Names the route enforces but the model leaves optional (loose ``Any``).
    required_extra: tuple[str, ...] = ()


def _rb(
    model: type[BaseModel],
    *,
    overlay: dict[str, Any] | None = None,
    replace: dict[str, Any] | None = None,
    required_extra: tuple[str, ...] = (),
) -> _RequestBodySpec:
    """Declare a request body derived from ``model`` plus reviewed overlays."""
    return _RequestBodySpec(
        model=model,
        overlay=dict(overlay or {}),
        replace=dict(replace or {}),
        required_extra=required_extra,
    )


def _normalize_derived(value: Any) -> Any:
    """Normalize a pydantic JSON Schema into the published request-body shape.

    - ``title`` (pydantic field metadata) is dropped;
    - ``default: null`` is dropped — the ``null`` union branch already says it;
    - ``additionalProperties: true`` is dropped (JSON Schema's own default);
    - a ``T | None`` union is rendered as ``type: [T, "null"]``.

    ``properties`` maps are walked as *maps*: their keys are user-visible field
    names, so a field named ``title`` (or ``description``) must never be
    mistaken for the pydantic metadata of the same name.
    """
    if isinstance(value, list):
        return [_normalize_derived(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if key == "properties" and isinstance(item, dict):
            normalized[key] = {name: _normalize_derived(child) for name, child in item.items()}
        elif key not in _DROPPED_SCHEMA_KEYS:
            normalized[key] = _normalize_derived(item)
    if normalized.get("additionalProperties") is True:
        del normalized["additionalProperties"]
    if normalized.get("default", _MISSING) is None:
        del normalized["default"]
    return _collapse_nullable_union(normalized)


def _collapse_nullable_union(node: dict[str, Any]) -> dict[str, Any]:
    """Render a ``T | None`` union as ``type: [T, "null"]``."""
    variants = node.get("anyOf")
    if not isinstance(variants, list) or len(variants) != 2:
        return node
    for index, variant in enumerate(variants):
        other = variants[1 - index]
        if variant != {"type": "null"} or not isinstance(other, dict):
            continue
        if other.get("type") not in _NULLABLE_UNION_TYPES:
            continue
        collapsed = {key: item for key, item in node.items() if key != "anyOf"}
        collapsed.update(other)
        collapsed["type"] = [other["type"], "null"]
        return collapsed
    return node


def _drop_declared_properties(schema: dict[str, Any], names: set[str]) -> dict[str, Any]:
    """Remove URL path parameters: they are never part of the request body."""
    for name in names:
        schema.get("properties", {}).pop(name, None)
    if names and "required" in schema:
        remaining = [name for name in schema["required"] if name not in names]
        if remaining:
            schema["required"] = remaining
        else:
            del schema["required"]
    return schema


def _request_body_node(
    model: type[BaseModel], *, drop: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Derive one request-body object node from its validating pydantic model."""
    return _drop_declared_properties(_normalize_derived(_schema(model)), set(drop))


def _replace_node(root: dict[str, Any], path: str, node: dict[str, Any]) -> None:
    """Replace the node at ``path`` (``""`` is the body root, ``a.b`` nested).

    The refinement is copied in: the same fragment object serves every
    generation, so merging an overlay into the document must not mutate it.
    """
    if not path:
        root.clear()
        root.update(deepcopy(node))
        return
    parts = path.split(".")
    parent = root
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = deepcopy(node)


#: Overlay keys that introduce a nested tree rather than a documentation value:
#: ``properties`` maps field names, ``items`` carries an array element schema.
_OVERLAY_CONTAINER_KEYS = frozenset({"properties", "items"})


def _merge_overlay(
    node: dict[str, Any], overlay: dict[str, Any], *, in_properties_map: bool = False
) -> None:
    """Merge documentation keys into the derived schema (structure untouched).

    A non-documentation key would be the second structure source issue #171
    removed, so the merge fails closed instead of quietly copying it. Inside a
    ``properties`` map the keys are user-visible field names and are therefore
    unrestricted; a field named ``title`` is not pydantic metadata.
    """
    for key, value in overlay.items():
        if not in_properties_map and key not in _OVERLAY_KEYS and key not in _OVERLAY_CONTAINER_KEYS:
            raise ValueError(
                f"request-body overlay key {key!r} is not documentation; "
                "derive the constraint from schemas.py (issue #171)."
            )
        current = node.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            _merge_overlay(
                current, value, in_properties_map=key == "properties" and not in_properties_map
            )
        else:
            node[key] = value


def _request_body_schema(
    spec: _RequestBodySpec, path_parameters: frozenset[str]
) -> dict[str, Any]:
    """Build one request body: model structure + reviewed refinements + overlay.

    ``path_parameters`` are the URL rule's ``<param>`` names: the view merges
    them into the JSON body before validation, so they are never body fields.
    """
    schema = _drop_declared_properties(_request_body_node(spec.model), set(path_parameters))
    for path, node in spec.replace.items():
        _replace_node(schema, path, node)
    if spec.required_extra:
        schema["required"] = [*schema.get("required", []), *spec.required_extra]
    _merge_overlay(schema, spec.overlay)
    return schema


def _any_of_patch_node(
    model: type[BaseModel], *, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Project a patch model's "provide at least one editable field" rule.

    The rule lives in a ``model_validator``; pydantic cannot project it, so the
    ``allOf``/``anyOf`` encoding is assembled here from ``model.model_fields``
    (never from a hand-typed field list).
    """
    properties = dict(_request_body_node(model)["properties"])
    properties.update(overrides or {})

    def branch(name: str) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": [name],
        }

    return {
        "allOf": [
            {"type": "object", "additionalProperties": False, "properties": properties},
            {"anyOf": [branch(name) for name in model.model_fields]},
        ]
    }


def _nullable_patch_node(model: type[BaseModel]) -> dict[str, Any]:
    """A nullable patch node keeping the published ``null``-first union."""
    return {"anyOf": [{"type": "null"}, _any_of_patch_node(model)]}


def _auth_config_union() -> dict[str, Any]:
    """Project the credential union enforced by ``AutoBangumiConfigPayload``.

    The union lives in the model's ``model_validator``; the branch membership
    is the only hand-declared fact here, and every branch property still comes
    from the model's own field set.
    """
    properties = _request_body_node(AutoBangumiConfigPayload)["properties"]

    def branch(mode: str, credentials: tuple[str, ...]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["auth_mode", "base_url", *credentials],
            "properties": {
                "auth_mode": {"const": mode},
                "base_url": properties["base_url"],
                **{name: properties[name] for name in credentials},
            },
        }

    return {
        "oneOf": [
            branch("password", ("username", "password")),
            branch("api_token", ("token",)),
        ]
    }


def _tracking_modify_body() -> dict[str, Any]:
    """Project the scope-discriminated external-modify union (US-245).

    ``TrackingModifyPayload`` binds ``target_scope`` to the patch family in a
    ``model_validator``; the discriminated encoding is assembled from the
    models here (the previous published shape and the generated client depend
    on it).
    """
    common = _request_body_node(
        TrackingDeleteExternalPayload, drop=frozenset({"tracking_id"})
    )

    def branch(scope: str, patch: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [*common.get("required", []), "patch"],
            "properties": {
                **common["properties"],
                "target_scope": {"const": scope},
                "patch": patch,
            },
        }

    return {
        "oneOf": [
            branch(
                "SUBSCRIPTION",
                _any_of_patch_node(
                    TrackingSubscriptionPatch,
                    overrides={"filter_rule": _nullable_patch_node(TrackingFilterRulePatch)},
                ),
            ),
            branch("ASSOCIATED_RSS", _any_of_patch_node(TrackingRssPatch)),
        ]
    }


#: ``RequestPreviewModifyPayload.patch`` is typed ``dict[str, Any]`` on purpose:
#: the service raises the Chinese ``invalid_modify_patch_field`` business
#: envelope instead of pydantic's generic error, so the published editable
#: subset is projected here (reviewed refinement).
_PREVIEW_MODIFY_PATCH: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected_subtitle_group": {"type": ["string", "null"]},
        "filter_rule": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "must_contain": {"type": "string"},
                "must_not_contain": {"type": "string"},
                "use_regex": {"type": "boolean"},
                "case_sensitive": {"type": "boolean"},
            },
        },
        "expected_folder_name": {"type": "string"},
    },
}

#: Reviewed structural refinements, as ``"<endpoint>|<path>"`` where ``""`` is
#: the body root and ``required+=<name>`` marks an extra required name. Every
#: entry is a constraint a ``model_validator`` enforces but pydantic cannot
#: project; adding one turns the request-body source test red until reviewed.
_REFINEMENT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PUT /api/v1/settings/autobangumi|properties.config",
        "POST /api/v1/settings/autobangumi/test|properties.config",
        "POST /api/v1/tracking/items/<path:tracking_id>/modify|",
        "POST /api/v1/requests/preview-modify|properties.patch",
        "POST /api/v1/preferences|properties.preferences",
        "POST /api/v1/preferences|required+=preferences",
        "POST /api/v1/corrections|properties.correction",
        "POST /api/v1/corrections|required+=correction",
    }
)


def refinement_keys(key: str, spec: _RequestBodySpec) -> frozenset[str]:
    """The ``"<endpoint>|<path>"`` keys of one spec's structural refinements."""
    return frozenset(
        [f"{key}|{path}" for path in spec.replace]
        + [f"{key}|required+={name}" for name in spec.required_extra]
    )


def _assert_reviewed_refinements(key: str, spec: _RequestBodySpec) -> None:
    """Fail closed when a request body handwrites structure off the allowlist."""
    unreviewed = sorted(refinement_keys(key, spec) - _REFINEMENT_ALLOWLIST)
    if unreviewed:
        raise ValueError(
            f"{key} declares unreviewed request-body refinement(s): "
            f"{', '.join(unreviewed)}. Derive the constraint from schemas.py, or "
            "review it and add it to _REFINEMENT_ALLOWLIST (issue #171)."
        )

_MANAGEMENT_ERRORS = {
    "400": {"data_validation_errors": "请求参数校验失败", "invalid_storage_dir": "storage_dir 必须为允许的相对目录", **{name: MANAGEMENT_ERROR_MESSAGES[name] for name in management_error_names_for_status(400)}},
    "404": {"tracking_not_found": "未找到该追番记录"},
    "409": {**{name: MANAGEMENT_ERROR_MESSAGES[name] for name in management_error_names_for_status(409)}},
}


def _management_endpoint(operation_id: str, summary: str, model: type[BaseModel]) -> dict[str, Any]:
    """One saved-connection management write; the body comes from ``model``."""
    return {
        "operationId": operation_id,
        "summary": summary,
        "parameters": [{"name": "tracking_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "requestBody": _rb(model),
        "success": TrackingManagementResultDTO,
        "errors": _MANAGEMENT_ERRORS,
    }


_ENDPOINTS: dict[str, dict[str, Any]] = {
    "GET /api/v1/settings/autobangumi": {
        "operationId": "getAutoBangumiConnection",
        "summary": "读取 Auto Bangumi 安全连接摘要",
        "success": AutoBangumiConnectionSummaryDTO,
        "errors": {"500": {"storage_error": "Auto Bangumi 配置存储不可用", "storage_json_error": "Auto Bangumi 配置内容无效"}},
    },
    "PUT /api/v1/settings/autobangumi": {
        "operationId": "saveAutoBangumiConnection",
        "summary": "保存 Auto Bangumi 部署连接",
        "requestBody": _rb(
            AutoBangumiConfigSavePayload,
            replace={"properties.config": _auth_config_union()},
        ),
        "success": AutoBangumiConnectionSummaryDTO,
        "errors": {"400": {"validation_error": "请求参数校验失败", "config_error": "Auto Bangumi 配置无效"}, "409": {"configuration_revision_conflict": "Auto Bangumi 配置已变化，请重新读取后重试", "connection_in_use": "Auto Bangumi 连接正在使用中"}, "500": {"storage_error": "Auto Bangumi 配置存储不可用"}},
    },
    "DELETE /api/v1/settings/autobangumi": {
        "operationId": "deleteAutoBangumiConnection",
        "summary": "清除 Auto Bangumi 部署连接",
        "requestBody": _rb(AutoBangumiConfigDeletePayload),
        "success": AutoBangumiConnectionSummaryDTO,
        "errors": {"400": {"validation_error": "请求参数校验失败"}, "409": {"configuration_revision_conflict": "Auto Bangumi 配置已变化，请重新读取后重试", "connection_in_use": "Auto Bangumi 连接正在使用中"}, "500": {"storage_error": "Auto Bangumi 配置存储不可用"}},
    },
    "POST /api/v1/settings/autobangumi/probe": {
        "operationId": "probeSavedAutoBangumiCapabilities",
        "summary": "探测已保存 Auto Bangumi 连接能力",
        "description": "显式只读探测当前保存配置；请求仅携带 opaque connection_ref 与 configuration_revision，服务端以不可变快照和 lease 执行，结果不持久化原始响应。",
        "requestBody": _rb(SavedAutoBangumiProbePayload),
        "success": AutoBangumiCapabilitiesDTO,
        "errors": {
            "400": {"data_validation_errors": "请求参数校验失败", "config_error": "Auto Bangumi 配置未配置或引用无效"},
            "409": {"configuration_revision_conflict": "Auto Bangumi 配置已变化，请重新读取后重试", "connection_ref_conflict": "Auto Bangumi 配置引用已变化"},
            "500": {"storage_error": "Auto Bangumi 配置存储不可用", "storage_json_error": "Auto Bangumi 配置内容无效"},
        },
    },
    "POST /api/v1/settings/autobangumi/test": {
        "operationId": "testAutoBangumiConnection",
        "summary": "瞬时测试 Auto Bangumi 连接",
        "description": "仅使用当前连接草稿执行只读探测，不保存配置或原始响应。",
        "requestBody": _rb(
            AutoBangumiConnectionTestPayload,
            replace={"properties.config": _auth_config_union()},
        ),
        "success": AutoBangumiConnectionTestResultDTO,
        "errors": {"400": {"validation_error": "请求参数校验失败", "config_error": "Auto Bangumi 配置无效"}},
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/delete-plan": {
        "operationId": "deleteTrackingPlan",
        "summary": "删除追番方案（可选同时删除受控外部订阅）",
        "description": "issue #92：删除本地追番方案与追番记录。存在受控外部订阅时可显式勾选同时删除该外部对象，默认不勾选；未勾选时外部订阅继续运行且 MiGuOrca 放弃管理。勾选时先以可靠管理序列删除精确映射的外部对象，只有明确成功才继续删除本地；明确失败或结果待确认时保留本地方案、追番记录、映射与恢复依据。外部删除固定不删除已下载媒体。",
        "requestBody": _rb(
            SavedTrackingPlanDeleteInput,
            overlay={
                'properties': {
                    'delete_external': {
                        'description': '仅当用户显式勾选“同时删除 Auto Bangumi 中的受控外部订阅”时为 true。',
                    },
                    'confirm': {
                        'description': '必须为 true：用户显式确认删除追番方案。',
                    },
                    'idempotency_key': {
                        'description': 'opaque 幂等键；同键重放复用同一次外部删除。',
                    },
                    'storage_dir': {
                        'description': '服务端允许根目录下的相对目录 profile。',
                    },
                },
            },
        ),
        "success": TrackingPlanDeleteResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "tracking_confirmation_required": "删除追番方案必须显式确认",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "409": {"tracking_state_conflict": "当前追番正在进行外部操作或存在未决结果，请先恢复后再删除"},
            "500": {
                "storage_error": "删除本地追番数据失败",
                "storage_json_error": "追番记录 JSON 损坏",
            },
        },
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/modify": {
        **_management_endpoint("modifyTrackingItem", "修改外部追番方案", TrackingModifyPayload),
        "requestBody": _rb(
            TrackingModifyPayload,
            replace={"": _tracking_modify_body()},
        ),
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/set-enabled": _management_endpoint("setTrackingItemEnabled", "启用或停用外部追番方案", TrackingSetEnabledPayload),
    "POST /api/v1/tracking/items/<path:tracking_id>/delete-external": _management_endpoint("deleteExternalTrackingItem", "删除外部追番方案（保留本地数据）", TrackingDeleteExternalPayload),
    "POST /api/v1/tracking/items/<path:tracking_id>/refresh": _management_endpoint("refreshTrackingRss", "立即刷新资源", TrackingRefreshRssPayload),
    "GET /api/v1/requests": {
        "operationId": "listRequests",
        "summary": "列出所有已保存订阅方案摘要",
        "description": "返回每个已保存 Request 的公开摘要（request_id、状态、标题、字幕组与种子统计）。storage_dir 为服务端允许根目录下的相对目录 profile。",
        "parameters": [
            {
                "name": "storage_dir",
                "in": "query",
                "required": False,
                "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                "schema": {"type": "string"},
            }
        ],
        "success": RequestListResultDTO,
        "errors": {
            "400": {
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_request_id": "已保存订阅方案缺少有效 request_id",
            },
            "500": {
                "storage_error": "读取订阅方案失败",
                "storage_json_error": "订阅方案 JSON 损坏",
            },
        },
    },
    "GET /api/v1/requests/<path:request_id>": {
        "operationId": "getRequestDetail",
        "summary": "查看单个订阅方案详情",
        "description": "返回 Request 快照、状态历史与 Auto Bangumi 提交结果（ab_result）。",
        "parameters": [
            {
                "name": "request_id",
                "in": "path",
                "required": True,
                "description": "已保存订阅方案的 request_id。",
                "schema": {"type": "string"},
            },
            {
                "name": "storage_dir",
                "in": "query",
                "required": False,
                "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                "schema": {"type": "string"},
            },
        ],
        "success": RequestDetailResultDTO,
        "errors": {
            "400": {
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_request_id": "request_id 不能包含路径片段",
            },
            "404": {"request_not_found": "订阅方案不存在"},
            "500": {
                "storage_error": "读取订阅方案失败",
                "storage_json_error": "订阅方案 JSON 损坏",
            },
        },
    },
    "POST /api/v1/requests": {
        "operationId": "createRequest",
        "summary": "生成订阅草案",
        "description": "按标题生成订阅草案。Web 统一使用服务端 MiKan 配置；服务端签发权威 draft_id 与 draft_revision，持久化仅由 save-confirm 完成。",
        "requestBody": _rb(
            RequestCreatePayload,
            overlay={
                'properties': {
                    'title': {
                        'description': '番剧名称（必填）。',
                    },
                    'season_confirmation': {
                        'description': '用户确认的季数（1-99）。',
                    },
                    'candidate_context': {
                        'description': '候选搜索签发的一次性 opaque token（request-scoped）。',
                        'x-legacy': True,
                    },
                    'mikan_bangumi': {
                        'description': 'MiKan 详情页 URL（request-scoped）。',
                        'x-legacy': True,
                    },
                },
            },
        ),
        "success": RequestCreateResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_input": "请求输入非法",
                "config_error": "MiKan 配置无效",
                "rss_parse_failed": "所有候选 RSS 均解析失败",
            },
            "409": {
                "candidate_context_invalid": "候选上下文已失效或已被消费",
                "invalid_request_status": "状态冲突",
                "season_evidence_conflict": "候选季数与确认季数冲突",
                "season_confirmation_required": "候选缺少可证明季数，需明确确认",
            },
            "502": {
                "mikan_connection_failed": "MiKan HTTP 连接失败",
                "mikan_http_failed": "MiKan HTTP 请求失败",
                "mikan_parse_failed": "MiKan 页面解析失败",
            },
            "504": {"mikan_timeout": "MiKan HTTP 请求超时"},
        },
    },
    "POST /api/v1/requests/preview-modify": {
        "operationId": "previewModifyRequest",
        "summary": "内存中修改未保存草案",
        "description": "US-194/211：只接受服务端签发的 draft_id、base_revision 与允许 patch，返回更新后的内存草案、同一 draft_id 与新 draft_revision（不落盘）。base_revision 不匹配时返回 409 draft_revision_conflict（error_data 只含 field=base_revision 与 current_revision）。客户端不得提交完整 Request 作为权威快照。",
        "requestBody": _rb(
            RequestPreviewModifyPayload,
            overlay={
                'properties': {
                    'draft_id': {
                        'description': '生成/上次修改时服务端签发的 opaque draft_id（request-scoped，不落盘）。',
                        'x-legacy': True,
                    },
                    'base_revision': {
                        'description': '客户端最后观察到的草案 revision（US-211，compare-and-swap）。',
                    },
                    'patch': {
                        'description': '允许的修改补丁：selected_subtitle_group/filter_rule/expected_folder_name。',
                        'example': {
                            'filter_rule': {
                                'use_regex': False,
                                'case_sensitive': False,
                            },
                        },
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
            replace={"properties.patch": _PREVIEW_MODIFY_PATCH},
        ),
        "success": RequestPreviewModifyResultDTO,
        "errors": {
            "400": {
                "invalid_modify_patch_field": "补丁包含不可修改字段",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
            "409": {
                "draft_expired": "订阅草案已过期或不存在，请重新生成",
                "draft_evicted": "订阅草案已失效（服务器容量已满），请重新生成",
                "draft_replayed": "订阅草案已被保存，请勿重复保存",
                "draft_revision_conflict": "草案已被更新，请基于最新版本重试",
            },
        },
    },
    "GET /api/v1/requests/<path:request_id>/safe-info": {
        "operationId": "getRequestSafeInfo",
        "summary": "查看订阅方案安全信息白名单",
        "description": "US-217：返回“全部信息”只读弹窗专用的严格安全白名单（RequestSafeInfoDTO，extra=forbid）。serializer 默认拒绝，逐字段显式构造：request_id、标题/别名/季度/公开季数证据摘要、选定 MiKan 合集标题与公开编号（不含完整合集/RSS URL）、字幕组/过滤规则用户可读摘要/相对 storage profile/安全文件夹名、有效/完整/排除资源数量与脱敏文件名摘要、总集数与 updated_episode=null/updated_episode_status=NOT_IMPLEMENTED、Request 状态、脱敏历史与安全 Auto Bangumi 状态摘要。完整 URL、RSS、magnet、endpoint、token、cookie、password、Authorization、原始响应与绝对路径绝不出现在成功响应、错误或 OpenAPI 示例。",
        "parameters": [
            {
                "name": "request_id",
                "in": "path",
                "required": True,
                "description": "已保存订阅方案的 request_id。",
                "schema": {"type": "string"},
            },
            {
                "name": "storage_dir",
                "in": "query",
                "required": False,
                "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                "schema": {"type": "string"},
            },
        ],
        "success": RequestSafeInfoResultDTO,
        "errors": {
            "400": {
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_request_id": "request_id 不能包含路径片段",
            },
            "404": {"request_not_found": "订阅方案不存在"},
            "500": {
                "storage_error": "读取订阅方案失败",
                "storage_json_error": "订阅方案 JSON 损坏",
            },
        },
    },
    "POST /api/v1/requests/save-confirm": {
        "operationId": "confirmRequestSave",
        "summary": "保存并确认单个订阅方案草案",
        "description": "US-214/US-222：一次请求完成 revision 校验、草案预留、持久化、确认与幂等结果提交。请求只接受服务端签发的 draft_id、base_revision 与 opaque idempotency_key，不接受完整 Request。成功返回 CONFIRMED、已保存的 ACCEPTED Request 与扩展 handoff（US-222 起 handoff 额外携带 tracking_id/tracking_status/tracking_ready/safe_message，确认的 Request 同步进入统一追番列表；tracking 写失败不回滚已确认 Request，tracking_ready=false + 固定 safe_message 后续访问补偿）。同一 idempotency_key 重试返回同一最终结果（终态重放不触碰草案且再次 ensure 收敛同一 tracking_id）；不同键重放已保存草案返回 409 draft_replayed；持久化成功但确认失败返回 409 save_confirm_failed，error_data.details 只含 outcome=SAVED_CONFIRM_FAILED、request_id 与 retry_action=ACCEPT_SAVED_REQUEST。idempotency_key 是 request-scoped opaque 值，只进请求体与页面内存，绝不进入 storage/URL/浏览器 storage/日志/trace。",
        "requestBody": _rb(
            RequestSaveConfirmPayload,
            overlay={
                'properties': {
                    'draft_id': {
                        'description': '生成/修改时服务端签发的 opaque draft_id（一次性，成功后失效）。',
                        'x-request-scoped': True,
                    },
                    'base_revision': {
                        'description': '客户端最后观察到的草案 revision（US-214，预留校验；不匹配返回 409 draft_revision_conflict）。',
                    },
                    'idempotency_key': {
                        'description': '一次明确客户端操作生成的 opaque 幂等键（US-213/214，request-scoped；重试必须复用，键只绑定一个 operation/fingerprint）。',
                        'x-request-scoped': True,
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": RequestSaveConfirmResultDTO,
        "errors": {
            "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
            "409": {
                "invalid_request_status": "只有待确认的订阅方案可以保存",
                "draft_expired": "订阅草案已过期或不存在，请重新生成",
                "draft_evicted": "订阅草案已失效（服务器容量已满），请重新生成",
                "draft_replayed": "订阅草案已被保存，请勿重复保存",
                "draft_revision_conflict": "草案已被更新，请基于最新版本重试",
                "draft_reserved": "订阅草案正在保存中，请稍后重试",
                "idempotency_conflict": "相同的幂等键不能用于不同的保存确认操作",
                "save_confirm_failed": "订阅方案已保存但确认失败，请对已保存的方案重试确认",
            },
        },
    },
    "POST /api/v1/requests/<path:request_id>/accept": {
        "operationId": "acceptRequest",
        "summary": "确认订阅方案",
        "requestBody": _rb(
            RequestActionPayload,
            overlay={
                'properties': {
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": RequestActionResultDTO,
        "errors": {
            "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
            "404": {"request_not_found": "订阅方案不存在"},
            "409": {"invalid_request_status": "状态冲突"},
        },
    },
    "POST /api/v1/requests/<path:request_id>/cancel": {
        "operationId": "cancelRequest",
        "summary": "取消订阅方案",
        "requestBody": _rb(
            RequestCancelPayload,
            overlay={
                'properties': {
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": RequestActionResultDTO,
        "errors": {
            "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
            "404": {"request_not_found": "订阅方案不存在"},
            "409": {"invalid_request_status": "状态冲突"},
        },
    },
    "POST /api/v1/requests/<path:request_id>/modify": {
        "operationId": "modifyRequest",
        "summary": "修改已保存订阅方案",
        "requestBody": _rb(
            RequestModifyPayload,
            overlay={
                'properties': {
                    'patch': {
                        'description': '允许的修改补丁：selected_subtitle_group/filter_rule/expected_folder_name。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": RequestActionResultDTO,
        "errors": {
            "400": {
                "invalid_modify_patch_field": "补丁包含不可修改字段",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
            "404": {"request_not_found": "订阅方案不存在"},
        },
    },
    "POST /api/v1/requests/<path:request_id>/delete": {
        "operationId": "deleteRequest",
        "summary": "删除订阅方案",
        "requestBody": _rb(
            RequestActionPayload,
            overlay={
                'properties': {
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": RequestDeleteResultDTO,
        "errors": {
            "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
            "404": {"request_not_found": "订阅方案不存在"},
        },
    },
    "GET /api/v1/tracking/items": {
        "operationId": "listTrackingItems",
        "summary": "列出统一追番记录安全摘要",
        "description": "US-223：读取本地统一追番记录安全投影，支持可选 q（标题/字幕组）、status_group 与 sort（固定枚举）筛选排序，返回 summary 计数与固定 warnings。执行前先运行历史回填协调器（manifest COMPLETE 后不重复全量扫描）；只读取本地存储，绝不访问外部系统。单条 tracking JSON 损坏不阻塞健康列表，只增加 unreadable 计数与固定 warning。",
        "parameters": [
            {
                "name": "storage_dir",
                "in": "query",
                "required": False,
                "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                "schema": {"type": "string"},
            },
            {
                "name": "q",
                "in": "query",
                "required": False,
                "description": "按标题或字幕组过滤的可选搜索词。",
                "schema": {"type": "string"},
            },
            {
                "name": "status_group",
                "in": "query",
                "required": False,
                "description": "按用户状态组过滤（PENDING/PROCESSING/ACTIVE/ATTENTION/INACTIVE）。",
                "schema": {
                    "type": "string",
                    "enum": ["PENDING", "PROCESSING", "ACTIVE", "ATTENTION", "INACTIVE"],
                },
            },
            {
                "name": "sort",
                "in": "query",
                "required": False,
                "description": "固定排序枚举（updated_at 倒序/title/status）。",
                "schema": {
                    "type": "string",
                    "enum": ["updated_at", "title", "status"],
                },
            },
        ],
        "success": TrackingItemListResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
            "500": {
                "storage_error": "读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
            "401": {"ab_auth_failed": "Auto Bangumi 认证失败"},
            "502": {"ab_connection_failed": "Auto Bangumi 连接失败", "ab_submit_failed": "Auto Bangumi 提交失败"},
            "503": {"ab_submit_unsupported": "Auto Bangumi 提交能力不可用", "ab_unsupported_version": "Auto Bangumi 版本不受支持", "ab_probe_unsupported": "Auto Bangumi 探测能力不可用"},
            "504": {"ab_timeout": "Auto Bangumi 请求超时"},
        },
    },
    "POST /api/v1/tracking/sync": {
        "operationId": "syncTrackingItems",
        "summary": "同步外部追番安全投影",
        "description": "US-233：使用已保存连接 generation 执行一次只读同步。confirm 必须为 true；响应只返回能力、安全计数与 TrackingItemDTO，不返回上游对象、外部 ID、URL 或凭据。",
        "requestBody": _rb(TrackingSyncPayload),
        "success": TrackingSyncResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "config_error": "Auto Bangumi 配置无效",
            },
            "500": {"tracking_storage_error": "追番同步存储失败"},
        },
    },
    "GET /api/v1/tracking/items/<path:tracking_id>": {
        "operationId": "getTrackingItemDetail",
        "summary": "查看统一追番记录安全详情",
        "description": "US-223：读取单条统一追番记录，复用 Request safe-info 白名单，额外只返回当前 operation 安全摘要、revalidation issues、外部安全映射摘要与最近 20 条审计事件；绝不回显完整 Request、外部原始 JSON、完整 URL、凭据、magnet 或绝对路径。缺失 → tracking_not_found；路径片段 → invalid_tracking_id。",
        "parameters": [
            {
                "name": "tracking_id",
                "in": "path",
                "required": True,
                "description": "统一追番记录的 tracking_id。",
                "schema": {"type": "string"},
            },
            {
                "name": "storage_dir",
                "in": "query",
                "required": False,
                "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                "schema": {"type": "string"},
            },
        ],
        "success": TrackingDetailResultDTO,
        "errors": {
            "400": {
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_tracking_id": "tracking_id 包含不合法字符或路径片段",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "500": {
                "storage_error": "读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/revalidate": {
        "operationId": "revalidateTrackingItem",
        "summary": "复核统一追番方案（纯本地）",
        "description": "US-224：对单条统一追番记录执行 revision-aware 纯本地复核。请求只接受 expected_revision 与可选 storage profile，绝不接收 ab_config/连接/capability 配置。服务端重新读取最新本地 Request 并复核（存在且 ACCEPTED、fingerprint、标题/季度、MiKan 合集、字幕组、有效资源、外部映射、未完成 operation 与当前 tracking 状态），业务复核失败仍返回 HTTP 200：ready=false、next_status=NEEDS_RECONFIRM 与固定 §11.5 issue code 列表；通过时 ready=true。expected_revision 过期 → 409 tracking_revision_conflict；非可复核状态 → 409 tracking_state_conflict。",
        "requestBody": _rb(
            TrackingRevalidatePayload,
            overlay={
                'properties': {
                    'expected_revision': {
                        'description': '客户端最后观察到的追番记录 revision（revision-aware 复核）。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": TrackingRevalidateResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_tracking_id": "tracking_id 包含不合法字符或路径片段",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "409": {
                "tracking_revision_conflict": "追番记录版本已变化，请刷新后重试",
                "tracking_state_conflict": "当前追番记录状态不允许复核",
            },
            "500": {
                "storage_error": "读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/tracking/batch-submit": {
        "operationId": "submitTrackingBatch",
        "summary": "批量提交显式选择的追番方案（逐条独立结果）",
        "description": "issue #87：一次显式批量提交 1～36 条互不相同的追番记录。每条携带自己的 expected_revision 与 opaque idempotency_key，并由服务端逐条走单条可靠提交序列；批量不是整批事务，单条失败不回滚已成功条目。逐条返回业务结果（或外部边界前的稳定 error_type），请求被接受时整体为 HTTP 200。同键重放复用原 operation，不会创建第二个外部订阅。",
        "requestBody": _rb(
            SavedTrackingBatchSubmitInput,
            overlay={
                'properties': {
                    'items': {
                        'description': '显式选择的追番记录；每条独立提交，不重复指向同一记录。',
                        'items': {
                            'properties': {
                                'idempotency_key': {
                                    'description': 'opaque 客户端操作 id；同键网络重放收敛到同一次外部调用。',
                                },
                            },
                        },
                    },
                    'confirm': {
                        'description': '必须为 true：用户显式确认这一批外部提交。',
                    },
                    'storage_dir': {
                        'description': '存储目录（服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": TrackingBatchSubmitResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "tracking_confirmation_required": "批量提交 Auto Bangumi 必须显式确认",
            },
            "500": {
                "storage_error": "写入/读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/submit": {
        "operationId": "submitTrackingItem",
        "summary": "提交统一追番方案到 Auto Bangumi（可靠顺序）",
        "description": "US-225：对单条统一追番记录执行可靠提交流程。confirm 必须严格为 true，连接通过已保存 generation 引用。服务端重新读取最新本地 Request 并执行完整本地复核；复核不通过时不访问 Auto Bangumi，已落盘业务结果仍返回 HTTP 200。外部调用前先持久化 TrackingRecord 与 operation；同 idempotency_key 重放复用原 operation。expected_revision 过期或绑定冲突时返回 409；confirm=false 返回 400。",
        "requestBody": _rb(
            SavedTrackingSubmitInput,
            overlay={
                'properties': {
                    'submission_mode': {
                        'description': 'issue #98：本次操作的提交方式。持续追番建立受控外部订阅；下载现有资源只把当前资源交给 Auto Bangumi 加入下载。只作用于本次操作，不写入本地方案。',
                    },
                    'expected_revision': {
                        'description': '客户端最后观察到的追番记录 revision（revision-aware 提交）。',
                    },
                    'idempotency_key': {
                        'description': 'opaque 客户端提交操作 id；同键网络重放收敛到同一次外部调用。只进请求体与页面内存。',
                    },
                    'confirm': {
                        'description': '必须为 true：用户显式确认提交最新方案。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": TrackingSubmitResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_tracking_id": "tracking_id 包含不合法字符或路径片段",
                "tracking_confirmation_required": "提交 Auto Bangumi 必须显式确认最新方案",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "409": {
                "tracking_revision_conflict": "追番记录版本已变化，请刷新后重试",
                "tracking_state_conflict": "当前追番记录状态不允许提交",
                "tracking_idempotency_conflict": "同一幂等键已绑定不同的提交内容，不能复用",
                "tracking_operation_in_progress": "存在尚未完成的提交操作，请先恢复后再提交",
            },
            "500": {
                "storage_error": "写入/读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/retry": {
        "operationId": "retryTrackingItem",
        "summary": "重试明确失败的统一追番提交（可靠顺序）",
        "description": "US-226：只允许从 SUBMIT_FAILED 重试；VERIFYING_EXTERNAL/RECOVERY_REQUIRED 必须先 recover 再 retry。请求使用已保存连接 generation 与 opaque idempotency_key。服务复用统一提交序列并在外部边界前持久化 operation；同键网络重放复用原 operation。expected_revision 过期、状态冲突或绑定冲突返回 409；confirm=false 返回 400。",
        "requestBody": _rb(
            SavedTrackingSubmitInput,
            overlay={
                'properties': {
                    'submission_mode': {
                        'description': 'issue #98：本次操作的提交方式。持续追番建立受控外部订阅；下载现有资源只把当前资源交给 Auto Bangumi 加入下载。只作用于本次操作，不写入本地方案。',
                    },
                    'expected_revision': {
                        'description': '客户端最后观察到的追番记录 revision（revision-aware 重试）。',
                    },
                    'idempotency_key': {
                        'description': 'opaque 客户端重试操作 id；一次点击一个新 operation，同键网络重放复用原 operation。只进请求体与页面内存。',
                    },
                    'confirm': {
                        'description': '必须为 true：用户显式确认重试提交最新方案。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": TrackingSubmitResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_tracking_id": "tracking_id 包含不合法字符或路径片段",
                "tracking_confirmation_required": "提交 Auto Bangumi 必须显式确认最新方案",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "409": {
                "tracking_revision_conflict": "追番记录版本已变化，请刷新后重试",
                "tracking_state_conflict": "只有明确提交失败的记录可以重试",
                "tracking_idempotency_conflict": "同一幂等键已绑定不同的提交内容，不能复用",
                "tracking_operation_in_progress": "存在尚未完成的提交操作，请先恢复后再提交",
            },
            "500": {
                "storage_error": "写入/读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/recover": {
        "operationId": "recoverTrackingItem",
        "summary": "恢复统一追番记录（AUTO 纯本地或人工核验）",
        "description": "US-330：恢复追番记录；AUTO/人工动作纯本地，VERIFY_EXTERNAL 仅使用已保存连接的 connection_ref + configuration_revision 执行 3.1.18 只读核验。",
        "requestBody": _rb(
            TrackingRecoverPayload,
            overlay={
                'properties': {
                    'expected_revision': {
                        'description': '客户端最后观察到的追番记录 revision（revision-aware 恢复）。',
                    },
                    'action': {
                        'description': '恢复动作：AUTO=纯本地；VERIFY_EXTERNAL=只读外部核验（需 saved connection generation）；MARK_SUCCEEDED/MARK_FAILED=人工核验（需 confirm=true）。',
                    },
                    'confirm': {
                        'description': '人工动作必须为 true；AUTO 忽略该字段。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": TrackingRecoverResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_tracking_id": "tracking_id 包含不合法字符或路径片段",
                "tracking_confirmation_required": "人工恢复必须显式确认核验结果",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "409": {
                "tracking_revision_conflict": "追番记录版本已变化，请刷新后重试",
                "tracking_state_conflict": "当前追番记录状态不允许恢复",
            },
            "500": {
                "storage_error": "写入/读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/check": {
        "operationId": "checkTrackingItem",
        "summary": "有界只读确认待确认的持续追番提交",
        "description": "issue #183：对结果待确认的持续追番提交执行一次有界只读确认，使用原提交 operation 绑定的已保存连接（客户端不提供连接，也不改绑）。检查只读，不创建、修改、删除或重发订阅；瞬时读取失败在端点总预算与最大次数内重查。已确认外部订阅返回 ACTIVE/DISABLED；仍无法确认时返回原待确认状态与已证实的原因分类。",
        "requestBody": _rb(
            TrackingCheckPayload,
            overlay={
                'properties': {
                    'expected_revision': {
                        'description': '客户端最后观察到的追番记录 revision（revision-aware 检查）。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": TrackingCheckResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_tracking_id": "tracking_id 包含不合法字符或路径片段",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "409": {
                "tracking_revision_conflict": "追番记录版本已变化，请刷新后重试",
                "tracking_state_conflict": "当前追番记录没有可核验的待确认提交",
                "tracking_check_in_progress": "该追番记录的只读检查正在进行",
            },
            "500": {
                "storage_error": "写入/读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/resubmit": {
        "operationId": "resubmitTrackingItem",
        "summary": "风险确认后的单条主动重新提交",
        "description": "issue #184：对结果待确认的持续追番提交提供单条主动重新提交。confirm=false 先执行与原提交绑定连接的有界只读检查：已确认外部订阅存在时收敛为追番中且外部写入为零；仍待确认时返回已证实的原因分类与精确绑定（revision + 原 operation + 连接 generation），页面据此渲染固定的重复/资源风险文案。confirm=true 必须携带该绑定，过期或改绑返回 409；服务端复检一次，命中仍零写收敛，否则以新幂等键创建可追溯原 operation 的单个新 operation 并执行一次既有可靠提交序列。外部写可能仍在执行、连接/版本无效或方案不满足提交前提时禁止重发并返回已证实原因；不提供批量强制重发，原未决记录与审计保留。",
        "requestBody": _rb(
            TrackingResubmitPayload,
            overlay={
                'properties': {
                    'expected_revision': {
                        'description': '客户端最后观察到的追番记录 revision；confirm=true 时必须等于确认发布时的 revision。',
                    },
                    'confirm': {
                        'description': 'false=只做只读检查；true=用户已确认重复/资源风险，携带精确绑定后创建一次新提交。',
                    },
                    'previous_operation_id': {
                        'description': '只读检查发布的原待确认 operation id；confirm=true 必填，省略表示只读阶段。不能改绑其他 operation。',
                    },
                    'connection_ref': {
                        'description': '原 operation 绑定的已保存连接 generation；confirm=true 必填，省略表示只读阶段。客户端不能提供其他连接。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": TrackingResubmitResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_tracking_id": "tracking_id 包含不合法字符或路径片段",
                "tracking_operation_not_found": "未找到该提交操作",
            },
            "404": {"tracking_not_found": "未找到该追番记录"},
            "409": {
                "tracking_revision_conflict": "追番记录版本已变化，请刷新后重新检查",
                "tracking_state_conflict": "当前追番记录没有可核验的待确认提交",
                "tracking_check_in_progress": "该追番记录的只读检查正在进行",
                "tracking_resubmit_binding_conflict": "本次重新提交绑定的操作或连接已变化，请重新检查后再确认",
                "tracking_operation_in_progress": "存在尚未完成的提交操作，请先恢复后再提交",
                "tracking_idempotency_conflict": "同一幂等键已绑定不同的提交内容，不能复用",
            },
            "500": {
                "storage_error": "写入/读取追番记录失败",
                "storage_json_error": "追番记录 JSON 损坏",
                "tracking_storage_error": "追番记录存储失败",
                "tracking_migration_error": "历史数据迁移失败",
            },
        },
    },
    "POST /api/v1/mikan/candidates": {
        "operationId": "searchMikanCandidates",
        "summary": "搜索 MiKan 候选",
        "description": "按标题搜索 MiKan 候选，返回公开候选元数据。搜索配置由服务端提供。",
        "requestBody": _rb(MikanCandidateSearchPayload),
        "success": MikanCandidateResultDTO,
        "errors": {
            "400": {"data_validation_errors": "query 为空或非法"},
            "502": {
                "mikan_connection_failed": "MiKan HTTP 连接失败",
                "mikan_http_failed": "MiKan HTTP 请求失败",
                "mikan_parse_failed": "MiKan 页面解析失败",
            },
            "504": {"mikan_timeout": "MiKan HTTP 请求超时"},
        },
    },
    "GET /api/v1/mikan/posters/<key>": {
        "operationId": "getMikanPoster",
        "summary": "读取候选海报（二进制）",
        "description": "按 opaque key 读取候选海报图片字节。该端点为函数视图，不经 JSON envelope；失败返回 JSON envelope + 分类状态码（US-192）：400 为非法 key/非法图片（invalid_poster_key/invalid_poster），404 为未注册或过期的 key（poster_not_found），502 为上游获取失败（poster_unavailable），500 为缓存读写错误（storage_error）。",
        "parameters": [
            {
                "name": "key",
                "in": "path",
                "required": True,
                "description": "候选搜索签发的 opaque poster key。",
                "schema": {"type": "string"},
            }
        ],
        "success": None,
        "errors": {
            "400": {
                "invalid_poster_key": "封面缓存标识无效",
                "invalid_poster": "封面响应不是支持的图片或地址无效",
            },
            "404": {"poster_not_found": "poster key 未注册或已过期"},
            "502": {"poster_unavailable": "上游封面获取失败"},
            "500": {"storage_error": "封面缓存读写失败"},
        },
        "responses": {
            "200": {
                "description": "海报图片字节。",
                "content": {
                    "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                    "image/png": {"schema": {"type": "string", "format": "binary"}},
                    "image/gif": {"schema": {"type": "string", "format": "binary"}},
                    "image/webp": {"schema": {"type": "string", "format": "binary"}},
                },
                "headers": {
                    "Cache-Control": {
                        "description": "private, max-age=86400",
                        "schema": {"type": "string"},
                    }
                },
            },
        },
        "binary": True,
    },
    "GET /api/v1/preferences": {
        "operationId": "getPreferences",
        "summary": "读取用户偏好",
        "parameters": [
            {
                "name": "storage_dir",
                "in": "query",
                "required": False,
                "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                "schema": {"type": "string"},
            }
        ],
        "success": PreferenceResultDTO,
        "errors": {
            "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
            "500": {"storage_json_error": "偏好文件损坏"},
        },
    },
    "POST /api/v1/preferences": {
        "operationId": "savePreferences",
        "summary": "保存用户偏好",
        "requestBody": _rb(
            PreferenceSavePayload,
            overlay={
                'properties': {
                    'preferences': {
                        'description': '非敏感偏好对象（version/subtitle_groups/filter_defaults/naming/search）。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
            replace={"properties.preferences": {"type": "object"}},
            required_extra=("preferences",),
        ),
        "success": PreferenceResultDTO,
        "errors": {
            "400": {
                "validation_error": "偏好配置不合法",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
        },
    },
    "GET /api/v1/corrections": {
        "operationId": "listCorrections",
        "summary": "读取标题修正列表",
        "parameters": [
            {
                "name": "storage_dir",
                "in": "query",
                "required": False,
                "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                "schema": {"type": "string"},
            }
        ],
        "success": CorrectionsResultDTO,
        "errors": _STORAGE_DIR_ERRORS,
    },
    "POST /api/v1/corrections": {
        "operationId": "saveCorrection",
        "summary": "保存一条标题修正",
        "requestBody": _rb(
            CorrectionSavePayload,
            overlay={
                'properties': {
                    'correction': {
                        'description': '非敏感标题修正对象（raw_title/canonical_title/season_hint/bangumi_metadata/query_correction）。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
            replace={"properties.correction": {"type": "object"}},
            required_extra=("correction",),
        ),
        "success": CorrectionsResultDTO,
        "errors": {
            "400": {
                "validation_error": "修正内容不合法",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
        },
    },
    "POST /api/v1/batches/parse": {
        "operationId": "parseBatchTitles",
        "summary": "批量解析番剧名称",
        "requestBody": _rb(
            BatchParsePayload,
            overlay={
                'properties': {
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": BatchParseResultDTO,
        "sse_progress": True,
        "description": (
            "Issue 112/129/132：只有显式 `Accept: text/event-stream` 时才把同一操作改为 SSE 逐部进度流"
            "（通配或未设置 Accept 仍是默认 JSON 表示）；"
            "每个 FOUND／EMPTY／FAILED 条目真正完成时推送一个 item 事件"
            "（completed/total/item），最后一个 result 事件给出与默认 JSON 表示完全"
            "一致的 {batch_id, raw_input, items}。没有持久任务、取消或续接语义：事件只"
            "存在于本次请求生命周期，刷新或关闭浏览器后需重新搜索，也不承诺服务端停止"
            "工作。输入错误在开始流之前仍以普通 JSON 失败 envelope 返回；中途失败以 "
            "error 事件结束，客户端不得把未收到 result 的批次当作已完成。"
        ),
        "errors": {
            "400": {
                "validation_error": "请至少输入一个番剧名称",
                "batch_limit_exceeded": "单批最多支持 36 部（US-215，标题解析/MiKan 前拒绝）",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
        },
    },
    "POST /api/v1/batches/<batch_id>/save-confirm": {
        "operationId": "saveConfirmBatchItems",
        "summary": "批量保存并确认选中草案（逐条部分成功）",
        "description": "US-216/US-222：按条执行与单番 POST /api/v1/requests/save-confirm 完全相同的用例（revision 校验、草案预留、持久化、确认与幂等结果提交）。请求每条只接受 item_id、draft_id、base_revision 与 opaque idempotency_key，不接受完整 Request。item_ids 可选：只处理选中项并保持输入顺序，省略时按 items 顺序处理全部。成功项不因其他条目失败回滚；可预期的单条业务失败（draft_expired/draft_revision_conflict/idempotency_conflict/save_confirm_failed 等）返回 HTTP 200 的逐条脱敏 failed 结果，请求级 shape/storage profile 错误仍走普通失败 envelope。同一 item + idempotency_key 幂等重试重放同一 CONFIRMED 结果，绝不创建第二个 Request。US-222 起每条 CONFIRMED 项同步进入统一追番列表并返回 tracking_id/tracking_ready，单条 tracking 写失败不回滚该已确认项或其他条目。",
        "requestBody": _rb(
            BatchSaveConfirmPayload,
            overlay={
                'properties': {
                    'items': {
                        'description': '批量卡片保存确认描述符（公开 item_id + 服务端签发 draft_id/base_revision + opaque 幂等键）。',
                        'items': {
                            'properties': {
                                'item_id': {
                                    'description': '批量卡片的公开 item_id（保持输入顺序）。',
                                },
                                'draft_id': {
                                    'description': '服务端签发的 opaque draft_id（一次性，成功后失效；request-scoped，不落盘）。',
                                    'x-request-scoped': True,
                                },
                                'base_revision': {
                                    'description': '客户端最后观察到的草案 revision（US-216，预留校验；不匹配返回逐条 failed draft_revision_conflict）。',
                                },
                                'idempotency_key': {
                                    'description': '一次明确客户端操作生成的 opaque 幂等键（request-scoped；重试必须复用，键只绑定一个 operation/fingerprint）。',
                                    'x-request-scoped': True,
                                },
                            },
                        },
                    },
                    'item_ids': {
                        'description': '可选：只处理选中 item_id（保持输入顺序）；缺省处理全部 items。',
                    },
                    'storage_dir': {
                        'description': '存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。',
                    },
                },
            },
        ),
        "success": BatchSaveConfirmResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败（缺失/非法 item 字段或 idempotency_key）",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
        },
    },
}

def _normalized_path(path: str) -> str:
    """Convert url_map <...> placeholders to OpenAPI {param} form."""
    import re

    return re.sub(r"<(?:path:)?([^>]+)>", r"{\1}", path)


def _path_parameters(path: str) -> frozenset[str]:
    """The URL rule's ``{param}`` names for a normalized OpenAPI path."""
    import re

    return frozenset(re.findall(r"\{([^}]+)\}", path))


def _build_openapi() -> dict[str, Any]:
    """Build the complete OpenAPI document from url_map + schema registry."""
    app = create_app("testing")
    paths: dict[str, Any] = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith("/api/v1/"):
            continue
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            path = _normalized_path(rule.rule)
            key = f"{method} {rule.rule}"
            entry = _ENDPOINTS.get(key)
            if entry is None:
                raise KeyError(
                    f"Endpoint {method} {rule.rule} has no schema registry entry; "
                    "add one to _ENDPOINTS (or extend the drift test whitelist)."
                )
            spec = entry.get("requestBody")
            if isinstance(spec, _RequestBodySpec):
                _assert_reviewed_refinements(key, spec)
            operation = _operation(entry, method, path)
            paths.setdefault(path, {})[method.lower()] = operation

    # Prefer the {param} placeholder form in path ordering (stable sort).
    ordered_paths = dict(
        sorted(paths.items(), key=lambda item: _path_sort_key(item[0]))
    )
    document = {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "MiGuOrca Web API",
            "version": "0.1.0",
            "description": (
                "MiGuOrca /api/v1 公开契约。成功信封 "
                "`{ok: true, result}`；失败信封 `{ok: false, error_type, "
                "error_message, error_data}`。所有示例均为虚构脱敏值；"
                "`example.invalid` 为文档保留域。凭据字段标记为 "
                "`x-request-scoped`，绝不进入 storage、URL、浏览器 storage、"
                "日志或 trace。request_id/batch_id/draft_id/candidate_context 生命周期见 "
                "`docs/api/endpoint_inventory.md` §5.3。"
            ),
        },
        "paths": ordered_paths,
        "components": {
            "schemas": {
                "ApiOkEnvelope": _envelope(None),
                "ApiErrorEnvelope": _error_envelope(),
            }
        },
    }
    _make_storage_dir_nullable(document)
    return document


def _path_sort_key(path: str) -> tuple[int, str]:
    """Sort static paths before templated ones, stable within each group."""
    has_params = "{" in path
    return (1 if has_params else 0, path)


def _sse_progress_content(entry: dict[str, Any]) -> dict[str, Any]:
    """Explicit shapes for the batch parse SSE frames (Issue 132).

    The item payload is the *same* schema the JSON envelope uses for one batch
    item, so the streaming and buffered representations cannot drift; the
    result payload reuses the buffered result schema. ``x-sse-events`` is the
    machine-readable part of the contract (SSE frames themselves are a string
    stream), so the generated client and its consumers can distinguish
    ``item`` / ``result`` / ``error`` instead of guessing from a wide object.
    """
    envelope = _envelope(entry.get("success"))
    result_schema = envelope["properties"]["result"]
    item_schema = result_schema["properties"]["items"]["items"]
    return {
        "text/event-stream": {
            "schema": {
                "type": "string",
                "description": "SSE 帧流：每帧由 `event: <item|result|error>` 与 `data: <JSON>` 两行组成，以空行结束；载荷形状见 x-sse-events。",
            },
            "x-sse-events": {
                "item": {
                    "type": "object",
                    "required": ["completed", "total", "item"],
                    "additionalProperties": False,
                    "properties": {
                        "completed": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "已真正完成的部数；FOUND／EMPTY／FAILED 都算该部完成。",
                        },
                        "total": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 36,
                            "description": "本次批量输入的非空行数（1～36）。",
                        },
                        "item": item_schema,
                    },
                },
                "result": {
                    "type": "object",
                    "required": ["ok", "result"],
                    "additionalProperties": False,
                    "properties": {
                        "ok": {"type": "boolean", "const": True},
                        "result": result_schema,
                    },
                },
                "error": {
                    "type": "object",
                    "required": ["ok", "error_type", "error_message"],
                    "additionalProperties": False,
                    "properties": {
                        "ok": {"type": "boolean", "const": False},
                        "error_type": {"type": "string"},
                        "error_message": {"type": "string"},
                        "error_data": {"type": "object"},
                    },
                },
            },
            "example": (
                "event: item\ndata: {\"completed\": 1, \"total\": 12, \"item\": {\"item_id\": \"item-1\","
                " \"raw_title\": \"示例\", \"status\": \"FOUND\"}}\n\n"
                "event: result\ndata: {\"ok\": true, \"result\": {\"batch_id\": \"batch-1\","
                " \"raw_input\": \"示例\", \"items\": []}}\n\n"
            ),
        }
    }


def _operation_id(method: str, path: str) -> str:
    """Derive a stable, unique camelCase operationId from method + path.

    This is the fallback for endpoints without an explicit ``operationId`` in
    ``_ENDPOINTS`` (every current endpoint declares an explicit readable id,
    so the derivation only guards future additions). ``GET
    /api/v1/requests/{request_id}`` → ``getRequestsByRequestId``.
    Path params are inlined so each endpoint gets a distinct name and
    TypeScript client generators get deterministic identifiers.
    """
    segments: list[str] = []
    for part in path.split("/"):
        if not part or part in {"api", "v1"}:
            continue
        if part.startswith("{") and part.endswith("}"):
            param = part[1:-1]
            segments.append(f"By{param[0].upper()}{param[1:]}")
        else:
            segments.append(part)
    base = "".join(segments).replace("-", "").replace("_", "")
    return method.lower() + base[0].upper() + base[1:]


def _operation(entry: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    op: dict[str, Any] = {
        "summary": entry.get("summary", ""),
        "description": entry.get("description", ""),
        "operationId": entry.get("operationId") or _operation_id(method, path),
        "responses": {
            "200": {
                "description": "成功",
                "content": {
                    "application/json": {
                        "schema": _envelope(entry.get("success")),
                        "example": _success_example(entry.get("success")),
                    }
                },
            }
        },
    }
    op["x-lifecycle"] = lifecycle_for(method, path.replace("{", "<").replace("}", ">"))
    if entry.get("responses"):
        # Explicit 200 response (e.g. the binary poster endpoint).
        op["responses"] = entry["responses"]
    extra_content = entry.get("extra_success_content")
    if entry.get("sse_progress"):
        extra_content = _sse_progress_content(entry)
    if extra_content:
        # Additional representations of the same successful operation (Issue
        # 112: the batch parse SSE progress stream).
        op["responses"]["200"]["content"].update(extra_content)
    parameters = list(entry.get("parameters", []))
    if parameters:
        op["parameters"] = parameters
    request_body = entry.get("requestBody")
    if request_body is not None:
        if not isinstance(request_body, _RequestBodySpec):
            raise TypeError(
                f"Endpoint {method} {path} declares a handwritten request body; "
                "declare it with _rb(<schemas.py model>) instead (issue #171)."
            )
        op["requestBody"] = _request_body(
            _request_body_schema(request_body, _path_parameters(path)),
            description=entry.get("summary", ""),
        )
    errors = entry.get("errors", {})
    if errors:
        op["responses"].update(_error_responses(errors))
    return op


def _error_responses(errors: dict[str, dict[str, str]]) -> dict[str, Any]:
    responses: dict[str, Any] = {}
    for status, mapping in errors.items():
        descriptions = " / ".join(f"{error_type}: {message}" for error_type, message in mapping.items())
        responses[status] = {
            "description": descriptions,
            "content": {
                "application/json": {
                    "schema": _error_envelope(),
                    "example": {
                        "ok": False,
                        "error_type": next(iter(mapping)),
                        "error_message": next(iter(mapping.values())),
                        "error_data": {"failed_step": "示例步骤"},
                    },
                }
            },
        }
    return responses


def _success_example(result_schema: Any) -> dict[str, Any]:
    """Build a fictional desensitized success example from a DTO."""
    if isinstance(result_schema, dict):
        return {
            "ok": True,
            "result": {
                key: _example_value(_normalize_property(item), required=False)
                for key, item in result_schema.items()
            },
        }
    if result_schema is None:
        return {"ok": True, "result": {}}
    example: dict[str, Any] = {}
    schema = _schema(result_schema)
    for key, prop in schema.get("properties", {}).items():
        example[key] = _example_value(prop, required=key in schema.get("required", []))
    return {"ok": True, "result": example}


def generate_openapi() -> dict[str, Any]:
    """Return the deterministic OpenAPI document."""
    return _build_openapi()


def write_openapi(output: Path = DEFAULT_OUTPUT) -> Path:
    """Write the OpenAPI document to ``output`` with stable formatting."""
    doc = generate_openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``python -m apps.migu_orca_web.openapi_gen``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--check" in argv:
        argv.remove("--check")
        current = generate_openapi()
        expected_text = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        actual = (
            DEFAULT_OUTPUT.read_text(encoding="utf-8")
            if DEFAULT_OUTPUT.exists()
            else None
        )
        if actual == expected_text:
            print("OpenAPI up to date.")
            return 0
        print(
            "OpenAPI drift detected. Run `uv run python -m "
            "apps.migu_orca_web.openapi_gen` to regenerate docs/api/openapi.json.",
            file=sys.stderr,
        )
        return 1
    target = Path(argv[0]) if argv else DEFAULT_OUTPUT
    written = write_openapi(target)
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
