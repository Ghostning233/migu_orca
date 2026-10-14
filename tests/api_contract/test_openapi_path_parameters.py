from __future__ import annotations

"""Issue #203: OpenAPI path parameters are derived from the Flask URL rule.

Before this ticket the registry carried a hand-written path-parameter skeleton
on some endpoints and nothing at all on twelve others, so a generated client
could not build the URL for those twelve.  The rule now has exactly one source:

- the **URL rule** decides which path parameters exist and their order;
- the registry may only add a documentation ``description`` overlay for a name
  the rule already declares (``name``/``in`` are the lookup keys, nothing else);
- a declared path name that the rule does not carry (a typo or a rename) aborts
  generation instead of publishing a phantom parameter.

These tests pin the derivation, the overlay-only registry contract, and the
consistency check that turns red for a missing, extra or renamed parameter.
"""

from typing import Any

import pytest

from apps.migu_orca_web import openapi_gen
from apps.migu_orca_web.openapi_gen import (
    _ENDPOINTS,
    _derived_path_parameters,
    _normalized_path,
    _operation_parameters,
    _ordered_path_parameters,
    _path_parameter_consistency,
    _path_parameters,
    generate_openapi,
)

_CHECK = "POST /api/v1/tracking/items/<path:tracking_id>/check"


def _documented_parameters(doc: dict[str, Any], key: str) -> list[dict[str, Any]]:
    method, rule = key.split(" ", 1)
    return doc["paths"][_normalized_path(rule)][method.lower()].get("parameters", [])


def _declared_path_names(parameters: list[dict[str, Any]]) -> list[str]:
    return [item["name"] for item in parameters if item.get("in") == "path"]


def test_every_endpoint_declares_exactly_the_url_rule_path_parameters() -> None:
    """The real document: declared path names == the URL rule's ``{param}`` set."""
    doc = generate_openapi()
    checked = 0
    for key in _ENDPOINTS:
        method, rule = key.split(" ", 1)
        path = _normalized_path(rule)
        parameters = _documented_parameters(doc, key)
        missing, extra = _path_parameter_consistency(
            _ordered_path_parameters(path), parameters
        )
        assert not missing, f"{key} is missing path parameter(s) {missing}"
        assert not extra, f"{key} declares unknown path parameter(s) {extra}"
        checked += 1
    assert checked == len(_ENDPOINTS)


def test_registry_path_parameters_are_description_overlays_only() -> None:
    """No endpoint may hand-write a path skeleton (issue #203)."""
    for key, entry in _ENDPOINTS.items():
        for parameter in entry.get("parameters", []):
            if parameter.get("in") != "path":
                continue
            assert set(parameter) <= {"name", "in", "description"}, (
                f"{key} hand-writes a path parameter skeleton: {parameter!r}; "
                "the URL rule owns name/in/required/schema."
            )


def test_derived_skeleton_is_complete_even_without_an_overlay() -> None:
    """A rule parameter without an overlay still gets a usable skeleton."""
    path = _normalized_path(_CHECK)
    derived = _derived_path_parameters(_CHECK, path, {})
    assert derived == [
        {
            "name": "tracking_id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
    ]


def test_derived_skeleton_keeps_the_chinese_description_overlay() -> None:
    """Descriptions are overlay-only, so they must survive the derivation."""
    entry = {
        "parameters": [
            {"name": "tracking_id", "in": "path", "description": "统一追番记录的 tracking_id。"},
            {"name": "storage_dir", "in": "query", "schema": {"type": "string"}},
        ]
    }
    path = _normalized_path("GET /api/v1/tracking/items/<path:tracking_id>")
    derived = _derived_path_parameters(
        "GET /api/v1/tracking/items/<path:tracking_id>", path, entry
    )
    assert derived == [
        {
            "name": "tracking_id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
            "description": "统一追番记录的 tracking_id。",
        }
    ]
    # Only the overlay is consumed: the query parameter passes through untouched.
    all_parameters = _operation_parameters(
        "GET /api/v1/tracking/items/<path:tracking_id>", path, entry
    )
    assert [item["in"] for item in all_parameters] == ["path", "query"]


def test_every_request_body_endpoint_gained_its_path_parameter() -> None:
    """The twelve endpoints #171 found missing now declare their parameter."""
    doc = generate_openapi()
    without_parameters = [
        key
        for key in _ENDPOINTS
        if _ENDPOINTS[key].get("requestBody") is not None
        and _ordered_path_parameters(_normalized_path(key.split(" ", 1)[1]))
        and not _declared_path_names(_documented_parameters(doc, key))
    ]
    assert without_parameters == []


def test_renamed_path_parameter_overlay_is_rejected() -> None:
    """A renamed declaration is rejected: the rule is the only name source."""
    entry = {"parameters": [{"name": "item_id", "in": "path", "description": "改名了"}]}
    with pytest.raises(ValueError, match="not a URL rule parameter"):
        _derived_path_parameters(_CHECK, _normalized_path(_CHECK), entry)


def test_duplicate_path_parameter_overlay_is_rejected() -> None:
    """A repeated overlay name fails closed instead of silently keeping the last."""
    entry = {
        "parameters": [
            {"name": "tracking_id", "in": "path", "description": "第一次"},
            {"name": "tracking_id", "in": "path", "description": "第二次"},
        ]
    }
    with pytest.raises(ValueError, match="more than once"):
        _derived_path_parameters(_CHECK, _normalized_path(_CHECK), entry)


def test_path_skeleton_keys_in_the_registry_are_rejected() -> None:
    """A re-declared ``required``/``schema`` is a second structure source."""
    entry = {
        "parameters": [
            {"name": "tracking_id", "in": "path", "required": False, "schema": {"type": "integer"}}
        ]
    }
    with pytest.raises(ValueError, match="skeleton"):
        _derived_path_parameters(_CHECK, _normalized_path(_CHECK), entry)


def test_unknown_parameter_location_is_rejected() -> None:
    entry = {"parameters": [{"name": "tracking_id", "in": "body"}]}
    with pytest.raises(ValueError, match="unsupported parameter location"):
        _operation_parameters(_CHECK, _normalized_path(_CHECK), entry)


def test_consistency_check_flags_missing_extra_and_renamed() -> None:
    """All three drift directions turn red (issue #203 acceptance)."""
    rule = ("tracking_id",)

    def declared(*names: str) -> list[dict[str, Any]]:
        return [{"name": name, "in": "path"} for name in names]


    # 少：URL rule 声明了参数，文档没有（生成器会从 rule 兜底补齐，检查必须看得见）
    assert _path_parameter_consistency(rule, []) == (("tracking_id",), ())
    # 多余：文档凭空多出一个参数
    assert _path_parameter_consistency(rule, declared("tracking_id", "other")) == ((), ("other",))
    # 改名：旧名未声明 + 新名不存在，两个方向同时红
    assert _path_parameter_consistency(rule, declared("item_id")) == (("tracking_id",), ("item_id",))
    # query／cookie 参数不算 path 声明，不参与比较
    assert _path_parameter_consistency(
        rule,
        [*declared("tracking_id"), {"name": "storage_dir", "in": "query"}],
    ) == ((), ())


def test_document_check_would_catch_a_lost_derivation() -> None:
    """Dropping the derived parameter from one operation is detected.

    This is the regression the consistency check exists for: hand-construct the
    broken operation (as if the skeleton were lost again) and prove the same
    helper the document test uses reports the missing parameter.
    """
    doc = generate_openapi()
    path = _normalized_path(_CHECK.split(" ", 1)[1])
    operation = doc["paths"][path]["post"]
    stripped = [item for item in operation["parameters"] if item.get("in") != "path"]
    assert _path_parameter_consistency(_ordered_path_parameters(path), stripped) == (
        ("tracking_id",),
        (),
    )


def test_path_parameters_never_leak_back_into_the_request_body() -> None:
    """The view merges path args into the body; they are not body fields."""
    for key, entry in _ENDPOINTS.items():
        spec = entry.get("requestBody")
        if spec is None:
            continue
        method, rule = key.split(" ", 1)
        path = _normalized_path(rule)
        body = openapi_gen._request_body_schema(spec, _path_parameters(path))
        for name in _ordered_path_parameters(path):
            assert name not in body.get("properties", {}), f"{key}: {name} is a body field"
            assert name not in body.get("required", []), f"{key}: {name} is a body required field"
