from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ab_engine.controllers.ab_connection_controller import test_ab_connection as run_connection_test
from shared.errors import Stage1Error


def test_connection_controller_imports_first_in_a_clean_process() -> None:
    """The lower AB layer must not initialize the Web application package."""
    src_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_root)
    result = subprocess.run(
        [sys.executable, "-c", "import ab_engine.controllers.ab_connection_controller"],
        cwd=src_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


class FakeClient:
    def __init__(self, summary: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.summary = summary or {"reachable": True, "authenticated": True, "version": "3.1.18", "adapter": "legacy_3_1", "submit_supported": True, "token": "secret-token", "base_url": "http://private-auto-bangumi.local"}
        self.error = error
        self.calls = 0

    def probe(self) -> dict[str, Any]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.summary


def _password_config() -> dict[str, Any]:
    return {"base_url": "http://private-auto-bangumi.local", "auth_mode": "password", "username": "private-user", "password": "private-password", "fallback_enabled": False}


def test_connection_returns_a_safe_password_summary() -> None:
    client = FakeClient()
    result = run_connection_test(ab_config=_password_config(), ab_client=client)
    assert result == {"success": True, "summary": {"reachable": True, "authenticated": True, "version": "3.1.18", "adapter": "legacy_3_1", "submit_supported": True, "auth_mode": "账号密码"}, "error": None}
    assert client.calls == 1
    assert "private" not in str(result)
    assert "secret" not in str(result)


def test_connection_supports_token_mode_with_a_chinese_summary() -> None:
    result = run_connection_test(ab_config={"base_url": "http://private-auto-bangumi.local", "auth_mode": "api_token", "token": "secret-token", "fallback_enabled": False}, ab_client=FakeClient({"reachable": True, "authenticated": True, "version": "4.0", "adapter": "api_token", "submit_supported": False}))
    assert result["success"] is True
    assert result["summary"]["auth_mode"] == "API Token"
    assert result["summary"]["submit_supported"] is False


@pytest.mark.parametrize(("error", "error_type", "category"), [(Stage1Error("ab_auth_failed", "认证失败 token=secret-token", "probe", {"username": "private-user"}), "ab_auth_failed", None), (TimeoutError("secret-token"), "ab_timeout", "timeout"), (ConnectionError("private-password"), "ab_connection_failed", "connection"), (ValueError("<html>private response</html>"), "invalid_ab_response", "protocol")])
def test_connection_classifies_and_redacts_failures(error: Exception, error_type: str, category: str | None) -> None:
    result = run_connection_test(ab_config=_password_config(), ab_client=FakeClient(error=error))
    assert result["success"] is False
    assert result["error"]["error_type"] == error_type
    if category:
        assert result["error"]["details"] == {"category": category}
    assert "private-user" not in str(result)
    assert "private-password" not in str(result)
    assert "secret-token" not in str(result)


def test_connection_never_calls_a_client_when_config_is_invalid() -> None:
    client = FakeClient()
    result = run_connection_test(ab_config={**_password_config(), "base_url": "invalid"}, ab_client=client)
    assert result["error"]["error_type"] == "config_error"
    assert client.calls == 0
