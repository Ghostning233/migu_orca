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
    AutoBangumiConnectionResultDTO,
    BatchAcceptResultDTO,
    BatchParseResultDTO,
    BatchQueueResultDTO,
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
    RequestPreviewModifyResultDTO,
    RequestPreviewSaveResultDTO,
    RequestSummaryDTO,
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


# ---------------------------------------------------------------------------
# Endpoint schema registry
# ---------------------------------------------------------------------------
# Keys are ``<METHOD> <path>`` (path with ``<param>`` placeholders, matching
# the url_map form). Each entry declares the request body schema (JSON
# endpoints), the success result DTO, and explicit error responses.

_ENDPOINTS: dict[str, dict[str, Any]] = {
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
        "success": {"requests": [RequestSummaryDTO]},
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
        "description": "按标题生成 Request。save_request=false 时仅返回内存预览，并签发服务端权威 draft_id（US-194：preview-modify/preview-save 只接受 draft_id，不接受客户端完整 Request）；save_request=true 时持久化为 PENDING_CONFIRM 草案。mikan_config/mikan_bangumi/candidate_context 均为 request-scoped，绝不落盘。",
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
        "description": "US-194：只接受服务端签发的 draft_id 与允许 patch，返回更新后的内存草案与摘要（不落盘）。客户端不得提交完整 Request 作为权威快照。",
        "requestBody": {
            "type": "object",
            "required": ["draft_id", "patch"],
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "生成/上次修改时服务端签发的 opaque draft_id（request-scoped，不落盘）。",
                    "x-request-scoped": True,
                },
                "patch": {
                    "type": "object",
                    "description": "允许的修改补丁：selected_subtitle_group/filter_rule/expected_folder_name。",
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
            },
        },
    },
    "POST /api/v1/requests/preview-save": {
        "operationId": "previewSaveRequest",
        "summary": "保存未修改的预览草案",
        "description": "US-194：消费服务端权威 draft_id（一次性，重放保护），仅允许 PENDING_CONFIRM 草案落盘并返回保存结果。",
        "requestBody": {
            "type": "object",
            "required": ["draft_id"],
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "生成/修改时服务端签发的 opaque draft_id（一次性，保存后失效）。",
                    "x-request-scoped": True,
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
    return {
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
                "`docs/api/endpoint_inventory.md` §5.4。"
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
