from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Generator

import pytest

from apps.base import create_app
from apps.migu_orca_entry.controllers.entry_controller import generate_request
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config
from shared.models import EntryRequest


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
    """Auto-skip browser tests when no browser binary is available."""
    if is_browser_available():
        return
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
    return create_app("testing")


@pytest.fixture(scope="session")
def live_server_url(app: Any) -> Generator[str, None, None]:
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
