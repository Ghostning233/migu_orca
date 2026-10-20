from __future__ import annotations

"""Issue #86: submit feedback channels in real Chromium.

A saved Auto Bangumi connection is enough to submit; the server answers with a
published, non-sensitive failure classification and the page routes it to the
fixed channel:

* success -> a lightweight global notification plus an immediate convergence of
  the overview, list and detail to 追番中,
* a blocking connection/credential/version problem -> an actionable dialog that
  offers the settings page,
* an external rejection -> stays on the affected record, never a dialog.

Nothing here touches MiKan or Auto Bangumi; the tracking DTO boundary and the
submit endpoint are mocked.
"""

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences
from tests.browser.saved_tracking_fixtures import _item, _status_groups_for, _summary

REPO_ROOT = Path(__file__).resolve().parents[2]
REF = "11111111-1111-4111-8111-111111111111"

pytestmark = pytest.mark.browser


def _dist_built() -> bool:
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    if not _dist_built():
        pytest.skip("frontend/dist not built; run `npm run build` in frontend/")


def _pending_item() -> dict[str, Any]:
    return {
        **_item("tracking-a", "葬送的芙莉莲"),
        "status": "PENDING_SUBMIT",
        "status_label": "待提交",
        "status_group": "PENDING",
        "available_actions": [
            {
                "code": "SUBMIT",
                "label": "提交到 Auto Bangumi",
                "style": "PRIMARY",
                "requires_confirmation": True,
                "target_scopes": [],
            }
        ],
    }


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "origin": "single",
        "batch_id": None,
        "created_at": "2026-09-01T00:00:00Z",
        "last_synced_at": None,
        "safe_info": item.get("safe_info"),
        "current_operation": None,
        "revalidation_issues": [],
        "external_mapping": None,
        # A submit result may carry the audit note the detail must render.
        "audit_events": item.get("audit_events", []),
        "warnings": [],
    }


def _install(page: Page, item: dict[str, Any], submit_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Mock settings/list/detail/submit; the item mutates on a submit result."""
    state: dict[str, Any] = {"item": dict(item)}
    posts: list[dict[str, Any]] = []

    def handler(route: Any, request: Any) -> None:
        path = request.url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if request.method == "GET" and path == "/settings/autobangumi":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "configured": True,
                        "credential_present": True,
                        "connection_ref": REF,
                        "configuration_revision": 3,
                        "connection_status": "CONFIGURED",
                    },
                }
            )
            return
        if request.method == "GET" and path == "/tracking/items":
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "items": [state["item"]],
                        "summary": _summary(1, pending=1),
                        "status_groups": _status_groups_for([state["item"]]),
                        "warnings": [],
                    },
                }
            )
            return
        if request.method == "GET" and path.startswith("/tracking/items/"):
            route.fulfill(json={"ok": True, "result": _detail(state["item"])})
            return
        if request.method == "POST" and path.endswith("/submit"):
            posts.append(request.post_data_json or {})
            state["item"] = {
                **submit_result.pop("tracking", state["item"]),
                "revision": state["item"]["revision"] + 1,
            }
            route.fulfill(
                json={
                    "ok": True,
                    "result": {
                        "tracking_id": "tracking-a",
                        "checked_revision": 1,
                        "next_revision": state["item"]["revision"],
                        "checked_at": "2026-09-14T00:00:00Z",
                        "operation_id": "op-1",
                        "issues": [],
                        **submit_result,
                        "tracking": state["item"],
                    },
                }
            )
            return
        route.continue_()

    page.route("**/api/v1/**", handler)
    return posts


def _open(page: Page, live_server_url: str, storage_dir: Path) -> None:
    _require_dist()
    set_storage_preferences(page, storage_dir)
    page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
    page.wait_for_selector("#tracking-submit")
    expect(page.locator("#tracking-submit")).to_be_enabled()


def _confirm(page: Page) -> None:
    """Issue #98: the submit confirmation is now the submission-mode choice."""
    page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
    page.locator("#tracking-mode-continue").click()


class TestSubmitFeedback:
    def test_success_converges_and_shows_a_lightweight_notice(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        item = _pending_item()
        posts = _install(page, item, {
            "outcome": "ACTIVE",
            "failure_category": None,
            "tracking": {**item, "status": "ACTIVE", "status_label": "追番中", "status_group": "ACTIVE", "available_actions": []},
        })
        _open(page, live_server_url, storage_dir)

        page.locator("#tracking-submit").click()
        _confirm(page)

        page.wait_for_selector(".global-notification", timeout=10_000)
        expect(page.locator(".global-notification")).to_contain_text("提交成功")
        # The list row and the detail converge without a manual refresh.
        expect(page.locator(".tracking-list-item").first).to_contain_text("追番中")
        expect(page.locator(".tracking-inspector")).to_contain_text("追番中")
        assert len(posts) == 1 and posts[0]["confirm"] is True

    def test_authentication_failure_opens_an_actionable_dialog(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        item = _pending_item()
        _install(page, item, {
            "outcome": "SUBMIT_FAILED",
            "failure_category": "AUTHENTICATION",
            "tracking": {**item, "status": "SUBMIT_FAILED", "status_label": "提交失败", "status_group": "ATTENTION"},
        })
        _open(page, live_server_url, storage_dir)

        page.locator("#tracking-submit").click()
        _confirm(page)

        # The blocking dialog is a *second* dialog after the impact confirmation.
        page.wait_for_function(
            "() => document.querySelector('.confirm-dialog-title')?.textContent?.includes('认证失败')"
        )
        expect(page.locator(".confirm-dialog-message")).to_contain_text("前往设置")
        expect(page.locator(".confirm-dialog .primary-button")).to_contain_text("前往设置")
        # The record keeps the actionable next step as well as the dialog.
        expect(page.locator("#tracking-submit-result")).to_contain_text("凭据")

    def test_unsupported_capability_opens_the_settings_dialog_not_a_version_hint(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """Issue #216 AC8: an unsupported submit capability is its own class.

        The saved connection cannot submit (for example an API Token connection)
        while the version is exactly the verified one, so the page must not claim
        a version problem: it offers the settings next step like the other
        blocking connection classes.
        """
        item = _pending_item()
        _install(page, item, {
            "outcome": "SUBMIT_FAILED",
            "failure_category": "CAPABILITY",
            "tracking": {**item, "status": "SUBMIT_FAILED", "status_label": "提交失败", "status_group": "ATTENTION"},
        })
        _open(page, live_server_url, storage_dir)

        page.locator("#tracking-submit").click()
        _confirm(page)

        page.wait_for_function(
            "() => document.querySelector('.confirm-dialog-title')?.textContent?.includes('不支持创建订阅')"
        )
        expect(page.locator(".confirm-dialog-message")).to_contain_text("API Token")
        expect(page.locator(".confirm-dialog .primary-button")).to_contain_text("前往设置")
        # The record keeps the actionable next step and never blames the version.
        expect(page.locator("#tracking-submit-result")).to_contain_text("不支持创建外部订阅")
        expect(page.locator("#tracking-submit-result")).not_to_contain_text("版本不在已验证")

    def test_external_rejection_stays_on_the_record_without_a_dialog(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        item = _pending_item()
        _install(page, item, {
            "outcome": "SUBMIT_FAILED",
            "failure_category": "REJECTED",
            "tracking": {**item, "status": "SUBMIT_FAILED", "status_label": "提交失败", "status_group": "ATTENTION"},
        })
        _open(page, live_server_url, storage_dir)

        page.locator("#tracking-submit").click()
        _confirm(page)
        page.wait_for_timeout(300)

        # No second dialog and no global success toast: the rejection copy lives
        # on the affected record.
        assert page.locator(".confirm-dialog").count() == 0
        assert page.locator(".global-notification").count() == 0
        expect(page.locator("#tracking-submit-result")).to_contain_text("明确拒绝")

class TestExactReadbackFeedback:
    """Issue #97: the page shows the exact read-back outcomes, not the body."""

    def test_zero_resources_keeps_the_plan_pending_with_the_exact_wording(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = _pending_item()
        _install(
            page,
            item,
            {
                "tracking": {
                    **item,
                    "status": "NEEDS_RECONFIRM",
                    "status_label": "需重新确认",
                    "status_group": "ATTENTION",
                },
                "issues": [
                    {
                        "code": "NO_VALID_RESOURCES",
                        "field": "resources",
                        "message": "在现有筛选规则下未找到资源，请重新检查追番方案",
                        "severity": "BLOCKING",
                    }
                ],
            },
        )

        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-submit")
        page.locator("#tracking-submit").click()
        page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
        page.locator("#tracking-mode-continue").click()

        # The exact, actionable wording is what the user reads; no success notice.
        expect(page.locator("#app-main")).to_contain_text(
            "在现有筛选规则下未找到资源，请重新检查追番方案"
        )
        assert page.locator(".global-notification").count() == 0

    def test_confirmed_subscription_with_an_unconfirmed_body_stays_active(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        """AC 4: the read-back wins, and the record keeps a safe warning note."""
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = _pending_item()
        warning = "订阅已建立，但 Auto Bangumi 的写响应未确认"
        _install(
            page,
            item,
            {
                "tracking": {
                    **item,
                    "status": "ACTIVE",
                    "status_label": "追番中",
                    "status_group": "ACTIVE",
                    "audit_events": [
                        {
                            "action": "SUBMIT_SUCCEEDED",
                            "actor": "SYSTEM",
                            "safe_message": warning,
                            "reason_code": None,
                            "created_at": "2026-09-14T00:00:00Z",
                        }
                    ],
                },
                "issues": [],
            },
        )

        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-submit")
        page.locator("#tracking-submit").click()
        page.wait_for_selector("#tracking-mode-continue", timeout=10_000)
        page.locator("#tracking-mode-continue").click()

        page.wait_for_selector("#tracking-overview", timeout=10_000)
        page.evaluate(
            "() => document.querySelectorAll('.tracking-inspector-content details')"
            ".forEach((el) => { el.open = true; })"
        )
        expect(page.locator("#app-main")).to_contain_text("追番中")
        expect(page.locator("#app-main")).to_contain_text(warning)

class TestSubmissionModeChoice:
    """Issue #98: one stable entry button, then an explicit mode choice."""

    def test_entry_opens_the_choice_without_a_request_and_cancel_sends_nothing(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        posts = _install(page, _pending_item(), {"tracking": _pending_item()})

        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-submit")
        # AC 2: the entry label is stable whatever the submission will become.
        expect(page.locator("#tracking-submit")).to_have_text("提交方案")

        page.locator("#tracking-submit").click()
        page.wait_for_selector("#tracking-mode-cancel", timeout=10_000)
        assert posts == [], "opening the dialog must not send anything"
        expect(page.locator(".tracking-mode-dialog .confirm-dialog-title")).to_have_text("选择提交方式")
        assert page.locator(".tracking-mode-dialog .confirm-dialog-actions button").all_inner_texts() == [
            "取消", "下载现有资源", "持续追番",
        ]

        page.locator("#tracking-mode-cancel").click()
        page.wait_for_timeout(200)
        assert posts == [], "cancelling the choice must send nothing"
        expect(page.locator("#tracking-submit")).to_have_text("提交方案")

    @pytest.mark.parametrize(
        ("button", "mode"),
        [("#tracking-mode-download", "DOWNLOAD_EXISTING"), ("#tracking-mode-continue", "CONTINUE_TRACKING")],
    )
    def test_choosing_a_mode_submits_once_with_that_mode(
        self, page: Page, live_server_url: str, storage_dir: Path, button: str, mode: str
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = _pending_item()
        posts = _install(
            page,
            item,
            {
                "tracking": {
                    **item,
                    "status": "ACTIVE",
                    "status_label": "追番中",
                    "status_group": "ACTIVE",
                }
            },
        )

        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-submit")
        page.locator("#tracking-submit").click()
        page.wait_for_selector(button, timeout=10_000)
        # The mode choice replaces the second impact dialog for submit-family actions.
        page.locator(button).click()
        page.wait_for_timeout(400)

        assert len(posts) == 1, "one choice must produce exactly one external request"
        body = posts[0]
        assert body["submission_mode"] == mode
        assert body["confirm"] is True
        # The dialog converged away once the write settled.
        assert page.locator(".tracking-mode-dialog").count() == 0

class TestAddedToDownloadLifecycle:
    """Issue #99: a one-time acceptance is local history, not a subscription."""

    def test_one_time_acceptance_lands_on_added_to_download(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = {
            **_pending_item(),
            "safe_info": {
                "request_id": "request-plan", "status": "ACCEPTED", "raw_title": "安全标题",
                "title": "葬送的芙莉莲", "aliases": [], "season": 1, "season_raw": None,
                "season_evidence": None, "subtitle_groups": [], "selected_subtitle_group": "喵萌",
                "mikan_collection": {"bangumi_id": "mikan-1234", "title": "葬送的芙莉莲", "season": 1},
                "filter_rule": {"must_contain": "", "must_not_contain": "", "use_regex": False, "case_sensitive": False},
                "resources": {"selected_subtitle_group": "喵萌", "valid_resource_count": 1,
                              "invalid_resource_count": 0, "complete_resource_count": 1,
                              "valid_file_names": ["第一集.mkv"], "excluded_file_names": []},
                "folder_name": "安全文件夹", "storage_profile": "profile", "total_episodes": None,
                "updated_episode": None, "updated_episode_status": "NOT_IMPLEMENTED",
                "history_summary": [], "ab_status": None,
            },
        }
        posts = _install(
            page,
            item,
            {
                "outcome": "ADDED_TO_DOWNLOAD",
                "failure_category": None,
                "tracking": {
                    **item,
                    "status": "ADDED_TO_DOWNLOAD",
                    "status_label": "已加入下载",
                    "status_group": "ACTIVE",
                    # No submit-family action remains: history stays readable.
                    "available_actions": [],
                }
            },
        )

        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        page.wait_for_selector("#tracking-submit")
        page.locator("#tracking-submit").click()
        page.wait_for_selector("#tracking-mode-download", timeout=10_000)
        page.locator("#tracking-mode-download").click()
        page.wait_for_timeout(400)

        assert len(posts) == 1 and posts[0]["submission_mode"] == "DOWNLOAD_EXISTING"
        # The acceptance is stated without promising completed media.
        expect(page.locator("#app-main")).to_contain_text("已加入下载")
        expect(page.locator("#app-main")).to_contain_text("不代表资源已下载完成")
        # AC 26: no in-place resubmit or retry for the completed record.
        assert page.locator("#tracking-submit").count() == 0
        assert page.locator("#tracking-retry").count() == 0
        # AC 23/25: the local history can still be deleted or reused.
        expect(page.locator("#tracking-delete-plan")).to_be_visible()
        expect(page.locator("#tracking-reuse-plan")).to_be_visible()

class TestFailureDiagnostics:
    """Issue #101: layered, sanitized failure feedback for both modes."""

    def _submit(self, page: Page, button: str) -> None:
        page.wait_for_selector("#tracking-submit")
        page.locator("#tracking-submit").click()
        page.wait_for_selector(button, timeout=10_000)
        page.locator(button).click()
        page.wait_for_timeout(400)

    def test_one_time_failure_keeps_only_the_retryable_sentence(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = _pending_item()
        _install(
            page,
            item,
            {
                "outcome": "SUBMIT_FAILED",
                "failure_category": "REJECTED",
                "diagnostics": {"http_status": 502, "message_zh": "上游繁忙"},
                "tracking": {
                    **item,
                    "status": "SUBMIT_FAILED",
                    "status_label": "提交失败",
                    "status_group": "ATTENTION",
                },
            },
        )

        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        self._submit(page, "#tracking-mode-download")

        result = page.locator("#tracking-submit-result")
        expect(result).to_contain_text("提交失败，可重新提交")
        # AC 1: a one-time failure claims nothing about external side effects.
        body = page.locator("#app-main").inner_text()
        for forbidden in ("尚未创建", "可能部分成功", "可安全重试"):
            assert forbidden not in body

        # AC 3/5: the bounded reason lives in the collapsed diagnostics only.
        page.evaluate(
            "() => document.querySelectorAll('.tracking-inspector-content details')"
            ".forEach((el) => { el.open = true; })"
        )
        diagnostics = page.locator("#tracking-write-diagnostics")
        expect(diagnostics).to_contain_text("502")
        expect(diagnostics).to_contain_text("上游繁忙")

    def test_missing_upstream_reason_is_stated_honestly(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        _require_dist()
        set_storage_preferences(page, storage_dir)
        item = _pending_item()
        _install(
            page,
            item,
            {
                "outcome": "SUBMIT_FAILED",
                "failure_category": "AUTHENTICATION",
                # Auto Bangumi gave no usable reason at all.
                "diagnostics": {},
                "tracking": {
                    **item,
                    "status": "SUBMIT_FAILED",
                    "status_label": "提交失败",
                    "status_group": "ATTENTION",
                },
            },
        )

        page.goto(f"{live_server_url}/app/tracking?tracking_id=tracking-a")
        self._submit(page, "#tracking-mode-continue")
        page.evaluate(
            "() => document.querySelectorAll('.tracking-inspector-content details')"
            ".forEach((el) => { el.open = true; })"
        )

        expect(page.locator("#tracking-write-diagnostic-reason")).to_have_text("未提供具体原因")
        assert "请检查方案内容" not in page.locator("#app-main").inner_text()
