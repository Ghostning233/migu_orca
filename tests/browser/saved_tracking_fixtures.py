def _item(tracking_id, title, status_group="ACTIVE"):
    return {"tracking_id": tracking_id, "request_id": "request-1", "title": title, "season": 1, "subtitle_group": "字幕组", "poster_path": None, "status": "ACTIVE" if status_group == "ACTIVE" else "PENDING_SUBMIT", "status_label": "追番中" if status_group == "ACTIVE" else "待提交", "status_group": status_group, "available_actions": [], "valid_resource_count": 1, "updated_episode": None, "updated_episode_status": "NOT_IMPLEMENTED", "total_episodes": None, "revision": 1, "updated_at": "2026-09-14T00:00:00Z"}

def _modify_actions():
    return [{"code": "MODIFY", "label": "修改外部方案", "style": "SECONDARY", "requires_confirmation": True, "target_scopes": ["SUBSCRIPTION", "ASSOCIATED_RSS"]}]

def _management_actions(status):
    return [{"code": "SET_ENABLED", "label": "停用追番", "style": "PRIMARY", "requires_confirmation": True, "target_scopes": ["SUBSCRIPTION"]}, {"code": "REFRESH_RSS", "label": "立即刷新资源", "style": "SECONDARY", "requires_confirmation": True, "target_scopes": ["ASSOCIATED_RSS"]}]

def _recovery_item(tracking_id, title, revision=1):
    return {**_item(tracking_id, title, "ATTENTION"), "status": "RECOVERY_REQUIRED", "status_label": "需要恢复", "revision": revision, "available_actions": [{"code": "RECOVER_AUTO", "label": "自动恢复", "style": "SECONDARY", "requires_confirmation": False, "target_scopes": []}]}

def _detail_payload(item):
    return {**item, "origin": "single", "batch_id": None, "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z", "last_synced_at": None, "safe_info": None, "current_operation": {"operation_id": "op-unknown", "state": "UNKNOWN"}, "revalidation_issues": [], "external_mapping": {"match_reason": "标题", "enabled": True, "external_deleted": False}, "audit_events": [], "warnings": []}

def _probe_capabilities():
    names = ("subscription_list", "subscription_detail", "subscription_submit", "subscription_modify", "subscription_enable", "subscription_disable", "subscription_delete", "rss_list", "rss_modify", "rss_enable", "rss_disable", "rss_delete", "rss_refresh", "external_verify")
    return {"probe_status": "VERIFIED", "version": "3.1.18", "adapter": "legacy_3_1", **{name: "SUPPORTED" for name in names}, "checked_at": None, "safe_message": "ok"}

def _delete_detail(revision=1):
    item = _item("tracking-a", "测试番")
    item["available_actions"] = [{"code": "DELETE_EXTERNAL", "label": "删除外部订阅", "style": "DANGER", "requires_confirmation": True, "target_scopes": ["SUBSCRIPTION", "ASSOCIATED_RSS"]}]
    return {"ok": True, "result": {**_detail_payload(item), "revision": revision}}

def _summary(total=1, **counts):
    """Complete tracking-list summary with the authoritative inactive count."""
    return {
        "total": total, "pending": 0, "processing": 0, "active": 0,
        "inactive": 0, "needs_attention": 0, "unreadable": 0, **counts,
    }
