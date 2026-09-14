from __future__ import annotations

import json
from pathlib import Path

import pytest

from ab_engine.controllers.ab_client import FakeAutoBangumiClient
from apps.migu_orca_entry.controllers.entry_controller import (
    apply_ab_submit_action,
    apply_confirmation_action,
    apply_modify_action,
    apply_request_save_action,
    generate_request,
    list_saved_requests,
    load_saved_request,
    main,
)
from mikan_engine.controllers.mikan_client import (
    MikanBangumiDetail,
    MikanSubgroupDetail,
    create_mikan_client,
)
from mikan_engine.controllers.mikan_config import MikanConfig
from request_engine.controllers.request_controller import summarize_request
from shared.errors import Stage1Error
from shared.models import BangumiCandidate, EntryRequest, MatchedBangumi, RssSource
from storage_engine.controllers.request_repository import save_request_snapshot
from storage_engine.controllers.storage_config import load_storage_config

_FAKE_RSS_XML = (
    "<rss><channel><item><title>芙莉莲 - 01</title>"
    "<link>https://example.invalid/1</link></item></channel></rss>"
)


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


def test_generate_request_supports_inline_mikan_config_with_fake_transport_success() -> None:
    config = MikanConfig(
        search_endpoint="https://mikan.example/Home/Search",
        timeout_seconds=3,
    )
    transport = _FakeMikanTransport(
        {
            "https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2": (
                '<a href="/Home/Bangumi/123" title="芙莉莲">芙莉莲</a>'
            ),
            "https://mikan.example/Home/Bangumi/123": (
                '<h1 class="bangumi-title">芙莉莲</h1>'
                '<section class="subgroup-section">'
                '<h2 class="subgroup-name">Loli</h2>'
                '<a href="/RSS/Bangumi?bangumiId=123&subgroupid=10">RSS</a>'
                "</section>"
            ),
            "https://mikan.example/RSS/Bangumi?bangumiId=123&subgroupid=10": (
                _FAKE_RSS_XML
            ),
        }
    )
    client = create_mikan_client(config, transport=transport)

    result = generate_request(
        EntryRequest(raw_title="芙莉莲"),
        source_mode="mikan_http",
        mikan_config=config,
        mikan_client=client,
    )

    request = result["request"]
    assert result["success"] is True
    assert transport.requests == [
        ("https://mikan.example/Home/Search?searchstr=%E8%8A%99%E8%8E%89%E8%8E%B2", 3.0),
        ("https://mikan.example/Home/Bangumi/123", 3.0),
        ("https://mikan.example/RSS/Bangumi?bangumiId=123&subgroupid=10", 3.0),
    ]
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"
    assert (
        request["confirmable_config"]["selected_rss_url"]
        == "https://mikan.example/RSS/Bangumi?bangumiId=123&subgroupid=10"
    )


def test_generate_request_mikan_direct_id_bypasses_search() -> None:
    config = MikanConfig(
        search_endpoint="https://mikan.example/Home/Search",
        timeout_seconds=3,
    )
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
                _FAKE_RSS_XML
            ),
        }
    )
    client = create_mikan_client(config, transport=transport)

    result = generate_request(
        EntryRequest(raw_title="不会用于搜索"),
        source_mode="mikan_http",
        mikan_config=config,
        mikan_client=client,
        mikan_bangumi="123",
    )

    request = result["request"]
    assert result["success"] is True
    assert transport.requests == [
        ("https://mikan.example/Home/Bangumi/123", 3.0),
        ("https://mikan.example/RSS/Bangumi?bangumiId=123&subgroupid=10", 3.0),
    ]
    assert request["source_info"]["matched_bangumi"]["title"] == "芙莉莲"
    assert (
        request["source_info"]["matched_bangumi"]["mikan_url"]
        == "https://mikan.example/Home/Bangumi/123"
    )
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"


def test_generate_request_mikan_direct_url_rejects_invalid_inputs() -> None:
    config = MikanConfig(
        search_endpoint="https://mikan.example/Home/Search",
        timeout_seconds=3,
    )
    client = create_mikan_client(config, transport=_FakeMikanTransport())

    for direct_entry in [
        "",
        "ftp://mikan.example/Home/Bangumi/123",
        "https://mikan.example/Home/Search?searchstr=secret-token",
        "https://evil.example/Home/Bangumi/123?token=secret-token",
        "https://mikan.example/Home/Bangumi/../123",
        "abc123",
    ]:
        result = generate_request(
            EntryRequest(raw_title="芙莉莲"),
            source_mode="mikan_http",
            mikan_config=config,
            mikan_client=client,
            mikan_bangumi=direct_entry,
        )

        assert result["success"] is False
        assert result["error"]["error_type"] == "invalid_input"
        assert result["error"]["failed_step"] in {"mikan_direct_entry", "validate_input"}
        assert "secret-token" not in json.dumps(result["error"])


def test_generate_request_redacts_sensitive_real_mikan_failure() -> None:
    config = MikanConfig(
        search_endpoint="https://mikan.example/Home/Search",
        timeout_seconds=3,
    )
    transport = _FakeMikanTransport(
        error=Stage1Error(
            "mikan_http_failed",
            "MiKan HTTP 请求失败 from https://mikan.example/private?token=secret",
            "mikan_search",
            {
                "raw_html": "<html>secret</html>",
                "rss_xml": "<rss>secret</rss>",
                "token": "secret-token",
            },
        )
    )
    client = create_mikan_client(config, transport=transport)

    result = generate_request(
        EntryRequest(raw_title="芙莉莲"),
        source_mode="mikan_http",
        mikan_config=config,
        mikan_client=client,
    )

    assert result["success"] is False
    assert result["error"]["error_message"] == "MiKan HTTP 请求失败"
    assert "token" not in json.dumps(result["error"]).lower()
    assert "http://" not in json.dumps(result["error"])
    assert "<rss" not in json.dumps(result["error"]).lower()


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


def test_main_without_save_request_does_not_touch_storage(
    capsys,
    monkeypatch,
) -> None:
    def fail_if_called(*args: object) -> None:
        raise AssertionError("storage should not be loaded")

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.load_storage_config",
        fail_if_called,
    )

    exit_code = main(["芙莉莲"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["status"] == "PENDING_CONFIRM"
    assert "saved_request" not in output


def test_main_can_save_generated_request_to_explicit_storage_dir(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"

    exit_code = main(["芙莉莲", "--save-request", "--storage-dir", str(storage_dir)])

    output = json.loads(capsys.readouterr().out)
    request = output["request"]
    saved = output["saved_request"]
    saved_path = storage_dir / "requests" / f"{request['request_id']}.json"
    assert exit_code == 0
    assert saved == {
        "request_id": request["request_id"],
        "storage": "local_json",
        "directory": "requests",
        "filename": f"{request['request_id']}.json",
    }
    assert json.loads(saved_path.read_text(encoding="utf-8")) == request
    assert (storage_dir / "history").is_dir()
    assert (storage_dir / "ab_results").is_dir()


def test_main_can_save_accepted_request(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"

    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "accept",
            "--save-request",
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    saved_path = storage_dir / "requests" / output["saved_request"]["filename"]
    assert exit_code == 0
    assert output["request"]["status"] == "ACCEPTED"
    assert json.loads(saved_path.read_text(encoding="utf-8"))["status"] == "ACCEPTED"


def test_main_can_list_saved_request_summaries(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"
    request = generate_request(EntryRequest(raw_title="芙莉莲"))["request"]
    save_request_snapshot(load_storage_config(storage_dir), request)

    exit_code = main(["--list-requests", "--storage-dir", str(storage_dir)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output == {
        "success": True,
        "requests": [summarize_request(request)],
        "error": None,
    }


def test_main_can_load_saved_request_by_id(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"
    request = generate_request(EntryRequest(raw_title="芙莉莲"))["request"]
    save_request_snapshot(load_storage_config(storage_dir), request)

    exit_code = main(
        [
            "--load-request",
            request["request_id"],
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output == {"success": True, "request": request, "error": None}


def test_main_load_saved_request_returns_stable_missing_error(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"

    exit_code = main(
        ["--load-request", "missing-request", "--storage-dir", str(storage_dir)]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output == {
        "success": False,
        "request": None,
        "error": {
            "error_type": "request_not_found",
            "error_message": "未找到已保存的订阅方案",
            "failed_step": "load_request_snapshot",
            "details": {"request_id": "missing-request"},
        },
    }
    assert str(tmp_path) not in str(output)


def test_list_saved_requests_returns_stable_error_for_corrupt_request(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"
    config = load_storage_config(storage_dir)
    config.requests_dir.mkdir(parents=True)
    (config.requests_dir / "broken.json").write_text("{", encoding="utf-8")

    result = list_saved_requests(storage_dir=storage_dir)

    assert result["success"] is False
    assert result["requests"] is None
    assert result["error"]["error_type"] == "storage_json_error"
    assert result["error"]["failed_step"] == "load_request_snapshot"
    assert result["error"]["details"]["request_id"] == "broken"
    assert str(tmp_path) not in str(result)


def test_load_saved_request_rejects_nested_request_id(tmp_path: Path) -> None:
    result = load_saved_request("nested/request", storage_dir=tmp_path / "migu-state")

    assert result["success"] is False
    assert result["request"] is None
    assert result["error"]["error_type"] == "invalid_request_id"
    assert result["error"]["failed_step"] == "load_request_snapshot"


def test_main_storage_query_does_not_generate_request(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("request generation should not run")

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.generate_request",
        fail_if_called,
    )

    exit_code = main(["--list-requests", "--storage-dir", str(storage_dir)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output == {"success": True, "requests": [], "error": None}


def test_main_save_request_records_accept_history(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"

    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "accept",
            "--save-request",
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    request_id = output["request"]["request_id"]
    history_path = storage_dir / "history" / f"{request_id}.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert output["saved_history"] == [
        {
            "request_id": request_id,
            "storage": "local_json",
            "directory": "history",
            "filename": f"{request_id}.json",
            "event_count": 1,
        }
    ]
    assert history == [
        {
            "request_id": request_id,
            "previous_status": "PENDING_CONFIRM",
            "next_status": "ACCEPTED",
            "action": "ACCEPT",
            "timestamp": output["request"]["updated_at"],
        }
    ]


def test_main_save_request_records_cancel_history_with_reason(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"

    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "cancel",
            "--cancel-reason",
            "稍后再订阅",
            "--save-request",
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    request_id = output["request"]["request_id"]
    history = json.loads(
        (storage_dir / "history" / f"{request_id}.json").read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert history[0]["action"] == "CANCEL"
    assert history[0]["details"] == {"reason": "稍后再订阅"}


def test_main_save_request_records_modify_history(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"
    patch = {"expected_folder_name": "芙莉莲 修改版"}

    exit_code = main(
        [
            "芙莉莲",
            "--modify-patch",
            json.dumps(patch, ensure_ascii=False),
            "--save-request",
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    request_id = output["request"]["request_id"]
    history = json.loads(
        (storage_dir / "history" / f"{request_id}.json").read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert output["request"]["status"] == "PENDING_CONFIRM"
    assert output["request"]["confirmable_config"]["expected_folder_name"] == (
        "芙莉莲 修改版"
    )
    assert history == [
        {
            "request_id": request_id,
            "previous_status": "PENDING_CONFIRM",
            "next_status": "PENDING_CONFIRM",
            "action": "MODIFY",
            "timestamp": output["request"]["updated_at"],
            "details": {"patch": patch},
        }
    ]


def test_apply_modify_action_returns_structured_error() -> None:
    result = generate_request(EntryRequest(raw_title="芙莉莲"))

    modified = apply_modify_action(result, {"selected_subtitle_group": "Unknown"})

    assert modified["success"] is False
    assert modified["error"]["error_type"] == "invalid_modify_patch"
    assert modified["error"]["failed_step"] == "modify_request"


def test_main_save_request_uses_documented_default_storage_dir(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    default_storage_dir = tmp_path / "default-storage"

    monkeypatch.setattr(
        "storage_engine.controllers.storage_config.DEFAULT_STORAGE_DIR",
        default_storage_dir,
    )

    exit_code = main(["芙莉莲", "--save-request"])

    output = json.loads(capsys.readouterr().out)
    saved_path = default_storage_dir / "requests" / output["saved_request"]["filename"]
    assert exit_code == 0
    assert saved_path.exists()


def test_apply_request_save_action_returns_stable_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    result = generate_request(EntryRequest(raw_title="芙莉莲"))

    def fail_save(*args: object) -> None:
        raise Stage1Error(
            "storage_error",
            "保存订阅方案 JSON 失败",
            "save_request_snapshot",
            {"directory": "requests"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.save_request_snapshot",
        fail_save,
    )

    saved = apply_request_save_action(
        result,
        True,
        storage_dir=tmp_path / "migu-state",
    )

    assert saved == {
        "success": False,
        "request": None,
        "error": {
            "error_type": "storage_error",
            "error_message": "保存订阅方案 JSON 失败",
            "failed_step": "save_request_snapshot",
            "details": {"directory": "requests"},
        },
    }
    assert str(tmp_path) not in str(saved)


def test_apply_request_save_action_returns_stable_error_for_history_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    result = generate_request(EntryRequest(raw_title="芙莉莲"))

    def fail_append_history(*args: object) -> None:
        raise Stage1Error(
            "storage_error",
            "保存订阅方案状态历史失败",
            "append_status_history",
            {"request_id": "stable-id", "directory": "history"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.append_status_history",
        fail_append_history,
    )

    saved = apply_request_save_action(
        result,
        True,
        storage_dir=tmp_path / "migu-state",
        history_events=[
            {
                "request_id": result["request"]["request_id"],
                "previous_status": "PENDING_CONFIRM",
                "next_status": "ACCEPTED",
                "action": "ACCEPT",
                "timestamp": result["request"]["updated_at"],
            }
        ],
    )

    assert saved == {
        "success": False,
        "request": None,
        "error": {
            "error_type": "storage_error",
            "error_message": "保存订阅方案状态历史失败",
            "failed_step": "append_status_history",
            "details": {"request_id": "stable-id", "directory": "history"},
        },
    }
    assert "saved_request" not in saved
    assert str(tmp_path) not in str(saved)


def test_generate_request_default_path_does_not_build_real_mikan_client(
    monkeypatch,
) -> None:
    def fail_if_called(*args: object) -> None:
        raise AssertionError("real MiKan client should not be created")

    monkeypatch.setattr(
        "mikan_engine.controllers.mikan_client.create_mikan_client",
        fail_if_called,
    )

    result = generate_request(EntryRequest(raw_title="芙莉莲"))

    assert result["success"] is True
    assert result["request"]["source_info"]["matched_bangumi"]["title"] == "葬送的芙莉莲"


def test_generate_request_real_mikan_mode_uses_injected_client_and_rss_transport() -> None:
    client = _FakeMikanClient()
    transport = _FakeRssTransport()

    result = generate_request(
        EntryRequest(raw_title="芙莉莲"),
        source_mode="mikan_http",
        mikan_client=client,
        mikan_rss_transport=transport,
    )

    assert result["success"] is True
    assert client.searches == ["芙莉莲"]
    assert client.rss_source_matches == ["葬送的芙莉莲"]
    assert transport.requests == [("https://mikan.example/rss/frieren.xml", 10.0)]
    request = result["request"]
    assert request["source_info"]["matched_bangumi"]["title"] == "葬送的芙莉莲"
    assert request["confirmable_config"]["selected_subtitle_group"] == "Loli"
    assert request["confirmable_config"]["selected_rss_url"] == (
        "https://mikan.example/rss/frieren.xml"
    )


def test_generate_request_real_mikan_mode_requires_explicit_config_or_client() -> None:
    result = generate_request(
        EntryRequest(raw_title="芙莉莲"),
        source_mode="mikan_http",
    )

    assert result == {
        "success": False,
        "request": None,
        "error": {
            "error_type": "config_error",
            "error_message": "真实 MiKan 数据源必须显式提供配置文件路径",
            "failed_step": "load_mikan_config",
            "details": {"field": "mikan_config"},
        },
    }


def test_main_real_mikan_mode_requires_config_path(capsys) -> None:
    exit_code = main(["芙莉莲", "--source", "mikan"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["error"]["error_type"] == "config_error"
    assert output["error"]["failed_step"] == "load_mikan_config"


def test_main_real_mikan_mode_can_accept_and_submit_ab(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    mikan_config = _mikan_config(tmp_path)
    ab_config = _ab_config(tmp_path, fallback_enabled=False)
    mikan_client = _FakeMikanClient()
    ab_client = FakeAutoBangumiClient()

    def build_mikan_client(config):
        assert config.search_endpoint == "https://mikan.example/Home/Search"
        return mikan_client

    monkeypatch.setattr(
        "mikan_engine.controllers.mikan_client.create_mikan_client",
        build_mikan_client,
    )
    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda config: ab_client,
    )

    exit_code = main(
        [
            "芙莉莲",
            "--source",
            "mikan",
            "--mikan-config",
            str(mikan_config),
            "--action",
            "accept",
            "--submit-ab",
            "--ab-config",
            str(ab_config),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["status"] == "ACCEPTED"
    assert output["ab_submit_result"]["success"] is True
    assert mikan_client.searches == ["芙莉莲"]
    assert ab_client.calls


def test_main_real_mikan_mode_accepts_direct_bangumi_without_title(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    mikan_config = _mikan_config(tmp_path)
    mikan_client = _FakeMikanClient()

    monkeypatch.setattr(
        "mikan_engine.controllers.mikan_client.create_mikan_client",
        lambda config: mikan_client,
    )

    exit_code = main(
        [
            "--source",
            "mikan",
            "--mikan-config",
            str(mikan_config),
            "--mikan-bangumi",
            "100",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["input"]["raw_title"] == "100"
    assert output["request"]["source_info"]["matched_bangumi"]["mikan_url"] == (
        "https://mikan.example/Home/Bangumi/100"
    )
    assert mikan_client.searches == []
    assert mikan_client.direct_entries == ["100"]


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
    config = _ab_config(tmp_path, fallback_enabled=True, password_mode=True)
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
    assert ab_submit_result["fallback_config"]["filter_rule"] == {"legacy_31_filter": "(?!)"}
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
    assert factory_configs[0].base_url == "http://auto-bangumi.local"
    assert client.calls


def test_main_save_request_persists_successful_ab_submit_result(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _ab_config(tmp_path, fallback_enabled=False)
    storage_dir = tmp_path / "migu-state"
    client = FakeAutoBangumiClient()

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda ab_config: client,
    )

    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "accept",
            "--submit-ab",
            "--ab-config",
            str(config),
            "--save-request",
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    request_id = output["request"]["request_id"]
    ab_result_path = storage_dir / "ab_results" / f"{request_id}.json"
    request_path = storage_dir / "requests" / f"{request_id}.json"
    saved_ab_result = json.loads(ab_result_path.read_text(encoding="utf-8"))
    saved_request = json.loads(request_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert output["saved_ab_result"] == {
        "request_id": request_id,
        "storage": "local_json",
        "directory": "ab_results",
        "filename": f"{request_id}.json",
    }
    assert saved_ab_result["request_id"] == request_id
    assert saved_ab_result["ab_submit_result"] == output["ab_submit_result"]
    assert saved_request["ab_submit_result"] == output["ab_submit_result"]
    assert "secret-token" not in str(saved_ab_result)


def test_main_save_request_persists_fallback_ab_submit_result(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _ab_config(tmp_path, fallback_enabled=True)
    storage_dir = tmp_path / "migu-state"
    client = FakeAutoBangumiClient(
        error=Stage1Error(
            "ab_submit_failed",
            "离线模拟失败",
            "create_ab_subscription",
            {"status_code": 503},
        )
    )

    monkeypatch.setattr(
        "ab_engine.controllers.ab_http_client.create_auto_bangumi_http_client",
        lambda ab_config: client,
    )

    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "accept",
            "--submit-ab",
            "--ab-config",
            str(config),
            "--save-request",
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    request_id = output["request"]["request_id"]
    saved_ab_result = json.loads(
        (storage_dir / "ab_results" / f"{request_id}.json").read_text(
            encoding="utf-8"
        )
    )
    loaded_exit_code = main(
        ["--load-request", request_id, "--storage-dir", str(storage_dir)]
    )
    loaded_output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["ab_submit_result"]["success"] is False
    assert output["ab_submit_result"]["fallback_config"]["title"] == "葬送的芙莉莲"
    assert saved_ab_result["ab_submit_result"]["fallback_config"] == (
        output["ab_submit_result"]["fallback_config"]
    )
    assert loaded_exit_code == 0
    assert loaded_output["request"]["ab_submit_result"] == output["ab_submit_result"]
    assert "secret-token" not in str(saved_ab_result)
    assert "http://auto-bangumi.local" not in str(saved_ab_result)


def test_main_save_request_without_submit_ab_does_not_create_ab_result_record(
    capsys,
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "migu-state"

    exit_code = main(
        [
            "芙莉莲",
            "--action",
            "accept",
            "--save-request",
            "--storage-dir",
            str(storage_dir),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["request"]["ab_submit_result"] is None
    assert "saved_ab_result" not in output
    assert list((storage_dir / "ab_results").glob("*.json")) == []


def test_apply_request_save_action_returns_stable_error_for_ab_result_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _ab_config(tmp_path, fallback_enabled=False)
    result = apply_confirmation_action(
        generate_request(EntryRequest(raw_title="芙莉莲")),
        "accept",
    )
    submitted = apply_ab_submit_action(
        result,
        True,
        ab_config_path=config,
        client=FakeAutoBangumiClient(),
    )

    def fail_save_ab_result(*args: object) -> None:
        raise Stage1Error(
            "storage_error",
            "保存 Auto Bangumi 提交结果失败",
            "save_ab_submit_result",
            {"request_id": "stable-id", "directory": "ab_results"},
        )

    monkeypatch.setattr(
        "apps.migu_orca_entry.controllers.entry_controller.save_ab_submit_result",
        fail_save_ab_result,
    )

    saved = apply_request_save_action(
        submitted,
        True,
        storage_dir=tmp_path / "migu-state",
    )

    assert saved == {
        "success": False,
        "request": None,
        "error": {
            "error_type": "storage_error",
            "error_message": "保存 Auto Bangumi 提交结果失败",
            "failed_step": "save_ab_submit_result",
            "details": {"request_id": "stable-id", "directory": "ab_results"},
        },
    }
    assert "saved_request" not in saved
    assert "saved_ab_result" not in saved
    assert str(tmp_path) not in str(saved)


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


def _ab_config(
    tmp_path: Path, *, fallback_enabled: bool, password_mode: bool = False
) -> Path:
    auth = (
        {
            "auth_mode": "password",
            "username": "private-user",
            "password": "private-password",
        }
        if password_mode
        else {"auth_mode": "api_token", "token": "secret-token"}
    )
    path = tmp_path / "ab-config.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "http://auto-bangumi.local",
                **auth,
                "fallback_enabled": fallback_enabled,
            }
        ),
        encoding="utf-8",
    )
    return path


def _mikan_config(tmp_path: Path) -> Path:
    path = tmp_path / "mikan-config.json"
    path.write_text(
        json.dumps(
            {
                "search_endpoint": "https://mikan.example/Home/Search",
                "timeout_seconds": 10,
            }
        ),
        encoding="utf-8",
    )
    return path


class _FakeMikanClient:
    def __init__(self) -> None:
        self.config = MikanConfig(
            search_endpoint="https://mikan.example/Home/Search",
            timeout_seconds=10.0,
        )
        self.transport = _FakeRssTransport()
        self.searches: list[str] = []
        self.direct_entries: list[str] = []
        self.rss_source_matches: list[str] = []

    def list_bangumi_candidates(self, raw_title: str) -> list[BangumiCandidate]:
        self.searches.append(raw_title)
        return [
            BangumiCandidate(
                bangumi_id="100",
                title="葬送的芙莉莲",
                aliases=["芙莉莲"],
                mikan_url="https://mikan.example/Home/Bangumi/100",
                rss_sources=[],
            )
        ]

    def list_rss_sources(self, matched_bangumi: MatchedBangumi) -> list[RssSource]:
        self.rss_source_matches.append(matched_bangumi.title)
        return [
            RssSource(
                subtitle_group="Loli",
                rss_url="https://mikan.example/rss/frieren.xml",
                source_type="mikan_http",
                fixture_path="",
            )
        ]

    def get_direct_bangumi_detail(self, direct_entry: str) -> MikanBangumiDetail:
        self.direct_entries.append(direct_entry)
        return MikanBangumiDetail(
            bangumi_id="100",
            title="葬送的芙莉莲",
            mikan_url="https://mikan.example/Home/Bangumi/100",
            broadcast_start=None,
            poster_url=None,
            bangumi_rss_url=None,
            subgroups=[
                MikanSubgroupDetail(
                    name="Loli",
                    rss_url="https://mikan.example/rss/frieren.xml",
                    episodes=[],
                )
            ],
        )

    def list_rss_sources_from_detail(
        self,
        detail: MikanBangumiDetail,
    ) -> list[RssSource]:
        self.rss_source_matches.append(detail.title)
        return [
            RssSource(
                subtitle_group="Loli",
                rss_url="https://mikan.example/rss/frieren.xml",
                source_type="mikan_http",
                fixture_path="",
            )
        ]


class _FakeRssTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, float]] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        self.requests.append((url, timeout))
        return """<?xml version="1.0" encoding="utf-8"?>
        <rss>
          <channel>
            <item>
              <title>[Loli] 葬送的芙莉莲 - 01</title>
              <link>https://mikan.example/download/frieren-01.torrent</link>
              <guid>frieren-01</guid>
            </item>
          </channel>
        </rss>"""
