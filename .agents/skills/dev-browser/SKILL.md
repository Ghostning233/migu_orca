---
name: dev-browser
description: "在 MiGuOrca 项目中执行浏览器验证。项目没有 MCP 浏览器工具；通过 Playwright 浏览器测试套件（tests/browser/）在真实 Chromium 上验证 Web UI 变更，并说明手动启动 Flask 后的替代验证方式。Use when a user story requires browser verification or a Web UI change needs verification."
user-invocable: true
---

# dev-browser：MiGuOrca 浏览器验证

本项目的 Web UI 是 Vue 3 + TypeScript + Vite SPA（`frontend/`，由 Flask 在 `/app/` 同源托管；
旧 Flask/Jinja 页面与 `app.js` 已删除）。浏览器验证的标准路径是**项目的 Playwright 测试套件**
（真实 Chromium 跑 Flask test server）；本地无 MCP 浏览器工具时不要尝试截图驱动，直接写/跑浏览器测试。

## 主验证路径：Playwright 套件

```bash
uv run pytest tests/browser/test_xxx.py::TestYyy::test_zzz -q   # 单个测试
uv run pytest tests/browser/ -q        # Stage 收尾的完整门禁，通常一次
```

前置条件：

- Chromium 可用（必要时先跑 `script/setup-browser-deps.sh`；`bin/chromium-wrapper.sh` 是包装脚本）
- 核对仓库根 `.migu_orca/storage`：陈旧运行数据会污染空状态/黄金路径；gitignore 不代表可以删除。
  优先隔离测试根；确需移走时先核对内容，移动到唯一备份目录、报告位置，不覆盖旧备份/丢失用户数据。
- SPA 测试需要最新 `frontend/dist`（依赖缺失时先 `npm ci`，然后 `npm run build`）；CI browser job 先构建再跑
- 普通 UI story/修复跑受影响定向用例；无变化不重复全量，完整门禁按根 AGENTS/当前 PRD 收尾执行

## 写新浏览器测试的关键模式

- 测试夹具在 `tests/browser/conftest.py`：`page`、`base_url`、`app`（Flask test server）等
- **SPA 测试走当前 `/app/*` 路由**（`/app/add`、`/app/plans`、`/app/tracking`、`/app/settings`）；
  `/app/workbench`、`/app/requests`、`/app/queue` 仅验证安全兼容重定向；
  入口 `/index`、`/settings` 默认重定向到 SPA（旧页面已删，没有 legacy 回退）
- **mock 外部依赖**：`page.route("**/api/v1/mikan/candidates", handler)` 拦截候选搜索等外部请求；handler 里对非 POST 请求要 `route.continue_()` 放行到真实 Flask 后端，只接管需要 mock 的 POST
- **共享 envelope**：mock 遵循真实 API DTO/serializer；候选搜索包含 status/parse_result/attempted_queries 等字段，
  FOUND/EMPTY/FAILED 不能只看 HTTP 200。candidate 仅使用契约允许的公开元数据
- **loading/超时验证**：用 held route 先保留请求，断言后 fulfill；不在同步 handler 中 sleep。
  较窄 route 后注册，避免宽通配吞掉目标请求；改行为时同步检查同页面既有 Vitest/浏览器断言
- **严格定位器**：Seeds 区有两个 `.seed-details`（完整种子/排除种子），必须用 `.complete-seed-details` / `.excluded-seed-details` / `.effective-seed-group` / `.subgroup-seed-group` 限定；`button:has-text('确认')` 会误匹配列表项按钮，意图是"动作按钮消失"时限定到 `#request-detail-container .detail-actions`
- **折叠 `<details>`**：`inner_text()` 只含 summary；要断言内部种子标题/`无种子标题。`，先 `page.evaluate("el => el.open = true")` 展开
- **敏感值回归**：参照 `tests/browser/test_app_*.py` 的敏感边界模式——把 token/cookie/endpoint/raw_html/raw_rss_xml/raw_response_body/magnet 注入 mock 响应，跑完流程后断言 URL、`localStorage`、`sessionStorage`、可见 body 文本、保存的 Request JSON、`history/` 文件全部干净
- **tab 顺序/可访问性**：参考 `test_app_responsive_a11y.py`；主面板前置表单会推后表单控件的 tab 次序，必要时提高 Tab 按键上限

## 手动验证替代路径（无 Playwright 或需要人工确认时）

```bash
uv run flask --app wsgi:app run    # 默认 http://127.0.0.1:5000
```

- `/` 与 `/index` 重定向到 `/app/add`；`/settings` 重定向到 `/app/settings`（旧页面已删）
- 用 curl 检查 HTML/API 可达性：`curl -s http://127.0.0.1:5000/app/add`；这不证明 Vue 交互正确
- 手动清单取当前执行 PRD/目标页面交互规格，验证键盘/焦点、加载/空/错误、确认分流和敏感边界。
  记录实际方法、结果和环境缺口；没有真实 Chromium 证据不能把手动说明或 curl 当作 UI 自动门禁通过

## 安全边界（验证时同样适用）

- 不向任何输出（日志、trace、截图、保存文件）写入 token、完整 endpoint URL、cookie、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径
- 真实外部调用（MiKan 搜索/详情、Auto Bangumi 提交、qBittorrent 连接测试）一律用 `page.route` mock 或显式 request-scoped 配置，测试默认不访问真实外部服务
