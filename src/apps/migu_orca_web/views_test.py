from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient
import pytest

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from batch_engine.controllers.anime_title_parser import FakeAnimeTitleParsingProvider
from batch_engine.controllers.batch_queue_controller import (
    complete_queue_item_submit,
    create_submission_queue,
    enqueue_item,
    start_queue_item_submit,
)
from batch_engine.models import (
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_PARSED,
    BATCH_QUEUE_STATUS_FAILED,
    BATCH_QUEUE_STATUS_READY_TO_SUBMIT,
    BATCH_QUEUE_STATUS_RETRYABLE,
    BATCH_QUEUE_STATUS_SUCCEEDED,
)
from mikan_engine.controllers.mikan_client import MikanCandidate, create_mikan_client
from mikan_engine.controllers.mikan_config import (
    DEFAULT_MIKAN_SEARCH_ENDPOINT,
    DEFAULT_MIKAN_TIMEOUT_SECONDS,
    MikanConfig,
    default_mikan_config,
)
from qbittorrent_engine.controllers.qbittorrent_config import QBittorrentConfig
from request_engine.controllers.request_controller import (
    accept_request,
    cancel_request,
    summarize_request,
)
from shared.errors import Stage1Error
from shared.models import (
    BangumiCandidate,
    EntryRequest,
    FilterDefaults,
    MatchedBangumi,
    NamingPreference,
    RssSource,
    SearchPreference,
    SubtitleGroupPreference,
    VersionedUserPreference,
)
from storage_engine.controllers.preference_repository import save_user_preferences
from storage_engine.controllers.ab_result_repository import (
    load_ab_submit_result,
    save_ab_submit_result,
)
from storage_engine.controllers.history_repository import (
    append_status_history,
    load_status_history,
)
from storage_engine.controllers.request_repository import (
    delete_request_snapshot,
    load_request_snapshot,
    save_request_snapshot,
)
from storage_engine.controllers.queue_repository import (
    load_submission_queue,
    save_submission_queue,
)
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


@pytest.fixture(autouse=True)
def _clear_candidate_cache() -> None:
    """Reset the shared in-process candidate cache before every view test.

    The candidate search cache is a process-level singleton, so tests that do not
    opt into cache behavior must never observe entries written by earlier tests.
    """
    from mikan_engine.controllers.mikan_candidate_cache import candidate_search_cache

    candidate_search_cache.clear()


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


class _FakeCandidateSearchClient:
    def __init__(
        self,
        candidates: list[Any] | None = None,
        error: Stage1Error | None = None,
    ) -> None:
        self.candidates = candidates or []
        self.error = error
        self.searches: list[str] = []

    def search_candidates(self, raw_title: str) -> list[Any]:
        self.searches.append(raw_title)
        if self.error is not None:
            raise self.error
        return self.candidates


class _MappedCandidateSearchClient:
    def __init__(
        self,
        responses: dict[str, list[MikanCandidate]] | None = None,
        errors: dict[str, Stage1Error] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.errors = errors or {}
        self.searches: list[str] = []

    def search_candidates(self, raw_title: str) -> list[MikanCandidate]:
        self.searches.append(raw_title)
        if raw_title in self.errors:
            raise self.errors[raw_title]
        return self.responses.get(raw_title, [])


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
    assert "<title>MiGuOrca 订阅方案工作台</title>" in html
    assert "Stage 13 订阅方案工作台" in html
    assert "Stage 7 Web UI MVP" not in html
    assert "Stage 8 Web UI Usability" not in html
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "运行模式：本地 JSON storage" in html
    assert "主流程通过真实 MiKan 候选搜索" in html
    assert "fixture-backed 生成保留在开发/离线测试区域" in html
    assert "外部数据源、连接测试与提交配置集中在 Settings" in html
    assert "真实 MiKan 候选搜索" in html
    assert "订阅方案列表" in html
    assert "订阅方案详情" in html
    assert 'href="/index"' in html
    assert 'href="/settings"' in html
    assert 'aria-current="page"' in html
    assert "订阅方案工作台" in html
    assert "Settings" in html
    assert 'id="generate-panel"' in html
    assert 'id="request-list-panel"' in html
    assert 'id="request-detail-panel"' in html
    assert 'id="dev-fixture-panel"' in html
    assert 'id="dev-fixture-disclosure"' in html
    assert 'id="dev-fixture-disclosure" open' not in html
    assert "默认收起" in html
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
    assert 'id="mikan-candidate-search-form"' in html
    assert 'id="mikan-candidate-query"' in html
    assert 'name="mikan_candidate_title"' in html
    assert 'id="batch-workbench-entry"' in html
    assert 'id="batch-parse-form"' in html
    assert 'id="batch-raw-input"' in html
    assert 'name="batch_raw_input"' in html
    assert "批量新番草案" in html
    assert "萌王S4" in html
    assert "路哥S4" in html
    assert "杖剑谭S2" in html
    assert "邻家天使S2" in html
    assert 'id="batch-parse-submit"' in html
    assert 'id="batch-parse-result"' in html
    assert 'id="batch-parse-error"' in html
    assert 'id="batch-accept-toolbar"' in html
    assert 'id="batch-select-all-checkbox"' in html
    assert 'id="batch-accept-selected-count"' in html
    assert 'id="batch-accept-submit"' in html
    assert 'id="batch-accept-all"' in html
    assert "已选择 0 项" in html
    assert "批量接受" in html
    assert "全接受" in html
    assert 'id="batch-queue-panel"' in html
    assert 'id="batch-queue-heading"' in html
    assert "提交前队列" in html
    assert 'id="batch-queue-refresh"' in html
    assert 'id="batch-queue-count"' in html
    assert 'id="batch-queue-list"' in html
    assert 'id="batch-queue-submit-form"' in html
    assert '<form id="batch-queue-submit-form" method="post" hidden>' in html
    assert 'id="batch-queue-ab-fallback-enabled"' in html
    assert 'id="batch-queue-ab-confirm"' in html
    assert "我已确认将这些订阅方案提交到 Auto Bangumi" in html
    assert 'id="batch-queue-submit-result"' in html
    assert 'id="batch-queue-submit-button"' in html
    assert "提交队列" in html
    assert 'id="mikan-candidate-search-endpoint"' not in html
    assert 'id="mikan-candidate-timeout-seconds"' not in html
    assert 'name="mikan_candidate_search_endpoint"' not in html
    assert 'name="mikan_candidate_timeout_seconds"' not in html
    assert 'id="mikan-candidate-search-submit"' in html
    assert 'id="mikan-candidate-search-result"' in html
    assert "search_endpoint" not in html
    assert "timeout_seconds" not in html
    assert 'id="mikan-fallback-enabled"' in html
    assert 'name="mikan_fallback_enabled"' in html
    assert "搜索无结果时使用直连合集" in html
    assert 'id="mikan-fallback-form"' in html
    assert 'id="mikan-fallback-form" class="candidate-fallback-form" hidden' in html
    assert 'id="mikan-fallback-bangumi"' in html
    assert 'name="mikan_fallback_bangumi"' in html
    assert 'id="mikan-fallback-help"' in html
    assert 'id="mikan-fallback-error"' in html
    assert 'id="mikan-fallback-generate"' in html
    assert 'name="storage_dir"' not in html
    assert 'name="save_request"' not in html
    assert 'id="storage-preference-summary"' in html
    assert "当前使用默认 `.migu_orca/storage`" in html
    assert "前往 Settings" in html
    assert 'id="request-form-error"' in html
    assert 'role="alert"' in html
    assert 'id="request-generate-submit"' in html
    assert 'data-default-label="生成"' in html
    assert "开发 / 离线测试" in html
    assert "Fixture 生成（开发 / 离线测试路径，不使用真实 MiKan）" in html
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
    assert "<option value=\"\">全部</option>" in html
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
    assert 'aria-label="刷新订阅方案列表"' in html
    assert 'aria-relevant="additions text"' in html
    assert "/migu-orca-static/app.js" in html
    # Stage 20 (US-147) adds an explicit request-scoped Auto Bangumi submit form
    # to the batch pre-submission queue panel, so endpoint/token field names are
    # legitimately present on /index (mirroring the Settings pattern). The
    # general generate flow and the settings-specific ids still stay off /index.
    assert 'id="batch-queue-ab-endpoint"' in html
    assert 'id="batch-queue-ab-token"' in html
    assert 'type="password"' in html
    assert 'id="settings-ab-token"' not in html
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
    assert "订阅方案工作台" in html
    assert "Settings" in html
    assert 'id="storage-settings-panel"' in html
    assert 'id="preference-settings-panel"' in html
    assert 'id="data-source-settings-panel"' in html
    assert 'id="qbittorrent-settings-panel"' in html
    assert 'id="auto-bangumi-settings-panel"' in html
    assert "Storage 偏好" in html
    assert "偏好默认值" in html
    assert "数据源" in html
    assert "qBittorrent" in html
    assert "Auto Bangumi" in html
    assert html.count('class="panel settings-panel"') == 5
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
    assert 'id="preference-settings-form"' in html
    assert 'id="preference-preferred-groups"' in html
    assert 'id="preference-excluded-groups"' in html
    assert 'id="preference-fallback"' in html
    assert 'id="preference-filter-must-contain"' in html
    assert 'id="preference-filter-must-not-contain"' in html
    assert 'id="preference-filter-use-regex"' in html
    assert 'id="preference-filter-case-sensitive"' in html
    assert 'id="preference-naming-strategy"' in html
    assert 'id="preference-naming-template"' in html
    assert 'id="preference-search-reuse-corrections"' in html
    assert 'id="preference-settings-save"' in html
    assert 'id="preference-settings-reset"' in html
    assert "偏好字幕组" in html
    assert "排除字幕组" in html
    assert "命名策略" in html
    assert "不会保存 endpoint、token、cookie" in html
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
    assert "仅已确认订阅方案可提交" in html
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
    assert "有效种子（当前选中字幕组：" in script
    assert "完整种子（按字幕组分组）" in script
    assert "排除种子 (" in script
    assert "complete-seed-details" in script
    assert "excluded-seed-details" in script
    assert "subgroup-seed-group" in script
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
    assert "window.confirm(\"确认提交此订阅方案到 Auto Bangumi？\")" in script
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


def test_static_app_script_wires_mikan_candidate_search_control() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "/api/v1/mikan/candidates" in script
    assert "mikan-candidate-search-form" in script
    assert "mikan-candidate-query" in script
    assert "mikan-candidate-search-endpoint" not in script
    assert "mikan-candidate-timeout-seconds" not in script
    assert "mikan-candidate-search-submit" in script
    assert "mikan-candidate-search-result" in script
    assert "mikan-candidate-search-error" in script
    assert "mikan_config" not in script
    assert "searchMikanCandidates" in script
    assert "clearCandidateSensitiveFields" not in script
    assert "正在搜索 MiKan 候选" in script
    assert "候选搜索失败" in script
    assert "未找到候选合集" in script
    assert "MiKan ID" in script
    assert "搜索词：" in script
    assert "candidate.recommendation" in script
    assert "candidate-recommendation" in script
    assert "搜索结果不会自动选择合集" not in script
    assert "选择此合集" in script
    assert "generateRequestFromCandidate" in script
    assert "finalizeGeneratedRequest" in script
    assert "mikan_bangumi" in script
    assert "lastCandidateSearchConfig" not in script
    assert "mikan-fallback-enabled" in script
    assert "syncCandidateFallbackVisibility" in script
    assert "mikan-fallback-form" in script
    assert "mikan-fallback-bangumi" in script
    assert "mikan-fallback-error" in script
    assert "mikan-fallback-generate" in script
    assert "generateRequestFromFallback" in script
    assert "MiKan 直连合集" in script
    assert "使用直连合集生成" in script
    # Candidate selection and direct fallback always produce an editable preview
    # draft (save_request=false); the user explicitly saves it with 保存草案.
    assert "save_request: false" in script
    assert "http://" not in script
    assert "https://" not in script


def test_static_app_script_wires_batch_parse_entry() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "/api/v1/batches/parse" in script
    assert "batch-parse-form" in script
    assert "batch-raw-input" in script
    assert "batch-parse-submit" in script
    assert "batch-parse-result" in script
    assert "batch-parse-error" in script
    assert "parseBatchDraft" in script
    assert "raw_input: rawInput" in script
    assert "批量获取前必须输入至少一个番剧名称" in script
    assert "正在解析批量番剧名称" in script
    assert "batchDraftCards" in script
    assert "batchCardTitle" in script
    assert "batchCardSourceName" in script
    assert "batchCardReviewData" in script
    assert "batchCardRequest" in script
    assert "openBatchCardModify" in script
    assert "updateBatchCardRequest" in script
    assert "acceptBatchCard" in script
    assert "submitBatchAccept" in script
    assert "resolveBatchAcceptDescriptors" in script
    assert "applyBatchAcceptResult" in script
    assert "markBatchCardAccepted" in script
    assert "savePreviewDraftRequest" in script
    assert "renderBatchCardReviewPanel" in script
    assert "canExpandBatchCard" in script
    assert "batchCardIsSelectable" in script
    assert "toggleBatchItemSelection" in script
    assert "setAllBatchItemsSelected" in script
    assert "updateBatchAcceptToolbar" in script
    assert "setBatchAcceptInFlight" in script
    assert "postBatchAccept" in script
    assert "deleteBatchCard" in script
    assert "batch-draft-card" in script
    assert "batch-card-grid" in script
    assert "batch-card-review" in script
    assert "batch-card-modify" in script
    assert "batch-card-accept" in script
    assert "batch-card-checkbox" in script
    assert "batch-card-queue-status" in script
    assert "batch-card-reason" in script
    assert "/api/v1/batches/\" + encodeURIComponent(currentBatchId) + \"/accept" in script
    assert "已选择 " in script
    assert "确认接受选中的 " in script
    assert "确认接受全部批量卡片" in script
    assert "缺少批次标识，请重新获取批量草案" in script
    assert "当前批量卡片已标记为已接受并待提交，其他卡片保持不变" in script
    assert "当前批量卡片已回流最新订阅草案" in script
    assert "无法接受：" in script
    assert "接受失败：" in script
    assert "待提交" in script
    assert "当前字幕组" in script
    assert "有效种子（当前选中字幕组：" in script
    assert "排除种子 (" in script
    assert "有效种子数：" in script
    assert "batchStatusLabel" in script
    assert "已解析" in script
    assert "解析失败" in script


def test_static_app_script_wires_batch_preference_display() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    # US-156 preference/review metadata helpers wired into the batch cards.
    assert "batchCardPreferenceHits" in script
    assert "batchCardPreferenceWarnings" in script
    assert "batchCardReviewHints" in script
    assert "batchCardEnhancedQueries" in script
    assert "batchCardAppliedPreferences" in script
    assert "batchCardPreferenceFallback" in script
    assert "batchCardPreferenceSummary" in script
    assert "batchCardNeedsReview" in script
    assert "buildBatchCardPreferenceBlock" in script
    assert "buildBatchCardSearchSourceBlock" in script
    assert "batch-card-preference" in script
    assert "batch-card-preference-block" in script
    assert "batch-card-search-source-block" in script
    assert "batch-card-preference-list" in script
    assert "batch-card-review-status" in script
    assert "偏好与审核" in script
    assert "偏好命中摘要" in script
    assert "偏好警告" in script
    assert "审核提示" in script
    assert "当前默认配置" in script
    # US-155 closure: accepted cards record user corrections via the
    # corrections API so later batch inputs reuse confirmed titles.
    assert "recordUserCorrection" in script
    assert 'fetchJson("/api/v1/corrections"' in script
    assert "raw_title: raw" in script
    assert "canonical_title: canonical" in script
    assert "query_correction" in script
    assert "偏好字幕组" in script
    assert "排除字幕组" in script
    assert "搜索词来源" in script
    assert "修正增强搜索词" in script
    assert "原始搜索词" in script
    assert "偏好不可用，已回退默认流程" in script
    assert "未配置偏好，使用默认流程" in script
    assert "偏好命中：" in script
    assert "需人工核对" in script
    assert "无需人工核对。" in script
    assert "无搜索词，已回退默认流程。" in script


def test_static_app_script_wires_batch_queue_result_panel() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "batchQueueItems" in script
    assert "batchIdFromLocation" in script
    assert "syncBatchIdToUrl" in script
    assert "batchQueueStatusLabel" in script
    assert "batchQueueStatusClass" in script
    assert "renderBatchQueueItem" in script
    assert "renderBatchQueuePanel" in script
    assert "loadBatchQueue" in script
    assert "applyQueueResult" in script
    assert "syncQueueStatusToCards" in script
    assert "submitBatchQueue" in script
    assert "setBatchQueueInFlight" in script
    assert "clearBatchQueueSensitiveFields" in script
    assert "batchQueueSummaryMessage" in script
    assert "showBatchQueueSubmitNotification" in script
    assert "retryBatchQueueItem" in script
    assert "batch-queue-item-retry" in script
    assert "recoverBatchQueueItem" in script
    assert "batch-queue-item-recover" in script
    assert "RESULT_PERSIST_FAILED" in script
    assert "结果保存失败" in script
    assert "/api/v1/batches/\" + encodeURIComponent(currentBatchId) + \"/queue" in script
    assert "/api/v1/batches/\" + encodeURIComponent(currentBatchId) + \"/submit" in script
    assert "/api/v1/batches/\" + encodeURIComponent(currentBatchId) + \"/retry" in script
    assert "/api/v1/batches/\" + encodeURIComponent(currentBatchId) + \"/recover" in script
    assert "无法自动判断 Auto Bangumi 是否已创建订阅" in script
    assert "batch-queue-submit-form" in script
    assert "batch-queue-ab-endpoint" in script
    assert "batch-queue-ab-token" in script
    assert "batch-queue-ab-confirm" in script
    assert "batch-queue-submit-button" in script
    assert "batch-queue-refresh" in script
    assert "提交前必须填写 endpoint" in script
    assert "提交前必须填写 token" in script
    assert "请勾选确认后再提交到 Auto Bangumi" in script
    assert "提交前必须填写 endpoint" in script
    assert "正在提交队列到 Auto Bangumi" in script
    assert "Auto Bangumi 批量提交失败" in script
    assert "Auto Bangumi 单项重试失败" in script
    assert "正在重试到 Auto Bangumi" in script
    assert "队列读取失败" in script
    assert "尚无结果摘要" in script
    assert "尝试次数：" in script
    assert "更新于：" in script
    assert "暂无队列项目" in script


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
    assert '["状态", statusLabel(request.status)]' in script
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
    assert "rssSource.seed_names ||" in script
    assert "combinedSeedNames(" in script
    assert "groupedSeeds.push({subtitleGroup: groupName, seedNames: groupSeedNames})" in script
    assert "totalCompleteCount" in script
    assert "完整种子" in script
    assert "有效种子（当前选中字幕组：" in script
    assert "renderExcludedSeedList" in script
    assert "document.createElement(\"details\")" in script
    assert "completeSummary.textContent" in script
    assert "renderHistorySection(auditSection, payload.history)" in script
    assert "renderAbResultSection(auditSection, payload.ab_result)" in script
    assert "selected_rss_url" in script
    assert "addDetailRow(fields, \"selected_rss_url\"" not in script


def test_static_app_script_maps_status_codes_to_chinese_labels() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "function statusLabel(status)" in script
    assert "PENDING_CONFIRM: \"待确认\"" in script
    assert "ACCEPTED: \"已确认\"" in script
    assert "CANCELLED: \"已取消\"" in script
    assert "function actionLabel(action)" in script
    assert "ACCEPT: \"确认\"" in script
    assert "CANCEL: \"取消\"" in script
    assert "MODIFY: \"修改\"" in script
    assert "statusLabel(summary.status)" in script
    assert "statusLabel(request.status)" in script
    assert "option.textContent = statusLabel(status)" in script
    assert "全部" in script
    # The raw status codes never render into user-visible strings in the main UI.
    assert '"待确认"' in script
    assert '"已确认"' in script
    assert '"已取消"' in script


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
    assert "已保存订阅方案 " in script
    assert "刷新列表" in script
    assert "查看详情" in script
    assert "订阅方案列表加载失败" in script
    assert "订阅方案详情加载失败" in script
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


def test_static_app_script_renders_unsaved_preview_as_editable_draft() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "订阅草案（未保存）" in script
    assert "订阅草案（未保存）：可编辑下方订阅方案" in script
    assert "保存草案" in script
    assert "async function savePreviewRequest" in script
    assert "/api/v1/requests/preview-save" in script
    assert "/api/v1/requests/preview-modify" in script
    assert "async function previewModify" in script
    assert "collectPreviewEditPatch" in script
    assert "buildPreviewEditForm" in script
    assert "detail-preview-edit-form" in script
    assert "preview-subtitle-group" in script
    assert "preview-must-contain" in script
    assert "preview-must-not-contain" in script
    assert "preview-filter-use-regex" in script
    assert "preview-filter-case-sensitive" in script
    assert "preview-folder-name" in script
    assert "应用修改" in script
    assert "renderDetailPayload(result, {preview: !result.saved_request})" in script
    assert "selectedRequestId = result.saved_request ? generatedRequestId : null" in script
    assert "syncRequestIdToUrl(null, {replace: true})" in script
    # The preview draft never renders confirm/cancel/delete/AB actions.
    assert script.index("if (isPreview)") < script.index("} else if (isPending)")
    assert script.index("if (isPreview)") < script.index(
        'performAction(request.request_id, "accept", {})'
    )
    # The preview edit form is distinct from the saved-request modify form.
    assert "detail-modify-form" in script
    assert "detail-preview-edit-form" in script


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
    assert "没有匹配的订阅方案。清空搜索或筛选后可恢复列表。" in script
    assert "listSearchInput.addEventListener(\"input\", renderList)" in script
    assert "listStatusFilter.addEventListener(\"change\", renderList)" in script
    assert "listSortSelect.addEventListener(\"change\", renderList)" in script
    assert "document.createElement(\"button\")" in script
    assert "item.type = \"button\"" in script
    assert 'item.setAttribute("aria-label", "查看订阅方案详情：" + requestLabel(summary))' in script
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
    generate_start = script.index("async function generateRequest(")
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


def test_static_app_script_wires_preference_settings_form() -> None:
    response = _client().get("/migu-orca-static/app.js")

    script = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "preference-settings-form" in script
    assert "preference-preferred-groups" in script
    assert "preference-excluded-groups" in script
    assert "preference-fallback" in script
    assert "preference-filter-must-contain" in script
    assert "preference-filter-must-not-contain" in script
    assert "preference-filter-use-regex" in script
    assert "preference-filter-case-sensitive" in script
    assert "preference-naming-strategy" in script
    assert "preference-naming-template" in script
    assert "preference-search-reuse-corrections" in script
    assert "loadPreferenceSettings" in script
    assert "savePreferenceSettings" in script
    assert "resetPreferenceSettings" in script
    assert "buildPreferenceSettingsPayload" in script
    assert "renderPreferenceSettings" in script
    assert "setPreferenceSettingsInFlight" in script
    assert "preferenceSettingsForm.addEventListener(\"submit\", savePreferenceSettings)" in script
    assert "preferenceSettingsResetButton.addEventListener(\"click\", resetPreferenceSettings)" in script
    assert 'apiPath("/api/v1/preferences")' in script
    assert 'fetchJson("/api/v1/preferences"' in script
    assert "reuse_explicit_corrections" in script
    assert "official_title_season" in script
    assert "此操作不会清除订阅方案、批量提交队列或 Auto Bangumi 结果存储" in script


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
    assert "确认提交此订阅方案到 Auto Bangumi？" in script
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
    assert ".batch-card-review" in css
    assert ".batch-card-review[hidden]" in css
    assert ".batch-accept-toolbar" in css
    assert ".batch-accept-toolbar[hidden]" in css
    assert ".batch-card-checkbox" in css
    assert ".batch-card-status-row" in css
    assert ".batch-card-queue-status" in css
    assert ".batch-card-reason" in css
    assert ".batch-queue-item" in css
    assert ".batch-queue-item-title" in css
    assert ".batch-queue-item-meta" in css
    assert ".batch-queue-item-summary" in css
    assert ".batch-queue-status-ready" in css
    assert ".batch-queue-status-succeeded" in css
    assert ".batch-queue-status-failed" in css
    assert ".batch-queue-status-retryable" in css
    assert "#batch-queue-submit-form[hidden]" in css
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
        "error_message": "未找到已保存的订阅方案",
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
        "error_message": "未找到已保存的订阅方案",
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
        "error_message": "未找到已保存的订阅方案",
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
            f"删除订阅方案 JSON 失败 {tmp_path}/secret-token",
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


def test_create_request_uses_default_mikan_config_when_source_is_mikan(
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
            "save_request": False,
        },
    )

    payload = response.get_json()
    request = payload["result"]["request"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["source_mode"] == "mikan_http"
    assert isinstance(captured["mikan_config"], MikanConfig)
    assert captured["mikan_config"] == default_mikan_config()
    assert captured["mikan_config"].search_endpoint == "https://mikanani.me/Home/Search"
    assert captured["mikan_config"].timeout_seconds == 15.0
    assert factory_configs == [captured["mikan_config"]]
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"


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


def test_candidate_search_api_returns_sanitized_candidates_with_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-image" href="/Home/Bangumi/2353">'
                '<img class="bangumi-poster" src="/assets/cover/2353.jpg">'
                "</a>"
                '<a class="an-text" href="/Home/Bangumi/2353" title="Frieren EN">'
                "葬送的芙莉莲"
                "</a>"
                "</div>"
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/3072">咒术回战 第三季</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["query"] == "芙莉莲"
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "2353",
            "title": "葬送的芙莉莲",
            "mikan_url": "https://mikan.example/Home/Bangumi/2353",
            "poster_url": "https://mikan.example/assets/cover/2353.jpg",
            "source_query": "芙莉莲",
            "aliases": ["Frieren EN"],
            "recommendation": "可能匹配",
        },
        {
            "bangumi_id": "3072",
            "title": "咒术回战 第三季",
            "mikan_url": "https://mikan.example/Home/Bangumi/3072",
            "poster_url": None,
            "source_query": "芙莉莲",
            "aliases": [],
            "recommendation": None,
        },
    ]
    assert transport.requests == [
        (
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2",
            5.0,
        )
    ]


def test_candidate_search_api_returns_empty_list_when_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=ghost": (
                '<section class="related-recommendations"><p>暂无相关合集</p></section>'
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "ghost",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["candidates"] == []


def test_candidate_search_api_rejects_empty_query_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("create_mikan_client should not be called for empty query")

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fail_if_called,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "   ",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "data_validation_errors"
    assert any(
        error["field"] == "query" for error in payload["error_data"]["errors"]
    )


def test_candidate_search_api_uses_default_mikan_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )
    received_configs: list[MikanConfig] = []

    def fake_create_mikan_client(config: MikanConfig):
        received_configs.append(config)
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={"query": "芙莉莲"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["query"] == "芙莉莲"
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "2353",
            "title": "葬送的芙莉莲",
            "mikan_url": "https://mikanani.me/Home/Bangumi/2353",
            "poster_url": None,
            "source_query": "芙莉莲",
            "aliases": [],
            "recommendation": "可能匹配",
        }
    ]
    assert received_configs == [default_mikan_config()]
    assert received_configs[0].search_endpoint == DEFAULT_MIKAN_SEARCH_ENDPOINT
    assert received_configs[0].timeout_seconds == DEFAULT_MIKAN_TIMEOUT_SECONDS
    assert transport.requests == [
        (
            "https://mikanani.me/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2",
            DEFAULT_MIKAN_TIMEOUT_SECONDS,
        )
    ]


@pytest.mark.parametrize(
    "error, expected_error_type, expected_failed_step",
    [
        (
            Stage1Error(
                "mikan_http_failed",
                "MiKan HTTP 请求失败",
                "mikan_search",
                {"status_code": 503},
            ),
            "mikan_http_failed",
            "mikan_search",
        ),
        (
            Stage1Error(
                "mikan_timeout",
                "MiKan HTTP 请求超时",
                "mikan_search",
                {"category": "timeout"},
            ),
            "mikan_timeout",
            "mikan_search",
        ),
        (
            Stage1Error(
                "mikan_parse_failed",
                "MiKan 页面解析失败",
                "mikan_search",
            ),
            "mikan_parse_failed",
            "mikan_search",
        ),
    ],
)
def test_candidate_search_api_returns_sanitized_mikan_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Stage1Error,
    expected_error_type: str,
    expected_failed_step: str,
) -> None:
    client = _FakeCandidateSearchClient(error=error)

    def fake_create_mikan_client(config: MikanConfig):
        return client

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == expected_error_type
    assert payload["error_data"]["failed_step"] == expected_failed_step
    assert client.searches == ["芙莉莲"]


def test_candidate_search_api_does_not_echo_raw_html_or_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                "<html><body>"
                "<script>var sessionToken = 'secret-candidate-token'</script>"
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/42">芙莉莲</a>'
                "</div>"
                "</body></html>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "芙莉莲",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "42",
            "title": "芙莉莲",
            "mikan_url": "https://mikan.example/Home/Bangumi/42",
            "poster_url": None,
            "source_query": "芙莉莲",
            "aliases": [],
            "recommendation": "可能匹配",
        }
    ]
    body = response.get_data(as_text=True)
    assert "secret-candidate-token" not in body
    assert "<script" not in body
    assert "<html" not in body
    assert "<rss" not in body


def test_candidate_search_api_includes_display_only_recommendation_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeCandidateSearchClient(
        candidates=[
            MikanCandidate(
                bangumi_id="3072",
                title="咒术回战 第三季",
                mikan_url="https://mikan.example/Home/Bangumi/3072",
                source_query="咒术回战 第三季",
            ),
            MikanCandidate(
                bangumi_id="3071",
                title="咒术回战 第二季",
                mikan_url="https://mikan.example/Home/Bangumi/3071",
                source_query="咒术回战 第三季",
            ),
        ]
    )

    def fake_create_mikan_client(config: MikanConfig):
        return client

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    response = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "咒术回战 第三季",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["candidates"] == [
        {
            "bangumi_id": "3072",
            "title": "咒术回战 第三季",
            "mikan_url": "https://mikan.example/Home/Bangumi/3072",
            "poster_url": None,
            "source_query": "咒术回战 第三季",
            "aliases": [],
            "recommendation": "推荐：第 3 季",
        },
        {
            "bangumi_id": "3071",
            "title": "咒术回战 第二季",
            "mikan_url": "https://mikan.example/Home/Bangumi/3071",
            "poster_url": None,
            "source_query": "咒术回战 第三季",
            "aliases": [],
            "recommendation": "季数不符",
        },
    ]


def test_candidate_search_api_serves_second_call_from_cache_without_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    payload = {
        "query": "芙莉莲",
        "mikan_config": {
            "search_endpoint": "https://mikan.example/Home/Search",
            "timeout_seconds": 5,
        },
    }
    first = _client().post("/api/v1/mikan/candidates", json=payload)
    second = _client().post("/api/v1/mikan/candidates", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json() == second.get_json()
    assert transport.requests == [
        ("https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2", 5.0)
    ]


def test_candidate_search_api_cache_isolates_different_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            ),
            "https://mikan.example/Home/Search?searchstr=%E5%92%92%E6%9C%AF%E5%9B%9E%E6%88%98": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/3072">咒术回战 第三季</a>'
                "</div>"
                "</section>"
            ),
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    common_config = {
        "search_endpoint": "https://mikan.example/Home/Search",
        "timeout_seconds": 5,
    }
    first = _client().post(
        "/api/v1/mikan/candidates",
        json={"query": "芙莉莲", "mikan_config": common_config},
    )
    second = _client().post(
        "/api/v1/mikan/candidates",
        json={"query": "咒术回战", "mikan_config": common_config},
    )

    assert first.get_json()["result"]["candidates"][0]["bangumi_id"] == "2353"
    assert second.get_json()["result"]["candidates"][0]["bangumi_id"] == "3072"
    assert len(transport.requests) == 2


def test_candidate_search_api_cache_isolates_different_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=ghost": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/100">A 番剧</a>'
                "</div>"
                "</section>"
            ),
            "https://other.example/Home/Search?searchstr=ghost": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/200">B 番剧</a>'
                "</div>"
                "</section>"
            ),
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    first = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "ghost",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )
    second = _client().post(
        "/api/v1/mikan/candidates",
        json={
            "query": "ghost",
            "mikan_config": {
                "search_endpoint": "https://other.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    assert first.get_json()["result"]["candidates"][0]["bangumi_id"] == "100"
    assert second.get_json()["result"]["candidates"][0]["bangumi_id"] == "200"
    assert len(transport.requests) == 2


def test_batch_parse_api_returns_per_item_parsed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 路哥S4 (high confidence, single candidate) gets a real candidate so it is
    # the no-review case; 萌王S4 (multi-candidate) and 邻家天使S2 (no candidate)
    # both must be flagged for review under US-154.
    def _search_candidates(search_queries: list[str], mikan_config: object) -> list[dict[str, object]]:
        if search_queries and "实力至上" in search_queries[0]:
            return [
                {
                    "bangumi_id": "4001",
                    "title": "欢迎来到实力至上主义的教室 第四季",
                    "mikan_url": "https://mikan.example/Home/Bangumi/4001",
                    "source_query": search_queries[0],
                }
            ]
        return []

    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        _search_candidates,
    )
    raw_input = "\n萌王S4\n  \n路哥S4\n邻家天使S2\n"

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": raw_input},
    )

    payload = response.get_json()
    result = payload["result"]
    items = result["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["batch_id"].startswith("batch-")
    assert result["raw_input"] == raw_input
    assert [item["raw_title"] for item in items] == [
        "萌王S4",
        "路哥S4",
        "邻家天使S2",
    ]
    assert len({item["item_id"] for item in items}) == 3
    assert all(item["item_id"].startswith("item-") for item in items)
    assert all(item["status"] == BATCH_ITEM_STATUS_PARSED for item in items)
    assert items[0]["canonical_title_candidates"] == [
        "关于我转生变成史莱姆这档事 第四季",
        "关于我转生变成史莱姆这档事 第4季",
    ]
    assert items[0]["season_hint"] == "S4"
    assert "转生史莱姆 第四季" in items[0]["search_queries"]
    assert items[0]["confidence"] == 0.86
    assert items[0]["needs_user_review"] is True
    assert items[0]["candidates"] == []
    assert items[1]["canonical_title_candidates"] == ["欢迎来到实力至上主义的教室 第四季"]
    assert items[1]["needs_user_review"] is False
    assert items[1]["candidates"][0]["bangumi_id"] == "4001"
    # US-154: no-candidate items (even high-confidence single-candidate ones)
    # must be flagged for review.
    assert items[2]["needs_user_review"] is True
    assert items[2]["candidates"] == []
    # Stage 21: every item carries applied_preferences + preference_warnings.
    assert items[0]["applied_preferences"] == {
        "subtitle_groups": {
            "preferred": [],
            "excluded": [],
            "fallback": "next_preferred",
        },
        "filter_rule": {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "expected_folder_name": "关于我转生变成史莱姆这档事 第四季",
    }
    assert items[0]["preference_warnings"] == []
    assert items[1]["applied_preferences"]["expected_folder_name"] == (
        "欢迎来到实力至上主义的教室 第四季"
    )
    assert items[1]["preference_warnings"] == []
    # US-154: preference_hits summarizes which preference defaults applied.
    assert items[1]["preference_hits"] == [
        {
            "field": "subtitle_groups",
            "applied": False,
            "summary": "未配置字幕组偏好，使用默认选择流程",
        },
        {
            "field": "filter_rule",
            "applied": False,
            "summary": "未配置筛选默认值",
        },
        {
            "field": "naming",
            "applied": True,
            "summary": "命名策略已生成默认目录名：欢迎来到实力至上主义的教室 第四季",
        },
    ]
    # The high-confidence single-candidate item with a candidate has no review
    # hints; the multi-candidate and no-candidate items carry Chinese hints.
    assert items[1]["review_hints"] == []
    assert any("存在多个候选名称" in hint for hint in items[0]["review_hints"])
    assert any("未找到候选合集" in hint for hint in items[2]["review_hints"])


def test_batch_parse_api_rejects_empty_input_with_chinese_validation_error() -> None:
    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "\n \t\n"},
    )

    payload = response.get_json()
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请至少输入一个番剧名称"
    assert payload["error_data"]["failed_step"] == "batch_parse"
    assert payload["error_data"]["details"] == {"field": "raw_input"}
    assert "/home/" not in body


def test_batch_parse_api_marks_single_provider_failure_without_blocking_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def provider() -> FakeAnimeTitleParsingProvider:
        return FakeAnimeTitleParsingProvider(fail_titles={"杖剑谭S2"})

    monkeypatch.setattr(
        "apps.migu_orca_web.views._batch_title_parsing_provider",
        provider,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n杖剑谭S2\n路哥S4"},
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert [item["status"] for item in items] == [
        BATCH_ITEM_STATUS_PARSED,
        BATCH_ITEM_STATUS_FAILED,
        BATCH_ITEM_STATUS_PARSED,
    ]
    assert items[1]["raw_title"] == "杖剑谭S2"
    assert items[1]["canonical_title_candidates"] == []
    assert items[1]["search_queries"] == []
    assert items[1]["candidates"] == []
    assert items[1]["needs_user_review"] is True
    assert items[1]["error"]["error_type"] == "ai_title_parse_failed"
    assert items[1]["error"]["failed_step"] == "ai_title_parse"
    assert items[0]["canonical_title_candidates"]
    assert items[2]["canonical_title_candidates"] == ["欢迎来到实力至上主义的教室 第四季"]


def test_batch_parse_api_failed_item_error_does_not_leak_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SensitiveProvider:
        def parse(self, raw_title: str):
            raise RuntimeError(
                "token=secret-token endpoint=https://llm.example/api "
                "cookie=session-id path=/home/ghostning/raw.html <html>raw</html>"
            )

    monkeypatch.setattr(
        "apps.migu_orca_web.views._batch_title_parsing_provider",
        lambda: SensitiveProvider(),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "敏感测试"},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FAILED
    assert item["error"]["error_message"] == "AI 名称解析失败，请检查该条目后重试"
    assert item["error"]["details"] == {
        "raw_title_length": 4,
        "provider_source": "fake",
        "recoverable": True,
    }
    assert "secret-token" not in body
    assert "llm.example" not in body
    assert "session-id" not in body
    assert "/home/ghostning" not in body


def test_batch_parse_api_applies_saved_preferences_from_storage_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(
                preferred=["Loli"],
                excluded=["示例组"],
                fallback="next_preferred",
            ),
            filter_defaults=FilterDefaults(
                must_contain="1080p",
                must_not_contain="合集版",
                use_regex=True,
                case_sensitive=True,
            ),
            naming=NamingPreference(strategy="raw_title", template="{title}"),
        ),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": str(storage_dir)},
    )

    item = response.get_json()["result"]["items"][0]
    assert response.status_code == 200
    assert item["applied_preferences"] == {
        "subtitle_groups": {
            "preferred": ["Loli"],
            "excluded": ["示例组"],
            "fallback": "next_preferred",
        },
        "filter_rule": {
            "must_contain": "1080p",
            "must_not_contain": "合集版",
            "use_regex": True,
            "case_sensitive": True,
        },
        "naming": {"strategy": "raw_title", "template": "{title}"},
        "expected_folder_name": "萌王S4",
    }
    assert item["preference_warnings"] == []


def test_batch_parse_api_preview_request_carries_preference_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US-153/US-156 closure: a parsed batch item gets an editable
    preview_request whose defaults come from the saved preferences, so the card
    can enter the existing preview-modify / preview-save / accept flow."""
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(
                preferred=["Loli"],
                excluded=["示例组"],
                fallback="next_preferred",
            ),
            filter_defaults=FilterDefaults(
                must_contain="1080p",
                must_not_contain="合集版",
                use_regex=True,
                case_sensitive=True,
            ),
            naming=NamingPreference(strategy="raw_title", template="{title}"),
        ),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": str(storage_dir)},
    )

    item = response.get_json()["result"]["items"][0]
    assert response.status_code == 200
    preview = item["preview_request"]
    assert preview is not None
    assert preview["status"] == "PENDING_CONFIRM"
    assert preview["input"] == {"raw_title": "萌王S4"}
    assert preview["request_id"] == f"{response.get_json()['result']['batch_id']}-{item['item_id']}"
    assert (
        preview["source_info"]["matched_bangumi"]["title"]
        == "关于我转生变成史莱姆这档事 第四季"
    )
    assert preview["source_info"]["rss_sources"] == []
    assert preview["confirmable_config"]["selected_subtitle_group"] == "Loli"
    assert preview["confirmable_config"]["filter_rule"] == {
        "must_contain": "1080p",
        "must_not_contain": "合集版",
        "use_regex": True,
        "case_sensitive": True,
    }
    assert preview["confirmable_config"]["expected_folder_name"] == "萌王S4"
    assert preview["confirmable_config"]["effective_seed_names"] == []
    # The preview skeleton never carries sensitive values.
    assert "token" not in str(preview)
    assert "endpoint" not in str(preview)
    assert "http" not in str(preview)


def test_batch_parse_api_preview_request_empty_defaults_without_preferences(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Without saved preferences the preview_request still exists but uses the
    empty Stage 19 defaults, so cards remain editable/acceptable."""
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": str(storage_dir)},
    )

    item = response.get_json()["result"]["items"][0]
    assert item["status"] == "PARSED"
    preview = item["preview_request"]
    assert preview is not None
    assert preview["status"] == "PENDING_CONFIRM"
    assert preview["confirmable_config"]["selected_subtitle_group"] is None
    assert preview["confirmable_config"]["filter_rule"] == {
        "must_contain": "",
        "must_not_contain": "",
        "use_regex": False,
        "case_sensitive": False,
    }
    # 无偏好时 expected_folder_name 仍由默认命名策略生成（官方标题+季数）。
    assert isinstance(preview["confirmable_config"]["expected_folder_name"], str)
    assert preview["confirmable_config"]["expected_folder_name"]


def test_batch_parse_api_failed_item_has_no_preview_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A FAILED item (parse/search failure) has no editable preview_request."""
    monkeypatch.setattr(
        "apps.migu_orca_web.views._batch_title_parsing_provider",
        lambda: FakeAnimeTitleParsingProvider(fail_titles={"萌王S4"}),
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": str(storage_dir)},
    )

    item = response.get_json()["result"]["items"][0]
    assert item["status"] == "FAILED"
    assert item.get("preview_request") is None


def test_batch_parse_api_falls_back_when_preference_file_is_damaged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    config = load_storage_config(storage_dir)
    config.preferences_dir.mkdir(parents=True, exist_ok=True)
    (config.preferences_dir / "user_preferences.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n路哥S4", "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert len(items) == 2
    assert all(item["status"] == BATCH_ITEM_STATUS_PARSED for item in items)
    assert all(item["applied_preferences"] is None for item in items)
    assert all(item["preference_warnings"] == ["偏好读取失败，已回退默认流程"] for item in items)
    assert items[0]["canonical_title_candidates"]
    assert items[1]["canonical_title_candidates"]


def test_batch_parse_api_failed_item_keeps_applied_preferences_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def provider() -> FakeAnimeTitleParsingProvider:
        return FakeAnimeTitleParsingProvider(fail_titles={"杖剑谭S2"})

    monkeypatch.setattr(
        "apps.migu_orca_web.views._batch_title_parsing_provider",
        provider,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(preferred=["Loli"]),
            naming=NamingPreference(strategy="raw_title", template="{title}"),
        ),
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n杖剑谭S2", "storage_dir": str(storage_dir)},
    )

    items = response.get_json()["result"]["items"]
    failed = next(item for item in items if item["status"] == BATCH_ITEM_STATUS_FAILED)
    parsed = next(item for item in items if item["status"] == BATCH_ITEM_STATUS_PARSED)
    assert failed["applied_preferences"]["expected_folder_name"] is None
    assert "该条目解析失败，命名默认值不可用" in failed["preference_warnings"]
    assert failed["applied_preferences"]["subtitle_groups"] == {
        "preferred": ["Loli"],
        "excluded": [],
        "fallback": "next_preferred",
    }
    assert parsed["applied_preferences"]["expected_folder_name"] == "萌王S4"
    assert parsed["preference_warnings"] == []


def test_batch_parse_api_preference_response_never_leaks_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )
    storage_dir = tmp_path / "migu-state"
    config = load_storage_config(storage_dir)
    config.preferences_dir.mkdir(parents=True, exist_ok=True)
    # A hand-edited/legacy file carrying extra sensitive keys alongside the
    # defined contract fields: the repository strips unknown keys on load, so
    # the batch parse response must never echo them back.
    (config.preferences_dir / "user_preferences.json").write_text(
        json.dumps(
            {
                "version": 1,
                "subtitle_groups": {
                    "preferred": ["Loli"],
                    "excluded": [],
                    "fallback": "next_preferred",
                },
                "filter_defaults": {
                    "must_contain": "1080p",
                    "must_not_contain": "",
                    "use_regex": False,
                    "case_sensitive": False,
                },
                "naming": {"strategy": "raw_title", "template": "{title}"},
                "search": {"reuse_explicit_corrections": True},
                "token": "secret-token",
                "endpoint": "https://llm.example/api",
                "cookie": "session-id",
            }
        ),
        encoding="utf-8",
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    body = response.get_data(as_text=True)
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_PARSED
    applied = item["applied_preferences"]
    assert applied is not None
    assert "token" not in applied
    assert "endpoint" not in applied
    assert "cookie" not in applied
    assert "secret-token" not in body
    assert "llm.example" not in body
    assert "session-id" not in body
    # US-154: preference_hits only carry public rule summaries, and review_hints
    # are safe Chinese prompts — no sensitive key or value can appear anywhere.
    for hit in item["preference_hits"]:
        assert set(hit) == {"field", "applied", "summary"}
        assert isinstance(hit["summary"], str)
    for hint in item["review_hints"]:
        assert isinstance(hint, str)
        assert "token" not in hint
        assert "cookie" not in hint
        assert "llm.example" not in hint


def test_batch_parse_api_searches_candidates_for_each_item_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                    aliases=["路哥 S4"],
                )
            ],
            "实力至上主义教室 S4": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="实力至上主义教室 S4",
                    aliases=["路哥 S4"],
                )
            ],
            "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季": [
                MikanCandidate(
                    bangumi_id="2002",
                    title="关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
                    mikan_url="https://mikan.example/Home/Bangumi/2002",
                    source_query="关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
                    poster_url="https://mikan.example/images/2002.jpg",
                )
            ],
        }
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "路哥S4\n邻家天使S2",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert [item["status"] for item in items] == [
        BATCH_ITEM_STATUS_PARSED,
        BATCH_ITEM_STATUS_PARSED,
    ]
    assert client.searches == [
        "欢迎来到实力至上主义的教室 第四季",
        "实力至上主义教室 S4",
        "路哥 S4",
        "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
        "邻家的天使大人 第二季",
        "邻家天使 S2",
    ]
    assert items[0]["candidates"] == [
        {
            "bangumi_id": "4001",
            "title": "欢迎来到实力至上主义的教室 第四季",
            "mikan_url": "https://mikan.example/Home/Bangumi/4001",
            "poster_url": None,
            "source_query": "欢迎来到实力至上主义的教室 第四季",
            "aliases": ["路哥 S4"],
            "recommendation": "推荐：第 4 季",
        }
    ]
    assert items[1]["candidates"] == [
        {
            "bangumi_id": "2002",
            "title": "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
            "mikan_url": "https://mikan.example/Home/Bangumi/2002",
            "poster_url": "https://mikan.example/images/2002.jpg",
            "source_query": "关于邻家的天使大人不知不觉把我惯成了废人这档子事 第二季",
            "aliases": [],
            "recommendation": "推荐：第 2 季",
        }
    ]


def test_batch_parse_api_marks_single_candidate_search_failure_without_blocking_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                )
            ]
        },
        errors={
            "杖与剑的魔剑谭 第二季": Stage1Error(
                "mikan_timeout",
                "MiKan HTTP 请求超时",
                "mikan_search",
                {
                    "url": "https://mikan.example/Home/Search?searchstr=secret-token",
                    "cookie": "session-cookie",
                },
            )
        },
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "路哥S4\n杖剑谭S2",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert [item["status"] for item in items] == [
        BATCH_ITEM_STATUS_PARSED,
        BATCH_ITEM_STATUS_FAILED,
    ]
    assert items[0]["candidates"][0]["bangumi_id"] == "4001"
    assert items[1]["raw_title"] == "杖剑谭S2"
    assert items[1]["canonical_title_candidates"] == ["杖与剑的魔剑谭 第二季"]
    assert items[1]["candidates"] == []
    assert items[1]["error"]["error_type"] == "mikan_timeout"
    assert items[1]["error"]["failed_step"] == "mikan_search"
    assert items[1]["error"]["details"] == {
        "url": "[redacted-url]",
        "[redacted]": "[redacted]",
    }
    # US-154: a search failure must be flagged for review with a Chinese hint,
    # but it never leaks the redacted URL/cookie from the search error.
    assert items[1]["needs_user_review"] is True
    assert any("候选搜索失败" in hint for hint in items[1]["review_hints"])
    assert "secret-token" not in body
    assert "session-cookie" not in body
    assert "https://mikan.example/Home/Search" not in body


def test_batch_parse_api_candidate_results_only_serialize_public_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SensitiveCandidate(MikanCandidate):
        def __init__(self) -> None:
            super().__init__(
                bangumi_id="9001",
                title="测试番剧",
                mikan_url="https://mikan.example/Home/Bangumi/9001",
                source_query="测试番剧",
                poster_url="https://mikan.example/public/poster.jpg",
                aliases=["公开别名"],
            )
            self.raw_html = "<html>secret-token</html>"
            self.raw_rss_xml = "<rss>raw</rss>"
            self.cookie = "session-cookie"
            self.token = "secret-token"
            self.magnet = "magnet:?xt=urn:btih:secret"

    client = _MappedCandidateSearchClient(
        responses={"测试番剧": [SensitiveCandidate()]}
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "测试番剧",
            "mikan_config": {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 5,
            },
        },
    )

    payload = response.get_json()
    candidates = payload["result"]["items"][0]["candidates"]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert candidates == [
        {
            "bangumi_id": "9001",
            "title": "测试番剧",
            "mikan_url": "https://mikan.example/Home/Bangumi/9001",
            "poster_url": "https://mikan.example/public/poster.jpg",
            "source_query": "测试番剧",
            "aliases": ["公开别名"],
            "recommendation": "可能匹配",
        }
    ]
    assert "raw_html" not in body
    assert "raw_rss_xml" not in body
    assert "session-cookie" not in body
    assert "secret-token" not in body
    assert "magnet:?" not in body
    assert "<html" not in body


def test_batch_parse_api_marks_low_confidence_item_for_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 杖剑谭S2 parses at 0.62 confidence (below the 0.7 threshold) and has a
    # single canonical candidate, so it must be flagged for review even though
    # the candidate search returns a result.
    client = _MappedCandidateSearchClient(
        responses={
            "杖与剑的魔剑谭 第二季": [
                MikanCandidate(
                    bangumi_id="2001",
                    title="杖与剑的魔剑谭 第二季",
                    mikan_url="https://mikan.example/Home/Bangumi/2001",
                    source_query="杖与剑的魔剑谭 第二季",
                )
            ]
        }
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "杖剑谭S2"},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_PARSED
    assert item["confidence"] == 0.62
    assert item["candidates"][0]["bangumi_id"] == "2001"
    assert item["needs_user_review"] is True
    assert any("置信度较低" in hint for hint in item["review_hints"])


def test_batch_parse_api_marks_preference_conflict_item_for_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # fallback=none with no preferred subtitle group conflicts with auto
    # selection, so the item is flagged for review even though the parse is
    # high-confidence and the candidate search succeeds.
    storage_dir = tmp_path / "migu-state"
    save_user_preferences(
        load_storage_config(storage_dir),
        VersionedUserPreference(
            version=1,
            subtitle_groups=SubtitleGroupPreference(
                preferred=[],
                excluded=[],
                fallback="none",
            ),
            filter_defaults=FilterDefaults(
                must_contain="",
                must_not_contain="",
                use_regex=False,
                case_sensitive=False,
            ),
            naming=NamingPreference(
                strategy="official_title_season", template="{title}"
            ),
            search=SearchPreference(reuse_explicit_corrections=True),
        ),
    )
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                )
            ]
        }
    )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={
            "raw_input": "路哥S4",
            "storage_dir": str(storage_dir),
        },
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_PARSED
    assert item["candidates"][0]["bangumi_id"] == "4001"
    assert item["needs_user_review"] is True
    assert any(
        "偏好字幕组存在冲突" in hint for hint in item["review_hints"]
    )
    assert item["preference_warnings"] == [
        "fallback 为 none 且未配置偏好字幕组，不会自动选择字幕组"
    ]


# --- US-155: title-correction API + enhanced batch search ---


def _correction_payload() -> dict[str, Any]:
    return {
        "raw_title": "路哥S4",
        "canonical_title": "欢迎来到实力至上主义的教室",
        "season_hint": "S4",
        "bangumi_metadata": {
            "bangumi_id": "4001",
            "title": "欢迎来到实力至上主义的教室",
        },
        "query_correction": "欢迎来到实力至上主义的教室 第四季",
    }


def _correction_save_body(
    storage_dir: Path,
    correction: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"storage_dir": str(storage_dir)}
    if correction is not None:
        body["correction"] = correction
    return body


def test_correction_api_reads_empty_list_when_missing(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().get(f"/api/v1/corrections?storage_dir={storage_dir}")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"] == {"corrections": []}


def test_correction_api_save_returns_normalized_list_and_persists(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    payload = _correction_payload()

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(storage_dir, payload),
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["ok"] is True
    assert result["result"]["corrections"] == [payload]
    assert result["result"]["corrections"][0]["bangumi_metadata"] == {
        "bangumi_id": "4001",
        "title": "欢迎来到实力至上主义的教室",
    }

    # The saved JSON on disk carries only the defined non-sensitive fields.
    config = load_storage_config(storage_dir)
    written = json.loads(
        (config.corrections_dir / "corrections.json").read_text(encoding="utf-8")
    )
    assert written == {"version": 1, "corrections": [payload]}


def test_correction_api_save_uses_latest_version_for_same_raw_title(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(storage_dir, _correction_payload()),
    )
    updated = {
        **_correction_payload(),
        "canonical_title": "欢迎来到实力至上主义的教室 第四季",
        "query_correction": "欢迎来到实力至上主义的教室 第四季",
    }
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(storage_dir, updated),
    )

    response = _client().get(f"/api/v1/corrections?storage_dir={storage_dir}")

    corrections = response.get_json()["result"]["corrections"]
    assert len(corrections) == 1
    assert corrections[0]["canonical_title"] == "欢迎来到实力至上主义的教室 第四季"


def test_correction_api_save_rejects_missing_correction(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(storage_dir, None),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供修正内容"
    assert payload["error_data"]["details"] == {"field": "correction"}


def test_correction_api_save_rejects_invalid_correction(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(
            storage_dir, {"canonical_title": "葬送的芙莉莲"}
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {"field": "raw_title"}


def test_correction_api_save_rejects_unknown_field_without_writing(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(
            storage_dir, {**_correction_payload(), "token": "secret"}
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "未定义字段" in payload["error_message"]
    assert not (
        load_storage_config(storage_dir).corrections_dir / "corrections.json"
    ).exists()


def test_correction_api_save_rejects_sensitive_value_without_writing(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(
            storage_dir,
            {**_correction_payload(), "query_correction": "https://mikan.example/api"},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "敏感内容" in payload["error_message"]
    assert not (
        load_storage_config(storage_dir).corrections_dir / "corrections.json"
    ).exists()


def test_batch_parse_api_searches_enhanced_queries_from_saved_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(storage_dir, _correction_payload()),
    )
    client = _MappedCandidateSearchClient(
        responses={
            "欢迎来到实力至上主义的教室 第四季": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="欢迎来到实力至上主义的教室 第四季",
                    aliases=["路哥 S4"],
                )
            ]
        }
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_PARSED
    # The enhanced queries are searched first; the original queries are never
    # searched because the enhanced search already found candidates.
    assert client.searches == [
        "欢迎来到实力至上主义的教室 第四季",
        "欢迎来到实力至上主义的教室 第4季",
        "欢迎来到实力至上主义的教室 S4",
        "欢迎来到实力至上主义的教室 Season 4",
        "欢迎来到实力至上主义的教室",
    ]
    assert item["enhanced_search_queries"] == [
        {
            "query": "欢迎来到实力至上主义的教室 第四季",
            "original_query": "欢迎来到实力至上主义的教室 第四季",
            "source": "correction:query",
        },
        {
            "query": "欢迎来到实力至上主义的教室 第4季",
            "original_query": "欢迎来到实力至上主义的教室 第四季",
            "source": "correction:query",
        },
        {
            "query": "欢迎来到实力至上主义的教室 S4",
            "original_query": "欢迎来到实力至上主义的教室 第四季",
            "source": "correction:query",
        },
        {
            "query": "欢迎来到实力至上主义的教室 Season 4",
            "original_query": "欢迎来到实力至上主义的教室 第四季",
            "source": "correction:query",
        },
        {
            "query": "欢迎来到实力至上主义的教室",
            "original_query": "欢迎来到实力至上主义的教室 第四季",
            "source": "correction:canonical",
        },
    ]
    assert item["candidates"][0]["bangumi_id"] == "4001"


def test_batch_parse_api_falls_back_to_original_queries_when_enhanced_finds_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(storage_dir, _correction_payload()),
    )
    # Only an original parse query has a candidate; the enhanced queries do not.
    client = _MappedCandidateSearchClient(
        responses={
            "路哥 S4": [
                MikanCandidate(
                    bangumi_id="4001",
                    title="欢迎来到实力至上主义的教室 第四季",
                    mikan_url="https://mikan.example/Home/Bangumi/4001",
                    source_query="路哥 S4",
                    aliases=["路哥 S4"],
                )
            ]
        }
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_PARSED
    # The enhanced queries are searched first, then the original queries on
    # fallback. The repeated first query is served from the candidate cache, so
    # it is not searched twice through the client.
    assert client.searches == [
        "欢迎来到实力至上主义的教室 第四季",
        "欢迎来到实力至上主义的教室 第4季",
        "欢迎来到实力至上主义的教室 S4",
        "欢迎来到实力至上主义的教室 Season 4",
        "欢迎来到实力至上主义的教室",
        "实力至上主义教室 S4",
        "路哥 S4",
    ]
    assert item["candidates"][0]["bangumi_id"] == "4001"


def test_batch_parse_api_falls_back_to_original_queries_when_corrections_file_damaged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    config = load_storage_config(storage_dir)
    config.corrections_dir.mkdir(parents=True, exist_ok=True)
    (config.corrections_dir / "corrections.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n路哥S4", "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert all(item["status"] == BATCH_ITEM_STATUS_PARSED for item in items)
    assert all(item["enhanced_search_queries"] == [] for item in items)


def test_batch_parse_api_does_not_leak_poisoned_corrections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    config = load_storage_config(storage_dir)
    config.corrections_dir.mkdir(parents=True, exist_ok=True)
    (config.corrections_dir / "corrections.json").write_text(
        json.dumps(
            {
                "version": 1,
                "corrections": [
                    {
                        "raw_title": "路哥S4",
                        "canonical_title": "https://mikan.example/api?token=secret",
                        "query_correction": "路哥",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_PARSED
    assert item["enhanced_search_queries"] == []
    assert "mikan.example" not in body
    assert "token=secret" not in body


def test_batch_parse_api_failed_search_keeps_enhanced_queries_for_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/corrections",
        json=_correction_save_body(storage_dir, _correction_payload()),
    )
    # Enhanced queries find nothing, and the original-query fallback raises.
    client = _MappedCandidateSearchClient()

    def _raise(*args: object, **kwargs: object) -> None:
        raise Stage1Error("mikan_timeout", "MiKan HTTP 请求超时", "mikan_search")

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        lambda config: client,
    )
    monkeypatch.setattr(
        "apps.migu_orca_web.views._search_batch_item_candidates",
        _raise,
    )

    response = _client().post(
        "/api/v1/batches/parse",
        json={"raw_input": "路哥S4", "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert item["status"] == BATCH_ITEM_STATUS_FAILED
    # The enhanced queries are still returned so the user can review what was
    # attempted even though the item failed.
    assert item["enhanced_search_queries"]
    assert all(
        entry["source"] in ("correction:query", "correction:canonical")
        for entry in item["enhanced_search_queries"]
    )


def test_candidate_search_api_cache_expires_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mikan_engine.controllers.mikan_candidate_cache import CandidateSearchCache

    now_holder = {"value": 1000.0}

    def _now() -> float:
        return now_holder["value"]

    cache = CandidateSearchCache(ttl_seconds=300, now=_now)
    monkeypatch.setattr("apps.migu_orca_web.views.candidate_search_cache", cache)

    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<section class="related-recommendations">'
                '<div class="bangumi-item">'
                '<a class="an-text" href="/Home/Bangumi/2353">葬送的芙莉莲</a>'
                "</div>"
                "</section>"
            )
        }
    )

    def fake_create_mikan_client(config: MikanConfig):
        return create_mikan_client(config, transport=transport)

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fake_create_mikan_client,
    )

    payload = {
        "query": "芙莉莲",
        "mikan_config": {
            "search_endpoint": "https://mikan.example/Home/Search",
            "timeout_seconds": 5,
        },
    }
    first = _client().post("/api/v1/mikan/candidates", json=payload)
    assert first.status_code == 200
    assert len(transport.requests) == 1

    now_holder["value"] += 301.0
    second = _client().post("/api/v1/mikan/candidates", json=payload)
    assert second.status_code == 200
    assert (
        second.get_json()["result"]["candidates"]
        == first.get_json()["result"]["candidates"]
    )
    assert len(transport.requests) == 2


def test_default_request_create_does_not_call_candidate_search_api_or_real_mikan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError(
            "default fixture generation must not create a real MiKan client"
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.mikan_client_module.create_mikan_client",
        fail_if_called,
    )

    response = _client().post(
        "/api/v1/requests",
        json={"title": "芙莉莲", "save_request": False},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["request"]["input"]["raw_title"] == "芙莉莲"
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


def test_preview_modify_recomputes_seeds_without_saving(tmp_path: Path) -> None:
    preview = generate_request(EntryRequest(raw_title="咒术回战"))["request"]
    original_filter = preview["confirmable_config"]["filter_rule"]
    assert original_filter["must_not_contain"] == ""

    response = _client().post(
        "/api/v1/requests/preview-modify",
        json={
            "request": preview,
            "patch": {
                "filter_rule": {
                    "must_not_contain": "V2",
                    "use_regex": False,
                    "case_sensitive": False,
                }
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    modified = payload["result"]["request"]
    assert modified["confirmable_config"]["filter_rule"]["must_not_contain"] == "V2"
    # The preview is recomputed in memory and never written to storage.
    assert not (tmp_path / "storage").exists()

    # Seeds were recomputed: the Loli source now excludes the V2 seed with a
    # Chinese exclusion reason, so valid + invalid equals total.
    selected_group = modified["confirmable_config"]["selected_subtitle_group"]
    source = next(
        s for s in modified["source_info"]["rss_sources"]
        if s["subtitle_group"] == selected_group
    )
    assert source["valid_seed_count"] + source["invalid_seed_count"] == source["total_seed_count"]
    excluded = source["excluded_seed_names"]
    assert any(
        "V2" in entry["name"] and entry["reason"] == "命中排除规则：V2"
        for entry in excluded
    )


def test_preview_modify_switches_selected_subtitle_group(tmp_path: Path) -> None:
    preview = generate_request(EntryRequest(raw_title="咒术回战"))["request"]
    groups = {s["subtitle_group"] for s in preview["source_info"]["rss_sources"]}
    current = preview["confirmable_config"]["selected_subtitle_group"]
    other = next(g for g in groups if g != current)

    response = _client().post(
        "/api/v1/requests/preview-modify",
        json={
            "request": preview,
            "patch": {"selected_subtitle_group": other},
        },
    )

    payload = response.get_json()
    assert payload["ok"] is True
    modified = payload["result"]["request"]
    confirmable = modified["confirmable_config"]
    assert confirmable["selected_subtitle_group"] == other
    other_source = next(
        s for s in modified["source_info"]["rss_sources"]
        if s["subtitle_group"] == other
    )
    assert confirmable["selected_rss_url"] == other_source["rss_url"]
    # effective_seed_names now reflect the newly selected group's valid seeds.
    assert confirmable["effective_seed_names"] == other_source["valid_seed_names"]


def test_preview_modify_rejects_invalid_patch_field() -> None:
    preview = generate_request(EntryRequest(raw_title="芙莉莲"))["request"]

    response = _client().post(
        "/api/v1/requests/preview-modify",
        json={"request": preview, "patch": {"illegal_field": "x"}},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_modify_patch_field"


def test_preview_save_persists_draft_and_enters_confirmation_flow(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"
    preview = generate_request(EntryRequest(raw_title="芙莉莲"))["request"]

    response = _client().post(
        "/api/v1/requests/preview-save",
        json={"request": preview, "storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert result["request"]["request_id"] == preview["request_id"]
    assert result["request"]["status"] == "PENDING_CONFIRM"
    assert result["saved_request"] == {
        "request_id": preview["request_id"],
        "storage": "local_json",
        "directory": "requests",
        "filename": f"{preview['request_id']}.json",
    }
    saved_path = storage_dir / "requests" / f"{preview['request_id']}.json"
    assert saved_path.exists()


def test_preview_save_rejects_non_pending_status() -> None:
    accepted = accept_request(
        generate_request(EntryRequest(raw_title="芙莉莲"))["request"]
    )

    response = _client().post(
        "/api/v1/requests/preview-save",
        json={"request": accepted},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["error_type"] == "invalid_request_status"


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
                "保存订阅方案 JSON 失败",
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
    assert payload["error_message"] == "保存订阅方案 JSON 失败"
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
    assert payload["error_message"] == "只有已确认订阅方案可以提交到 Auto Bangumi"
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


def _batch_accept(
    client: FlaskClient,
    batch_id: str,
    storage_dir: Path,
    items: list[dict[str, Any]],
    item_ids: list[str] | None = None,
) -> Any:
    """POST the batch accept endpoint and return the raw test response."""
    payload: dict[str, Any] = {
        "items": items,
        "storage_dir": str(storage_dir),
    }
    if item_ids is not None:
        payload["item_ids"] = item_ids
    return client.post(f"/api/v1/batches/{batch_id}/accept", json=payload)


def _batch_submit_payload(storage_dir: Path) -> dict[str, Any]:
    return {
        "storage_dir": str(storage_dir),
        "confirm": True,
        "ab_config": {
            "endpoint": "http://auto-bangumi.local/api",
            "token": "secret-token",
            "fallback_enabled": False,
        },
    }


def test_batch_accept_api_accepts_selected_items_and_returns_queue(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    _saved_request(tmp_path, "咒术回战第三季", "request-b")
    storage_dir = tmp_path / "storage"

    response = _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"},
            {
                "item_id": "item-b",
                "request_id": "request-b",
                "title": "咒术回战第三季",
            },
        ],
        item_ids=["item-a"],
    )

    payload = response.get_json()
    result = payload["result"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["batch_id"] == "batch-1"
    assert result["summary"] == {
        "accepted": 1,
        "already_accepted": 0,
        "unacceptable": 0,
        "failed": 0,
    }
    assert result["items"] == [
        {
            "item_id": "item-a",
            "request_id": "request-a",
            "title": "芙莉莲",
            "status": "accepted",
            "reason": None,
            "error_type": None,
            "queued": True,
        }
    ]
    queue_items = result["queue"]["items"]
    assert len(queue_items) == 1
    assert queue_items[0]["item_id"] == "item-a"
    assert queue_items[0]["request_id"] == "request-a"
    assert queue_items[0]["status"] == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
    assert queue_items[0]["status_label"] == "待提交"
    assert queue_items[0]["attempts"] == 0
    assert queue_items[0]["last_error"] is None
    assert queue_items[0]["ab_result_summary"] is None

    # The accepted request is persisted as ACCEPTED with an ACCEPT history event.
    config = load_storage_config(storage_dir)
    saved = load_request_snapshot(config, "request-a")
    assert saved["status"] == "ACCEPTED"
    history = load_status_history(config, "request-a")
    assert history[-1]["action"] == "ACCEPT"


def test_batch_accept_api_accepts_all_when_item_ids_omitted(tmp_path: Path) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    _saved_request(tmp_path, "咒术回战第三季", "request-b")
    storage_dir = tmp_path / "storage"

    response = _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"},
            {
                "item_id": "item-b",
                "request_id": "request-b",
                "title": "咒术回战第三季",
            },
        ],
    )

    payload = response.get_json()
    result = payload["result"]
    assert payload["ok"] is True
    assert [item["status"] for item in result["items"]] == ["accepted", "accepted"]
    assert [item["queued"] for item in result["items"]] == [True, True]
    assert [item["item_id"] for item in result["queue"]["items"]] == [
        "item-a",
        "item-b",
    ]
    assert result["summary"]["accepted"] == 2


def test_batch_accept_api_marks_unacceptable_items_with_chinese_reason(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"

    response = _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"},
            {"item_id": "item-b", "request_id": "missing-request", "title": "不存在"},
            {"item_id": "item-c", "title": "无草案"},
        ],
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert payload["ok"] is True
    assert [(item["status"], item["queued"]) for item in items] == [
        ("accepted", True),
        ("unacceptable", False),
        ("unacceptable", False),
    ]
    assert items[1]["reason"] == "订阅方案不存在或已删除"
    assert items[2]["reason"] == "卡片缺少订阅草案，无法接受"
    assert payload["result"]["summary"]["unacceptable"] == 2
    assert len(payload["result"]["queue"]["items"]) == 1


def test_batch_accept_api_is_idempotent_for_already_accepted_items(
    tmp_path: Path,
) -> None:
    _saved_accepted_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"

    response = _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert payload["ok"] is True
    assert item["status"] == "already_accepted"
    assert item["reason"] == "该订阅方案已确认，已补建提交队列"
    assert item["queued"] is True
    # The ACCEPTED Request had no queue item, so one READY_TO_SUBMIT item is
    # rebuilt so it can still be submitted.
    queue_items = payload["result"]["queue"]["items"]
    assert len(queue_items) == 1
    assert queue_items[0]["request_id"] == "request-a"
    assert queue_items[0]["status"] == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
    assert payload["result"]["summary"]["already_accepted"] == 1


def test_batch_accept_api_keeps_existing_queue_item_idempotent(
    tmp_path: Path,
) -> None:
    """ACCEPTED + queue already holds the request_id: no duplicate enqueue."""
    _saved_accepted_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    response = _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    payload = response.get_json()
    item = payload["result"]["items"][0]
    assert payload["ok"] is True
    assert item["status"] == "already_accepted"
    assert item["reason"] == "该订阅方案已确认，跳过重复接受"
    assert item["queued"] is False
    assert len(payload["result"]["queue"]["items"]) == 1


def test_batch_accept_api_accepts_empty_selection(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _batch_accept(_client(), "batch-1", storage_dir, items=[])

    payload = response.get_json()
    result = payload["result"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["batch_id"] == "batch-1"
    assert result["items"] == []
    assert result["queue"]["items"] == []
    assert result["summary"] == {
        "accepted": 0,
        "already_accepted": 0,
        "unacceptable": 0,
        "failed": 0,
    }


def test_batch_accept_api_single_failure_does_not_block_others(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    _saved_cancelled_request(tmp_path, "咒术回战", "request-b")
    storage_dir = tmp_path / "storage"

    response = _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"},
            {"item_id": "item-b", "request_id": "request-b", "title": "咒术回战"},
        ],
    )

    payload = response.get_json()
    items = payload["result"]["items"]
    assert payload["ok"] is True
    assert items[0]["status"] == "accepted"
    assert items[1]["status"] == "unacceptable"
    assert items[1]["error_type"] == "request_cancelled"
    assert len(payload["result"]["queue"]["items"]) == 1


def test_batch_accept_api_redacts_sensitive_item_title(tmp_path: Path) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    malicious_title = "芙莉莲 https://ab.example.com/api token=secret-token"

    response = _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {
                "item_id": "item-a",
                "request_id": "request-a",
                "title": malicious_title,
            }
        ],
    )

    payload = response.get_json()
    body = response.get_data(as_text=True)
    assert payload["ok"] is True
    assert (
        payload["result"]["items"][0]["title"]
        == "芙莉莲 [redacted-url] [redacted]"
    )
    assert (
        payload["result"]["queue"]["items"][0]["title"]
        == "芙莉莲 [redacted-url] [redacted]"
    )
    assert "ab.example.com" not in body
    assert "secret-token" not in body


def test_batch_queue_api_returns_sanitized_queue(tmp_path: Path) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    response = _client().get(
        "/api/v1/batches/batch-1/queue",
        query_string={"storage_dir": str(storage_dir)},
    )

    payload = response.get_json()
    result = payload["result"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["batch_id"] == "batch-1"
    assert result["queue"]["batch_id"] == "batch-1"
    assert result["queue"]["queue_id"]
    assert len(result["queue"]["items"]) == 1
    item = result["queue"]["items"][0]
    assert item["request_id"] == "request-a"
    assert item["status"] == BATCH_QUEUE_STATUS_READY_TO_SUBMIT
    assert item["status_label"] == "待提交"
    assert item["attempts"] == 0
    assert item["last_error"] is None
    assert item["ab_result_summary"] is None


def test_batch_queue_api_returns_none_when_queue_missing(tmp_path: Path) -> None:
    response = _client().get(
        "/api/v1/batches/batch-missing/queue",
        query_string={"storage_dir": str(tmp_path / "storage")},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": True,
        "result": {"batch_id": "batch-missing", "queue": None},
    }


def test_batch_queue_api_does_not_leak_sensitive_values(tmp_path: Path) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {
                "item_id": "item-a",
                "request_id": "request-a",
                "title": "芙莉莲 https://ab.example.com/api token=secret-token",
            }
        ],
    )

    response = _client().get(
        "/api/v1/batches/batch-1/queue",
        query_string={"storage_dir": str(storage_dir)},
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "ab.example.com" not in body
    assert "secret-token" not in body
    assert "Authorization" not in body


def test_batch_submit_api_requires_confirmation(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/batches/batch-1/submit",
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
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "validation_error",
        "error_message": "请确认提交到 Auto Bangumi",
        "error_data": {
            "failed_step": "batch_submit",
            "details": {"field": "confirm"},
        },
    }
    assert "secret-token" not in str(payload)


def test_batch_submit_api_requires_ab_config(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/batches/batch-1/submit",
        json={"storage_dir": str(storage_dir), "confirm": True},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "validation_error",
        "error_message": "请提供 Auto Bangumi 配置",
        "error_data": {
            "failed_step": "batch_submit",
            "details": {"field": "ab_config"},
        },
    }


def test_batch_submit_api_submits_queue_items_successfully(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    client = FakeAutoBangumiClient()
    received_configs = []

    def build_client(ab_config):
        received_configs.append(ab_config)
        return client

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        build_client,
    )

    response = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )

    payload = response.get_json()
    result = payload["result"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["batch_id"] == "batch-1"
    assert result["summary"] == {
        "succeeded": 1,
        "failed": 0,
        "retryable": 0,
        "skipped": 0,
        "needs_manual": 0,
    }
    assert result["items"] == [
        {
            "item_id": "item-a",
            "request_id": "request-a",
            "title": "芙莉莲",
            "status": "succeeded",
            "reason": None,
            "error_type": None,
            "attempts": 1,
        }
    ]
    queue_item = result["queue"]["items"][0]
    assert queue_item["status"] == BATCH_QUEUE_STATUS_SUCCEEDED
    assert queue_item["status_label"] == "提交成功"
    assert queue_item["attempts"] == 1
    assert (
        queue_item["ab_result_summary"]
        == "ab_subscription_id=fake-ab-subscription; success=True"
    )
    assert len(client.calls) == 1
    assert received_configs[0].endpoint == "http://auto-bangumi.local/api"
    assert received_configs[0].token == "secret-token"

    # The request-scoped ab_config is never persisted into the queue storage.
    queue_body = (
        load_storage_config(storage_dir).queue_dir / "batch-1.json"
    ).read_text(encoding="utf-8")
    assert "secret-token" not in queue_body
    assert "auto-bangumi.local" not in queue_body


def test_batch_submit_api_single_failure_does_not_block_others(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    _saved_request(tmp_path, "咒术回战第三季", "request-b")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"},
            {
                "item_id": "item-b",
                "request_id": "request-b",
                "title": "咒术回战第三季",
            },
        ],
    )
    # Remove request-b's snapshot so pre-submit validation rejects that item.
    delete_request_snapshot(load_storage_config(storage_dir), "request-b")

    client = FakeAutoBangumiClient()
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: client,
    )

    response = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )

    payload = response.get_json()
    result = payload["result"]
    assert payload["ok"] is True
    assert result["summary"] == {
        "succeeded": 1,
        "failed": 1,
        "retryable": 0,
        "skipped": 0,
        "needs_manual": 0,
    }
    assert result["items"][0]["status"] == "succeeded"
    assert result["items"][1]["status"] == "failed"
    assert result["items"][1]["error_type"] == "request_not_found"
    assert result["items"][1]["reason"] == "订阅方案不存在或已删除，无法提交"
    # Only the surviving item was submitted to Auto Bangumi.
    assert len(client.calls) == 1


def test_batch_submit_api_skips_already_succeeded_items(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    client = FakeAutoBangumiClient()
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: client,
    )

    submit_payload = _batch_submit_payload(storage_dir)
    first = _client().post("/api/v1/batches/batch-1/submit", json=submit_payload)
    second = _client().post("/api/v1/batches/batch-1/submit", json=submit_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    second_payload = second.get_json()
    assert second_payload["ok"] is True
    assert second_payload["result"]["summary"] == {
        "succeeded": 0,
        "failed": 0,
        "retryable": 0,
        "skipped": 1,
        "needs_manual": 0,
    }
    assert second_payload["result"]["items"][0]["status"] == "skipped"
    assert (
        second_payload["result"]["items"][0]["reason"]
        == "已提交成功，跳过重复提交"
    )
    # The already-succeeded item is never re-submitted.
    assert len(client.calls) == 1


def test_batch_submit_api_returns_queue_not_found_for_missing_queue(
    tmp_path: Path,
) -> None:
    response = _client().post(
        "/api/v1/batches/batch-missing/submit",
        json=_batch_submit_payload(tmp_path / "storage"),
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "queue_not_found",
        "error_message": "未找到该批次的提交队列",
        "error_data": {
            "failed_step": "load_submission_queue",
            "details": {"batch_id": "batch-missing"},
        },
    }


def test_batch_submit_api_does_not_leak_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {
                "item_id": "item-a",
                "request_id": "request-a",
                "title": "芙莉莲 https://ab.example.com/api token=secret-token",
            }
        ],
    )

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: FakeAutoBangumiClient(),
    )

    response = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "ab.example.com" not in body
    assert "secret-token" not in body
    assert "auto-bangumi.local" not in body
    assert "Authorization" not in body


def test_batch_submit_api_persists_ab_result_into_request_and_ab_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Batch submit writes the sanitized AB result into the Request snapshot and
    ab_results/<request_id>.json, and the detail API can read it."""
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: FakeAutoBangumiClient(),
    )

    response = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["items"][0]["status"] == "succeeded"

    config = load_storage_config(storage_dir)
    # Request snapshot carries the sanitized AB result (single-item contract).
    request_body = (config.requests_dir / "request-a.json").read_text(encoding="utf-8")
    request_snapshot = json.loads(request_body)
    assert request_snapshot["ab_submit_result"]["success"] is True
    assert (
        request_snapshot["ab_submit_result"]["ab_subscription_id"]
        == "fake-ab-subscription"
    )
    # ab_results/<request_id>.json exists with the sanitized record.
    ab_result = load_ab_submit_result(config, "request-a")
    assert ab_result["request_id"] == "request-a"
    assert ab_result["ab_submit_result"]["success"] is True
    assert (
        ab_result["ab_submit_result"]["ab_subscription_id"]
        == "fake-ab-subscription"
    )
    # The Request detail API can read and show the result.
    detail = _client().get(
        "/api/v1/requests/request-a",
        query_string={"storage_dir": str(storage_dir)},
    ).get_json()
    assert detail["ok"] is True
    assert detail["result"]["ab_result"]["available"] is True
    assert (
        detail["result"]["ab_result"]["record"]["ab_submit_result"][
            "ab_subscription_id"
        ]
        == "fake-ab-subscription"
    )
    # No secrets in any persisted file.
    for text in (
        request_body,
        (config.ab_results_dir / "request-a.json").read_text(encoding="utf-8"),
    ):
        assert "secret-token" not in text
        assert "auto-bangumi.local" not in text
        assert "Authorization" not in text


def test_batch_submit_api_persists_failed_ab_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed batch submit also persists the sanitized failure result."""
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    failing_client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_auth_failed",
            "Auto Bangumi 认证失败",
            "submit_ab_subscription",
            {},
        )
    )
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: failing_client,
    )

    response = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["result"]["items"][0]["status"] == "failed"
    assert payload["result"]["items"][0]["error_type"] == "ab_auth_failed"

    config = load_storage_config(storage_dir)
    request_snapshot = json.loads(
        (config.requests_dir / "request-a.json").read_text(encoding="utf-8")
    )
    assert request_snapshot["ab_submit_result"]["success"] is False
    assert (
        request_snapshot["ab_submit_result"]["error"]["error_type"]
        == "ab_auth_failed"
    )
    ab_result = load_ab_submit_result(config, "request-a")
    assert ab_result["ab_submit_result"]["success"] is False
    assert ab_result["ab_submit_result"]["error"]["error_type"] == "ab_auth_failed"


def test_batch_retry_api_requires_ab_config(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/batches/batch-1/retry",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "confirm": True,
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "validation_error",
        "error_message": "请提供 Auto Bangumi 配置",
        "error_data": {
            "failed_step": "batch_retry",
            "details": {"field": "ab_config"},
        },
    }


def test_batch_retry_api_requires_confirmation(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/batches/batch-1/retry",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "ab_config": {
                "endpoint": "http://auto-bangumi.local/api",
                "token": "secret-token",
                "fallback_enabled": False,
            },
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "validation_error",
        "error_message": "请确认提交到 Auto Bangumi",
        "error_data": {
            "failed_step": "batch_retry",
            "details": {"field": "confirm"},
        },
    }
    assert "secret-token" not in str(payload)


def test_batch_retry_api_retries_failed_item_successfully(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    failing_client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "离线模拟失败",
            "create_ab_subscription",
            {"status_code": 503},
        )
    )
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: failing_client,
    )
    first = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )
    first_result = first.get_json()["result"]
    assert first_result["items"][0]["status"] == "failed"
    assert first_result["items"][0]["attempts"] == 1

    success_client = FakeAutoBangumiClient()
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: success_client,
    )
    response = _client().post(
        "/api/v1/batches/batch-1/retry",
        json={**_batch_submit_payload(storage_dir), "request_id": "request-a"},
    )

    payload = response.get_json()
    result = payload["result"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert result["batch_id"] == "batch-1"
    assert result["summary"] == {
        "succeeded": 1,
        "failed": 0,
        "retryable": 0,
        "skipped": 0,
        "needs_manual": 0,
    }
    assert result["items"] == [
        {
            "item_id": "item-a",
            "request_id": "request-a",
            "title": "芙莉莲",
            "status": "succeeded",
            "reason": None,
            "error_type": None,
            "attempts": 2,
        }
    ]
    queue_item = result["queue"]["items"][0]
    assert queue_item["status"] == BATCH_QUEUE_STATUS_SUCCEEDED
    assert queue_item["status_label"] == "提交成功"
    assert queue_item["attempts"] == 2
    # The retry submitted exactly one more Auto Bangumi request.
    assert len(success_client.calls) == 1
    assert len(failing_client.calls) == 1

    # The request-scoped ab_config is never persisted into the queue storage.
    queue_body = (
        load_storage_config(storage_dir).queue_dir / "batch-1.json"
    ).read_text(encoding="utf-8")
    assert "secret-token" not in queue_body
    assert "auto-bangumi.local" not in queue_body


def test_batch_retry_api_failure_keeps_retryable_status_and_increments_attempts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    timeout_client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_timeout",
            "请求超时",
            "create_ab_subscription",
            {"category": "timeout"},
        )
    )
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: timeout_client,
    )
    first = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )
    assert first.get_json()["result"]["items"][0]["status"] == "retryable"

    response = _client().post(
        "/api/v1/batches/batch-1/retry",
        json={**_batch_submit_payload(storage_dir), "request_id": "request-a"},
    )

    payload = response.get_json()
    result = payload["result"]
    assert payload["ok"] is True
    assert result["summary"] == {
        "succeeded": 0,
        "failed": 0,
        "retryable": 1,
        "skipped": 0,
        "needs_manual": 0,
    }
    item = result["items"][0]
    assert item["status"] == "retryable"
    assert item["error_type"] == "ab_timeout"
    assert item["reason"] == "请求超时"
    assert item["attempts"] == 2
    queue_item = result["queue"]["items"][0]
    assert queue_item["status"] == BATCH_QUEUE_STATUS_RETRYABLE
    assert queue_item["status_label"] == "可重试"
    assert queue_item["attempts"] == 2
    assert len(timeout_client.calls) == 2


def test_batch_retry_api_skips_succeeded_items_without_resubmit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    success_client = FakeAutoBangumiClient()
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: success_client,
    )
    first = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )
    assert first.get_json()["result"]["items"][0]["status"] == "succeeded"

    retry_client = FakeAutoBangumiClient()
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: retry_client,
    )
    response = _client().post(
        "/api/v1/batches/batch-1/retry",
        json={**_batch_submit_payload(storage_dir), "request_id": "request-a"},
    )

    payload = response.get_json()
    result = payload["result"]
    assert payload["ok"] is True
    assert result["summary"] == {
        "succeeded": 0,
        "failed": 0,
        "retryable": 0,
        "skipped": 1,
        "needs_manual": 0,
    }
    assert result["items"][0]["status"] == "skipped"
    assert result["items"][0]["reason"] == "已提交成功，不可重复提交"
    assert result["items"][0]["attempts"] == 1
    assert result["queue"]["items"][0]["status"] == BATCH_QUEUE_STATUS_SUCCEEDED
    # The already-succeeded item is never re-submitted.
    assert len(retry_client.calls) == 0


def test_batch_retry_api_returns_queue_item_not_found_for_unknown_request_id(
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[{"item_id": "item-a", "request_id": "request-a", "title": "芙莉莲"}],
    )

    response = _client().post(
        "/api/v1/batches/batch-1/retry",
        json={**_batch_submit_payload(storage_dir), "request_id": "request-missing"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload == {
        "ok": False,
        "error_type": "queue_item_not_found",
        "error_message": "队列中不存在该订阅方案项目",
        "error_data": {
            "failed_step": "batch_retry",
            "details": {"field": "request_id", "batch_id": "batch-1"},
        },
    }


def test_batch_retry_api_does_not_leak_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _saved_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _batch_accept(
        _client(),
        "batch-1",
        storage_dir,
        items=[
            {
                "item_id": "item-a",
                "request_id": "request-a",
                "title": "芙莉莲 https://ab.example.com/api token=secret-token",
            }
        ],
    )

    failing_client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "离线模拟失败",
            "create_ab_subscription",
            {"status_code": 503},
        )
    )
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: failing_client,
    )
    first = _client().post(
        "/api/v1/batches/batch-1/submit",
        json=_batch_submit_payload(storage_dir),
    )
    assert first.get_json()["result"]["items"][0]["status"] == "failed"

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda _config: FakeAutoBangumiClient(),
    )
    response = _client().post(
        "/api/v1/batches/batch-1/retry",
        json={**_batch_submit_payload(storage_dir), "request_id": "request-a"},
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "ab.example.com" not in body
    assert "secret-token" not in body
    assert "auto-bangumi.local" not in body
    assert "Authorization" not in body
    assert "<rss" not in body


def _submitting_queue_json(
    storage_dir: Path,
    *,
    batch_id: str = "batch-1",
    request_id: str = "request-a",
    item_id: str = "item-a",
    title: str = "芙莉莲",
) -> None:
    """Persist a queue whose item is stuck SUBMITTING (as after an interrupt)."""
    queue = create_submission_queue(
        batch_id,
        queue_id_factory=lambda: "queue-1",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = enqueue_item(
        queue,
        item_id=item_id,
        request_id=request_id,
        title=title,
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = start_queue_item_submit(
        queue,
        request_id,
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    save_submission_queue(load_storage_config(storage_dir), queue)


def _result_persist_failed_queue_json(
    storage_dir: Path,
    *,
    batch_id: str = "batch-1",
    request_id: str = "request-a",
    item_id: str = "item-a",
    title: str = "芙莉莲",
) -> None:
    """Persist a queue whose item is stuck RESULT_PERSIST_FAILED."""
    queue = create_submission_queue(
        batch_id,
        queue_id_factory=lambda: "queue-1",
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = enqueue_item(
        queue,
        item_id=item_id,
        request_id=request_id,
        title=title,
        now_factory=lambda: "2026-08-19T00:00:00+00:00",
    )
    queue = start_queue_item_submit(
        queue,
        request_id,
        now_factory=lambda: "2026-08-19T00:01:00+00:00",
    )
    queue = complete_queue_item_submit(
        queue,
        request_id,
        "RESULT_PERSIST_FAILED",
        last_error={"error_type": "result_persist_failed", "error_message": "保存失败"},
        now_factory=lambda: "2026-08-19T00:02:00+00:00",
    )
    save_submission_queue(load_storage_config(storage_dir), queue)


def _saved_request_with_ab_result(
    tmp_path: Path,
    title: str,
    request_id: str,
) -> None:
    """Save an ACCEPTED Request snapshot that already carries an AB result."""
    request = _saved_accepted_request(tmp_path, title, request_id)
    request["ab_submit_result"] = {
        "success": True,
        "ab_subscription_id": "fake-ab-subscription",
        "ab_response": {"id": "fake-ab-subscription"},
        "fallback_config": None,
        "error": None,
    }
    save_request_snapshot(load_storage_config(tmp_path / "storage"), request)


def test_batch_recover_api_auto_recovers_submitting_to_succeeded(
    tmp_path: Path,
) -> None:
    """auto recovery: SUBMITTING item whose Request already has a persisted AB
    result is finalized to SUCCEEDED (interruption-safe queue recovery)."""
    _saved_request_with_ab_result(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _submitting_queue_json(storage_dir)

    response = _client().post(
        "/api/v1/batches/batch-1/recover",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "action": "auto",
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["items"][0]["status"] == "succeeded"
    assert (
        payload["result"]["items"][0]["reason"]
        == "已根据保存的提交结果恢复为提交成功"
    )
    queue_item = payload["result"]["queue"]["items"][0]
    assert queue_item["status"] == "SUCCEEDED"
    # The recovered queue is persisted.
    persisted = load_submission_queue(load_storage_config(storage_dir), "batch-1")
    assert persisted.items[0].status == "SUCCEEDED"


def test_batch_recover_api_auto_returns_needs_manual_without_result(
    tmp_path: Path,
) -> None:
    _saved_accepted_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _submitting_queue_json(storage_dir)

    response = _client().post(
        "/api/v1/batches/batch-1/recover",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "action": "auto",
        },
    )

    payload = response.get_json()
    assert payload["ok"] is True
    item = payload["result"]["items"][0]
    assert item["status"] == "needs_manual"
    assert item["error_type"] == "requires_manual_recovery"
    assert payload["result"]["queue"]["items"][0]["status"] == "SUBMITTING"


def test_batch_recover_api_manual_succeeded_requires_confirm(
    tmp_path: Path,
) -> None:
    _saved_accepted_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _result_persist_failed_queue_json(storage_dir)

    # Without confirm the manual action is rejected.
    response = _client().post(
        "/api/v1/batches/batch-1/recover",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "action": "succeeded",
        },
    )
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请确认人工核验结果后再恢复"

    # With confirm the item is resolved to SUCCEEDED.
    response = _client().post(
        "/api/v1/batches/batch-1/recover",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "action": "succeeded",
            "confirm": True,
        },
    )
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["result"]["items"][0]["status"] == "succeeded"
    assert payload["result"]["queue"]["items"][0]["status"] == "SUCCEEDED"


def test_batch_recover_api_manual_failed_resolves_result_persist_failed(
    tmp_path: Path,
) -> None:
    _saved_accepted_request(tmp_path, "芙莉莲", "request-a")
    storage_dir = tmp_path / "storage"
    _result_persist_failed_queue_json(storage_dir)

    response = _client().post(
        "/api/v1/batches/batch-1/recover",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "action": "failed",
            "confirm": True,
        },
    )

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["result"]["items"][0]["status"] == "failed"
    assert payload["result"]["queue"]["items"][0]["status"] == "FAILED"
    # The recovered FAILED item is a normal retryable failure now.
    persisted = load_submission_queue(load_storage_config(storage_dir), "batch-1")
    assert persisted.items[0].status == "FAILED"
    assert "manual_recovery_failed" in (persisted.items[0].last_error or "")


def test_batch_recover_api_rejects_invalid_action(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/batches/batch-1/recover",
        json={
            "storage_dir": str(storage_dir),
            "request_id": "request-a",
            "action": "invalid",
        },
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "恢复动作必须是 auto、succeeded 或 failed"


def _preferences_save_body(
    storage_dir: Path,
    preferences: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"storage_dir": str(storage_dir)}
    if preferences is not None:
        body["preferences"] = preferences
    return body


def _full_preferences_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "subtitle_groups": {
            "preferred": ["Loli", "喵萌"],
            "excluded": ["示例组"],
            "fallback": "next_preferred",
        },
        "filter_defaults": {
            "must_contain": "1080p",
            "must_not_contain": "合集版",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "search": {"reuse_explicit_corrections": True},
    }


def test_preference_api_reads_defaults_when_missing(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().get(
        f"/api/v1/preferences?storage_dir={storage_dir}"
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"] == {
        "version": 1,
        "subtitle_groups": {
            "preferred": [],
            "excluded": [],
            "fallback": "next_preferred",
        },
        "filter_defaults": {
            "must_contain": "",
            "must_not_contain": "",
            "use_regex": False,
            "case_sensitive": False,
        },
        "naming": {"strategy": "official_title_season", "template": "{title}"},
        "search": {"reuse_explicit_corrections": True},
    }


def test_preference_api_reads_saved_preferences(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, _full_preferences_payload()),
    )

    response = _client().get(
        f"/api/v1/preferences?storage_dir={storage_dir}"
    )

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["result"] == _full_preferences_payload()


def test_preference_api_save_returns_normalized_preferences_and_persists(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    payload = _full_preferences_payload()

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, payload),
    )

    result = response.get_json()
    assert response.status_code == 200
    assert result["ok"] is True
    assert result["result"] == payload

    # The saved JSON on disk carries only the defined non-sensitive fields.
    config = load_storage_config(storage_dir)
    written = json.loads(
        (config.preferences_dir / "user_preferences.json").read_text(
            encoding="utf-8"
        )
    )
    assert written == payload


def test_preference_api_save_accepts_empty_payload_as_reset(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"
    _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, _full_preferences_payload()),
    )

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, {}),
    )

    result = response.get_json()
    assert result["ok"] is True
    assert result["result"]["subtitle_groups"]["preferred"] == []
    assert result["result"]["subtitle_groups"]["excluded"] == []
    assert result["result"]["filter_defaults"]["must_contain"] == ""


def test_preference_api_save_rejects_missing_preferences(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, None),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "请提供偏好配置"
    assert payload["error_data"]["details"] == {"field": "preferences"}


def test_preference_api_save_rejects_non_object_payload(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, ["Loli"]),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "偏好配置必须是对象"


def test_preference_api_save_rejects_unknown_field_without_leaking(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {
                "subtitle_groups": {"preferred": ["Loli"]},
                "endpoint": "https://secret-endpoint.example/api",
            },
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_message"] == "preferences 包含未定义字段"
    assert "secret-endpoint" not in str(payload)


def test_preference_api_save_rejects_empty_string_list_item(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {"subtitle_groups": {"preferred": [""]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "subtitle_groups.preferred"
    }
    assert "空字符串" in payload["error_message"]


def test_preference_api_save_rejects_duplicate_subtitle_groups(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {"subtitle_groups": {"preferred": ["Loli", "Loli"]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "subtitle_groups.preferred"
    }
    assert "重复" in payload["error_message"]


def test_preference_api_save_rejects_group_in_both_lists(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {
                "subtitle_groups": {
                    "preferred": ["Loli"],
                    "excluded": ["Loli"],
                }
            },
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {"field": "subtitle_groups"}
    assert "不能同时出现" in payload["error_message"]


def test_preference_api_save_rejects_invalid_fallback_enum(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {"subtitle_groups": {"fallback": "auto"}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "subtitle_groups.fallback"
    }


def test_preference_api_save_rejects_invalid_naming_strategy(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {"naming": {"strategy": "random"}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {"field": "naming.strategy"}


def test_preference_api_save_rejects_non_boolean_filter_flag(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {"filter_defaults": {"use_regex": "yes"}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert payload["error_data"]["details"] == {
        "field": "filter_defaults.use_regex"
    }


def test_preference_api_save_rejects_overlong_string(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {"subtitle_groups": {"preferred": ["长" * 101]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "长度不能超过" in payload["error_message"]


def test_preference_api_save_rejects_sensitive_values(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(
            storage_dir,
            {"subtitle_groups": {"preferred": ["https://mikan.example/Home/Search"]}},
        ),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "validation_error"
    assert "敏感内容" in payload["error_message"]
    assert "https://mikan.example" not in str(payload)
    # No preference file is written for an illegal save.
    config = load_storage_config(storage_dir)
    assert not (config.preferences_dir / "user_preferences.json").exists()


def test_preference_api_save_does_not_leak_sensitive_values(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, _full_preferences_payload()),
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    for marker in (
        "http://",
        "https://",
        "magnet:",
        "token",
        "secret",
        "cookie",
        "Authorization",
        "raw_html",
        "raw_rss",
        "<html",
        "<rss",
    ):
        assert marker not in body.lower()


def test_preference_api_save_storage_failure_returns_chinese_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "storage"

    def fail_save(*args: object, **kwargs: object) -> dict[str, Any]:
        raise Stage1Error(
            "storage_error",
            "保存用户偏好 JSON 失败",
            "save_user_preferences",
            {
                "reason": f"cannot write {tmp_path}/private-token at https://example.test/api",
                "directory": "preferences",
            },
        )

    monkeypatch.setattr(
        "apps.migu_orca_web.views.save_user_preferences",
        fail_save,
    )

    response = _client().post(
        "/api/v1/preferences",
        json=_preferences_save_body(storage_dir, _full_preferences_payload()),
    )

    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error_type"] == "storage_error"
    assert payload["error_message"] == "保存用户偏好 JSON 失败"
    assert payload["error_data"]["failed_step"] == "save_user_preferences"
    assert str(tmp_path) not in str(payload)
    assert "https://example.test/api" not in str(payload)
    assert "token" not in str(payload).lower()
