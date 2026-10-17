from __future__ import annotations

"""Real Auto Bangumi 3.1.18 write envelopes (issue #216).

The verified write contract has no ``status`` field: every 3.1.18 write endpoint
answers with ``{"msg_en": str, "msg_zh": str}`` and the HTTP status carries the
result.  Upstream tag 3.1.18 ``module/api/response.py`` (``u_response``) returns a
``JSONResponse`` with exactly those two keys, so FastAPI never re-serializes the
declared ``APIResponse`` model — which is how the disproved ``status: true``
assumption entered this repository.

Provenance of every constant below:

``RECORDED_*``
    Recorded from the real 3.1.18 test instance during issue #216's work package
    (2026-10-17).  Only the public message fields are kept: endpoint, credential,
    Cookie, raw body, full RSS URL and local paths are never copied here.
The issue's own recorded table (``POST /api/v1/rss/disable/many`` with an empty
body → ``200 {"msg_en": "Disable RSS successfully.", "msg_zh": "禁用 RSS 成功。"}``)
is the same envelope shape; it is not repeated here because no current client
call reaches that exact route.

``SOURCE_DERIVED_*``
    Synthetic but shape-exact fixtures derived from the upstream ``u_response``
    source where no byte-for-byte recording exists.  They exist so no test keeps
    asserting the disproved ``{"status": true}`` assumption, and they are never
    presented as a real-machine recording.
"""

#: Recorded ``GET /api/v1/bangumi/enable/999999``: HTTP 406 with the documented
#: id error.  This is the management write rejection used by the AC4 tests.
RECORDED_MISSING_ID_STATUS = 406
RECORDED_MISSING_ID_ENVELOPE = {
    "msg_en": "Can't find id 999999",
    "msg_zh": "无法找到 id 999999",
}

#: Recorded ``DELETE /api/v1/rss/delete/<id>``: HTTP 200 with the success
#: envelope.  A real accepted management write, body and all.
RECORDED_RSS_DELETE_STATUS = 200
RECORDED_RSS_DELETE_ENVELOPE = {
    "msg_en": "Delete RSS successfully.",
    "msg_zh": "删除 RSS 成功。",
}

#: Recorded ``POST /api/v1/rss/subscribe`` on a feed Auto Bangumi could not
#: download: HTTP 406, and the instance **still created** the subscription and
#: its RSS row (a real partial effect).  The message carries no duplicate marker,
#: which is why the submit path may never treat a rejected write body as proof
#: that nothing was created — the exact read-back is what confirms it.
RECORDED_SUBSCRIBE_FEED_FAILED_STATUS = 406
RECORDED_SUBSCRIBE_FEED_FAILED_ENVELOPE = {
    "msg_en": "[Engine] Download MiGuOrcaProbe216 failed.",
    "msg_zh": "[Engine] 下载 MiGuOrcaProbe216 失败。",
}

#: Recorded ``POST /api/v1/rss/subscribe`` on a feed the instance could not
#: fetch at all: HTTP 500 with an **empty** body.  Neither the status nor the
#: absent body may be read as a definite failure, because the instance had
#: already written its RSS row.
RECORDED_SUBSCRIBE_SERVER_ERROR_STATUS = 500
RECORDED_SUBSCRIBE_SERVER_ERROR_BODY = b""

#: Recorded ``GET /api/v1/rss/refresh/<id>``: HTTP 200 with the success
#: envelope.  A write-through-GET uses the very same write envelope, so the
#: criterion is not specific to POST/PATCH/DELETE.
RECORDED_REFRESH_RSS_STATUS = 200
RECORDED_REFRESH_RSS_ENVELOPE = {
    "msg_en": "Refresh RSS successfully.",
    "msg_zh": "刷新 RSS 成功。",
}

#: Shape-exact synthetic success envelope for a persistent subscription write.
#: Source-derived: the real endpoint sends these two string keys and no id, so
#: the exact wording is irrelevant to the success criterion and is deliberately
#: not presented as a recording.
SOURCE_DERIVED_SUBSCRIBE_ENVELOPE = {
    "msg_en": "Subscribe successfully.",
    "msg_zh": "订阅成功。",
}

#: Shape-exact synthetic envelope for a duplicate subscription rejection.  The
#: real instance refuses an equal subscribe with a non-200 status; only the
#: category is derived by MiGuOrca from the bounded message fields.
SOURCE_DERIVED_DUPLICATE_ENVELOPE = {
    "msg_en": "The subscription already exists.",
    "msg_zh": "该订阅已存在，请勿重复添加。",
}

#: Shape-exact synthetic success envelope for the one-time collection endpoint
#: ``POST /api/v1/rss/collect`` (issue #217).  Source-derived: 3.1.18 answers
#: every write through the same ``u_response`` helper, so a collection success is
#: the same two string keys with no ``status`` and no id.  The exact wording is
#: irrelevant to the criterion and is deliberately not a recording.
SOURCE_DERIVED_COLLECT_ENVELOPE = {
    "msg_en": "Collections of MiguOrcaProbe217 Season 1 completed.",
    "msg_zh": "收集 MiguOrcaProbe217 第 1 季完成。",
}

#: Shape-exact synthetic 406 envelope for the two semantics upstream cannot tell
#: apart — "filtered to nothing" and "downloader rejected / already added"
#: (``collector.py:37-46``).  Source-derived from that source; a collection
#: rejection must never be read as a success.
SOURCE_DERIVED_COLLECT_REJECTED_ENVELOPE = {
    "msg_en": "Collection of MiguOrcaProbe217 Season 1 failed.",
    "msg_zh": "收集 MiguOrcaProbe217 第 1 季失败, 种子已经添加。",
}
