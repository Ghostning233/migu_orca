from __future__ import annotations

"""US-208: auditable parity matrix from the 269 legacy Chromium journeys.

Every legacy browser test file (the pre-Stage-27 Flask/Jinja journeys) maps to
the new SPA route that now provides the same user capability. The matrix is
data (not code) so it stays reviewable in PRs; ``test_parity_matrix_guard.py``
keeps it honest by re-counting the legacy suites and asserting every mapped
journey has a corresponding SPA browser suite with at least as many tests.

Mapping rules:

- ``legacy_file``: the ``tests/browser/<file>.py`` basename (without the
  ``test_`` prefix / ``.py`` suffix) of a legacy journey suite. The guard
  counts ``def test_`` in the real file, so renaming a legacy suite breaks
  the guard instead of silently changing the matrix.
- ``legacy_tests``: the exact number of test functions in that file today
  (the "269 journeys" total). The guard re-counts and fails on drift.
- ``spa_suite``: the SPA browser test file that covers the migrated
  capability (US-202..US-207 suites). The guard asserts it exists and has
  at least as many tests as the legacy file.
- ``spa_route``: the SPA route(s) that replace the legacy entry. ``/index``
  maps to the workbench (search + batch + list + detail + queue all live
  under the 4 SPA routes; queue specifically under ``/app/queue``), and
  ``/settings`` maps to ``/app/settings``.

The matrix deliberately treats the *legacy file* as the audit unit: US-208's
acceptance is "旧 269 个 Chromium 旅程到新路由的可审查 parity 矩阵，关键旅程
全部由新前端覆盖" — every legacy journey is accounted for and has a new-frontend
counterpart, not that each individual old assertion is replicated (the SPA
suites assert the same business behavior from the migrated views, US-202-207).
"""

PARITY_MATRIX: list[dict[str, str | int]] = [
    # legacy_file → (legacy_tests, spa_suite, spa_route)
    {
        "legacy_file": "shell",
        "legacy_tests": 22,
        "spa_suite": "test_app_shell",
        "spa_route": "/app/ → /app/workbench、/app/requests、/app/queue、/app/settings",
    },
    {
        "legacy_file": "actions",
        "legacy_tests": 41,
        "spa_suite": "test_app_request_detail",
        "spa_route": "/app/requests（详情面板：确认/取消/修改/删除/AB 入口）",
    },
    {
        "legacy_file": "list",
        "legacy_tests": 10,
        "spa_suite": "test_app_requests",
        "spa_route": "/app/requests（列表加载/搜索/筛选/排序/计数/空状态/URL 恢复）",
    },
    {
        "legacy_file": "detail",
        "legacy_tests": 32,
        "spa_suite": "test_app_request_detail",
        "spa_route": "/app/requests（详情分区/URL 状态恢复/Seeds/Audit/AB 入口）",
    },
    {
        "legacy_file": "preferences",
        "legacy_tests": 11,
        "spa_suite": "test_app_settings",
        "spa_route": "/app/settings（偏好默认值/恢复默认/敏感输入拒绝）",
    },
    {
        "legacy_file": "qbittorrent_connection",
        "legacy_tests": 8,
        "spa_suite": "test_app_settings",
        "spa_route": "/app/settings（qBittorrent 连接测试）",
    },
    {
        "legacy_file": "generation",
        "legacy_tests": 24,
        "spa_suite": "test_app_workbench",
        "spa_route": "/app/workbench（生成/预览草案/保存/确认）",
    },
    {
        "legacy_file": "fixture_mode",
        "legacy_tests": 5,
        "spa_suite": "test_app_workbench",
        "spa_route": "/app/workbench（真实 MiKan 主流程；fixture 只保留 CLI/API seam）",
    },
    {
        "legacy_file": "batch_workbench",
        "legacy_tests": 39,
        "spa_suite": "test_app_batch_workbench",
        "spa_route": "/app/workbench（批量工作台）+ /app/queue（提交队列）",
    },
    {
        "legacy_file": "mikan_candidates",
        "legacy_tests": 36,
        "spa_suite": "test_app_workbench",
        "spa_route": "/app/workbench（候选搜索/季数确认/冲突禁用/草案编辑）",
    },
    {
        "legacy_file": "a11y",
        "legacy_tests": 14,
        "spa_suite": "test_app_responsive_a11y",
        "spa_route": "/app/*（键盘/skip link/焦点/ARIA/reduced-motion）",
    },
    {
        "legacy_file": "infrastructure",
        "legacy_tests": 11,
        "spa_suite": "test_app_shell",
        "spa_route": "/app/（SPA 托管/fallback 边界/探针不被截获）",
    },
    {
        "legacy_file": "ui_quality",
        "legacy_tests": 12,
        "spa_suite": "test_app_responsive_a11y",
        "spa_route": "/app/*（360px/无障碍/状态不只靠颜色/按钮语义）",
    },
    {
        "legacy_file": "stage11_real_config_entry",
        "legacy_tests": 4,
        "spa_suite": "test_app_settings",
        "spa_route": "/app/settings?request_id=<id>（AB 提交上下文）",
    },
]

LEGACY_TOTAL = sum(int(entry["legacy_tests"]) for entry in PARITY_MATRIX)
