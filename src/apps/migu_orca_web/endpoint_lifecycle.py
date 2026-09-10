from __future__ import annotations

"""Machine-readable lifecycle contract for the B-A through B-C2 endpoints."""

from typing import Final, TypedDict


class EndpointLifecycle(TypedDict):
    lifecycle: str
    relation: str
    authority: str


_PRIMARY = "PRIMARY"
_RECOVERY = "RECOVERY"
_COMPATIBILITY = "COMPATIBILITY"


def _entry(lifecycle: str, relation: str, authority: str) -> EndpointLifecycle:
    return {"lifecycle": lifecycle, "relation": relation, "authority": authority}


# Keys intentionally use Flask's spelling.  OpenAPI and the markdown inventory
# are projections of this registry and must not grow an independent list.
ENDPOINT_LIFECYCLE: Final[dict[tuple[str, str], EndpointLifecycle]] = {
    ("POST", "/api/v1/autobangumi/capabilities"): _entry(_PRIMARY, "只读能力探测；管理写入时重新探测", "Capability probe"),
    ("POST", "/api/v1/autobangumi/test-connection"): _entry(_PRIMARY, "连接诊断，不替代管理写入校验", "Request-scoped probe"),
    ("POST", "/api/v1/qbittorrent/test-connection"): _entry(_PRIMARY, "连接诊断", "Request-scoped probe"),
    ("GET", "/api/v1/preferences"): _entry(_PRIMARY, "偏好读取", "Preference store"),
    ("POST", "/api/v1/preferences"): _entry(_PRIMARY, "偏好保存", "Preference store"),
    ("GET", "/api/v1/corrections"): _entry(_PRIMARY, "纠正规则读取", "Correction store"),
    ("POST", "/api/v1/corrections"): _entry(_PRIMARY, "纠正规则保存", "Correction store"),
    ("POST", "/api/v1/mikan/candidates"): _entry(_PRIMARY, "候选搜索；保存前真实 MiKan 选择", "Request draft"),
    ("GET", "/api/v1/mikan/posters/<key>"): _entry(_PRIMARY, "候选海报安全代理", "In-memory poster registry"),
    ("GET", "/api/v1/requests"): _entry(_PRIMARY, "订阅方案安全列表", "Request store"),
    ("POST", "/api/v1/requests"): _entry(_PRIMARY, "创建订阅草案", "Request draft"),
    ("GET", "/api/v1/requests/<path:request_id>"): _entry(_PRIMARY, "订阅方案安全详情", "Request store"),
    ("GET", "/api/v1/requests/<path:request_id>/safe-info"): _entry(_PRIMARY, "订阅方案安全详情投影", "Request store"),
    ("POST", "/api/v1/requests/preview-modify"): _entry(_PRIMARY, "服务端权威草案修改", "DraftStore"),
    ("POST", "/api/v1/requests/save-confirm"): _entry(_PRIMARY, "单番保存确认并 handoff tracking", "TrackingRecord"),
    ("POST", "/api/v1/batches/parse"): _entry(_PRIMARY, "批量草案解析", "Batch draft"),
    ("POST", "/api/v1/batches/<batch_id>/save-confirm"): _entry(_PRIMARY, "批量保存确认并 handoff tracking", "TrackingRecord"),
    ("GET", "/api/v1/tracking/items"): _entry(_PRIMARY, "统一追番安全列表", "TrackingRecord"),
    ("GET", "/api/v1/tracking/items/<path:tracking_id>"): _entry(_PRIMARY, "统一追番安全详情", "TrackingRecord"),
    ("POST", "/api/v1/tracking/sync"): _entry(_PRIMARY, "只读外部同步安全投影", "TrackingRecord"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/revalidate"): _entry(_PRIMARY, "提交前本地复核", "TrackingRecord"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/submit"): _entry(_PRIMARY, "可靠外部提交", "TrackingRecord + operation"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/retry"): _entry(_PRIMARY, "明确失败的可靠重试", "TrackingRecord + operation"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/modify"): _entry(_PRIMARY, "外部方案修改", "TrackingRecord + operation"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/set-enabled"): _entry(_PRIMARY, "外部方案启停", "TrackingRecord + operation"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/delete-external"): _entry(_PRIMARY, "外部删除并保留本地数据", "TrackingRecord + operation"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/refresh"): _entry(_PRIMARY, "关联 RSS 刷新", "TrackingRecord + operation"),
    ("POST", "/api/v1/tracking/items/<path:tracking_id>/recover"): _entry(_RECOVERY, "未知结果保守恢复；不得盲目重放", "TrackingRecord + operation"),
    ("POST", "/api/v1/requests/<path:request_id>/accept"): _entry(_RECOVERY, "保存后确认失败的 Request 恢复入口", "Request + TrackingRecord"),
    ("POST", "/api/v1/requests/<path:request_id>/cancel"): _entry(_RECOVERY, "待确认 Request 的显式取消", "Request store"),
    ("POST", "/api/v1/requests/<path:request_id>/modify"): _entry(_RECOVERY, "已保存 Request 的兼容修改入口", "Request store"),
    ("POST", "/api/v1/requests/<path:request_id>/delete"): _entry(_RECOVERY, "本地 Request 显式删除入口", "Request store"),
    ("POST", "/api/v1/requests/<path:request_id>/submit-ab"): _entry(_COMPATIBILITY, "旧单番提交；改由统一 TrackingRecord/operation 收敛", "TrackingRecord + operation"),
    ("POST", "/api/v1/requests/preview-save"): _entry(_COMPATIBILITY, "旧预览保存；由 save-confirm 替代，保持可用", "DraftStore + TrackingRecord"),
    ("POST", "/api/v1/batches/<batch_id>/accept"): _entry(_COMPATIBILITY, "旧批量接受；由批量 save-confirm 替代，保持可用", "TrackingRecord + queue projection"),
    ("GET", "/api/v1/batches/<batch_id>/queue"): _entry(_COMPATIBILITY, "旧队列读取；保留为兼容投影", "TrackingRecord; queue projection"),
    ("POST", "/api/v1/batches/<batch_id>/submit"): _entry(_COMPATIBILITY, "旧批量提交；收敛到统一提交服务", "TrackingRecord + operation"),
    ("POST", "/api/v1/batches/<batch_id>/retry"): _entry(_COMPATIBILITY, "旧批量重试；收敛到统一恢复保护", "TrackingRecord + operation"),
    ("POST", "/api/v1/batches/<batch_id>/recover"): _entry(_COMPATIBILITY, "旧批量恢复；收敛到统一恢复保护", "TrackingRecord + operation"),
}

LIFECYCLE_VALUES: Final[frozenset[str]] = frozenset({_PRIMARY, _RECOVERY, _COMPATIBILITY})


def lifecycle_for(method: str, path: str) -> EndpointLifecycle:
    """Return a defensive copy for a live Flask route."""
    normalized = path.replace("<path:", "<").replace("{", "<").replace("}", ">")
    for (registered_method, registered_path), entry in ENDPOINT_LIFECYCLE.items():
        registered_normalized = registered_path.replace("<path:", "<")
        if registered_method == method.upper() and registered_normalized == normalized:
            return dict(entry)
    raise KeyError((method.upper(), path))
