from __future__ import annotations

import json
from pathlib import Path

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.migu_orca_entry.controllers.entry_controller import (
    apply_ab_submit_action,
    apply_confirmation_action,
    generate_request,
    main,
)
from shared.errors import Stage1Error
from shared.models import EntryRequest


def test_generate_request_end_to_end() -> None:
    result = generate_request(EntryRequest(raw_title="咒术回战第三季"))

    assert result["success"] is True
    request = result["request"]
    assert request["status"] == "PENDING_CONFIRM"
    assert request["source_info"]["matched_bangumi"]["title"] == "咒术回战 第三季"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"
    assert request["confirmable_config"]["expected_folder_name"] == "咒术回战 第三季"
    assert request["ab_submit_result"] is None
    assert "CREATED" not in json.dumps(request)
    assert "SEARCHING" not in json.dumps(request)


def test_generate_request_rejects_empty_title() -> None:
    result = generate_request(EntryRequest(raw_title="  "))

    assert result["success"] is False
    assert result["error"]["failed_step"] == "validate_input"


def test_main_prints_json(capsys) -> None:
    exit_code = main(["芙莉莲"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["status"] == "PENDING_CONFIRM"


def test_apply_confirmation_action_accepts_generated_request() -> None:
    result = generate_request(EntryRequest(raw_title="芙莉莲"))

    confirmed = apply_confirmation_action(result, "accept")

    assert confirmed["success"] is True
    assert confirmed["request"]["status"] == "ACCEPTED"
    assert confirmed["request"]["user_action"]["action"] == "ACCEPT"
    assert result["request"]["status"] == "PENDING_CONFIRM"


def test_main_can_cancel_generated_request(capsys) -> None:
    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "cancel",
            "--cancel-reason",
            "稍后再订阅",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["status"] == "CANCELLED"
    assert output["request"]["user_action"]["reason"] == "稍后再订阅"


def test_main_without_submit_ab_does_not_build_real_ab_client(
    capsys,
    monkeypatch,
) -> None:
    def fail_if_called(*args: object) -> None:
        raise AssertionError("real AB client should not be created")

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        fail_if_called,
    )

    exit_code = main(["芙莉莲", "--action", "accept"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["status"] == "ACCEPTED"
    assert output.get("ab_submit_result") is None
    assert output["request"]["ab_submit_result"] is None


def test_apply_ab_submit_action_skips_when_not_requested() -> None:
    result = apply_confirmation_action(
        generate_request(EntryRequest(raw_title="芙莉莲")),
        "accept",
    )

    submitted = apply_ab_submit_action(result, False)

    assert submitted is result
    assert submitted["request"]["ab_submit_result"] is None


def test_apply_ab_submit_action_attaches_success_result_to_accepted_request(
    tmp_path: Path,
) -> None:
    config = _ab_config(tmp_path, fallback_enabled=False)
    client = FakeAutoBangumiClient()
    result = apply_confirmation_action(
        generate_request(EntryRequest(raw_title="芙莉莲")),
        "accept",
    )

    submitted = apply_ab_submit_action(
        result,
        True,
        ab_config_path=config,
        client=client,
    )

    assert submitted["success"] is True
    assert submitted["error"] is None
    assert submitted["ab_submit_result"] == {
        "success": True,
        "ab_subscription_id": "fake-ab-subscription",
        "ab_response": {"id": "fake-ab-subscription", "status": "created"},
        "fallback_config": None,
        "error": None,
    }
    assert client.calls
    assert submitted["request"]["ab_submit_result"] == submitted["ab_submit_result"]
    assert result["request"]["ab_submit_result"] is None


def test_apply_ab_submit_action_outputs_fallback_config_for_ab_failure(
    tmp_path: Path,
) -> None:
    config = _ab_config(tmp_path, fallback_enabled=True)
    client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "离线模拟失败",
            "create_ab_subscription",
            {"status_code": 503},
        )
    )
    result = apply_confirmation_action(
        generate_request(EntryRequest(raw_title="芙莉莲")),
        "accept",
    )

    submitted = apply_ab_submit_action(
        result,
        True,
        ab_config_path=config,
        client=client,
    )

    assert submitted["success"] is True
    ab_submit_result = submitted["ab_submit_result"]
    assert ab_submit_result["success"] is False
    assert ab_submit_result["error"]["error_type"] == "ab_submit_failed"
    assert ab_submit_result["fallback_config"]["title"] == "葬送的芙莉莲"
    assert ab_submit_result["fallback_config"]["rss_url"]
    assert ab_submit_result["fallback_config"]["save_path"] == "葬送的芙莉莲"
    assert (
        ab_submit_result["fallback_config"]["failure_reason"]
        == ab_submit_result["error"]
    )


def test_apply_ab_submit_action_keeps_fallback_disabled_by_config(
    tmp_path: Path,
) -> None:
    config = _ab_config(tmp_path, fallback_enabled=False)
    client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "离线模拟失败",
            "create_ab_subscription",
        )
    )
    result = apply_confirmation_action(
        generate_request(EntryRequest(raw_title="芙莉莲")),
        "accept",
    )

    submitted = apply_ab_submit_action(
        result,
        True,
        ab_config_path=config,
        client=client,
    )

    assert submitted["success"] is True
    assert submitted["ab_submit_result"]["success"] is False
    assert submitted["ab_submit_result"]["fallback_config"] is None


def test_apply_ab_submit_action_requires_explicit_config_path() -> None:
    result = apply_confirmation_action(
        generate_request(EntryRequest(raw_title="芙莉莲")),
        "accept",
    )

    submitted = apply_ab_submit_action(result, True)

    assert submitted == {
        "success": False,
        "request": None,
        "ab_submit_result": None,
        "error": {
            "error_type": "config_error",
            "error_message": "提交 Auto Bangumi 必须显式提供配置文件路径",
            "failed_step": "load_ab_config",
            "details": {"field": "ab_config"},
        },
    }


def test_apply_ab_submit_action_rejects_non_accepted_request(tmp_path: Path) -> None:
    config = _ab_config(tmp_path, fallback_enabled=True)
    result = generate_request(EntryRequest(raw_title="芙莉莲"))

    submitted = apply_ab_submit_action(result, True, ab_config_path=config)

    assert submitted["success"] is False
    assert submitted["ab_submit_result"] is None
    assert submitted["error"]["error_type"] == "invalid_request_status"
    assert submitted["error"]["failed_step"] == "build_ab_subscription_payload"


def test_main_can_submit_accepted_request_to_real_ab_client_factory(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _ab_config(tmp_path, fallback_enabled=False)
    client = FakeAutoBangumiClient()
    factory_configs = []

    def build_client(ab_config):
        factory_configs.append(ab_config)
        return client

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        build_client,
    )

    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "accept",
            "--submit-ab",
            "--ab-config",
            str(config),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["status"] == "ACCEPTED"
    assert output["ab_submit_result"]["success"] is True
    assert output["request"]["ab_submit_result"] == output["ab_submit_result"]
    assert len(factory_configs) == 1
    assert factory_configs[0].endpoint == "http://auto-bangumi.local"
    assert client.calls


def test_main_returns_structured_error_for_cancel_without_reason(capsys) -> None:
    exit_code = main(["芙莉莲", "--action", "cancel"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output == {
        "success": False,
        "request": None,
        "error": {
            "error_type": "invalid_cancel_reason",
            "error_message": "取消原因不能为空",
            "failed_step": "cancel_request",
            "details": {},
        },
    }


def test_all_filtered_out_still_returns_request_without_selection(
    tmp_path: Path,
) -> None:
    config = tmp_path / "rules.json"
    config.write_text(
        """{
          "filter_rule": {
            "must_contain": "绝对不会命中的文本",
            "must_not_contain": ""
          },
          "subtitle_group_priority": ["Loli", "喵萌"]
        }""",
        encoding="utf-8",
    )

    result = generate_request(
        EntryRequest(raw_title="咒术回战第三季"),
        user_config_path=config,
    )

    assert result["success"] is True
    confirmable = result["request"]["confirmable_config"]
    assert confirmable["selected_subtitle_group"] is None
    assert confirmable["selected_rss_url"] is None
    assert confirmable["warnings"]


def _ab_config(tmp_path: Path, *, fallback_enabled: bool) -> Path:
    path = tmp_path / "ab-config.json"
    path.write_text(
        json.dumps(
            {
                "endpoint": "http://auto-bangumi.local",
                "token": "secret-token",
                "fallback_enabled": fallback_enabled,
            }
        ),
        encoding="utf-8",
    )
    return path
