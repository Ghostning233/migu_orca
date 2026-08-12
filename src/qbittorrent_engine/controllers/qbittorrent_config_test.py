from __future__ import annotations

import json
from pathlib import Path

import pytest

from extensions.flask_api.api import sanitize_error_data
from qbittorrent_engine.controllers.qbittorrent_config import (
    QBittorrentConfig,
    build_qbittorrent_config,
    load_qbittorrent_config,
)
from shared.errors import Stage1Error


def test_load_qbittorrent_config_from_explicit_json_path(tmp_path: Path) -> None:
    path = tmp_path / "qbittorrent.json"
    path.write_text(
        """{
          "endpoint": " https://qb.example.invalid ",
          "username": " user-value ",
          "password": " password-value ",
          "timeout_seconds": 8,
          "verify_tls": false
        }""",
        encoding="utf-8",
    )

    config = load_qbittorrent_config(path)

    assert config == QBittorrentConfig(
        endpoint="https://qb.example.invalid",
        username="user-value",
        password="password-value",
        timeout_seconds=8.0,
        verify_tls=False,
    )


def test_build_qbittorrent_config_defaults_verify_tls_to_true() -> None:
    config = build_qbittorrent_config(
        {
            "endpoint": "https://qb.example.invalid",
            "username": "user-value",
            "password": "password-value",
            "timeout_seconds": 5,
        }
    )

    assert config.verify_tls is True


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (
            {
                "username": "user-value",
                "password": "password-value",
                "timeout_seconds": 5,
            },
            "endpoint",
        ),
        (
            {
                "endpoint": "https://qb.example.invalid",
                "password": "password-value",
                "timeout_seconds": 5,
            },
            "username",
        ),
        (
            {
                "endpoint": "https://qb.example.invalid",
                "username": "user-value",
                "timeout_seconds": 5,
            },
            "password",
        ),
    ],
)
def test_load_qbittorrent_config_requires_explicit_sensitive_fields(
    tmp_path: Path,
    payload: dict[str, object],
    field: str,
) -> None:
    path = tmp_path / "qbittorrent.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_qbittorrent_config(path)

    assert error.value.as_dict()["error_type"] == "config_error"
    assert error.value.as_dict()["failed_step"] == "load_qbittorrent_config"
    assert error.value.as_dict()["details"] == {"field": field}


@pytest.mark.parametrize(
    "timeout_seconds",
    [0, -1, "5"],
)
def test_load_qbittorrent_config_rejects_invalid_timeout(
    tmp_path: Path,
    timeout_seconds: object,
) -> None:
    path = tmp_path / "qbittorrent.json"
    path.write_text(
        json.dumps(
            {
                "endpoint": "https://qb.example.invalid",
                "username": "user-value",
                "password": "password-value",
                "timeout_seconds": timeout_seconds,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Stage1Error) as error:
        load_qbittorrent_config(path)

    assert error.value.as_dict()["details"] == {"field": "timeout_seconds"}


def test_load_qbittorrent_config_rejects_invalid_verify_tls(tmp_path: Path) -> None:
    path = tmp_path / "qbittorrent.json"
    path.write_text(
        json.dumps(
            {
                "endpoint": "https://qb.example.invalid",
                "username": "user-value",
                "password": "password-value",
                "timeout_seconds": 5,
                "verify_tls": "false",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Stage1Error) as error:
        load_qbittorrent_config(path)

    assert error.value.as_dict()["details"] == {"field": "verify_tls"}


def test_load_qbittorrent_config_rejects_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "qbittorrent.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(Stage1Error) as error:
        load_qbittorrent_config(path)

    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "qBittorrent 配置必须是 JSON 对象",
        "failed_step": "load_qbittorrent_config",
        "details": {},
    }


def test_load_qbittorrent_config_does_not_expose_missing_file_path(tmp_path: Path) -> None:
    missing_path = tmp_path / "private" / "qbittorrent.json"

    with pytest.raises(Stage1Error) as error:
        load_qbittorrent_config(missing_path)

    assert str(missing_path) not in error.value.message
    assert error.value.as_dict() == {
        "error_type": "config_error",
        "error_message": "qBittorrent 配置文件不存在",
        "failed_step": "load_qbittorrent_config",
        "details": {},
    }


def test_qbittorrent_config_errors_are_safe_after_shared_sanitization() -> None:
    sensitive_endpoint = "https://admin:secret@qb.example.invalid:8080/gui"
    sensitive_username = "private-user"
    sensitive_password = "private-password"
    sensitive_sid = "SID=private-session"
    raw_html = "<html>private response</html>"

    error = Stage1Error(
        "config_error",
        f"failed for {sensitive_endpoint} {sensitive_username} {sensitive_password} {sensitive_sid} {raw_html}",
        "load_qbittorrent_config",
        {
            "endpoint": sensitive_endpoint,
            "username": sensitive_username,
            "password": sensitive_password,
            "cookie": sensitive_sid,
            "path": "/home/user/private/qbittorrent.json",
            "raw_html": raw_html,
        },
    )

    sanitized = sanitize_error_data(error.as_dict())

    assert sensitive_endpoint not in str(sanitized)
    assert sensitive_username not in str(sanitized)
    assert sensitive_password not in str(sanitized)
    assert sensitive_sid not in str(sanitized)
    assert raw_html not in str(sanitized)
    assert "/home/user/private/qbittorrent.json" not in str(sanitized)
    assert sanitized["details"]["password"] == "[redacted]"
    assert sanitized["details"]["cookie"] == "[redacted]"
