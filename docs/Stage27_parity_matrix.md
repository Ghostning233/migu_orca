# MiGuOrca Stage 27 parity 矩阵（US-208）

> 本文档是 US-208 的产物：把旧前端（Stage 13～25 累积的 Flask/Jinja + `app.js`
> Web UI）的 **269 个真实 Chromium 旅程**映射到新前端（Vue 3 + TypeScript + Vite
> SPA，`/app/`）的覆盖套件与路由，作为「新旧功能对等」的可审查证据。自动核对：
> `tests/api_contract/test_parity_matrix_guard.py` 逐一重数旧套件测试数、核对
> 矩阵条目与 SPA 套件存在性，任何旧套件重命名/删减都会导致测试失败。

## 1. 矩阵

旧旅程套件（`tests/browser/test_*.py`）→ 新前端覆盖套件（`tests/browser/test_app_*.py`）
与 SPA 路由。`legacy_tests` 是旧套件当前 `def test_` 数量（合计 269），由 guard 重数守护。

| 旧旅程套件 | 旧测试数 | 新前端覆盖套件 | SPA 路由 |
| --- | --- | --- | --- |
| shell | 22 | test_app_shell | `/app/` → `/app/workbench`、`/app/requests`、`/app/queue`、`/app/settings` |
| actions | 41 | test_app_request_detail | `/app/requests`（详情面板：确认/取消/修改/删除/AB 入口） |
| list | 10 | test_app_requests | `/app/requests`（列表加载/搜索/筛选/排序/计数/空状态/URL 恢复） |
| detail | 32 | test_app_request_detail | `/app/requests`（详情分区/URL 状态恢复/Seeds/Audit/AB 入口） |
| preferences | 11 | test_app_settings | `/app/settings`（偏好默认值/恢复默认/敏感输入拒绝） |
| qbittorrent_connection | 8 | test_app_settings | `/app/settings`（qBittorrent 连接测试） |
| generation | 24 | test_app_workbench | `/app/workbench`（生成/预览草案/保存/确认） |
| fixture_mode | 5 | test_app_workbench | `/app/workbench`（真实 MiKan 主流程；fixture 只保留 CLI/API seam） |
| batch_workbench | 39 | test_app_batch_workbench | `/app/workbench`（批量工作台）+ `/app/queue`（提交队列） |
| mikan_candidates | 36 | test_app_workbench | `/app/workbench`（候选搜索/季数确认/冲突禁用/草案编辑） |
| a11y | 14 | test_app_responsive_a11y | `/app/*`（键盘/skip link/焦点/ARIA/reduced-motion） |
| infrastructure | 11 | test_app_shell | `/app/`（SPA 托管/fallback 边界/探针不被截获） |
| ui_quality | 12 | test_app_responsive_a11y | `/app/*`（360px/无障碍/状态不只靠颜色/按钮语义） |
| stage11_real_config_entry | 4 | test_app_settings | `/app/settings?request_id=<id>`（AB 提交上下文） |
| **合计** | **269** | — | — |

> `test_components_primitives`（US-200 的 `/app/components-demo` 原语演示）不是旧旅程，
> 是迁移脚手架，US-209 随脚手架删除，不进入矩阵。

## 2. 入口切换（默认 entry）

US-208 把默认 Web 入口从旧 Jinja 页面切换到 SPA（`src/apps/migu_orca_web/views.py` 的
`web_entry_mode()`，服务端环境变量控制，浏览器不可控）：

- 默认（`spa`）：`GET /` → `/app/workbench`；`GET /index` → `/app/workbench`
  （保留 `request_id`/`batch_id` query）；`GET /Settings`、`GET /settings` →
  `/app/settings`（保留 `request_id` query）。`#auto-bangumi` 锚点是 no-op，
  SPA Settings 在同一页面渲染 AB 面板。
- `MIGU_ORCA_WEB_ENTRY_LEGACY=1`（回退演练/旧旅程回归）：`GET /` → `/index`，
  `/index`、`/settings` 恢复旧 Jinja 页面。
- `MIGU_ORCA_WEB_ENTRY_SPA=1` 强制 SPA（默认即 SPA）。

只转发公开已保存标识符（`request_id`/`batch_id`）；endpoint/token/storage 路径等
敏感值绝不进入重定向 URL（`test_spa_entry_never_forwards_sensitive_query_values` 守护）。

## 3. 回退演练（不修改业务数据）

`tests/browser/test_app_entry_switch.py`（真实 Chromium）：

1. 在默认 SPA entry 下打开 `/app/workbench`，确认 SPA 挂载、`/api/v1/requests`
   与 `/healthz` 正常；
2. 切换 `MIGU_ORCA_WEB_ENTRY_LEGACY=1`（测试用 `page.route` 拦截页面请求并
   redirect 到旧页面，模拟部署回退），确认旧 `/index`/`/settings` 恢复、SPA
   `/app/*` 仍可用；
3. 确认整个过程中 `/api/v1/*` 与 storage 行为不变（API 不回滚，storage 不写入）。

## 4. 关键旅程覆盖证据

- 单个 FOUND/EMPTY/FAILED、候选选择、季数确认、冲突禁用、draft 失效恢复 → `test_app_workbench.py`。
- 批量解析/候选浮层/草案详情与删除/单个·批量·全接受 → `test_app_batch_workbench.py`。
- 队列读取/顺序提交/失败重试/recover/刷新恢复 → `test_app_queue.py`。
- Request 修改/取消/删除/AB Settings 上下文 → `test_app_request_detail.py` + `test_app_settings.py`。
- qB/AB 成功、认证失败、超时、非 JSON、敏感字段清理 → `test_app_settings.py`。
- localStorage/sessionStorage/URL/页面/构建产物敏感值 → 各 SPA 套件的敏感边界断言。
- 360px/键盘/焦点恢复/ARIA/reduced-motion/SPA fallback 边界 → `test_app_responsive_a11y.py` + `test_app_shell.py`。
