from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import set_storage_preferences

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.browser


def _dist_built() -> bool:
    """True when the Vite production build exists (frontend/dist/index.html)."""
    return (REPO_ROOT / "frontend" / "dist" / "index.html").is_file()


def _require_dist() -> None:
    """The SPA build is a hard prerequisite for these browser tests."""
    if _dist_built():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1":
        raise RuntimeError(
            "frontend/dist missing in CI — run `npm ci && npm run build` "
            "in frontend/ before the browser suite."
        )
    pytest.skip(
        "frontend/dist not built — run `cd frontend && npm ci && npm run build` "
        "to verify the US-206 queue migration in the browser."
    )


def _queue_item(
    item_id: str,
    request_id: str,
    title: str,
    status: str = "READY_TO_SUBMIT",
    *,
    batch_id: str = "batch-spa",
    attempts: int = 0,
    last_error: str | None = None,
    ab_result_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "queue_id": f"queue-{batch_id}",
        "batch_id": batch_id,
        "item_id": item_id,
        "request_id": request_id,
        "title": title,
        "status": status,
        "status_label": "待提交",
        "attempts": attempts,
        "last_error": last_error,
        "ab_result_summary": ab_result_summary,
        "created_at": "2026-08-19T00:00:00+00:00",
        "updated_at": "2026-08-19T00:00:00+00:00",
    }


def _queue_result(items: list[dict[str, Any]], *, batch_id: str = "batch-spa") -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": batch_id,
                "queue": {
                    "queue_id": f"queue-{batch_id}",
                    "batch_id": batch_id,
                    "created_at": "2026-08-19T00:00:00+00:00",
                    "updated_at": "2026-08-19T00:00:00+00:00",
                    "items": items,
                },
            },
        },
        ensure_ascii=False,
    )


def _submit_result(
    items: list[dict[str, Any]],
    queue_items: list[dict[str, Any]],
    summary: dict[str, int],
    *,
    batch_id: str = "batch-spa",
) -> str:
    return json.dumps(
        {
            "ok": True,
            "result": {
                "batch_id": batch_id,
                "queue": {
                    "queue_id": f"queue-{batch_id}",
                    "batch_id": batch_id,
                    "created_at": "2026-08-19T00:00:00+00:00",
                    "updated_at": "2026-08-19T00:00:00+00:00",
                    "items": queue_items,
                },
                "items": items,
                "summary": summary,
            },
        },
        ensure_ascii=False,
    )


def _open_queue(
    page: Page,
    live_server_url: str,
    items: list[dict[str, Any]],
    *,
    batch_id: str = "batch-spa",
) -> None:
    """Navigate to /app/queue with a mocked queue GET returning the items."""
    _require_dist()

    def _queue_get(route: Any, request: Any) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_queue_result(items, batch_id=batch_id),
        )

    page.route(f"**/api/v1/batches/{batch_id}/queue*", _queue_get)
    page.goto(f"{live_server_url}/app/queue?batch_id={batch_id}")
    page.wait_for_selector("#batch-queue-count", timeout=5000)


def _fill_api_token_config(page: Page) -> None:
    """Fill the shared AB credential form in API-token mode."""
    page.select_option("#batch-queue-ab-auth-mode", value="api_token")
    page.fill("#batch-queue-ab-endpoint", "https://ab.example/api")
    page.fill("#batch-queue-ab-token", "ab-secret-token")


class TestAppQueueRead:
    """AC: 队列读取、batch_id 刷新恢复与空状态."""

    def test_empty_state_without_batch_id_disables_refresh(
        self, page: Page, live_server_url: str
    ) -> None:
        _require_dist()
        page.goto(f"{live_server_url}/app/queue")
        page.wait_for_selector("#batch-queue-count", timeout=5000)

        expect(page.locator("#batch-queue-count")).to_contain_text("队列中 0 项")
        expect(page.locator("#batch-queue-list .empty-state")).to_contain_text(
            "暂无队列项目"
        )
        expect(page.locator("#batch-queue-refresh")).to_be_disabled()
        expect(page.locator("#batch-queue-submit-form")).to_have_count(0)

    def test_queue_loads_from_url_batch_id_and_renders_statuses(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_queue(
            page,
            live_server_url,
            [
                _queue_item("item-1", "req-1", "关于我转生变成史莱姆这档事 第四季", status="SUCCEEDED", attempts=1, ab_result_summary="Auto Bangumi 已接受该订阅方案"),
                _queue_item("item-2", "req-2", "实力至上主义教室 第四季", status="FAILED", attempts=2, last_error="订阅方案已不存在，跳过提交"),
                _queue_item("item-3", "req-3", "邻家天使 第二季", status="RETRYABLE", attempts=2, last_error="Auto Bangumi 暂时不可用，稍后重试"),
            ],
        )

        expect(page.locator("#batch-queue-count")).to_contain_text("队列中 3 项")
        expect(page.locator(".batch-queue-item")).to_have_count(3)
        ok = page.locator('.batch-queue-item[data-item-id="item-1"]')
        fail = page.locator('.batch-queue-item[data-item-id="item-2"]')
        retryable = page.locator('.batch-queue-item[data-item-id="item-3"]')
        expect(ok.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(ok.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        expect(fail.locator(".batch-queue-status")).to_contain_text("提交失败")
        expect(fail.locator(".batch-queue-item-summary")).to_contain_text(
            "错误：订阅方案已不存在，跳过提交"
        )
        expect(retryable.locator(".batch-queue-item-meta")).to_contain_text("尝试次数：2")
        # The submit form appears only when the queue has items.
        expect(page.locator("#batch-queue-submit-form")).to_be_visible()
        # Only FAILED/RETRYABLE offer the retry button.
        expect(page.locator(".batch-queue-item-retry")).to_have_count(2)

    def test_queue_read_failure_shows_safe_error(self, page: Page, live_server_url: str) -> None:
        _require_dist()

        def _fail(route: Any, request: Any) -> None:
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_type": "storage_error",
                        "error_message": "队列读取失败：存储错误",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/batch-spa/queue*", _fail)
        page.goto(f"{live_server_url}/app/queue?batch_id=batch-spa")
        page.wait_for_selector("#batch-queue-list .error-state", timeout=5000)

        expect(page.locator("#batch-queue-list .error-state")).to_contain_text(
            "队列读取失败"
        )
        body_text = page.locator("body").inner_text()
        assert "storage_error" not in body_text

    def test_360px_no_horizontal_overflow(self, page: Page, live_server_url: str) -> None:
        _open_queue(
            page,
            live_server_url,
            [
                _queue_item("item-1", "req-1", "关于我转生变成史莱姆这档事 第四季", status="SUCCEEDED"),
                _queue_item("item-2", "req-2", "实力至上主义教室 第四季", status="SUBMITTING"),
            ],
        )
        page.set_viewport_size({"width": 360, "height": 800})
        page.wait_for_timeout(200)

        overflow = page.evaluate("() => document.body.scrollWidth > window.innerWidth")
        assert overflow is False


class TestAppQueueSubmit:
    """AC: 顺序提交、确认、防重复提交与失败保留输入."""

    def _setup_one_ready(self, page: Page, live_server_url: str) -> None:
        _open_queue(
            page,
            live_server_url,
            [_queue_item("item-1", "req-1", "关于我转生变成史莱姆这档事 第四季")],
        )

    def test_submit_requires_confirm_and_config(self, page: Page, live_server_url: str) -> None:
        submit_calls: list[dict[str, Any]] = []

        def _submit(route: Any, request: Any) -> None:
            submit_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

        page.route("**/api/v1/batches/batch-spa/submit*", _submit)
        self._setup_one_ready(page, live_server_url)

        page.click("#batch-queue-submit-button")
        expect(page.locator("#batch-queue-submit-form .status-alert")).to_contain_text(
            "请填写服务地址。"
        )
        assert submit_calls == []

        _fill_api_token_config(page)
        page.click("#batch-queue-submit-button")
        expect(page.locator("#batch-queue-submit-form .status-alert")).to_contain_text(
            "请勾选确认后再提交到 Auto Bangumi。"
        )
        assert submit_calls == []

    def test_submit_success_clears_sensitive_inputs_and_updates_queue(
        self, page: Page, live_server_url: str
    ) -> None:
        submit_calls: list[dict[str, Any]] = []

        def _submit(route: Any, request: Any) -> None:
            submit_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_submit_result(
                    [{"item_id": "item-1", "request_id": "req-1", "status": "succeeded", "reason": None}],
                    [_queue_item("item-1", "req-1", "关于我转生变成史莱姆这档事 第四季", status="SUCCEEDED", attempts=1, ab_result_summary="Auto Bangumi 已接受该订阅方案")],
                    {"succeeded": 1},
                ),
            )

        page.route("**/api/v1/batches/batch-spa/submit*", _submit)
        self._setup_one_ready(page, live_server_url)

        _fill_api_token_config(page)
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("批量提交成功")
        expect(page.locator("#batch-queue-submit-form .status-alert")).to_contain_text(
            "提交成功 1 项"
        )
        item = page.locator('.batch-queue-item[data-item-id="item-1"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(item.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        # Sensitive inputs cleared after success; confirm unchecked.
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value("")
        expect(page.locator("#batch-queue-ab-token")).to_have_value("")
        expect(page.locator("#batch-queue-ab-confirm")).not_to_be_checked()

        payload = submit_calls[-1]
        assert payload["confirm"] is True
        assert payload["ab_config"]["auth_mode"] == "api_token"
        assert payload["ab_config"]["base_url"] == "https://ab.example/api"
        assert payload["ab_config"]["token"] == "ab-secret-token"
        assert payload["storage_dir"] is None

    def test_submit_failure_preserves_inputs_with_safe_copy(
        self, page: Page, live_server_url: str
    ) -> None:
        def _submit_fail(route: Any, request: Any) -> None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_message": "Auto Bangumi 连接失败",
                        "error_type": "ab_connection_failed",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/batch-spa/submit*", _submit_fail)
        self._setup_one_ready(page, live_server_url)

        _fill_api_token_config(page)
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("批量提交失败")
        expect(page.locator("#batch-queue-submit-form .status-alert")).to_contain_text(
            "Auto Bangumi 批量提交失败"
        )
        # HTTP-level failure preserves inputs for retry (legacy parity).
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value("https://ab.example/api")
        expect(page.locator("#batch-queue-ab-token")).to_have_value("ab-secret-token")
        expect(page.locator("#batch-queue-ab-confirm")).to_be_checked()
        item = page.locator('.batch-queue-item[data-item-id="item-1"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("待提交")
        # The raw error_type/message never reaches the DOM.
        body_text = page.locator("body").inner_text()
        assert "ab_connection_failed" not in body_text
        assert "Auto Bangumi 连接失败" not in body_text
        assert "ab-secret-token" not in body_text

    def test_submit_disables_controls_while_in_flight(
        self, page: Page, live_server_url: str
    ) -> None:
        # Submit endpoint is not mocked: conftest's test-slow-submit delayed
        # route returns 400 after ~1.5s so the in-flight state is observable.
        _open_queue(
            page,
            live_server_url,
            [_queue_item("item-1", "req-1", "关于我转生变成史莱姆这档事 第四季")],
            batch_id="test-slow-submit",
        )
        _fill_api_token_config(page)
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")

        # The shared BaseButton shows a spinner + disables while in flight
        # (slot text stays, matching the SPA convention).
        expect(page.locator("#batch-queue-submit-button")).to_be_disabled()
        expect(page.locator("#batch-queue-submit-button")).to_have_attribute("aria-busy", "true")
        expect(page.locator("#batch-queue-ab-endpoint")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-token")).to_be_disabled()
        expect(page.locator("#batch-queue-ab-confirm")).to_be_disabled()

        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)
        expect(page.locator("#batch-queue-submit-button")).to_be_enabled()
        expect(page.locator("#batch-queue-submit-button")).to_contain_text("提交队列")


class TestAppQueueRetry:
    """AC: 失败项独立重试与恢复."""

    def test_retry_button_only_for_failed_and_retryable(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_queue(
            page,
            live_server_url,
            [
                _queue_item("item-ok", "req-ok", "A", status="SUCCEEDED"),
                _queue_item("item-fail", "req-fail", "B", status="FAILED"),
                _queue_item("item-retry", "req-retry", "C", status="RETRYABLE"),
                _queue_item("item-ready", "req-ready", "D"),
            ],
        )
        expect(page.locator(".batch-queue-item-retry")).to_have_count(2)
        retry_button = page.locator('.batch-queue-item[data-item-id="item-retry"] .batch-queue-item-retry')
        expect(retry_button).to_contain_text("重试")
        assert retry_button.get_attribute("data-request-id") == "req-retry"
        expect(page.locator('.batch-queue-item[data-item-id="item-ok"] .batch-queue-item-retry')).to_have_count(0)
        expect(page.locator('.batch-queue-item[data-item-id="item-ready"] .batch-queue-item-retry')).to_have_count(0)

    def test_retry_success_updates_item_and_clears_sensitive_inputs(
        self, page: Page, live_server_url: str
    ) -> None:
        retry_calls: list[dict[str, Any]] = []
        failed = _queue_item("item-fail", "req-fail", "实力至上主义教室 第四季", status="FAILED", attempts=1, last_error="Auto Bangumi HTTP 提交失败")

        def _retry(route: Any, request: Any) -> None:
            retry_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_submit_result(
                    [{"item_id": "item-fail", "request_id": "req-fail", "status": "succeeded", "reason": None}],
                    [_queue_item("item-fail", "req-fail", "实力至上主义教室 第四季", status="SUCCEEDED", attempts=2, ab_result_summary="Auto Bangumi 已接受该订阅方案")],
                    {"succeeded": 1},
                ),
            )

        page.route("**/api/v1/batches/batch-spa/retry*", _retry)
        _open_queue(page, live_server_url, [failed])

        _fill_api_token_config(page)
        page.check("#batch-queue-ab-confirm")
        page.click('.batch-queue-item[data-item-id="item-fail"] .batch-queue-item-retry')
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("批量提交成功")
        item = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交成功")
        expect(item.locator(".batch-queue-item-meta")).to_contain_text("尝试次数：2")
        expect(item.locator(".batch-queue-item-summary")).to_contain_text(
            "结果：Auto Bangumi 已接受该订阅方案"
        )
        expect(item.locator(".batch-queue-item-retry")).to_have_count(0)
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value("")
        expect(page.locator("#batch-queue-ab-token")).to_have_value("")
        expect(page.locator("#batch-queue-ab-confirm")).not_to_be_checked()

        payload = retry_calls[0]
        assert payload["request_id"] == "req-fail"
        assert payload["ab_config"]["auth_mode"] == "api_token"
        assert payload["confirm"] is True

    def test_retry_failure_preserves_inputs_and_keeps_item_retryable(
        self, page: Page, live_server_url: str
    ) -> None:
        def _retry_fail(route: Any, request: Any) -> None:
            route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_message": "Auto Bangumi 单项重试失败：连接超时",
                        "error_type": "ab_connection_failed",
                    },
                    ensure_ascii=False,
                ),
            )

        page.route("**/api/v1/batches/batch-spa/retry*", _retry_fail)
        _open_queue(
            page,
            live_server_url,
            [_queue_item("item-fail", "req-fail", "B", status="FAILED", attempts=1, last_error="Auto Bangumi HTTP 提交失败")],
        )

        _fill_api_token_config(page)
        page.check("#batch-queue-ab-confirm")
        page.click('.batch-queue-item[data-item-id="item-fail"] .batch-queue-item-retry')
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("单项重试失败")
        expect(page.locator("#batch-queue-submit-form .status-alert")).to_contain_text(
            "Auto Bangumi 单项重试失败"
        )
        expect(page.locator("#batch-queue-ab-endpoint")).to_have_value("https://ab.example/api")
        expect(page.locator("#batch-queue-ab-token")).to_have_value("ab-secret-token")
        expect(page.locator("#batch-queue-ab-confirm")).to_be_checked()
        item = page.locator('.batch-queue-item[data-item-id="item-fail"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交失败")
        expect(item.locator(".batch-queue-item-retry")).to_have_count(1)
        body_text = page.locator("body").inner_text()
        assert "ab-secret-token" not in body_text


class TestAppQueueRecover:
    """AC: SUBMITTING/RESULT_PERSIST_FAILED 的恢复（自动 + 人工核验）."""

    def test_recover_button_only_for_stuck_items(
        self, page: Page, live_server_url: str
    ) -> None:
        _open_queue(
            page,
            live_server_url,
            [
                _queue_item("item-sub", "req-sub", "A", status="SUBMITTING"),
                _queue_item("item-persist", "req-persist", "B", status="RESULT_PERSIST_FAILED"),
                _queue_item("item-ok", "req-ok", "C", status="SUCCEEDED"),
            ],
        )
        expect(page.locator(".batch-queue-item-recover")).to_have_count(2)
        recover_button = page.locator('.batch-queue-item[data-item-id="item-sub"] .batch-queue-item-recover')
        expect(recover_button).to_contain_text("恢复")
        assert recover_button.get_attribute("data-request-id") == "req-sub"

    def test_recover_auto_succeeds_without_manual_verification(
        self, page: Page, live_server_url: str
    ) -> None:
        recover_calls: list[dict[str, Any]] = []

        def _recover(route: Any, request: Any) -> None:
            recover_calls.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_submit_result(
                    [{"item_id": "item-sub", "request_id": "req-sub", "status": "succeeded", "reason": None}],
                    [_queue_item("item-sub", "req-sub", "A", status="SUCCEEDED", attempts=1)],
                    {"succeeded": 1},
                ),
            )

        page.route("**/api/v1/batches/batch-spa/recover*", _recover)
        _open_queue(page, live_server_url, [_queue_item("item-sub", "req-sub", "A", status="SUBMITTING")])

        page.click('.batch-queue-item[data-item-id="item-sub"] .batch-queue-item-recover')
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        expect(page.locator(".global-notification")).to_contain_text("批量提交成功")
        item = page.locator('.batch-queue-item[data-item-id="item-sub"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交成功")
        # Only one recover call: auto succeeded, no manual dialog.
        assert len(recover_calls) == 1
        assert recover_calls[0]["action"] == "auto"
        assert recover_calls[0]["confirm"] is False

    def test_recover_needs_manual_asks_user_and_marks_succeeded(
        self, page: Page, live_server_url: str
    ) -> None:
        recover_calls: list[dict[str, Any]] = []

        def _recover(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            recover_calls.append(payload)
            if payload.get("action") == "auto":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=_submit_result(
                        [{"item_id": "item-sub", "request_id": "req-sub", "status": "needs_manual", "reason": "requires_manual_recovery"}],
                        [_queue_item("item-sub", "req-sub", "A", status="SUBMITTING")],
                        {"needs_manual": 1},
                    ),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_submit_result(
                    [{"item_id": "item-sub", "request_id": "req-sub", "status": "succeeded", "reason": None}],
                    [_queue_item("item-sub", "req-sub", "A", status="SUCCEEDED", attempts=1)],
                    {"succeeded": 1},
                ),
            )

        page.route("**/api/v1/batches/batch-spa/recover*", _recover)
        _open_queue(page, live_server_url, [_queue_item("item-sub", "req-sub", "A", status="SUBMITTING")])

        page.click('.batch-queue-item[data-item-id="item-sub"] .batch-queue-item-recover')
        page.wait_for_selector(".confirm-dialog", timeout=5000)

        expect(page.locator(".confirm-dialog")).to_contain_text("无法自动判断 Auto Bangumi 是否已创建订阅")
        # 已创建订阅 → succeeded.
        page.locator(".confirm-dialog .primary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        assert len(recover_calls) == 2
        assert recover_calls[0]["action"] == "auto"
        assert recover_calls[1]["action"] == "succeeded"
        assert recover_calls[1]["confirm"] is True
        item = page.locator('.batch-queue-item[data-item-id="item-sub"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交成功")

    def test_recover_manual_cancel_marks_failed(
        self, page: Page, live_server_url: str
    ) -> None:
        recover_calls: list[dict[str, Any]] = []

        def _recover(route: Any, request: Any) -> None:
            payload = json.loads(request.post_data or "{}")
            recover_calls.append(payload)
            if payload.get("action") == "auto":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=_submit_result(
                        [{"item_id": "item-persist", "request_id": "req-persist", "status": "needs_manual", "reason": "requires_manual_recovery"}],
                        [_queue_item("item-persist", "req-persist", "B", status="RESULT_PERSIST_FAILED")],
                        {"needs_manual": 1},
                    ),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_submit_result(
                    [{"item_id": "item-persist", "request_id": "req-persist", "status": "failed", "reason": None}],
                    [_queue_item("item-persist", "req-persist", "B", status="FAILED", attempts=2)],
                    {"failed": 1},
                ),
            )

        page.route("**/api/v1/batches/batch-spa/recover*", _recover)
        _open_queue(
            page,
            live_server_url,
            [_queue_item("item-persist", "req-persist", "B", status="RESULT_PERSIST_FAILED")],
        )

        page.click('.batch-queue-item[data-item-id="item-persist"] .batch-queue-item-recover')
        page.wait_for_selector(".confirm-dialog", timeout=5000)
        # 未创建订阅 → failed（可重试）.
        page.locator(".confirm-dialog .secondary-button").click()
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        assert len(recover_calls) == 2
        assert recover_calls[1]["action"] == "failed"
        assert recover_calls[1]["confirm"] is True
        item = page.locator('.batch-queue-item[data-item-id="item-persist"]')
        expect(item.locator(".batch-queue-status")).to_contain_text("提交失败")
        expect(item.locator(".batch-queue-item-retry")).to_have_count(1)


class TestAppQueueSensitiveBoundary:
    """AC: 提交队列全程不泄漏敏感值."""

    def test_submit_flow_never_persists_or_renders_sensitive_values(
        self, page: Page, live_server_url: str, storage_dir: Path
    ) -> None:
        sensitive_values = (
            "https://private-ab.stage22.local/api",
            "stage22-ab-token",
            "stage22-ab-password",
            "stage22-ab-username",
        )
        set_storage_preferences(page, storage_dir)

        def _queue_get(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_queue_result(
                    [_queue_item("item-1", "req-1", "关于我转生变成史莱姆这档事 第四季")],
                ),
            )

        def _submit(route: Any, request: Any) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_submit_result(
                    [{"item_id": "item-1", "status": "succeeded", "reason": None}],
                    [_queue_item("item-1", "req-1", "关于我转生变成史莱姆这档事 第四季", status="SUCCEEDED")],
                    {"succeeded": 1},
                ),
            )

        page.route("**/api/v1/batches/batch-spa/queue*", _queue_get)
        page.route("**/api/v1/batches/batch-spa/submit*", _submit)
        page.goto(f"{live_server_url}/app/queue?batch_id=batch-spa")
        page.wait_for_selector("#batch-queue-submit-form", timeout=5000)

        page.select_option("#batch-queue-ab-auth-mode", value="api_token")
        page.fill("#batch-queue-ab-endpoint", sensitive_values[0])
        page.fill("#batch-queue-ab-token", sensitive_values[1])
        # Switch back to password mode: the shared form clears all credentials
        # (endpoint + token) and shows the username/password fields, which we
        # fill with the remaining sensitive values.
        page.select_option("#batch-queue-ab-auth-mode", value="password")
        page.fill("#batch-queue-ab-endpoint", sensitive_values[0])
        page.fill("#batch-queue-ab-username", sensitive_values[3])
        page.fill("#batch-queue-ab-password", sensitive_values[2])
        page.check("#batch-queue-ab-confirm")
        page.click("#batch-queue-submit-button")
        page.wait_for_selector(".global-notification:not(:empty)", timeout=5000)

        browser_state = page.evaluate(
            """() => ({
                url: window.location.href,
                localStorage: JSON.stringify(window.localStorage),
                sessionStorage: JSON.stringify(window.sessionStorage),
                bodyText: document.body.innerText,
            })"""
        )
        persisted_json = "\n".join(
            path.read_text(encoding="utf-8")
            for path in storage_dir.rglob("*.json")
        ) if storage_dir.exists() else ""
        for value in sensitive_values:
            assert value not in browser_state["url"]
            assert value not in browser_state["localStorage"]
            assert value not in browser_state["sessionStorage"]
            assert value not in browser_state["bodyText"]
            assert value not in persisted_json
