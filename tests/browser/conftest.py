from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from shared.models import EntryRequest
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config

CHROMIUM_LIB_DIRS = (
    Path("/tmp/chromium-libs/usr/lib/x86_64-linux-gnu"),
    Path("/tmp/chromium-libs/lib/x86_64-linux-gnu"),
)
PLAYWRIGHT_CACHE_DIR = Path.home() / ".cache/ms-playwright"


def _chromium_lib_path_prefix() -> str:
    return ":".join(str(path) for path in CHROMIUM_LIB_DIRS if path.is_dir())


# Ensure Playwright-launched Chromium can find extracted system libraries.
if _chromium_lib_path_prefix():
    _existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    _prefix = _chromium_lib_path_prefix()
    os.environ["LD_LIBRARY_PATH"] = (
        f"{_prefix}:{_existing_ld}" if _existing_ld else _prefix
    )


# ---------------------------------------------------------------------------
# browser availability detection
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _browser_executable() -> str | None:
    """Return the best available Chromium executable path."""
    candidates = [
        *PLAYWRIGHT_CACHE_DIR.glob(
            "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"
        ),
        *PLAYWRIGHT_CACHE_DIR.glob("chromium-*/chrome-linux64/chrome"),
    ]
    for candidate in sorted(candidates, reverse=True):
        if candidate.is_file():
            return str(candidate)
    return None


def _browser_env() -> dict[str, str]:
    """Build environment variables needed to run Chromium.

    When system libraries are missing (e.g. libnspr4.so, libnss3.so),
    we prepend extracted .deb libraries to LD_LIBRARY_PATH.
    """
    env = os.environ.copy()
    if _chromium_lib_path_prefix():
        existing = env.get("LD_LIBRARY_PATH", "")
        prefix = _chromium_lib_path_prefix()
        env["LD_LIBRARY_PATH"] = f"{prefix}:{existing}" if existing else prefix
    return env


_browser_available: bool | None = None


def is_browser_available() -> bool:
    """Check whether a working Chromium binary + libraries are available.

    Result is cached after the first call.
    """
    global _browser_available
    if _browser_available is not None:
        return _browser_available

    exe = _browser_executable()
    if exe is None:
        _browser_available = False
        return False
    try:
        result = subprocess.run(
            [exe, "--version"],
            env=_browser_env(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        _browser_available = result.returncode == 0
    except Exception:
        _browser_available = False
    return _browser_available


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip browser tests when no browser binary is available.

    US-195: in CI the browser suite must *not* be silently skipped — a UI
    change cannot count as verified without a real Chromium run. When
    ``MIGU_ORCA_CI=1`` is set and the browser is unavailable, collection fails
    loudly instead of skipping.
    """
    if is_browser_available():
        return
    if os.environ.get("MIGU_ORCA_CI") == "1" and any(
        "browser" in item.keywords for item in items
    ):
        raise RuntimeError(
            "Browser binary or system libraries unavailable in CI. "
            "Run './script/setup-browser-deps.sh' (or install Chromium deps) "
            "before the browser job — a skipped browser suite is not a pass."
        )
    skip_browser = pytest.mark.skip(
        reason="Browser binary or system libraries unavailable. "
        "Run './script/setup-browser-deps.sh' or install Chromium system deps."
    )
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip_browser)
    if any("browser" in item.keywords for item in items):
        print(
            "\n⚠  Browser not available — browser tests will be skipped.\n"
            "  See docs for manual fallback instructions.\n",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app() -> Any:
    app = create_app("testing")
    _register_test_routes(app)
    return app


def _register_test_routes(app: Any) -> None:
    """Register browser-test-only routes on the shared Flask app.

    These routes exist only for the test session and never touch sensitive
    config: they return fixed Chinese error payloads and a controlled delay,
    so browser tests can observe transient UI states deterministically.
    """

    @app.route("/api/v1/batches/test-slow-accept/accept", methods=["POST"])
    def _slow_batch_accept() -> tuple[Any, int]:
        # 让接受请求保持 ~1.5s，浏览器测试可稳定观察 in-flight 的 loading/disabled 状态。
        time.sleep(1.5)
        return (
            {
                "ok": False,
                "error_message": "批量接受失败：服务器内部错误",
                "error_type": "batch_accept_failed",
            },
            400,
        )

    @app.route("/api/v1/batches/test-slow-submit/submit", methods=["POST"])
    def _slow_batch_submit() -> tuple[Any, int]:
        # 让提交请求保持 ~1.5s，浏览器测试可稳定观察提交中的 loading/disabled 状态。
        # 返回 400，同时覆盖“失败保留输入便于重试”的断言。永不触碰敏感配置。
        time.sleep(1.5)
        return (
            {
                "ok": False,
                "error_message": "Auto Bangumi 批量提交失败：连接超时",
                "error_type": "ab_connection_failed",
            },
            400,
        )

    @app.route("/api/v1/batches/test-slow-retry/retry", methods=["POST"])
    def _slow_batch_retry() -> tuple[Any, int]:
        # 让单项重试请求保持 ~1.5s，浏览器测试可稳定观察 in-flight 的 loading/disabled 状态。
        # 返回 400，同时覆盖“重试失败保留输入便于再次重试”的断言。永不触碰敏感配置。
        time.sleep(1.5)
        return (
            {
                "ok": False,
                "error_message": "Auto Bangumi 单项重试失败：连接超时",
                "error_type": "ab_connection_failed",
            },
            400,
        )

    @app.route("/api/v1/batches/test-slow-queue/queue", methods=["GET"])
    def _slow_batch_queue() -> tuple[Any, int]:
        # 让队列读取保持 ~1.5s，浏览器测试可稳定观察 LoadingState（US-207
        # reduced-motion 收敛：加载文案 + aria-busy 不只靠 spinner 动画）。
        # 永不触碰敏感配置。
        time.sleep(1.5)
        return (
            {
                "ok": True,
                "result": {
                    "batch_id": "test-slow-queue",
                    "queue": {
                        "queue_id": "queue-test-slow-queue",
                        "batch_id": "test-slow-queue",
                        "created_at": "2026-08-19T00:00:00+00:00",
                        "updated_at": "2026-08-19T00:00:00+00:00",
                        "items": [],
                    },
                },
            },
            200,
        )


@pytest.fixture(scope="session")
def live_server_url(app: Any) -> Generator[str]:
    """Start the Flask app on a random port and return its base URL.

    The server runs for the entire test session and is killed when the session ends.
    """
    port = _find_free_port()
    host = "127.0.0.1"

    server = threading.Thread(
        target=app.run,
        kwargs={"host": host, "port": port, "debug": False, "use_reloader": False},
        daemon=True,
    )
    server.start()

    url = f"http://{host}:{port}"
    deadline = time.time() + 10.0
    while time.time() < deadline:
        try:
            import urllib.request

            urllib.request.urlopen(f"{url}/healthz", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("Flask app did not start within 10 seconds")

    yield url


@pytest.fixture(scope="function")
def storage_dir(tmp_path: Path) -> Path:
    """Temporary storage directory isolated per test function.

    Browser tests must never touch `.migu_orca/storage`.
    """
    return tmp_path / "storage"


@pytest.fixture(autouse=True)
def _web_storage_root(tmp_path: Path) -> None:
    """US-193: point the Web storage root at the per-test tmp dir.

    The browser server runs in-process, so the server-side storage root must be
    the same tmp parent the ``storage_dir`` fixture lives under. The browser
    then selects the *relative profile* ``storage`` instead of an absolute
    tmp path, keeping absolute paths out of API payloads/URLs/localStorage.
    """
    from apps.migu_orca_web.drafts import draft_store
    from apps.migu_orca_web.services import set_web_storage_root

    set_web_storage_root(tmp_path)
    draft_store.clear()
    yield
    draft_store.clear()
    set_web_storage_root(None)


def create_saved_request(storage_root: Path, title: str, request_id: str) -> dict[str, Any]:
    """Generate and save a Request to temporary storage for browser tests.

    Uses static-fixture data source (no real MiKan, Auto Bangumi, or qBittorrent access).
    Returns the full Request dict as stored on disk.
    """
    request = {
        **generate_request(EntryRequest(raw_title=title))["request"],
        "request_id": request_id,
    }
    save_request_snapshot(load_storage_config(storage_root), request)
    return request


def preview_result_json(
    request: dict[str, Any],
    *,
    draft_id: str | None = None,
    summary: dict[str, Any] | None = None,
) -> str:
    """Build a ``POST /api/v1/requests`` response body for an unsaved preview draft.

    US-194: an unsaved generation returns an opaque ``draft_id`` and the server
    holds the authoritative draft. To let browser tests exercise the real
    preview-modify/preview-save backend, the draft is issued into the in-process
    ``draft_store`` singleton (cleared per test by the ``_web_storage_root``
    fixture), and the response carries the same id the real backend would.
    """
    from apps.migu_orca_web.drafts import draft_store
    from request_engine.controllers.request_controller import summarize_request

    if draft_id is None:
        draft_id = draft_store.issue(request).draft_id
    body = {
        "ok": True,
        "result": {
            "request": request,
            "summary": summary if summary is not None else summarize_request(request),
            "draft_id": draft_id,
            "draft_revision": 1,
        }
    }
    return json.dumps(body, ensure_ascii=False)


def issue_draft_id(request: dict[str, Any]) -> str:
    """Issue a server-authoritative draft for a preview Request (test seam).

    Used by batch-parse mock helpers so a card's ``preview_request`` has a real
    draft_id the frontend can send to the real preview-modify/save backend.
    """
    from apps.migu_orca_web.drafts import draft_store

    return draft_store.issue(request).draft_id


def save_preview_handler(calls: list[dict[str, Any]] | None = None):
    """Build a ``POST /api/v1/requests/preview-save`` route handler.

    Mirrors the real US-194 backend contract for browser tests: consumes the
    ``draft_id`` from the in-process draft store (the card's draft was issued
    when the mocked batch parse response was built) and returns the saved
    request. Never persists to disk (the original mocks did not either) and
    never returns sensitive draft content. ``calls`` (optional) records every
    preview-save payload for assertions.
    """
    from apps.migu_orca_web.drafts import draft_store
    from request_engine.controllers.request_controller import summarize_request

    def _handler(route: Any, request: Any) -> None:
        payload = json.loads(request.post_data or "{}")
        if calls is not None:
            calls.append(payload)
        draft_id = payload.get("draft_id")
        draft, _ = draft_store.consume_for_save(draft_id)
        if draft is None:
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error_type": "draft_expired",
                        "error_message": "订阅草案已过期或不存在，请重新生成",
                        "error_data": {"failed_step": "consume_preview_draft", "details": {"field": "draft_id"}},
                    },
                    ensure_ascii=False,
                ),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "request": draft,
                        "summary": summarize_request(draft),
                    },
                },
                ensure_ascii=False,
            ),
        )

    return _handler


def set_storage_preferences(
    page: Any, storage_root: Path | str, *, save_request: bool = False
) -> None:
    """Seed non-sensitive Settings preferences before loading Web UI pages.

    US-193: localStorage holds a *relative profile* under the server storage
    root (e.g. ``storage``), never an absolute path. A Path argument is treated
    as a tmp-based storage dir whose profile is its basename.
    """
    profile = storage_root.name if isinstance(storage_root, Path) else str(storage_root)
    storage_dir_json = json.dumps(profile)
    save_request_json = json.dumps(save_request)
    page.add_init_script(
        f"""
        window.localStorage.setItem("miguOrca.web.storageDir", {storage_dir_json});
        window.localStorage.setItem("miguOrca.web.saveRequest", String({save_request_json}));
        """
    )
