from __future__ import annotations

import pytest

from shared.sensitive_values import contains_sensitive_value, redact_sensitive_text


@pytest.mark.parametrize(
    "text",
    [
        "https://mikan.example/Home/Bangumi/1",
        "magnet:?xt=urn:btih:abc",
        "/etc/passwd",
        "C:\\Users\\me\\secret",
        "file:///tmp/x",
        "<html><body>raw</body></html>",
        "token=abc123",
        'password: "hunter2"',
        "api_key",
        "raw_rss",
    ],
)
def test_contains_sensitive_value_rejects_sensitive_shapes(text: str) -> None:
    assert contains_sensitive_value(text) is True


@pytest.mark.parametrize(
    "text",
    ["1080p 喵萌奶茶屋", "转生史莱姆 第四季", "01 [1080p]"],
)
def test_contains_sensitive_value_keeps_legitimate_values(text: str) -> None:
    assert contains_sensitive_value(text) is False


def test_allow_relative_paths_only_rejects_real_root_paths() -> None:
    # 命名模板里的相对分隔符放行；真正的根路径仍然拒绝。
    assert contains_sensitive_value("TV/{title}/Season N", allow_relative_paths=True) is False
    assert contains_sensitive_value("/home/user/media", allow_relative_paths=True) is True
    assert contains_sensitive_value("D:\\media", allow_relative_paths=True) is True
    # 默认口径下相对斜杠片段也算可疑（保持旧判定）。
    assert contains_sensitive_value("TV/{title}/Season N") is True


def test_redact_sensitive_text_keeps_the_legacy_placeholders() -> None:
    text = "https://x/y magnet:?xt=1 token=abc /abs/path"
    assert redact_sensitive_text(text) == (
        "[redacted-url] [redacted] [redacted] [redacted-path]"
    )


def test_redact_sensitive_text_collapses_markup_to_one_marker() -> None:
    assert redact_sensitive_text("<html>raw</html>") == "[redacted-content]"
