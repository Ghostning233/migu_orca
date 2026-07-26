from __future__ import annotations

import json
from pathlib import Path

from apps.migu_orca_entry.controllers.entry_controller import generate_request, main
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
