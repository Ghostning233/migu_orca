"""#155：固定安全 fixture 的人工交互预览（测试期专用，不进入产品代码）。

目标：让「人工交互预览」与截图使用**同一份已校验 dist**、**同一批固定安全 fixture**，
同时不接触用户真实数据、不需要真实凭据、不产生任何外部写。

隔离与安全边界
--------------
- 预览进程把 ``MIGU_ORCA_WEB_CONFIG_ROOT`` 与 Web storage root 指向新建的临时目录：
  不读也不写 ``.migu_orca/storage``、部署配置或任何真实运行数据；
- ``/api/v1`` 只应答固定 fixture 覆盖的读路径（连接摘要=未配置、追番列表=空、
  批量解析=仓库内固定批次、候选全集=固定安全候选、海报=确定性色块 PNG）；
- 其余 ``/api/v1`` 路径一律在本地 fail closed（返回 ``preview_read_only``），**不转发**
  给真实 handler，因此预览不会触发真实 MiKan 查询、Auto Bangumi／qBittorrent 连接或
  任何保存/提交/删除写；
- 不放宽生产代码：本模块只包装既有 Flask app 的请求入口，产品路由与 DTO 不变。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from apps.base import create_app
from apps.migu_orca_web.drafts import draft_store
from apps.migu_orca_web.services import set_web_storage_root
from tests.browser.add_anime_visual_fixtures import poster_png
from tests.browser.batch_draft_visual_fixtures import (
    BATCH_ID,
    SELECTIONS,
    batch_draft_items,
    batch_parse_envelope,
    raw_input_for,
    with_public_resources,
)
from tests.browser.batch_visual_fixtures import batch_candidate, preview_request
from tests.browser.conftest import issue_draft_id
from tests.browser.saved_tracking_fixtures import _status_groups, _summary

PREVIEW_BATCH_ID = f"{BATCH_ID}-preview"
"""预览批量解析返回的批次标识（与截图 fixture 同一批）。"""


def preview_urls(host: str, port: int) -> tuple[str, str]:
    """返回 ``(首屏 URL, 固定批量草案现场 URL)``，供 CLI 与文档共用。"""
    return (
        f"http://{host}:{port}/app/add",
        f"http://{host}:{port}/app/workbench?batch_id={PREVIEW_BATCH_ID}",
    )
PREVIEW_SINGLE_QUERY = "星海旅途"

_SINGLE_CANDIDATES: tuple[tuple[str, str, int, int], ...] = (
    ("2353", "星海旅途", 1, 12),
    ("3072", "星海旅途 第二季", 2, 13),
    ("3510", "星海旅途 外传", 0, 6),
    ("4096", "星海旅途 特别篇", 0, 4),
)

_UNCONFIGURED_CONNECTION = {
    "configured": False,
    "credential_present": False,
    "connection_status": "UNCONFIGURED",
    "capabilities": None,
}

_READ_ONLY_ERROR = {
    "code": "preview_read_only",
    "message": "预览模式：该接口未被固定安全 fixture 覆盖，已在本地 fail closed；不产生外部写。",
}

# 只有这些路径可以交给生产 Flask 应用（SPA 外壳、静态资源与探针）；其余一律不进生产路由。
_FORWARD_EXACT = frozenset({"/", "/index", "/settings", "/Settings", "/healthz", "/readiness", "/favicon.ico"})
_MULTI_SLASH_RE = re.compile(r"/{2,}")


def canonical_request_path(raw: str) -> str:
    """把请求路径规范化成可比对的形式。

    WSGI 的 ``PATH_INFO`` 已按 URL 解码，因此 ``/%2Fapi/v1/...`` 会变成 ``//api/v1/...``；
    再加上 ``..``/``.`` 与重复斜杠，直接做前缀判断会被绕过。这里统一：先把反斜杠视作
    分隔符，丢弃空段与 ``.``、消解 ``..``，再拼回以 ``/`` 开头的路径。
    """
    decoded = unquote(raw or "/").replace("\\", "/")
    segments: list[str] = []
    for segment in decoded.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    return "/" + "/".join(segments)


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _may_reach_production(path: str) -> bool:
    return path in _FORWARD_EXACT or path == "/app" or path.startswith("/app/")


def _json_response(payload: dict[str, Any], *, status: int = 200) -> tuple[bytes, int, str]:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8"), status, "application/json"


def _candidate_envelope(query: str) -> tuple[bytes, int, str]:
    candidates = [
        {
            **batch_candidate(
                bangumi_id=bangumi_id,
                title=title,
                season=season,
                total_episodes=total,
                source_query=query,
            ),
            "candidate_context": f"preview-{bangumi_id}",
        }
        for bangumi_id, title, season, total in _SINGLE_CANDIDATES
    ]
    return _json_response(
        {
            "ok": True,
            "result": {
                "query": query,
                "status": "FOUND",
                "parse_result": None,
                "attempted_queries": [],
                "error": None,
                "candidates": candidates,
            },
        }
    )


class PreviewFixtureApp:
    """WSGI 包装：固定 fixture 应答 ``/api/v1``，其余 API 一律 fail closed。"""

    def __init__(self, app: Any, *, items: list[dict[str, Any]] | None = None) -> None:
        self.app = app
        self.items = items if items is not None else batch_draft_items()
        self.raw_input = raw_input_for(self.items)
        self.parse_body = batch_parse_envelope(self.items, self.raw_input)
        self.selection_specs: dict[str, tuple[str, int]] = {
            bangumi_id: (title, effective_count)
            for bangumi_id, title, effective_count in SELECTIONS.values()
        }

    # -- WSGI --------------------------------------------------------------

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        # PATH_INFO 与原始 request-target 都做规范化，任一落到 API 命名空间就按 API 处理；
        # 只有明确属于 SPA/探针的路径才允许转发给生产应用（fail closed by default）。
        path_info = str(environ.get("PATH_INFO") or "/")
        path = canonical_request_path(path_info)
        raw_target = str(environ.get("RAW_URI") or environ.get("REQUEST_URI") or "")
        raw_path_info = raw_target.split("?", 1)[0] if raw_target else path_info
        raw_path = canonical_request_path(raw_path_info)
        canonical_forward_path = path_info == path and raw_path_info == path
        safe_trailing_slash = (
            path != "/"
            and path_info == f"{path}/"
            and raw_path_info == path_info
        )
        if path != raw_path:
            payload, status, content_type = _json_response(
                {"ok": False, "error": dict(_READ_ONLY_ERROR), "result": None},
                status=409,
            )
        elif _is_api_path(path):
            method = str(environ.get("REQUEST_METHOD") or "GET").upper()
            payload, status, content_type = self._respond(path, method, environ)
        elif (
            _may_reach_production(path)
            and (canonical_forward_path or safe_trailing_slash)
        ):
            # Flask/Werkzeug 路由匹配 PATH_INFO；只允许规范白名单路径及其单个尾斜杠，
            # 点段、重复斜杠、编码分隔符等歧义写法一律 fail closed。
            return self.app(environ, start_response)
        else:
            payload, status, content_type = _json_response(
                {"ok": False, "error": dict(_READ_ONLY_ERROR), "result": None},
                status=409,
            )
        start_response(
            f"{status} {'OK' if status < 400 else 'ERROR'}",
            [
                ("Content-Type", f"{content_type}; charset=utf-8"),
                ("Content-Length", str(len(payload))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [payload]

    # -- fixture routes ----------------------------------------------------

    def _respond(
        self, path: str, method: str, environ: dict[str, Any]
    ) -> tuple[bytes, int, str]:
        if path == "/api/v1/settings/autobangumi" and method == "GET":
            return _json_response({"ok": True, "result": dict(_UNCONFIGURED_CONNECTION)})
        if path == "/api/v1/tracking/items" and method == "GET":
            return _json_response({"ok": True, "result": {
                "items": [],
                "summary": _summary(0),
                "status_groups": _status_groups(),
                "warnings": [],
            }})
        if path.startswith("/api/v1/mikan/posters/") and method == "GET":
            bangumi_id = path.rsplit("/", 1)[-1]
            if not bangumi_id:
                return _json_response({"ok": False, "error": dict(_READ_ONLY_ERROR), "result": None}, status=404)
            return poster_png(bangumi_id), 200, "image/png"
        if path == "/api/v1/mikan/candidates" and method == "POST":
            query = self._json_field(environ, "query") or PREVIEW_SINGLE_QUERY
            return _candidate_envelope(str(query))
        if path == "/api/v1/batches/parse" and method == "POST":
            return self.parse_body.encode("utf-8"), 200, "application/json"
        if path == "/api/v1/requests" and method == "POST":
            return self._create_preview_draft(environ)
        # 写路径与其他未覆盖接口：本地 fail closed，绝不转发给真实 handler。
        return _json_response({"ok": False, "error": dict(_READ_ONLY_ERROR), "result": None}, status=409)

    def _create_preview_draft(self, environ: dict[str, Any]) -> tuple[bytes, int, str]:
        """只对 fixture 登记过的候选生成草案（与视觉截图同源的人工选择路径）。"""
        bangumi_id = str(self._json_field(environ, "mikan_bangumi") or "").rsplit("/", 1)[-1]
        spec = self.selection_specs.get(bangumi_id)
        if spec is None:
            return _json_response(
                {
                    "ok": False,
                    "error": {
                        "code": "preview_unknown_candidate",
                        "message": "预览模式只支持固定 fixture 登记的候选合集。",
                    },
                    "result": None,
                },
                status=409,
            )
        title, effective_count = spec
        preview = with_public_resources(
            preview_request(title, f"req-{PREVIEW_BATCH_ID}-{bangumi_id}"),
            bangumi_id=bangumi_id,
            title=title,
            effective_count=effective_count,
        )
        draft_id = issue_draft_id(preview)
        return _json_response(
            {
                "ok": True,
                "result": {
                    "request": preview,
                    "summary": {},
                    "draft_id": draft_id,
                    "draft_revision": 1,
                },
            }
        )

    @staticmethod
    def _json_field(environ: dict[str, Any], name: str) -> Any:
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return None
        raw = environ["wsgi.input"].read(length)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return None
        return payload.get(name) if isinstance(payload, dict) else None


def create_preview_app(*, items: list[dict[str, Any]] | None = None) -> tuple[Any, Path]:
    """构造隔离预览应用；返回 ``(wsgi_app, 临时根目录)``。

    调用方负责在进程退出时结束服务；临时目录只包含本次预览的 config/storage。
    """
    temp_root = Path(tempfile.mkdtemp(prefix="migu-orca-preview-"))
    config_root = temp_root / "config"
    storage_root = temp_root / "storage"
    config_root.mkdir(parents=True, exist_ok=True)
    storage_root.mkdir(parents=True, exist_ok=True)
    os.environ["MIGU_ORCA_WEB_CONFIG_ROOT"] = str(config_root)
    set_web_storage_root(storage_root)
    draft_store.clear()
    app = create_app()
    return PreviewFixtureApp(app, items=items), temp_root
