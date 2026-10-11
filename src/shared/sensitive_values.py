"""外部值的敏感模式与判定（#170）。

`tracking_engine/models/tracking.py`（把审计/展示文本里的敏感值脱敏）与
`storage_engine/controllers/preference_repository.py`（拒绝敏感偏好值）此前各自
复制了同一组正则。这里保留一份，两处改为引用。

两个用途对「哪些模式参与」不同，因此导出的是**模式本身**加两个语义明确的函数，
而不是一个带开关的大函数：

- `redact_sensitive_text()`：只替换，不查关键词表（保持 tracking 侧的既有输出）；
- `contains_sensitive_value()`：只判定，不替换（保持 preference 侧的既有判定）。
"""

from __future__ import annotations

import re

URL_RE = re.compile(r"https?://[^\s<>'\"]+")
MAGNET_RE = re.compile(r"magnet:\?[^\s<>'\"]*", re.IGNORECASE)
ABSOLUTE_PATH_RE = re.compile(r"(?<!\w)(?:/[^\s<>'\"]+)+")
#: 只匹配「根路径」形态（行首或空白/引号之后的 ``/…``）：供允许相对路径分隔符的
#: 字段使用（例如命名模板 ``TV/{title}/Season N``），真正的绝对路径仍被拒绝。
ABSOLUTE_PATH_STRICT_RE = re.compile(r"(?:^|[\s'\"])(/[^\s<>'\"]+)")
FILE_SCHEME_RE = re.compile(r"file://", re.IGNORECASE)
WINDOWS_DRIVE_RE = re.compile(r"(?i)\b[a-z]:[\\/]")
MARKUP_RE = re.compile(r"<\s*(?:html|rss|xml|svg|script|body|!doctype)\b", re.IGNORECASE)
SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session|endpoint|rss_url)\s*[=:]\s*[^\s,;]+"
)
#: 偏好值的词边界关键词表（比键值对形态更宽：包含 api_key/raw_html 等）。
SENSITIVE_KEYWORDS_RE = re.compile(
    r"(?i)\b(?:token|secret|cookie|authorization|password|passwd|bearer|"
    r"username|sid|session|endpoint|api_key|apikey|rss_url|raw_html|raw_rss|"
    r"response_body|request_body|magnet)\b"
)


def contains_sensitive_value(text: str, *, allow_relative_paths: bool = False) -> bool:
    """``text`` 是否看起来像敏感的外部值（判定，不修改文本）。

    ``allow_relative_paths`` 供合法包含相对路径分隔符的字段使用：此时只拒绝真正的
    绝对路径（根路径、Windows 盘符、``file://``），相对斜杠片段放行。
    """
    if URL_RE.search(text):
        return True
    if MAGNET_RE.search(text):
        return True
    if allow_relative_paths:
        if ABSOLUTE_PATH_STRICT_RE.search(text):
            return True
    elif ABSOLUTE_PATH_RE.search(text):
        return True
    if FILE_SCHEME_RE.search(text):
        return True
    if WINDOWS_DRIVE_RE.search(text):
        return True
    if MARKUP_RE.search(text):
        return True
    if SENSITIVE_KEY_VALUE_RE.search(text):
        return True
    return bool(SENSITIVE_KEYWORDS_RE.search(text))


def redact_sensitive_text(value: str) -> str:
    """把 ``value`` 中的 URL/magnet/键值/路径替换为固定占位符。

    替换顺序与占位符沿用既有实现（``[redacted]`` / ``[redacted-url]`` /
    ``[redacted-path]`` / ``[redacted-content]``），输出逐字节不变。
    """
    text = MAGNET_RE.sub("[redacted]", value)
    text = URL_RE.sub("[redacted-url]", text)
    text = SENSITIVE_KEY_VALUE_RE.sub("[redacted]", text)
    text = ABSOLUTE_PATH_RE.sub("[redacted-path]", text)
    text = FILE_SCHEME_RE.sub("[redacted-url]", text)
    text = WINDOWS_DRIVE_RE.sub("[redacted-path]", text)
    if MARKUP_RE.search(text):
        return "[redacted-content]"
    return text
