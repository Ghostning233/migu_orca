from __future__ import annotations

from pathlib import Path
from typing import Any

from flask.testing import FlaskClient
import pytest

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from mikan_engine.controllers.mikan_client import create_mikan_client
from mikan_engine.controllers.mikan_config import MikanConfig
from qbittorrent_engine.controllers.qbittorrent_config import QBittorrentConfig
from request_engine.controllers.request_controller import (
    accept_request,
    cancel_request,
    summarize_request,
)
from shared.errors import Stage1Error
from shared.models import BangumiCandidate, EntryRequest, MatchedBangumi, RssSource
from storage_engine.controllers.ab_result_repository import save_ab_submit_result
from storage_engine.controllers.history_repository import append_status_history
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config


def _client() -> FlaskClient:
    return create_app("testing").test_client()


def _saved_request(tmp_path: Path, title: str, request_id: str) -> dict[str, Any]:
    request = {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request


def _saved_accepted_request(
    tmp_path: Path,
    title: str = "芙莉莲",
    request_id: str = "request-1",
) -> dict[str, Any]:
    request = accept_request(
        {
            **generate_request(EntryRequest(raw_title=title))["request"],
            "request_id": request_id,
        }
    )
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request


def _saved_cancelled_request(
    tmp_path: Path,
    title: str = "芙莉莲",
    request_id: str = "request-cancelled",
) -> dict[str, Any]:
    request = cancel_request(
        {
            **generate_request(EntryRequest(raw_title=title))["request"],
            "request_id": request_id,
        },
        "不需要",
    )
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)
    return request


class _FakeMikanTransport:
    def __init__(self, responses: dict[str, str] | None = None, error: Stage1Error | None = None) -> None:
        self.responses = responses or {}
        self.error = error
        self.requests: list[tuple[str, float]] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.responses[url]


class _FakeMikanClient:
    def __init__(self, config: MikanConfig, transport: _FakeMikanTransport) -> None:
        self.config = config
        self.transport = transport

    def list_bangumi_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        assert raw_title == "芙莉莲"
        return [
            BangumiCandidate(
                bangumi_id="123",
                title="芙莉莲",
                aliases=["葬送的芙莉莲"],
                mikan_url="https://mikan.example/Home/Bangumi/123",
                rss_sources=[],
            )
        ]

    def list_rss_sources(self, matched_bangumi: MatchedBangumi) -> list[RssSource]:
        assert matched_bangumi.title == "芙莉莲"
        return [
            RssSource(
                subtitle_group="Loli",
                rss_url="https://mikan.example/RSS/Bangumi?bangumiId=123",
                source_type="mikan_http",
                fixture_path="",
            )
        ]


def test_root_redirects_to_index() -> None:
    response = _client().get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/index"


def test_index_serves_web_ui_shell() -> None:
    response = _client().get("/index")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "text/html" in response.content_type
    assert "MiGuOrca" in html
    assert "<title>MiGuOrca Request 工作台</title>" in html
    assert "Stage 13 Request 工作台" in html
    assert "Stage 7 Web UI MVP" not in html
    assert "Stage 8 Web UI Usability" not in html
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "运行模式：本地 JSON storage" in html
    assert "Request 生成默认使用仓库 fixture-backed 数据" in html
    assert "外部数据源、连接测试与提交配置集中在 Settings" in html
    assert "Request 生成" in html
    assert "Request 列表" in html
    assert "Request 详情" in html
    assert 'href="/index"' in html
    assert 'href="/settings"' in html
    assert 'aria-current="page"' in html
    assert "Request 工作台" in html
    assert "Settings" in html
    assert 'id="generate-panel"' in html
    assert 'id="request-list-panel"' in html
    assert 'id="request-detail-panel"' in html
    assert 'id="request-generate-form"' in html
    assert 'name="title"' in html
    assert "例如：葬送的芙莉莲" in html
    assert "至少输入 1 个非空白字符" in html
    assert 'aria-describedby="request-title-help request-form-error"' in html
    assert 'id="request-source"' not in html
    assert 'name="source"' not in html
    assert 'id="mikan-config-fields"' not in html
    assert 'name="mikan_search_endpoint"' not in html
    assert 'name="mikan_timeout_seconds"' not in html
    assert "search_endpoint" not in html
    assert "timeout_seconds" not in html
    assert 'name="storage_dir"' not in html
    assert 'name="save_request"' not in html
    assert 'id="storage-preference-summary"' in html
    assert "当前使用默认 `.migu_orca/storage`" in html
    assert "前往 Settings" in html
    assert 'id="request-form-error"' in html
    assert 'role="alert"' in html
    assert 'id="request-generate-submit"' in html
    assert 'data-default-label="生成"' in html
    assert 'id="clear-web-preferences"' not in html
    assert 'id="qbittorrent-config-toggle"' not in html
    assert 'id="qbittorrent-test-form"' not in html
    assert 'name="qbittorrent_endpoint"' not in html
    assert 'name="qbittorrent_username"' not in html
    assert 'name="qbittorrent_password"' not in html
    assert 'name="qbittorrent_timeout_seconds"' not in html
    assert 'name="qbittorrent_verify_tls"' not in html
    assert "verify_tls" not in html
    assert "/api/v1/qbittorrent/test-connection" not in html
    assert 'id="request-list-container"' in html
    assert 'id="request-list-refresh"' in html
    assert 'id="request-list-search"' in html
    assert "标题、request_id、字幕组或 folder_name" in html
    assert 'id="request-list-status-filter"' in html
    assert "<option value=\"\">All</option>" in html
    assert 'id="request-list-sort"' in html
    assert '<option value="default">默认顺序</option>' in html
    assert '<option value="title_asc">标题升序</option>' in html
    assert '<option value="request_id_asc">request_id 升序</option>' in html
    assert 'id="request-list-count"' in html
    assert "显示 0 / 0" in html
    assert 'id="request-detail-container"' in html
    assert 'id="page-notification"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'role="status"' in html
    assert 'aria-describedby="save-request-help"' not in html
    assert 'aria-label="刷新 Request 列表"' in html
    assert 'aria-relevant="additions text"' in html
    assert "/migu-orca-static/app.js" in html
    assert "token" not in html.lower()
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<rss" not in html.lower()


def test_settings_case_redirects_to_settings() -> None:
    response = _client().get("/Settings")

    assert response.status_code == 302
    assert response.headers["Location"] == "/settings"


def test_settings_serves_placeholder_shell_with_shared_navigation() -> None:
    response = _client().get("/settings")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "text/html" in response.content_type
    assert "<title>MiGuOrca Settings</title>" in html
    assert "MiGuOrca Settings" in html
    assert "Stage 13 Settings" in html
    assert 'href="/index"' in html
    assert 'href="/settings"' in html
    assert 'aria-current="page"' in html
    assert "Request 工作台" in html
    assert "Settings" in html
    assert 'id="storage-settings-panel"' in html
    assert 'id="data-source-settings-panel"' in html
    assert 'id="qbittorrent-settings-panel"' in html
    assert 'id="auto-bangumi-settings-panel"' in html
    assert "Storage 偏好" in html
    assert "数据源" in html
    assert "qBittorrent" in html
    assert "Auto Bangumi" in html
    assert html.count('class="panel settings-panel"') == 4
    assert "empty-state" in html
    assert 'id="storage-preferences-form"' in html
    assert 'id="settings-storage-dir"' in html
    assert 'name="storage_dir"' in html
    assert 'id="settings-save-request"' in html
    assert 'name="save_request"' in html
    assert 'id="storage-preferences-save"' in html
    assert 'id="storage-preferences-clear"' in html
    assert "非敏感浏览器偏好" in html
    assert "localStorage" in html
    qbittorrent_panel_html = html[
        html.index('id="qbittorrent-settings-panel"') : html.index('id="auto-bangumi-settings-panel"')
    ]
    assert 'id="qbittorrent-settings-details"' not in html
    assert "<details" not in qbittorrent_panel_html
    assert "<summary" not in qbittorrent_panel_html
    assert 'id="settings-qbittorrent-test-form"' in html
    assert 'name="qbittorrent_endpoint"' in html
    assert 'name="qbittorrent_username"' in html
    assert 'name="qbittorrent_password"' in html
    assert 'type="password"' in html
    assert 'name="qbittorrent_timeout_seconds"' in html
    assert 'name="qbittorrent_verify_tls"' in html
    assert 'id="settings-qbittorrent-result"' in html
    assert "尚未测试 qBittorrent 连接" in html
    assert "测试 qBittorrent 连接" in html
    assert "status、reachable 和 version" in html
    assert "qBittorrent 连接测试将在此处迁移" not in html
    assert 'id="settings-ab-submit-form"' in html
    assert 'id="settings-ab-request-id"' in html
    assert 'id="settings-ab-endpoint"' in html
    assert 'name="ab_submit_endpoint"' in html
    assert 'id="settings-ab-token"' in html
    assert 'name="ab_submit_token"' in html
    assert 'id="settings-ab-fallback-enabled"' in html
    assert 'name="ab_submit_fallback_enabled"' in html
    assert 'id="settings-ab-result"' in html
    assert 'id="settings-ab-return-link"' in html
    assert "仅 ACCEPTED Request 可提交" in html
    assert "尚未提交 Auto Bangumi" in html
    assert "/migu-orca-static/style.css" in html
    assert "/migu-orca-static/app.js" in html


def test_static_app_script_wires_request_list_and_detail_interactions() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "/api/v1/requests" in script
    assert "loadList" in script
    assert "loadDetail" in script
    assert "request-list-refresh" in script
    assert "selected_rss_url ? \"已选择\" : \"未选择\"" in script
    assert "有效种子标题" in script
    assert "状态历史" in script
    assert "Auto Bangumi 结果" in script
    assert "fallback_config" in script
    assert "folder_name" in script
    assert "filter_rule" in script
    assert "Overview" in script
    assert "Source" in script
    assert "Filter" in script
    assert "Seeds" in script
    assert "Audit" in script
    assert "复制 request_id" in script
    assert "copyTextToClipboard" in script
    assert "navigator.clipboard.writeText" in script
    assert "查看筛选种子列表" in script
    assert "seed-details" in script
    assert "modify-filter-use-regex" in script
    assert "modify-filter-case-sensitive" in script
    assert "使用正则" in script
    assert "大小写敏感" in script
    assert "包含规则" in script
    assert "排除规则" in script
    assert "literalExcludePattern" not in script
    assert "modify-must-not-contain-literal" not in script
    assert "暂无状态历史。" in script
    assert "暂无 Auto Bangumi 提交结果。" in script
    assert "提交 Auto Bangumi" in script
    assert "去 Settings 提交 Auto Bangumi" in script
    assert "settings-ab-submit-form" in script
    assert "settings-ab-endpoint" in script
    assert "settings-ab-token" in script
    assert "settings-ab-fallback-enabled" in script
    assert "Auto Bangumi 提交" in script
    assert "fallback_enabled" in script
    assert "window.confirm(\"确认提交此 Request 到 Auto Bangumi？\")" in script
    assert "storage_dir: currentStorageDir() || null" in script
    assert "requestIdFromLocation" in script
    assert "syncRequestIdToUrl" in script
    assert "url.searchParams.set(\"request_id\", requestId)" in script
    assert "window.addEventListener(\"popstate\"" in script
    assert "selectRequest(summary.request_id, {pushUrl: true})" in script
    assert "secret-token" not in script
    assert "http://" not in script
    assert "https://" not in script
    assert "<rss" not in script.lower()


def test_static_app_script_wires_auto_bangumi_submit_controls() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "currentDetailPayload" in script
    assert "status === \"ACCEPTED\"" in script
    assert "可提交到 Auto Bangumi" in script
    assert "settingsAbReturnLink.href" in script
    assert "clearSettingsAbSensitiveFields" in script
    assert "ab_submit_result" in script
    assert "提交成功" in script
    assert "提交失败" in script
    assert "notifyApiError" in script
    assert "提交失败" in script


def test_static_app_script_groups_request_detail_without_exposing_rss_url() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'createDetailSection("Overview", "overview-section")' in script
    assert 'createDetailSection("Source", "source-section")' in script
    assert 'createDetailSection("Filter", "filter-section")' in script
    assert 'createDetailSection("Seeds", "seeds-section")' in script
    assert 'createDetailSection("Audit", "audit-group-section")' in script
    assert '["request_id", request.request_id]' in script
    assert '["status", request.status]' in script
    assert '["原始标题", input.raw_title]' in script
    assert '["匹配标题", matched.title]' in script
    assert "copyButton.className = \"secondary-button copy-request-id\"" in script
    assert "copyTextToClipboard(request.request_id)" in script
    assert '["RSS 来源", config.selected_rss_url ? "已选择" : "未选择"]' in script
    assert '["包含规则", filterRule.must_contain]' in script
    assert '["排除规则", filterRule.must_not_contain]' in script
    assert '["匹配模式", matchMode]' in script
    assert '["大小写", caseMode]' in script
    assert '["folder_name", config.expected_folder_name]' in script
    assert '["有效种子数", effectiveSeeds.length]' in script
    assert '["排除种子数", excludedSeeds.length]' in script
    assert "source.seed_names || combinedSeedNames(validSeeds, excludedSeeds)" in script
    assert "完整种子" in script
    assert "renderExcludedSeedList" in script
    assert "document.createElement(\"details\")" in script
    assert "seedSummary.textContent" in script
    assert "renderHistorySection(auditSection, payload.history)" in script
    assert "renderAbResultSection(auditSection, payload.ab_result)" in script
    assert "selected_rss_url" in script
    assert "addDetailRow(fields, \"selected_rss_url\"" not in script


def test_static_app_script_shows_filter_mode_and_case_status_in_detail() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'var matchMode = filterRule.use_regex === true ? "正则" : "普通字符"' in script
    assert 'var caseMode = filterRule.case_sensitive === true ? "区分大小写" : "不区分大小写"' in script
    assert "匹配模式" in script
    assert "普通字符" in script
    assert "正则" in script
    assert "不区分大小写" in script
    assert "区分大小写" in script
    assert '["包含规则", filterRule.must_contain]' in script
    assert '["排除规则", filterRule.must_not_contain]' in script


def test_static_app_script_sends_regex_and_case_sensitive_filter_options() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "patch.filter_rule.use_regex = useRegex" in script
    assert "patch.filter_rule.case_sensitive = caseSensitive" in script
    assert "useRegex !== originalUseRegex" in script
    assert "caseSensitive !== originalCaseSensitive" in script
    assert "regexInput.checked = originalUseRegex" in script
    assert "caseInput.checked = originalCaseSensitive" in script
    # Stage 14 literal helper must not auto-transform raw filter text anymore.
    assert "escapeRegexLiteral" not in script
    assert "(?i:" not in script


def test_static_app_script_wires_page_notifications() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "page-notification" in script
    assert "showNotification" in script
    assert "hideNotification" in script
    assert "notifyApiError" in script
    assert "notification.hidden = false" in script
    assert "notification.replaceChildren()" in script
    assert "notification.setAttribute(\"role\", kind === \"error\" ? \"alert\" : \"status\")" in script
    assert "notification-close" in script
    assert "关闭" in script
    assert "预览已生成" in script
    assert "保存成功" in script
    assert "已保存 Request " in script
    assert "刷新列表" in script
    assert "查看详情" in script
    assert "Request 列表加载失败" in script
    assert "Request 详情加载失败" in script
    assert "校验失败" in script
    assert "error.errorData = payload.error_data || null" in script
    assert "summarizeValidationErrors" in script
    assert "field + \": \" + message" in script
    assert "safeText" in script
    assert "displayValue(value)" in script
    assert "secret-token" not in script
    assert "http://" not in script
    assert "https://" not in script
    assert "<rss" not in script.lower()


def test_static_app_script_renders_unsaved_preview_as_read_only() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "预览（未保存）" in script
    assert "预览模式：此 Request 尚未保存，只能查看" in script
    assert "保存此 Request" in script
    assert "async function savePreviewRequest" in script
    assert "buildCreateRequestPayload(title, {saveRequest: true})" in script
    assert "renderDetailPayload(result, {preview: !result.saved_request})" in script
    assert "selectedRequestId = result.saved_request ? generatedRequestId : null" in script
    assert "syncRequestIdToUrl(null, {replace: true})" in script
    assert script.index("if (isPreview)") < script.index("} else if (isPending)")
    assert script.index("if (isPreview)") < script.index(
        'performAction(request.request_id, "accept", {})'
    )


def test_static_app_script_shows_action_success_after_refresh() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    action_start = script.index("async function performAction")
    action_end = script.index("function buildModifyForm")
    action_script = script[action_start:action_end]
    assert action_script.index("await loadDetail(requestId);") < action_script.index(
        "showNotification(\"success\""
    )
    assert action_script.index("await loadList({loadSelectedDetail: false});") < action_script.index(
        "showNotification(\"success\""
    )


def test_static_app_script_wires_request_list_filter_sort_controls() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "request-list-search" in script
    assert "request-list-status-filter" in script
    assert "request-list-sort" in script
    assert "request-list-count" in script
    assert "loadedRequests" in script
    assert "searchableText" in script
    assert "syncStatusFilterOptions" in script
    assert "filteredAndSortedRequests" in script
    assert "summary.bangumi_title" in script
    assert "summary.request_id" in script
    assert "summary.selected_subtitle_group" in script
    assert "summary.expected_folder_name" in script
    assert "summary.folder_name" in script
    assert "summary.status" in script
    assert "listCount.textContent = \"显示 \"" in script
    assert "没有匹配的 Request。清空搜索或筛选后可恢复列表。" in script
    assert "listSearchInput.addEventListener(\"input\", renderList)" in script
    assert "listStatusFilter.addEventListener(\"change\", renderList)" in script
    assert "listSortSelect.addEventListener(\"change\", renderList)" in script
    assert "document.createElement(\"button\")" in script
    assert "item.type = \"button\"" in script
    assert 'item.setAttribute("aria-label", "查看 Request 详情：" + requestLabel(summary))' in script
    assert 'item.setAttribute("aria-current", "true")' in script
    assert "fetchJson(apiPath(\"/api/v1/requests\"))" in script
    assert "fetchJson(apiPath(\"/api/v1/requests?search" not in script
    assert "title_asc" in script
    assert "request_id_asc" in script
    assert "localeCompare" in script


def test_static_app_script_wires_generation_form_validation_and_busy_state() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "request-form-error" in script
    assert "request-generate-submit" in script
    assert "request-source" not in script
    assert "mikan-config-fields" not in script
    assert "await loadList({loadSelectedDetail: false});" in script
    assert "syncRequestIdToUrl(selectedRequestId)" in script
    assert "mikan-search-endpoint" not in script
    assert "mikan-timeout-seconds" not in script
    assert "setFormError" in script
    assert "clearFormError" in script
    assert "setSubmitInFlight" in script
    assert "syncMikanConfigVisibility" not in script
    assert "buildCreateRequestPayload" in script
    assert "titleInput.value.trim()" in script
    assert "请输入标题，至少包含 1 个非空白字符。" in script
    assert "选择 mikan 时必须填写 search_endpoint。" not in script
    assert "选择 mikan 时 timeout_seconds 必须为正数。" not in script
    assert "titleInput.focus()" in script
    assert "validationError.field.focus()" in script
    assert "setSubmitInFlight(true)" in script
    assert "setSubmitInFlight(false)" in script
    assert "正在生成..." in script
    assert '"title: title"' not in script
    assert "title: title" in script
    assert "source: \"static-fixture\"" in script
    assert "payload.source = \"mikan\"" not in script
    assert "payload.mikan_config" not in script
    generate_start = script.index("async function generateRequest")
    generate_end = script.index('refreshButton.addEventListener("click", loadList)')
    generate_script = script[generate_start:generate_end]
    assert generate_script.index("if (!title)") < generate_script.index(
        'fetchJson("/api/v1/requests"',
    )
    assert generate_script.index("buildCreateRequestPayload(title)") < generate_script.index(
        'fetchJson("/api/v1/requests"',
    )
    assert generate_script.index("setSubmitInFlight(true)") < generate_script.index(
        'fetchJson("/api/v1/requests"',
    )


def test_static_app_script_wires_local_web_preferences() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "miguOrca.web.storageDir" in script
    assert "miguOrca.web.saveRequest" in script
    assert "miguOrca.web.mikan" not in script
    assert "miguOrca.web.source" not in script
    assert "miguOrca.web.ab" not in script
    assert "sessionStorage" not in script
    assert "window.localStorage.getItem" in script
    assert "window.localStorage.setItem" in script
    assert "window.localStorage.removeItem" in script
    assert "restoreWebPreferences" in script
    assert "persistWebPreferences" in script
    assert "clearWebPreferences" in script
    assert "savedStorageDir" in script
    assert 'savedSaveRequest === null ? true : savedSaveRequest === "true"' in script
    assert "settingsStorageInput.value = storageDirPreference" in script
    assert "settingsSaveInput.checked = saveRequestPreference" in script
    assert "storage-preferences-clear" in script
    assert "storagePreferencesForm.addEventListener(\"submit\", persistWebPreferences)" in script
    assert script.index("restoreWebPreferences()") < script.index("loadList()")
    assert "currentSaveRequest()" in script


def test_static_app_script_wires_explicit_ab_submit_form() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "settings-ab-submit-form" in script
    assert "settings-ab-endpoint" in script
    assert "settings-ab-token" in script
    assert "settings-ab-fallback-enabled" in script
    assert "settingsAbTokenInput" in script
    assert "settingsAbFallbackInput" in script
    assert "initializeSettingsAbForm" in script
    assert "submitSettingsAb" in script
    assert "提交 Auto Bangumi 前必须填写 endpoint。" in script
    assert "提交 Auto Bangumi 前必须填写 token。" in script
    assert "确认提交此 Request 到 Auto Bangumi？" in script
    assert '"/submit-ab"' in script
    assert "storage_dir: currentStorageDir() || null" in script
    assert "ab_config" in script
    assert "fallback_enabled: settingsAbFallbackInput ? settingsAbFallbackInput.checked : false" in script
    assert "Auto Bangumi 提交成功" in script
    assert "clearSettingsAbSensitiveFields" in script
    assert "secret-token" not in script
    assert "Authorization" not in script
    assert "http://" not in script
    assert "https://" not in script


def test_static_app_script_wires_explicit_qbittorrent_connection_form() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "settings-qbittorrent-test-form" in script
    assert "settings-qbittorrent-endpoint" in script
    assert "settings-qbittorrent-username" in script
    assert "settings-qbittorrent-password" in script
    assert "settings-qbittorrent-timeout-seconds" in script
    assert "settings-qbittorrent-verify-tls" in script
    assert "settings-qbittorrent-error" in script
    assert "settings-qbittorrent-test-submit" in script
    assert "settings-qbittorrent-result" in script
    assert "buildQbittorrentConnectionPayload" in script
    assert "testQbittorrentConnection" in script
    assert "renderQbittorrentResult" in script
    assert "clearQbittorrentSensitiveFields" in script
    assert "测试 qBittorrent 前必须填写 endpoint。" in script
    assert "测试 qBittorrent 前必须填写 username。" in script
    assert "测试 qBittorrent 前必须填写 password。" in script
    assert "测试 qBittorrent 前 timeout_seconds 必须为正数。" in script
    assert "确认使用当前 qBittorrent 配置测试连接？" in script
    assert "/api/v1/qbittorrent/test-connection" in script
    assert "qbittorrent_config" in script
    assert '["endpoint", summary.endpoint]' not in script
    assert '["username", summary.username]' not in script
    assert '["password", summary.password]' not in script
    assert '["sid", summary.sid]' not in script
    assert '["session", summary.session]' not in script
    assert "qbittorrentEndpointInput.value = \"\"" in script
    assert "qbittorrentUsernameInput.value = \"\"" in script
    assert "qbittorrentPasswordInput.value = \"\"" in script
    assert "secret-session" not in script
    assert "private-password" not in script
    assert "http://" not in script
    assert "https://" not in script


def test_static_app_script_does_not_auto_test_qbittorrent_connection_on_load() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    initialization = script[script.rindex("restoreWebPreferences()"):]
    assert "loadList();" in initialization
    assert 'await testQbittorrentConnection' not in initialization
    assert 'testQbittorrentConnection();' not in initialization
    assert 'qbittorrentForm.addEventListener("submit", testQbittorrentConnection)' in initialization
    assert 'qbittorrentToggle.addEventListener("click"' not in initialization


def test_static_app_script_does_not_persist_qbittorrent_config() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "miguOrca.web.qbittorrent" not in script
    assert "miguOrca.web.qbt" not in script
    assert "sessionStorage" not in script
    assert "window.localStorage.getItem" in script
    assert "window.localStorage.setItem" in script
    assert "window.localStorage.removeItem" in script
    assert "qbittorrentEndpointInput.value" not in script[
        script.index("function persistWebPreferences"):script.index("function clearWebPreferences")
    ]
    assert "qbittorrentPasswordInput.value" not in script[
        script.index("function persistWebPreferences"):script.index("function clearWebPreferences")
    ]


def test_static_app_script_shows_ab_submit_only_for_accepted_requests() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'var isAccepted = request.status === "ACCEPTED";' in script
    assert "else if (isAccepted)" in script
    assert 'abSubmitBtn.textContent = "去 Settings 提交 Auto Bangumi"' in script
    assert '"/settings?request_id="' in script
    assert '"#auto-bangumi"' in script
    assert "detail-ab-submit-form" not in script
    assert "ab-submit-endpoint" not in script
    assert script.index("else if (isAccepted)") > script.index(
        'var isPending = request.status === "PENDING_CONFIRM";'
    )
    assert script.index('abSubmitBtn.textContent = "去 Settings 提交 Auto Bangumi"') < script.index(
        "actionsContainer.appendChild(abSubmitBtn)"
    )


def test_static_app_script_shows_modify_and_delete_for_accepted_requests() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "else if (isAccepted)" in script
    assert 'acceptedModifyBtn.textContent = "修改"' in script
    assert 'acceptedModifyBtn.className = "secondary-button detail-action"' in script
    assert 'deleteBtn.textContent = "删除"' in script
    assert 'deleteBtn.className = "danger-button detail-action"' in script
    assert "deleteRequest(request.request_id)" in script
    assert "async function deleteRequest(requestId)" in script
    assert "syncRequestIdToUrl(null)" in script
    assert 'actionsContainer.appendChild(deleteBtn)' in script
    # The delete button must render after the AB submit entry for ACCEPTED details.
    assert script.index('deleteBtn.textContent = "删除"') > script.index(
        'abSubmitBtn.textContent = "去 Settings 提交 Auto Bangumi"'
    )
    assert '"删除成功"' in script


def test_static_style_defines_generation_form_validation_states() -> None:
    response = _client().get("/migu-orca-static/style.css")

    css = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ".field-help" in css
    assert ".field-error" in css
    assert ".inline-config-fields" in css
    assert ".inline-config-fields[hidden]" in css
    assert 'input[aria-invalid="true"]' in css
    assert 'input[type="number"]' in css
    assert 'input[type="password"]' in css
    assert "button:disabled" in css
    assert ".secondary-button" in css


def test_static_style_defines_request_list_filter_controls() -> None:
    response = _client().get("/migu-orca-static/style.css")

    css = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ".request-list-controls" in css
    assert ".request-list-count" in css
    assert "select" in css
    assert "grid-template-columns: minmax(180px, 1fr)" in css
    assert "grid-template-columns: 1fr" in css


def test_static_style_defines_request_detail_sections() -> None:
    response = _client().get("/migu-orca-static/style.css")

    css = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ".detail-section" in css
    assert ".detail-inline-form" in css
    assert ".overview-actions" in css
    assert ".copy-request-id" in css
    assert ".seed-details summary" in css
    assert ".seed-groups" in css
    assert ".seed-exclude-reason" in css
    assert "overflow-wrap" in css
    assert ".audit-section" in css
    assert ".fallback-config" in css


def test_static_style_defines_page_notifications() -> None:
    response = _client().get("/migu-orca-static/style.css")

    css = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ".page-notification" in css
    assert ".page-notification[hidden]" in css
    assert ".notification-success" in css
    assert ".notification-error" in css
    assert ".notification-detail" in css
    assert ".notification-actions" in css
    assert ".notification-close" in css


def test_static_style_defines_qbittorrent_connection_panel() -> None:
    response = _client().get("/migu-orca-static/style.css")

    css = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ".qbittorrent-panel" in css
    assert ".qbittorrent-result" in css
    assert ".qbittorrent-result-success" in css
    assert "grid-column: 1 / -1" in css
    assert "background: #edf8f0" in css
    assert "border: 1px solid #abd3b6" in css


def test_static_style_defines_responsive_accessibility_contracts() -> None:
    response = _client().get("/migu-orca-static/style.css")

    css = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ":where(a, button, input, select, summary):focus-visible" in css
    assert "outline: 3px solid #22577a" in css
    assert "outline-offset: 2px" in css
    assert ".panel" in css
    assert "min-width: 0" in css
    assert "max-width: 100%" in css
    assert ".request-list-item strong" in css
    assert "overflow-wrap: anywhere" in css
    assert "@media (max-width: 760px)" in css
    assert "@media (max-width: 520px)" in css
    assert ".app-layout" in css
    assert "grid-template-columns: 1fr" in css
    assert ".top-nav a,\n  button" in css
    assert "width: 100%" in css


def test_list_requests_returns_empty_list_for_missing_storage_dir(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": str(tmp_path / "missing-storage")},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "result": {"requests": []}}


def test_list_requests_returns_saved_request_summaries(tmp_path: Path) -> None:
    request_b = _saved_request(tmp_path, "芙莉莲", "request-b")
    request_a = _saved_request(tmp_path, "咒术回战第三季", "request-a")

    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "result": {
            "requests": [
                summarize_request(request_a),
                summarize_request(request_b),
            ]
        },
    }


def test_get_request_detail_returns_complete_saved_snapshot(tmp_path: Path) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "result": {
            "request": request,
            "history": {"available": True, "events": [], "error": None},
            "ab_result": {"available": False, "record": None, "error": None},
        },
    }


def test_get_request_detail_returns_saved_history_and_ab_result(
    tmp_path: Path,
) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")
    config = load_storage_config(tmp_path / "storage")
    event = {
        "request_id": "request-1",
        "previous_status": "PENDING_CONFIRM",
        "next_status": "ACCEPTED",
        "action": "ACCEPT",
        "timestamp": "2026-08-06T12:00:00+00:00",
    }
    append_status_history(config, event)
    request["ab_submit_result"] = {
        "success": False,
        "ab_subscription_id": None,
        "ab_response": None,
        "fallback_config": {
            "title": "芙莉莲",
            "rss_url": "https://example.invalid/rss.xml",
            "save_path": "芙莉莲",
        },
        "error": None,
    }
    save_ab_submit_result(config, request)

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["history"] == {
        "available": True,
        "events": [event],
        "error": None,
    }
    assert payload["result"]["ab_result"]["available"] is True
    assert payload["result"]["ab_result"]["record"]["request_id"] == "request-1"
    assert (
        payload["result"]["ab_result"]["record"]["ab_submit_result"]
        == request["ab_submit_result"]
    )


def test_get_request_detail_treats_damaged_history_as_nonfatal(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-1")
    config = load_storage_config(tmp_path / "storage")
    config.history_dir.mkdir(parents=True, exist_ok=True)
    (config.history_dir / "request-1.json").write_text("{", encoding="utf-8")

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["request_id"] == "request-1"
    assert payload["result"]["history"]["available"] is False
    assert payload["result"]["history"]["events"] == []
    assert payload["result"]["history"]["error"]["error_type"] == "storage_json_error"
    assert str(tmp_path) not in str(payload)


def test_get_request_detail_treats_damaged_ab_result_as_nonfatal(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-1")
    config = load_storage_config(tmp_path / "storage")
    config.ab_results_dir.mkdir(parents=True, exist_ok=True)
    (config.ab_results_dir / "request-1.json").write_text("[", encoding="utf-8")

    response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["request_id"] == "request-1"
    assert payload["result"]["ab_result"]["available"] is False
    assert payload["result"]["ab_result"]["record"] is None
    assert payload["result"]["ab_result"]["error"]["error_type"] == "storage_json_error"
    assert str(tmp_path) not in str(payload)


def test_get_request_detail_returns_unified_error_for_missing_request(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests/missing-request",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "request_not_found",
        "error_message": "未找到已保存的 Request",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"request_id": "missing-request"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_get_request_detail_rejects_path_fragments_without_leaking_storage_path(
    tmp_path: Path,
) -> None:
    response = _client().get(
        "/api/v1/requests/nested%2Frequest",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "invalid_request_id",
        "error_message": "request_id 不能包含路径片段",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"field": "request_id"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_list_requests_returns_unified_error_for_damaged_snapshot(
    tmp_path: Path,
) -> None:
    config = load_storage_config(tmp_path / "storage")
    config.requests_dir.mkdir(parents=True)
    (config.requests_dir / "broken.json").write_text("{", encoding="utf-8")

    response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_json_error"
    assert payload["error_data"]["failed_step"] == "load_request_snapshot"
    assert payload["error_data"]["details"]["request_id"] == "broken"
    assert str(tmp_path) not in str(payload)


def test_delete_request_removes_saved_request_and_refreshes_list_and_detail(
    tmp_path: Path,
) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")
    storage_dir = tmp_path / "storage"

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/delete",
        json={"storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {
            "request_id": "request-1",
            "storage": "local_json",
            "directory": "requests",
            "filename": "request-1.json",
            "deleted": True,
        },
    }
    assert not (storage_dir / "requests" / "request-1.json").exists()

    list_response = _client().get(
        "/api/v1/requests",
        query_string={"storage_dir": str(storage_dir)},
    )
    assert list_response.get_json() == {"ok": True, "result": {"requests": []}}

    detail_response = _client().get(
        "/api/v1/requests/request-1",
        query_string={"storage_dir": str(storage_dir)},
    )
    assert detail_response.get_json() == {
        "ok": False,
        "error_type": "request_not_found",
        "error_message": "未找到已保存的 Request",
        "error_data": {
            "failed_step": "load_request_snapshot",
            "details": {"request_id": "request-1"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_delete_request_returns_unified_error_for_missing_request(
    tmp_path: Path,
) -> None:
    response = _client().post(
        "/api/v1/requests/missing-request/delete",
        json={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "request_not_found",
        "error_message": "未找到已保存的 Request",
        "error_data": {
            "failed_step": "delete_request_snapshot",
            "details": {"request_id": "missing-request"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_delete_request_rejects_path_fragments_without_leaking_storage_path(
    tmp_path: Path,
) -> None:
    response = _client().post(
        "/api/v1/requests/nested%2Frequest/delete",
        json={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "invalid_request_id",
        "error_message": "request_id 不能包含路径片段",
        "error_data": {
            "failed_step": "delete_request_snapshot",
            "details": {"field": "request_id"},
        },
    }
    assert str(tmp_path) not in str(payload)


def test_delete_request_returns_unified_error_for_delete_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_delete(*args: object, **kwargs: object) -> dict[str, object]:
        raise Stage1Error(
            "storage_error",
            f"删除 Request JSON 失败 {tmp_path}/secret-token",
            "delete_request_snapshot",
            {
                "request_id": "request-1",
                "directory": "requests",
                "reason": f"cannot unlink {tmp_path}/requests/request-1.json",
            },
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.delete_request_snapshot",
        fail_delete,
    )

    response = _client().post(
        "/api/v1/requests/request-1/delete",
        json={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    serialized = str(payload)
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_error"
    assert payload["error_data"]["failed_step"] == "delete_request_snapshot"
    assert payload["error_data"]["details"]["directory"] == "requests"
    assert str(tmp_path) not in serialized
    assert "secret-token" not in serialized


def test_modify_accepted_request_preserves_status_and_records_history(
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path, "芙莉莲", "request-1")
    storage_dir = tmp_path / "storage"
    patch = {"expected_folder_name": "芙莉莲 修改版"}

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/modify",
        json={
            "storage_dir": str(storage_dir),
            "patch": patch,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["status"] == "ACCEPTED"
    assert (
        payload["result"]["request"]["confirmable_config"]["expected_folder_name"]
        == "芙莉莲 修改版"
    )
    assert payload["result"]["summary"]["status"] == "ACCEPTED"

    detail_response = _client().get(
        f"/api/v1/requests/{request['request_id']}",
        query_string={"storage_dir": str(storage_dir)},
    )
    detail = detail_response.get_json()
    assert detail["ok"] is True
    assert detail["result"]["history"]["available"] is True
    assert detail["result"]["history"]["events"] == [
        {
            "request_id": "request-1",
            "previous_status": "ACCEPTED",
            "next_status": "ACCEPTED",
            "action": "MODIFY",
            "timestamp": payload["result"]["request"]["updated_at"],
            "details": {"patch": patch},
        }
    ]


def test_modify_accepted_request_recomputes_seeds_and_rejects_cancelled(
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path, "芙莉莲", "request-1")
    cancelled = _saved_cancelled_request(tmp_path, "咒术回战", "request-cancelled")
    storage_dir = tmp_path / "storage"

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/modify",
        json={
            "storage_dir": str(storage_dir),
            "patch": {"filter_rule": {"must_contain": "01", "must_not_contain": ""}},
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["status"] == "ACCEPTED"
    assert payload["result"]["request"]["confirmable_config"]["filter_rule"] == {
        "must_contain": "01",
        "must_not_contain": "",
        "use_regex": False,
        "case_sensitive": False,
    }
    assert payload["result"]["summary"]["effective_seed_count"] == 1

    cancel_response = _client().post(
        f"/api/v1/requests/{cancelled['request_id']}/modify",
        json={
            "storage_dir": str(storage_dir),
            "patch": {"expected_folder_name": "不应成功"},
        },
    )
    cancel_payload = cancel_response.get_json()
    assert cancel_payload["ok"] is False
    assert cancel_payload["error_type"] == "invalid_request_status"
    assert cancel_payload["error_data"]["details"] == {"status": "CANCELLED"}
    assert str(tmp_path) not in str(cancel_payload)


def test_create_request_generates_without_writing_storage(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": str(storage_dir),
            "save_request": False,
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert request["input"]["raw_title"] == "芙莉莲"
    assert payload["result"]["summary"] == summarize_request(request)
    assert "saved_request" not in payload["result"]
    assert not storage_dir.exists()


def test_create_request_defaults_to_static_fixture_without_mikan_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def spy_generate_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["source_mode"] = kwargs.get("source_mode")
        captured["mikan_config"] = kwargs.get("mikan_config")
        return generate_request(*args, **kwargs)

    monkeypatch.setattr("apps.migu_orca_web.views.generate_request", spy_generate_request)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "save_request": False,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["source_mode"] == "static_fixture"
    assert captured["mikan_config"] is None
    assert payload["result"]["request"]["input"]["raw_title"] == "芙莉莲"


def test_create_request_uses_inline_mikan_config_when_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    factory_configs: list[MikanConfig] = []

    def fake_create_mikan_client(config: MikanConfig) -> _FakeMikanClient:
        factory_configs.append(config)
        transport = _FakeMikanTransport(
            {
                "https://mikan.example/RSS/Bangumi?bangumiId=123": (
                    "<rss><channel><item><title>芙莉莲 - 01</title>"
                    "<link>https://example.invalid/1</link></item></channel></rss>"
                )
            }
        )
        return _FakeMikanClient(config, transport)

    def spy_generate_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["source_mode"] = kwargs.get("source_mode")
        captured["mikan_config"] = kwargs.get("mikan_config")
        return generate_request(*args, **kwargs)

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )
    monkeypatch.setattr("apps.migu_orca_web.views.generate_request", spy_generate_request)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "mikan",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
            "save_request": False,
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["source_mode"] == "mikan_http"
    assert isinstance(captured["mikan_config"], MikanConfig)
    assert captured["mikan_config"].search_endpoint == "https://mikan.example/Home/Search"
    assert captured["mikan_config"].timeout_seconds == 5.0
    assert factory_configs == [captured["mikan_config"]]
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"
    assert request["confirmable_config"]["selected_rss_url"] == "https://mikan.example/RSS/Bangumi?bangumiId=123"


def test_create_request_accepts_request_scoped_mikan_direct_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Bangumi/123": (
                '<h1 class="bangumi-title">芙莉莲</h1>'
                '<a class="mikan-rss" href="/RSS/Bangumi?bangumiId=123">RSS</a>'
                '<section class="subgroup-section">'
                '<h2 class="subgroup-name">Loli</h2>'
                '<a href="/RSS/Bangumi?bangumiId=123&subgroupid=10">RSS</a>'
                "</section>"
            ),
            "https://mikan.example/RSS/Bangumi?bangumiId=123&subgroupid=10": (
                "<rss><channel><item><title>芙莉莲 - 01</title>"
                "<link>https://example.invalid/1</link></item></channel></rss>"
            ),
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "不会用于搜索",
            "source": "mikan",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
            "mikan_bangumi": "123",
            "storage_dir": str(storage_dir),
            "save_request": True,
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    saved_path = storage_dir / "requests" / payload["result"]["saved_request"]["filename"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert transport.requests == [
        ("https://mikan.example/Home/Bangumi/123", 5.0),
        ("https://mikan.example/RSS/Bangumi?bangumiId=123&subgroupid=10", 5.0),
    ]
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert (
        request["source_info"]["matched_bangumi"]["mikan_url"]
        == "https://mikan.example/Home/Bangumi/123"
    )
    assert saved_path.exists()
    assert "mikan_bangumi" not in saved_path.read_text(encoding="utf-8")


def test_create_request_rejects_invalid_mikan_direct_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("generate_request should not be called for invalid payload")

    monkeypatch.setattr("apps.migu_orca_web.views.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "mikan",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
            "mikan_bangumi": "   ",
            "save_request": False,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "mikan_bangumi"
        for error in payload["error_data"]["errors"]
    )
    assert called is False


def test_create_request_rejects_missing_mikan_config_when_source_is_mikan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("generate_request should not be called for invalid payload")

    monkeypatch.setattr("apps.migu_orca_web.views.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "mikan",
            "save_request": False,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "mikan_config"
        for error in payload["error_data"]["errors"]
    )
    assert called is False


def test_create_request_rejects_unsupported_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("generate_request should not be called for invalid payload")

    monkeypatch.setattr("apps.migu_orca_web.views.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "real-live-mikan",
            "save_request": False,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "source"
    assert called is False


def test_create_request_rejects_invalid_mikan_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("generate_request should not be called for invalid payload")

    monkeypatch.setattr("apps.migu_orca_web.views.generate_request", fail_if_called)

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "source": "mikan",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 0,
            },
            "save_request": False,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"].startswith("mikan_config.timeout_seconds")
        for error in payload["error_data"]["errors"]
    )
    assert called is False


def test_create_request_saves_when_explicitly_requested(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": str(storage_dir),
            "save_request": True,
        },
    )

    payload = response.get_json()
    saved_request = payload["result"]["saved_request"]
    saved_path = storage_dir / "requests" / saved_request["filename"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert saved_request == {
        "request_id": payload["result"]["request"]["request_id"],
        "storage": "local_json",
        "directory": "requests",
        "filename": f"{payload['result']['request']['request_id']}.json",
    }
    assert saved_path.exists()


def test_create_request_returns_validation_error_for_missing_title() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"save_request": False},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "title"


def test_create_request_returns_validation_error_for_blank_title() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"title": "   "},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "title"


def test_create_request_returns_validation_error_for_invalid_storage_dir_type() -> None:
    response = _client().post(
        "/api/v1/requests",
        json={"title": "芙莉莲", "storage_dir": 123},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "storage_dir"


def test_create_request_returns_unified_error_for_save_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_save(*args: object, **kwargs: object) -> dict[str, Any]:
        return {
            "success": False,
            "request": None,
            "error": Stage1Error(
                "storage_error",
                "保存 Request JSON 失败",
                "save_request_snapshot",
                {
                    "reason": f"cannot write {tmp_path}/private-token at https://example.test/api",
                    "directory": "requests",
                },
            ).as_dict(),
        }

    monkeypatch.setattr(
        "apps.migu_orca_web.views.apply_request_save_action",
        fail_save,
    )

    response = _client().post(
        "/api/v1/requests",
        json={
            "title": "芙莉莲",
            "storage_dir": str(tmp_path / "storage"),
            "save_request": True,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_error"
    assert payload["error_message"] == "保存 Request JSON 失败"
    assert payload["error_data"]["failed_step"] == "save_request_snapshot"
    assert payload["error_data"]["details"]["directory"] == "requests"
    assert str(tmp_path) not in str(payload)
    assert "https://example.test/api" not in str(payload)
    assert "token" not in str(payload).lower()


def test_submit_ab_accepts_request_scoped_config_and_persists_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path)
    storage_dir = tmp_path / "storage"
    client = FakeAutoBangumiClient()
    factory_configs = []

    def build_client(ab_config):
        factory_configs.append(ab_config)
        return client

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.ab_http_client.create_auto_bangumi_http_client",
        build_client,
    )

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/submit-ab",
        json={
            "storage_dir": str(storage_dir),
            "ab_config": {
                "endpoint": "http://auto-bangumi.local/api/subscriptions",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    result = payload["result"]
    saved_request = load_storage_config(storage_dir).requests_dir / (
        f"{request['request_id']}.json"
    )
    saved_ab_result = load_storage_config(storage_dir).ab_results_dir / (
        f"{request['request_id']}.json"
    )
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["request"]["status"] == "ACCEPTED"
    assert result["ab_submit_result"] == {
        "success": True,
        "ab_subscription_id": "fake-ab-subscription",
        "ab_response": {"id": "fake-ab-subscription", "status": "created"},
        "fallback_config": None,
        "error": None,
    }
    assert result["request"]["ab_submit_result"] == result["ab_submit_result"]
    assert result["saved_request"]["request_id"] == request["request_id"]
    assert result["saved_ab_result"]["request_id"] == request["request_id"]
    assert saved_request.exists()
    assert saved_ab_result.exists()
    assert factory_configs[0].endpoint == "http://auto-bangumi.local/api/subscriptions"
    assert factory_configs[0].token == "secret-token"
    assert client.calls
    assert "secret-token" not in saved_request.read_text(encoding="utf-8")
    assert "auto-bangumi.local" not in saved_request.read_text(encoding="utf-8")
    assert "secret-token" not in saved_ab_result.read_text(encoding="utf-8")
    assert "auto-bangumi.local" not in saved_ab_result.read_text(encoding="utf-8")


def test_submit_ab_persists_sanitized_fallback_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path)
    storage_dir = tmp_path / "storage"
    client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "Auto Bangumi rejected http://auto-bangumi.local/api secret-token",
            "create_ab_subscription",
            {
                "Authorization": "Bearer secret-token",
                "endpoint": "http://auto-bangumi.local/api",
            },
        )
    )
    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: client,
    )

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/submit-ab",
        json={
            "storage_dir": str(storage_dir),
            "ab_config": {
                "endpoint": "http://auto-bangumi.local/api",
                "token": "secret-token",
                "fallback_enabled": True,
            },
        },
    )

    payload = response.get_json()
    serialized = str(payload)
    saved_ab_result = (
        load_storage_config(storage_dir).ab_results_dir / f"{request['request_id']}.json"
    ).read_text(encoding="utf-8")
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["ab_submit_result"]["success"] is False
    assert payload["result"]["ab_submit_result"]["fallback_config"]["title"]
    assert "secret-token" not in serialized
    assert "auto-bangumi.local" not in serialized
    assert "Authorization" not in serialized
    assert "secret-token" not in saved_ab_result
    assert "auto-bangumi.local" not in saved_ab_result


def test_submit_ab_rejects_missing_token_without_calling_ab(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path)
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("AB client should not be created for invalid payload")

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.ab_http_client.create_auto_bangumi_http_client",
        fail_if_called,
    )

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/submit-ab",
        json={
            "storage_dir": str(tmp_path / "storage"),
            "ab_config": {
                "endpoint": "http://auto-bangumi.local/api",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "ab_config.[redacted]"
        for error in payload["error_data"]["errors"]
    )
    assert called is False
    assert "auto-bangumi.local" not in str(payload)


def test_submit_ab_rejects_non_accepted_request(tmp_path: Path) -> None:
    request = _saved_request(tmp_path, "芙莉莲", "request-1")

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/submit-ab",
        json={
            "storage_dir": str(tmp_path / "storage"),
            "ab_config": {
                "endpoint": "http://auto-bangumi.local/api",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_request_status"
    assert payload["error_message"] == "只有 ACCEPTED Request 可以提交到 Auto Bangumi"
    assert payload["error_data"]["failed_step"] == "build_ab_subscription_payload"
    assert "secret-token" not in str(payload)
    assert "auto-bangumi.local" not in str(payload)


def test_submit_ab_sanitizes_echoed_ab_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _saved_accepted_request(tmp_path)
    storage_dir = tmp_path / "storage"
    client = FakeAutoBangumiClient(
        response={
            "id": "sub-123",
            "endpoint": "http://auto-bangumi.local/api",
            "Authorization": "Bearer secret-token",
        }
    )
    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: client,
    )

    response = _client().post(
        f"/api/v1/requests/{request['request_id']}/submit-ab",
        json={
            "storage_dir": str(storage_dir),
            "ab_config": {
                "endpoint": "http://auto-bangumi.local/api",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    saved_ab_result = (
        load_storage_config(storage_dir).ab_results_dir / f"{request['request_id']}.json"
    ).read_text(encoding="utf-8")
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["ab_submit_result"]["ab_response"] == {
        "id": "sub-123",
        "endpoint": "[redacted-url]",
        "[redacted]": "[redacted]",
    }
    assert "secret-token" not in str(payload)
    assert "auto-bangumi.local" not in str(payload)
    assert "secret-token" not in saved_ab_result
    assert "auto-bangumi.local" not in saved_ab_result


def test_qbittorrent_test_connection_returns_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_test_qbittorrent_connection(
        *,
        qbittorrent_config: QBittorrentConfig,
    ) -> dict[str, Any]:
        captured["config"] = qbittorrent_config
        return {
            "success": True,
            "summary": {
                "status": "connected",
                "reachable": True,
                "version": "v4.6.7",
                "endpoint": "http://qbittorrent.local:8080",
                "username": "private-user",
                "password": "private-password",
                "cookie": "SID=secret-session",
            },
            "error": None,
        }

    monkeypatch.setattr(
        "apps.migu_orca_web.views.test_qbittorrent_connection",
        fake_test_qbittorrent_connection,
    )

    response = _client().post(
        "/api/v1/qbittorrent/test-connection",
        json={
            "qbittorrent_config": {
                "endpoint": "http://qbittorrent.local:8080",
                "username": "private-user",
                "password": "private-password",
                "timeout_seconds": 7,
                "verify_tls": False,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {
            "status": "connected",
            "reachable": True,
            "version": "v4.6.7",
        },
    }
    assert "private-user" not in str(payload)
    assert "private-password" not in str(payload)
    assert "SID=secret-session" not in str(payload)
    assert "qbittorrent.local" not in str(payload)
    assert captured["config"] == QBittorrentConfig(
        endpoint="http://qbittorrent.local:8080",
        username="private-user",
        password="private-password",
        timeout_seconds=7.0,
        verify_tls=False,
    )


def test_qbittorrent_test_connection_requires_password_without_calling_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("qBittorrent controller should not be called")

    monkeypatch.setattr(
        "apps.migu_orca_web.views.test_qbittorrent_connection",
        fail_if_called,
    )

    response = _client().post(
        "/api/v1/qbittorrent/test-connection",
        json={
            "qbittorrent_config": {
                "endpoint": "http://qbittorrent.local:8080",
                "username": "private-user",
                "timeout_seconds": 7,
                "verify_tls": True,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "qbittorrent_config.[redacted]"
        for error in payload["error_data"]["errors"]
    )
    assert called is False
    assert "private-user" not in str(payload)
    assert "qbittorrent.local" not in str(payload)


@pytest.mark.parametrize(
    ("controller_result", "expected_error_type"),
    [
        (
            {
                "success": False,
                "summary": None,
                "error": {
                    "error_type": "qbittorrent_auth_failed",
                    "error_message": (
                        "qBittorrent 认证失败 http://qbittorrent.local:8080 "
                        "private-user private-password SID=secret-session"
                    ),
                    "failed_step": "qbittorrent_login",
                    "details": {
                        "category": "auth",
                        "endpoint": "http://qbittorrent.local:8080",
                        "username": "private-user",
                        "password": "private-password",
                        "cookie": "SID=secret-session",
                    },
                },
            },
            "qbittorrent_auth_failed",
        ),
        (
            {
                "success": False,
                "summary": None,
                "error": {
                    "error_type": "qbittorrent_timeout",
                    "error_message": "qBittorrent HTTP 请求超时",
                    "failed_step": "qbittorrent_login",
                    "details": {"category": "timeout"},
                },
            },
            "qbittorrent_timeout",
        ),
    ],
)
def test_qbittorrent_test_connection_returns_sanitized_failures(
    monkeypatch: pytest.MonkeyPatch,
    controller_result: dict[str, Any],
    expected_error_type: str,
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.views.test_qbittorrent_connection",
        lambda *, qbittorrent_config: controller_result,
    )

    response = _client().post(
        "/api/v1/qbittorrent/test-connection",
        json={
            "qbittorrent_config": {
                "endpoint": "http://qbittorrent.local:8080",
                "username": "private-user",
                "password": "private-password",
                "timeout_seconds": 7,
                "verify_tls": True,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == expected_error_type
    assert payload["error_data"]["failed_step"] == controller_result["error"][
        "failed_step"
    ]
    assert "private-user" not in str(payload)
    assert "private-password" not in str(payload)
    assert "SID=secret-session" not in str(payload)
    assert "qbittorrent.local" not in str(payload)


def test_qbittorrent_test_connection_rejects_invalid_endpoint() -> None:
    response = _client().post(
        "/api/v1/qbittorrent/test-connection",
        json={
            "qbittorrent_config": {
                "endpoint": "qbittorrent.local:8080",
                "username": "private-user",
                "password": "private-password",
                "timeout_seconds": 7,
                "verify_tls": True,
            }
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "config_error"
    assert payload["error_message"] == "qBittorrent endpoint 必须是 http(s) URL"
    assert payload["error_data"]["failed_step"] == "load_qbittorrent_config"
    assert "private-user" not in str(payload)
    assert "private-password" not in str(payload)
    assert "qbittorrent.local" not in str(payload)


def test_qbittorrent_test_connection_rejects_missing_config_object() -> None:
    response = _client().post(
        "/api/v1/qbittorrent/test-connection",
        json={},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert payload["error_data"]["errors"][0]["field"] == "qbittorrent_config"
