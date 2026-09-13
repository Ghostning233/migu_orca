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
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from apps.base import create_app
from apps.migu_orca_web.api_contract import (
    ApiErrorEnvelope,
    AutoBangumiCapabilitiesDTO,
    AutoBangumiConnectionResultDTO,
    BatchAcceptResultDTO,
    BatchParseResultDTO,
    BatchQueueResultDTO,
    BatchSaveConfirmResultDTO,
    BatchSubmitResultDTO,
    CorrectionsResultDTO,
    MikanCandidateResultDTO,
    PreferenceResultDTO,
    QbittorrentConnectionResultDTO,
    RequestAbSubmitResultDTO,
    RequestActionResultDTO,
    RequestCreateResultDTO,
    RequestDeleteResultDTO,
    RequestDetailResultDTO,
    RequestListResultDTO,
    RequestPreviewModifyResultDTO,
    RequestPreviewSaveResultDTO,
    RequestSafeInfoResultDTO,
    RequestSaveConfirmResultDTO,
    TrackingDetailResultDTO,
    TrackingItemListResultDTO,
    TrackingManagementResultDTO,
    TrackingRecoverResultDTO,
    TrackingRevalidateResultDTO,
    TrackingSubmitResultDTO,
    TrackingSyncResultDTO,
)
from apps.migu_orca_web.endpoint_lifecycle import lifecycle_for
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
# the url_map form). Each entry declares the request body schema (JSON
# endpoints), the success result DTO, and explicit error responses.

_MANAGEMENT_AB_CONFIG = {
    "type": "object", "additionalProperties": False, "x-request-scoped": True,
    "properties": {
        "auth_mode": {"type": "string", "enum": ["password", "api_token"]},
        "base_url": {"type": "string", "x-request-scoped": True},
        "username": {"type": "string", "x-request-scoped": True},
        "password": {"type": "string", "x-request-scoped": True},
        "token": {"type": "string", "x-request-scoped": True},
        "fallback_enabled": {"type": "boolean"},
    },
    "required": ["auth_mode", "fallback_enabled"],
}
_MANAGEMENT_COMMON = {
    "tracking_id": {"type": "string"},
    "target_scope": {"type": "string", "enum": ["SUBSCRIPTION", "ASSOCIATED_RSS"]},
    "expected_revision": {"type": "integer", "minimum": 1},
    "idempotency_key": {"type": "string", "x-request-scoped": True},
    "confirm": {"const": True},
    "ab_config": _MANAGEMENT_AB_CONFIG,
    "storage_dir": {"type": "string"},
}
_MANAGEMENT_ERRORS = {
    "400": {"data_validation_errors": "请求参数校验失败", "invalid_storage_dir": "storage_dir 必须为允许的相对目录", **{name: MANAGEMENT_ERROR_MESSAGES[name] for name in management_error_names_for_status(400)}},
    "404": {"tracking_not_found": "未找到该追番记录"},
    "409": {**{name: MANAGEMENT_ERROR_MESSAGES[name] for name in management_error_names_for_status(409)}},
}


def _management_endpoint(operation_id: str, summary: str, *, extra: dict[str, Any] | None = None, required_extra: list[str] | None = None, scope: list[str] | None = None) -> dict[str, Any]:
    properties = {**_MANAGEMENT_COMMON, **(extra or {})}
    if scope is not None:
        properties["target_scope"] = {"type": "string", "enum": scope}
    properties = {key: value for key, value in properties.items() if key != "tracking_id"}
    required = ["target_scope", "expected_revision", "idempotency_key", "confirm", "ab_config"] + (required_extra or [])
    return {
        "operationId": operation_id,
        "summary": summary,
        "parameters": [{"name": "tracking_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "requestBody": {"type": "object", "additionalProperties": False, "required": required, "properties": properties},
        "success": TrackingManagementResultDTO,
        "errors": _MANAGEMENT_ERRORS,
    }


def _modify_request_body() -> dict[str, Any]:
    """Strict scope-discriminated request union for external modify."""
    common = {key: value for key, value in _MANAGEMENT_COMMON.items() if key != "tracking_id"}
    filter_properties = {
        "must_contain": {"type": ["string", "null"]},
        "must_not_contain": {"type": ["string", "null"]},
        "use_regex": {"type": ["boolean", "null"]},
        "case_sensitive": {"type": ["boolean", "null"]},
    }
    subscription_properties = {
            "title": {"type": ["string", "null"]},
            "season": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
            "subtitle_group": {"type": ["string", "null"]},
            "filter_rule": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "allOf": [
                            {"type": "object", "additionalProperties": False, "properties": filter_properties},
                            {"anyOf": [
                                {"type": "object", "additionalProperties": False, "properties": filter_properties, "required": [field]}
                                for field in filter_properties
                            ]},
                        ],
                    },
                ],
            },
            "offset": {"type": ["integer", "null"], "minimum": 0},
            "expected_folder_name": {"type": ["string", "null"]},
    }
    subscription_patch = {
        "allOf": [
            {"type": "object", "additionalProperties": False, "properties": subscription_properties},
            {"anyOf": [
                {"type": "object", "additionalProperties": False, "properties": subscription_properties, "required": [field]}
                for field in subscription_properties
            ]},
        ],
    }
    rss_properties = {
        "name": {"type": ["string", "null"]},
        "aggregate": {"type": ["boolean", "null"]},
        "parser": {"type": ["string", "null"]},
    }
    rss_patch = {
        "allOf": [
            {"type": "object", "additionalProperties": False, "properties": rss_properties},
            {"anyOf": [
                {"type": "object", "additionalProperties": False, "properties": rss_properties, "required": [field]}
                for field in rss_properties
            ]},
        ],
    }

    def branch(scope: str, patch: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["target_scope", "expected_revision", "idempotency_key", "confirm", "ab_config", "patch"],
            "properties": {
                **common,
                "target_scope": {"const": scope},
                "patch": patch,
            },
        }

    return {
        "oneOf": [branch("SUBSCRIPTION", subscription_patch), branch("ASSOCIATED_RSS", rss_patch)],
    }
_ENDPOINTS: dict[str, dict[str, Any]] = {
    "POST /api/v1/tracking/items/<path:tracking_id>/modify": {
        **_management_endpoint("modifyTrackingItem", "修改外部追番方案", required_extra=["patch"]),
        "requestBody": _modify_request_body(),
    },
    "POST /api/v1/tracking/items/<path:tracking_id>/set-enabled": _management_endpoint(
        "setTrackingItemEnabled", "启用或停用外部追番方案",
        extra={"enabled": {"type": "boolean"}}, required_extra=["enabled"]
    ),
    "POST /api/v1/tracking/items/<path:tracking_id>/delete-external": _management_endpoint(
        "deleteExternalTrackingItem", "删除外部追番方案（保留本地数据）"
    ),
    "POST /api/v1/tracking/items/<path:tracking_id>/refresh": _management_endpoint(
        "refreshTrackingRss", "刷新关联 RSS", scope=["ASSOCIATED_RSS"]
    ),
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
        "summary": "生成订阅方案（可保存）",
        "description": "按标题生成 Request。save_request=false 时仅返回内存预览，并签发服务端权威 draft_id 与 draft_revision（US-194/211：preview-modify/preview-save 只接受 draft_id，不接受客户端完整 Request；US-211 起响应同时携带单调 draft_revision 供下次修改作为 base_revision）；save_request=true 时持久化为 PENDING_CONFIRM 草案。mikan_config/mikan_bangumi/candidate_context 均为 request-scoped，绝不落盘。",
        "requestBody": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "番剧名称（必填）。"},
                "source": {
                    "type": "string",
                    "enum": ["static-fixture", "mikan"],
                    "default": "static-fixture",
                },
                "save_request": {
                    "type": "boolean",
                    "default": False,
                },
                "season_confirmation": {
                    "type": "integer",
                    "description": "用户确认的季数（1-99）。",
                },
                "candidate_context": {
                    "type": "string",
                    "description": "候选搜索签发的一次性 opaque token（request-scoped）。",
                    "x-request-scoped": True,
                },
                "mikan_config": {
                    "type": "object",
                    "description": "MiKan 搜索配置（request-scoped，不落盘）。",
                    "properties": {
                        "search_endpoint": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "timeout_seconds": {"type": "number"},
                    },
                },
                "mikan_bangumi": {
                    "type": "string",
                    "description": "MiKan 详情页 URL（request-scoped）。",
                    "x-request-scoped": True,
                },
            },
            "required": ["title"],
        },
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
        "requestBody": {
            "type": "object",
            "required": ["draft_id", "base_revision", "patch"],
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "生成/上次修改时服务端签发的 opaque draft_id（request-scoped，不落盘）。",
                    "x-request-scoped": True,
                },
                "base_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "客户端最后观察到的草案 revision（US-211，compare-and-swap）。",
                },
                "patch": {
                    "type": "object",
                    "description": "允许的修改补丁：selected_subtitle_group/filter_rule/expected_folder_name。",
                    "additionalProperties": False,
                    "example": {"filter_rule": {"use_regex": False, "case_sensitive": False}},
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
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
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
    "POST /api/v1/requests/preview-save": {
        "operationId": "previewSaveRequest",
        "summary": "保存未修改的预览草案",
        "description": "US-194/US-212：以 draft_id + base_revision 预留服务端权威草案，持久化成功后才提交重放 tombstone；持久化失败会释放预留，同一 draft/revision 可安全重试，不再因写盘失败丢失草案。仅允许 PENDING_CONFIRM 草案落盘并返回保存结果。",
        "requestBody": {
            "type": "object",
            "required": ["draft_id", "base_revision"],
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "生成/修改时服务端签发的 opaque draft_id（一次性，保存成功后失效）。",
                    "x-request-scoped": True,
                },
                "base_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "客户端最后观察到的草案 revision（US-212，预留校验；不匹配返回 409 draft_revision_conflict）。",
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": RequestPreviewSaveResultDTO,
        "errors": {
            "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
            "409": {
                "invalid_request_status": "只有待确认的订阅草案可以保存",
                "draft_expired": "订阅草案已过期或不存在，请重新生成",
                "draft_evicted": "订阅草案已失效（服务器容量已满），请重新生成",
                "draft_replayed": "订阅草案已被保存，请勿重复保存",
                "draft_revision_conflict": "草案已被更新，请基于最新版本重试",
                "draft_reserved": "订阅草案正在保存中，请稍后重试",
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
        "requestBody": {
            "type": "object",
            "required": ["draft_id", "base_revision", "idempotency_key"],
            "additionalProperties": False,
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "生成/修改时服务端签发的 opaque draft_id（一次性，成功后失效）。",
                    "x-request-scoped": True,
                },
                "base_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "客户端最后观察到的草案 revision（US-214，预留校验；不匹配返回 409 draft_revision_conflict）。",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "一次明确客户端操作生成的 opaque 幂等键（US-213/214，request-scoped；重试必须复用，键只绑定一个 operation/fingerprint）。",
                    "x-request-scoped": True,
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
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
        "requestBody": {
            "type": "object",
            "properties": {
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"}
            },
        },
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
        "requestBody": {
            "type": "object",
            "properties": {
                "cancel_reason": {"type": "string"},
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
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
        "requestBody": {
            "type": "object",
            "required": ["patch"],
            "properties": {
                "patch": {
                    "type": "object",
                    "description": "允许的修改补丁：selected_subtitle_group/filter_rule/expected_folder_name。",
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
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
        "requestBody": {
            "type": "object",
            "properties": {
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"}
            },
        },
        "success": RequestDeleteResultDTO,
        "errors": {
            "400": {"invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录"},
            "404": {"request_not_found": "订阅方案不存在"},
        },
    },
    "POST /api/v1/requests/<path:request_id>/submit-ab": {
        "operationId": "submitRequestToAutoBangumi",
        "summary": "提交订阅方案到 Auto Bangumi",
        "description": "ab_config 为 request-scoped 凭据，绝不进入 storage、URL、浏览器 storage、日志或 trace。",
        "requestBody": {
            "type": "object",
            "required": ["ab_config"],
            "properties": {
                "ab_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "properties": {
                        "auth_mode": {
                            "type": "string",
                            "enum": ["password", "api_token"],
                        },
                        "base_url": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "username": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "password": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "token": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": RequestAbSubmitResultDTO,
        "errors": {
            "400": {
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "config_error": "Auto Bangumi 配置无效",
            },
            "404": {"request_not_found": "订阅方案不存在"},
            "409": {"invalid_request_status": "只有已确认订阅方案可以提交"},
            "502": {
                "ab_connection_failed": "Auto Bangumi HTTP 连接失败",
                "ab_submit_failed": "Auto Bangumi HTTP 提交失败",
            },
            "503": {"ab_submit_unsupported": "当前 Auto Bangumi 版本或认证模式暂不支持提交"},
            "504": {"ab_timeout": "Auto Bangumi HTTP 请求超时"},
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
        },
    },
    "POST /api/v1/tracking/sync": {
        "operationId": "syncTrackingItems",
        "summary": "同步外部追番安全投影",
        "description": "US-233：使用 request-scoped Auto Bangumi 配置执行一次只读同步。confirm 必须为 true；响应只返回能力、安全计数与 TrackingItemDTO，不返回上游对象、外部 ID、URL 或凭据。",
        "requestBody": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ab_config", "confirm"],
            "properties": {
                "ab_config": {
                    "type": "object", "additionalProperties": False, "x-request-scoped": True,
                    "properties": {
                        "auth_mode": {"type": "string", "enum": ["password", "api_token"]},
                        "base_url": {"type": "string", "x-request-scoped": True},
                        "username": {"type": "string", "x-request-scoped": True},
                        "password": {"type": "string", "x-request-scoped": True},
                        "token": {"type": "string", "x-request-scoped": True},
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                },
                "storage_dir": {"type": "string"},
                "confirm": {"const": True},
            },
        },
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
        "requestBody": {
            "type": "object",
            "required": ["expected_revision"],
            "properties": {
                "expected_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "客户端最后观察到的追番记录 revision（revision-aware 复核）。",
                },
                "storage_dir": {
                    "type": "string",
                    "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                },
            },
        },
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
    "POST /api/v1/tracking/items/<path:tracking_id>/submit": {
        "operationId": "submitTrackingItem",
        "summary": "提交统一追番方案到 Auto Bangumi（可靠顺序）",
        "description": "US-225：对单条统一追番记录执行可靠提交流程。confirm 必须严格为 true，ab_config 只在单次请求内存中存在（绝不进入 storage/URL/日志/trace）。服务端重新读取最新本地 Request 并执行完整本地复核（纯本地，不信任浏览器 fingerprint）；复核不通过时不访问 Auto Bangumi，已落盘业务结果仍返回 HTTP 200，outcome 为 NEEDS_RECONFIRM/SUBMIT_FAILED/VERIFYING_EXTERNAL/RECOVERY_REQUIRED/ACTIVE。仅 Request fingerprint 变化且其余复核通过时，confirm=true 表示采纳最新方案并继续同一次提交。外部调用前先持久化 TrackingRecord=SUBMITTING 与 operation=IN_PROGRESS 作为外部可能发生的持久化边界；同 idempotency_key 重放复用原 operation，并发同键只允许一次外部调用。expected_revision 过期 → 409 tracking_revision_conflict；confirm=false → 400 tracking_confirmation_required；同键不同绑定 → 409 tracking_idempotency_conflict；进行中的提交操作 → 409 tracking_operation_in_progress。",
        "requestBody": {
            "type": "object",
            "required": ["expected_revision", "idempotency_key", "confirm", "ab_config"],
            "properties": {
                "expected_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "客户端最后观察到的追番记录 revision（revision-aware 提交）。",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "opaque 客户端提交操作 id；同键网络重放收敛到同一次外部调用。只进请求体与页面内存。",
                },
                "confirm": {
                    "type": "boolean",
                    "enum": [True],
                    "description": "必须为 true：用户显式确认提交最新方案。",
                },
                "ab_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "properties": {
                        "auth_mode": {
                            "type": "string",
                            "enum": ["password", "api_token"],
                        },
                        "base_url": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "username": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "password": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "token": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                },
                "storage_dir": {
                    "type": "string",
                    "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                },
            },
        },
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
        "description": "US-226：只允许从 SUBMIT_FAILED 重试；VERIFYING_EXTERNAL/RECOVERY_REQUIRED 必须先 recover 再 retry。请求 shape 与 submit 相同（confirm 严格 true、ab_config 只在单次请求内存、opaque idempotency_key）。服务复用统一提交序列：重新读取最新本地 Request 并复核、bind 新 operation=PREPARED、持久化 TrackingRecord=SUBMITTING、operation=IN_PROGRESS 作为外部边界、单次 Auto Bangumi 调用、结果分类与落盘。同 idempotency_key 网络重放复用原 operation。expected_revision 过期 → 409 tracking_revision_conflict；非 SUBMIT_FAILED → 409 tracking_state_conflict；confirm=false → 400 tracking_confirmation_required；同键不同绑定 → 409 tracking_idempotency_conflict。",
        "requestBody": {
            "type": "object",
            "required": ["expected_revision", "idempotency_key", "confirm", "ab_config"],
            "properties": {
                "expected_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "客户端最后观察到的追番记录 revision（revision-aware 重试）。",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "opaque 客户端重试操作 id；一次点击一个新 operation，同键网络重放复用原 operation。只进请求体与页面内存。",
                },
                "confirm": {
                    "type": "boolean",
                    "enum": [True],
                    "description": "必须为 true：用户显式确认重试提交最新方案。",
                },
                "ab_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "properties": {
                        "auth_mode": {
                            "type": "string",
                            "enum": ["password", "api_token"],
                        },
                        "base_url": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "username": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "password": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "token": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                },
                "storage_dir": {
                    "type": "string",
                    "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                },
            },
        },
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
        "description": "US-234：解决外部结果未知（VERIFYING_EXTERNAL）、本地结果落盘失败（RECOVERY_REQUIRED）或状态未知（UNKNOWN）的追番记录。action 允许 AUTO/MARK_SUCCEEDED/MARK_FAILED/VERIFY_EXTERNAL：AUTO 纯本地；VERIFY_EXTERNAL 仅在本次请求内接收 ab_config 并调用 3.1.18 只读管理读取，能力未知、无匹配或多匹配保持 RECOVERY_REQUIRED；人工动作必须 confirm=true。绝不接收外部 ID/URL/原始结果或调用管理写操作。",
        "requestBody": {
            "type": "object",
            "required": ["expected_revision", "action"],
            "properties": {
                "expected_revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "客户端最后观察到的追番记录 revision（revision-aware 恢复）。",
                },
                "action": {
                    "type": "string",
                    "enum": ["AUTO", "MARK_SUCCEEDED", "MARK_FAILED", "VERIFY_EXTERNAL"],
                    "description": "恢复动作：AUTO=纯本地；VERIFY_EXTERNAL=只读外部核验（需 request-scoped ab_config）；MARK_SUCCEEDED/MARK_FAILED=人工核验（需 confirm=true）。",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "人工动作必须为 true；AUTO 忽略该字段。",
                },
                "storage_dir": {
                    "type": "string",
                    "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。",
                },
                "ab_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "description": "仅 VERIFY_EXTERNAL 使用；连接配置只在本次请求内存中存在。",
                    "properties": {
                        "auth_mode": {"type": "string", "enum": ["password", "api_token"]},
                        "base_url": {"type": "string", "x-request-scoped": True},
                        "username": {"type": "string", "x-request-scoped": True},
                        "password": {"type": "string", "x-request-scoped": True},
                        "token": {"type": "string", "x-request-scoped": True},
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "base_url", "fallback_enabled"],
                },
            },
        },
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
    "POST /api/v1/mikan/candidates": {
        "operationId": "searchMikanCandidates",
        "summary": "搜索 MiKan 候选",
        "description": "按标题搜索 MiKan 候选，返回公开候选元数据。mikan_config 为 request-scoped。",
        "requestBody": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "mikan_config": {
                    "type": "object",
                    "properties": {
                        "search_endpoint": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "timeout_seconds": {"type": "number"},
                    },
                },
            },
        },
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
        "requestBody": {
            "type": "object",
            "required": ["preferences"],
            "properties": {
                "preferences": {
                    "type": "object",
                    "description": "非敏感偏好对象（version/subtitle_groups/filter_defaults/naming/search）。",
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
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
        "requestBody": {
            "type": "object",
            "required": ["correction"],
            "properties": {
                "correction": {
                    "type": "object",
                    "description": "非敏感标题修正对象（raw_title/canonical_title/season_hint/bangumi_metadata/query_correction）。",
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
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
        "requestBody": {
            "type": "object",
            "required": ["raw_input"],
            "properties": {
                "raw_input": {"type": "string"},
                "mikan_config": {
                    "type": "object",
                    "properties": {
                        "search_endpoint": {
                            "type": "string",
                            "x-request-scoped": True,
                        },
                        "timeout_seconds": {"type": "number"},
                    },
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": BatchParseResultDTO,
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
        "requestBody": {
            "type": "object",
            "required": ["items"],
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "description": "批量卡片保存确认描述符（公开 item_id + 服务端签发 draft_id/base_revision + opaque 幂等键）。",
                    "items": {
                        "type": "object",
                        "required": ["item_id", "draft_id", "base_revision", "idempotency_key"],
                        "additionalProperties": False,
                        "properties": {
                            "item_id": {"type": "string", "description": "批量卡片的公开 item_id（保持输入顺序）。"},
                            "draft_id": {
                                "type": "string",
                                "description": "服务端签发的 opaque draft_id（一次性，成功后失效；request-scoped，不落盘）。",
                                "x-request-scoped": True,
                            },
                            "base_revision": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "客户端最后观察到的草案 revision（US-216，预留校验；不匹配返回逐条 failed draft_revision_conflict）。",
                            },
                            "idempotency_key": {
                                "type": "string",
                                "description": "一次明确客户端操作生成的 opaque 幂等键（request-scoped；重试必须复用，键只绑定一个 operation/fingerprint）。",
                                "x-request-scoped": True,
                            },
                        },
                    },
                },
                "item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：只处理选中 item_id（保持输入顺序）；缺省处理全部 items。",
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": BatchSaveConfirmResultDTO,
        "errors": {
            "400": {
                "data_validation_errors": "请求参数校验失败（缺失/非法 item 字段或 idempotency_key）",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
        },
    },
    "POST /api/v1/batches/<batch_id>/accept": {
        "operationId": "acceptBatchItems",
        "summary": "接受批量卡片进入提交前队列",
        "requestBody": {
            "type": "object",
            "required": ["batch_id", "items"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "request_id": {"type": "string"},
                            "title": {"type": "string"},
                        },
                        "required": ["item_id"],
                    },
                },
                "item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：只接受指定卡片（缺省接受全部）。",
                },
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": BatchAcceptResultDTO,
        "errors": {
            "400": {
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_batch_id": "batch_id 不能包含路径片段",
            },
        },
    },
    "GET /api/v1/batches/<batch_id>/queue": {
        "operationId": "getBatchQueue",
        "summary": "读取提交前队列",
        "parameters": [
            {
                "name": "batch_id",
                "in": "path",
                "required": True,
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
        "success": BatchQueueResultDTO,
        "errors": {
            "400": {
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
                "invalid_batch_id": "batch_id 不能包含路径片段",
            },
        },
    },
    "POST /api/v1/batches/<batch_id>/submit": {
        "operationId": "submitBatchQueue",
        "summary": "提交队列到 Auto Bangumi",
        "requestBody": {
            "type": "object",
            "required": ["batch_id", "confirm"],
            "properties": {
                "ab_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "description": "Auto Bangumi 凭据（request-scoped，绝不落盘）。",
                    "properties": {
                        "auth_mode": {"type": "string", "enum": ["password", "api_token"]},
                        "base_url": {"type": "string", "x-request-scoped": True},
                        "username": {"type": "string", "x-request-scoped": True},
                        "password": {"type": "string", "x-request-scoped": True},
                        "token": {"type": "string", "x-request-scoped": True},
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                },
                "confirm": {"type": "boolean", "description": "显式用户确认。"},
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": BatchSubmitResultDTO,
        "errors": {
            "400": {
                "validation_error": "缺少 ab_config 或 confirm",
                "queue_not_found": "队列不存在",
                "invalid_batch_id": "batch_id 不能包含路径片段",
                "config_error": "Auto Bangumi 配置无效",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
            "502": {
                "ab_connection_failed": "Auto Bangumi HTTP 连接失败",
                "ab_submit_failed": "Auto Bangumi HTTP 提交失败",
            },
            "503": {"ab_submit_unsupported": "当前 Auto Bangumi 版本或认证模式暂不支持提交"},
            "504": {"ab_timeout": "Auto Bangumi HTTP 请求超时"},
        },
    },
    "POST /api/v1/batches/<batch_id>/retry": {
        "operationId": "retryBatchQueueItem",
        "summary": "重试队列中单个失败项目",
        "requestBody": {
            "type": "object",
            "required": ["batch_id", "request_id", "confirm"],
            "properties": {
                "request_id": {"type": "string"},
                "ab_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "properties": {
                        "auth_mode": {"type": "string", "enum": ["password", "api_token"]},
                        "base_url": {"type": "string", "x-request-scoped": True},
                        "username": {"type": "string", "x-request-scoped": True},
                        "password": {"type": "string", "x-request-scoped": True},
                        "token": {"type": "string", "x-request-scoped": True},
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                },
                "confirm": {"type": "boolean"},
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": BatchSubmitResultDTO,
        "errors": {
            "400": {
                "validation_error": "缺少 ab_config/confirm/request_id",
                "queue_not_found": "队列不存在",
                "invalid_batch_id": "batch_id 不能包含路径片段",
                "config_error": "Auto Bangumi 配置无效",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
            "404": {"queue_item_not_found": "队列中不存在该 request_id"},
            "502": {
                "ab_connection_failed": "Auto Bangumi HTTP 连接失败",
                "ab_submit_failed": "Auto Bangumi HTTP 提交失败",
            },
            "503": {"ab_submit_unsupported": "当前 Auto Bangumi 版本或认证模式暂不支持提交"},
            "504": {"ab_timeout": "Auto Bangumi HTTP 请求超时"},
        },
    },
    "POST /api/v1/batches/<batch_id>/recover": {
        "operationId": "recoverBatchQueueItem",
        "summary": "恢复卡住的队列项目",
        "requestBody": {
            "type": "object",
            "required": ["batch_id", "request_id", "action"],
            "properties": {
                "request_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["auto", "succeeded", "failed"],
                },
                "confirm": {"type": "boolean"},
                "storage_dir": {"type": "string", "description": "存储目录（US-193 起为服务端允许根目录下的相对目录 profile）。"},
            },
        },
        "success": BatchSubmitResultDTO,
        "errors": {
            "400": {
                "validation_error": "action 非法或缺少确认",
                "invalid_batch_id": "batch_id 不能包含路径片段",
                "invalid_storage_dir": "storage_dir 必须是服务器允许根目录下的相对目录",
            },
            "404": {"queue_item_not_found": "队列中不存在该 request_id"},
        },
    },
    "POST /api/v1/qbittorrent/test-connection": {
        "operationId": "testQbittorrentConnection",
        "summary": "测试 qBittorrent 连接",
        "description": "qbittorrent_config 为 request-scoped 凭据；成功响应只回白名单字段。",
        "requestBody": {
            "type": "object",
            "required": ["qbittorrent_config"],
            "properties": {
                "qbittorrent_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "properties": {
                        "endpoint": {"type": "string", "x-request-scoped": True},
                        "username": {"type": "string", "x-request-scoped": True},
                        "password": {"type": "string", "x-request-scoped": True},
                        "timeout_seconds": {"type": "number"},
                        "verify_tls": {"type": "boolean"},
                    },
                    "required": ["endpoint", "username", "password"],
                }
            },
        },
        "success": QbittorrentConnectionResultDTO,
        "errors": {
            "400": {"config_error": "qBittorrent 配置无效"},
            "401": {"qbittorrent_auth_failed": "认证失败"},
            "502": {
                "qbittorrent_connection_failed": "连接失败",
                "qbittorrent_http_failed": "HTTP 请求失败",
                "qbittorrent_unexpected_response": "响应无法识别",
            },
            "504": {"qbittorrent_timeout": "请求超时"},
        },
    },
    "POST /api/v1/autobangumi/test-connection": {
        "operationId": "testAutoBangumiConnection",
        "summary": "测试 Auto Bangumi 连接",
        "description": "ab_config 为 request-scoped 凭据；成功响应只回白名单字段。",
        "requestBody": {
            "type": "object",
            "required": ["ab_config"],
            "properties": {
                "ab_config": {
                    "type": "object",
                    "x-request-scoped": True,
                    "properties": {
                        "auth_mode": {"type": "string", "enum": ["password", "api_token"]},
                        "base_url": {"type": "string", "x-request-scoped": True},
                        "username": {"type": "string", "x-request-scoped": True},
                        "password": {"type": "string", "x-request-scoped": True},
                        "token": {"type": "string", "x-request-scoped": True},
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                }
            },
        },
        "success": AutoBangumiConnectionResultDTO,
        "errors": {
            "400": {"config_error": "Auto Bangumi 配置无效"},
            "401": {"ab_auth_failed": "认证失败"},
            "502": {
                "ab_connection_failed": "连接失败",
                "ab_submit_failed": "提交失败",
            },
            "503": {
                "ab_unsupported_version": "版本不受支持",
                "ab_probe_unsupported": "当前认证模式不支持此探测方式",
            },
            "504": {"ab_timeout": "请求超时"},
        },
    },
    "POST /api/v1/autobangumi/capabilities": {
        "operationId": "probeAutoBangumiCapabilities",
        "summary": "探测 Auto Bangumi 只读能力",
        "description": "ab_config 仅为 request-scoped 凭据；响应严格白名单，未知能力 fail closed。",
        "requestBody": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ab_config"],
            "properties": {
                "ab_config": {
                    "type": "object",
                    "additionalProperties": False,
                    "x-request-scoped": True,
                    "properties": {
                        "auth_mode": {"type": "string", "enum": ["password", "api_token"]},
                        "base_url": {"type": "string", "x-request-scoped": True},
                        "username": {"type": "string", "x-request-scoped": True},
                        "password": {"type": "string", "x-request-scoped": True},
                        "token": {"type": "string", "x-request-scoped": True},
                        "fallback_enabled": {"type": "boolean"},
                    },
                    "required": ["auth_mode", "fallback_enabled"],
                }
            },
        },
        "success": AutoBangumiCapabilitiesDTO,
        "errors": {"400": {"config_error": "Auto Bangumi 配置无效"}},
    },
}


def _normalized_path(path: str) -> str:
    """Convert url_map <...> placeholders to OpenAPI {param} form."""
    import re

    return re.sub(r"<(?:path:)?([^>]+)>", r"{\1}", path)


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


def _operation_id(method: str, path: str) -> str:
    """Derive a stable, unique camelCase operationId from method + path.

    This is the fallback for endpoints without an explicit ``operationId`` in
    ``_ENDPOINTS`` (every current endpoint declares an explicit readable id,
    so the derivation only guards future additions). ``GET
    /api/v1/requests/{request_id}`` → ``getRequestsByRequestId``; ``POST
    /api/v1/batches/{batch_id}/submit`` → ``postBatchesByBatchIdSubmit``.
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
    if entry.get("binary"):
        op["responses"] = entry["responses"]
    parameters = list(entry.get("parameters", []))
    if parameters:
        op["parameters"] = parameters
    request_body = entry.get("requestBody")
    if request_body is not None:
        op["requestBody"] = _request_body(request_body, description=entry.get("summary", ""))
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
