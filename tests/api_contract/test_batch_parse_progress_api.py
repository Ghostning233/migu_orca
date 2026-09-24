"""Issue 112：批量解析逐部进度流的 API 契约回归。

覆盖：

- 每个 FOUND／EMPTY／FAILED 条目在真正完成时各推进一格，事件顺序与输入一致；
- 最终 result 事件与同步端点 ``POST /api/v1/batches/parse`` 的批次结果一致；
- 输入错误在开始流之前以普通 JSON envelope 返回；
- 中途失败以脱敏 ``error`` 事件结束，且不发送 result；
- 不暴露可续接的任务号，也没有可轮询的进度端点；断连后服务端仍可继续服务。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from flask.testing import FlaskClient

from batch_engine.models import (
    BATCH_ITEM_STATUS_EMPTY,
    BATCH_ITEM_STATUS_FAILED,
    BATCH_ITEM_STATUS_FOUND,
)
from shared.errors import Stage1Error


def _sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE body into ``(event, data)`` pairs (test-only helper)."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name: str | None = None
        data: str | None = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        assert name is not None, block
        assert data is not None, block
        events.append((name, json.loads(data)))
    return events


def _batch_raw_input(line_count: int) -> str:
    return "\n".join(f"番剧名称{index}" for index in range(1, line_count + 1))


def _empty_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates",
        lambda search_queries, mikan_config: [],
    )


def _stream(client: FlaskClient, raw_input: str) -> list[tuple[str, dict[str, Any]]]:
    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": raw_input},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    return _sse_events(response.get_data(as_text=True))


@pytest.mark.parametrize("line_count", [1, 12, 36])
def test_progress_stream_emits_one_item_event_per_completed_item(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, line_count: int
) -> None:
    """1／12／36 部都在每部真正完成时推进一格，并给出完整批次结果。"""
    _empty_search(monkeypatch)
    raw_input = _batch_raw_input(line_count)

    events = _stream(client, raw_input)

    item_events = [data for name, data in events if name == "item"]
    result_events = [data for name, data in events if name == "result"]
    assert len(item_events) == line_count
    assert [event["completed"] for event in item_events] == list(range(1, line_count + 1))
    assert all(event["total"] == line_count for event in item_events)
    assert [event["item"]["raw_title"] for event in item_events] == [
        f"番剧名称{index}" for index in range(1, line_count + 1)
    ]
    assert len(result_events) == 1

    result = result_events[0]["result"]
    assert set(result) == {"batch_id", "raw_input", "items"}
    assert [item["item_id"] for item in result["items"]] == [
        event["item"]["item_id"] for event in item_events
    ]


def test_progress_stream_result_matches_the_synchronous_endpoint(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE 的 result 与同步端点给出同一批次结果形状与顺序。"""
    _empty_search(monkeypatch)
    raw_input = "萌王S4\n路哥S4\n杖剑谭S2"

    streamed = _stream(client, raw_input)
    result = next(data for name, data in streamed if name == "result")["result"]

    sync = client.post("/api/v1/batches/parse", json={"raw_input": raw_input})
    sync_result = sync.get_json()["result"]
    assert set(sync_result) == set(result)
    assert [item["raw_title"] for item in result["items"]] == [
        item["raw_title"] for item in sync_result["items"]
    ]
    assert [item["status"] for item in result["items"]] == [
        item["status"] for item in sync_result["items"]
    ]


def test_progress_stream_advances_for_found_empty_and_failed(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FOUND、EMPTY、FAILED 都算该部完成并各推进一格，且不泄露上游细节。"""

    def _search(search_queries: list[str], mikan_config: Any) -> list[dict[str, object]]:
        query = search_queries[0]
        if "失败" in query:
            raise Stage1Error(
                "mikan_http_failed",
                "MiKan HTTP 请求失败",
                "mikan_search",
                {"url": "https://private.example/search?token=secret"},
            )
        if "空" in query:
            return []
        return [
            {
                "bangumi_id": "42",
                "mikan_url": "https://mikan.example/Home/Bangumi/42",
                "title": "找到的合集",
            }
        ]

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._search_batch_item_candidates", _search
    )

    events = _stream(client, "找到一部\n空候选一部\n失败一部")
    item_events = [data for name, data in events if name == "item"]
    assert [event["completed"] for event in item_events] == [1, 2, 3]
    assert [event["item"]["status"] for event in item_events] == [
        BATCH_ITEM_STATUS_FOUND,
        BATCH_ITEM_STATUS_EMPTY,
        BATCH_ITEM_STATUS_FAILED,
    ]
    serialized = json.dumps(events, ensure_ascii=False)
    # 上游私有地址与凭据绝不进入进度流；公开 MiKan 合集地址属于既有契约字段。
    assert "private.example" not in serialized
    assert "secret" not in serialized


def test_progress_stream_rejects_invalid_input_before_streaming(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空输入、超过 36 部与非法 storage profile 都在开始流之前返回 JSON envelope。"""
    _empty_search(monkeypatch)

    empty = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "\n \t\n"},
        headers={"Accept": "text/event-stream"},
    )
    assert empty.status_code == 400
    assert empty.headers["Content-Type"].startswith("application/json")
    assert empty.get_json()["error_type"] == "validation_error"

    over = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": _batch_raw_input(37)},
        headers={"Accept": "text/event-stream"},
    )
    assert over.status_code == 400
    assert over.headers["Content-Type"].startswith("application/json")
    assert over.get_json()["error_type"] == "batch_limit_exceeded"

    bad_profile = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4", "storage_dir": "../escape"},
        headers={"Accept": "text/event-stream"},
    )
    assert bad_profile.status_code == 400
    assert bad_profile.get_json()["error_type"] == "invalid_storage_dir"


def test_progress_stream_error_frame_is_sanitized_and_never_sends_result(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中途失败：先前的 item 事件保留，随后只有脱敏 error 事件，没有 result。"""
    _empty_search(monkeypatch)
    calls = {"count": 0}
    original = None

    from apps.migu_orca_web import routes_batches

    original = routes_batches._serialize_batch_parse_result

    def _fail_on_second(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] >= 2:
            raise RuntimeError("boom https://private.example/x /abs/path token=secret")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "apps.migu_orca_web.routes_batches._serialize_batch_parse_result", _fail_on_second
    )

    events = _stream(client, "第一部\n第二部\n第三部")

    names = [name for name, _ in events]
    assert names.count("item") == 1
    assert names.count("result") == 0
    assert names[-1] == "error"
    error = events[-1][1]
    assert error["ok"] is False
    assert error["error_type"] == "internal_server_error"
    serialized = json.dumps(events, ensure_ascii=False)
    assert "private.example" not in serialized
    assert "/abs/path" not in serialized
    assert "secret" not in serialized
    assert "RuntimeError" not in serialized


def test_progress_stream_exposes_no_resume_handle_or_polling_endpoint(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """进度事件不携带任务号；没有可轮询的进度端点，两次请求互相独立。"""
    _empty_search(monkeypatch)

    first = _stream(client, "萌王S4\n路哥S4")
    second = _stream(client, "萌王S4\n路哥S4")

    for name, data in first:
        if name == "item":
            assert "batch_id" not in json.dumps(data, ensure_ascii=False)
    first_batch = next(data for name, data in first if name == "result")["result"]["batch_id"]
    second_batch = next(data for name, data in second if name == "result")["result"]["batch_id"]
    assert first_batch != second_batch

    # 没有按 id 查询进度的续接入口；默认表示仍是一次性 JSON。
    assert client.get(f"/api/v1/batches/{first_batch}/progress").status_code == 404
    buffered = client.post("/api/v1/batches/parse", json={"raw_input": "萌王S4"})
    assert buffered.headers["Content-Type"].startswith("application/json")
    assert buffered.get_json()["ok"] is True


def test_progress_stream_disconnect_does_not_break_later_requests(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """客户端提前断开后，服务端不崩溃，也不产生可续接的残留状态。"""
    _empty_search(monkeypatch)

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": _batch_raw_input(5)},
        headers={"Accept": "text/event-stream"},
        buffered=False,
    )
    iterator = iter(response.response)
    next(iterator)
    close = getattr(iterator, "close", None)
    if callable(close):
        close()

    # 断开不产生持久任务：后续同步请求仍是全新的完整批次。
    sync = client.post("/api/v1/batches/parse", json={"raw_input": "萌王S4"})
    payload = sync.get_json()
    assert payload["ok"] is True
    assert [item["raw_title"] for item in payload["result"]["items"]] == ["萌王S4"]


# ---------------------------------------------------------------------------
# Issue 129: default JSON vs explicit SSE negotiation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "headers",
    [
        {},  # 未设置 Accept
        {"Accept": "*/*"},  # 通配（浏览器/常见客户端默认）
        {"Accept": "application/json"},
        {"Accept": "application/json, text/plain, */*"},
        {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    ],
)
def test_batch_parse_default_representations_stay_json(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    """#129：未显式请求事件流时不误选 SSE，仍返回原有 JSON envelope。"""
    _empty_search(monkeypatch)

    response = client.post(
        "/api/v1/batches/parse", json={"raw_input": "萌王S4\n路哥S4"}, headers=headers
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.get_json()
    assert payload["ok"] is True
    assert set(payload["result"]) == {"batch_id", "raw_input", "items"}
    assert [item["raw_title"] for item in payload["result"]["items"]] == ["萌王S4", "路哥S4"]
    assert "event:" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "accept",
    ["text/event-stream", "text/event-stream, application/json", "application/json;q=0.1, text/event-stream"],
)
def test_batch_parse_explicit_event_stream_selection_streams(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, accept: str
) -> None:
    """#129：显式选择 text/event-stream 时仍返回逐部事件与同形最终结果。"""
    _empty_search(monkeypatch)

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4\n路哥S4"},
        headers={"Accept": accept},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    events = _sse_events(response.get_data(as_text=True))
    assert [name for name, _ in events] == ["item", "item", "result"]
    assert [data["completed"] for name, data in events if name == "item"] == [1, 2]
    result = next(data for name, data in events if name == "result")["result"]
    assert [item["raw_title"] for item in result["items"]] == ["萌王S4", "路哥S4"]


def test_batch_parse_rejects_event_stream_with_zero_quality(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#129：显式拒绝事件流（q=0）时回到默认 JSON。"""
    _empty_search(monkeypatch)

    response = client.post(
        "/api/v1/batches/parse",
        json={"raw_input": "萌王S4"},
        headers={"Accept": "text/event-stream;q=0, application/json"},
    )

    assert response.headers["Content-Type"].startswith("application/json")
    assert response.get_json()["ok"] is True


# ---------------------------------------------------------------------------
# Issue 132: explicit SSE event shapes in the formal contract
# ---------------------------------------------------------------------------

def test_openapi_documents_the_three_sse_event_shapes() -> None:
    """正式契约明确 item／result／error 三类事件形状，且 item 与 JSON 表示同源。"""
    from apps.migu_orca_web.openapi_gen import generate_openapi

    spec = generate_openapi()
    content = spec["paths"]["/api/v1/batches/parse"]["post"]["responses"]["200"]["content"]
    assert set(content) == {"application/json", "text/event-stream"}

    stream = content["text/event-stream"]
    assert stream["schema"]["type"] == "string"
    events = stream["x-sse-events"]
    assert set(events) == {"item", "result", "error"}

    # item：逐部完成事件，形状固定且不允许额外字段。
    assert events["item"]["required"] == ["completed", "total", "item"]
    assert events["item"]["additionalProperties"] is False
    assert events["item"]["properties"]["total"]["maximum"] == 36
    assert events["item"]["properties"]["completed"]["minimum"] == 1

    # result／error：终态与失败帧分别有固定必填字段。
    assert events["result"]["required"] == ["ok", "result"]
    assert events["result"]["properties"]["ok"]["const"] is True
    assert events["error"]["required"] == ["ok", "error_type", "error_message"]
    assert events["error"]["properties"]["ok"]["const"] is False

    # item 载荷与默认 JSON 表示的同一条目 schema 完全一致，避免两套形状漂移。
    json_item = content["application/json"]["schema"]["properties"]["result"]["properties"]["items"]["items"]
    assert events["item"]["properties"]["item"] == json_item
    assert events["result"]["properties"]["result"] == content["application/json"]["schema"]["properties"]["result"]
