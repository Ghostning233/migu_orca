---
name: dev-browser
description: "在 MiGuOrca 项目中执行浏览器验证。项目没有 MCP 浏览器工具；通过 Playwright 浏览器测试套件（tests/browser/）在真实 Chromium 上验证 Web UI 变更，并说明手动启动 Flask 后的替代验证方式。Use when a user story requires browser verification or a Web UI change needs verification."
user-invocable: true
---

# dev-browser：MiGuOrca 浏览器验证

本项目的 Web UI 是 Flask 服务端渲染 + 原生 JS（无前端构建链）。浏览器验证的标准路径是**项目的 Playwright 测试套件**（真实 Chromium 跑 Flask test server）；本地无 MCP 浏览器工具时不要尝试截图驱动，直接写/跑浏览器测试。

## 主验证路径：Playwright 套件

```bash
uv run pytest tests/browser/ -q        # 全部浏览器测试
uv run pytest tests/browser/test_xxx.py::TestYyy::test_zzz -q   # 单个测试
```

前置条件：

- Chromium 可用（必要时先跑 `script/setup-browser-deps.sh`；`bin/chromium-wrapper.sh` 是包装脚本）
- **仓库根 `.migu_orca/storage` 必须不存在**——陈旧 saved Request 会挂掉 `test_empty_list_state`、`test_no_default_storage_pollution`、`test_list_count_shows_zero` 等测试（目录被 gitignore，可直接删除）

## 写新浏览器测试的关键模式

- 测试夹具在 `tests/browser/conftest.py`：`page`、`base_url`、`app`（Flask test server）等
- **驱动 fixture 生成表单**：表单藏在默认收起的 `<details id="dev-fixture-disclosure">`，先调用 conftest 里的幂等 helper `open_dev_fixture_panel(page)`（`page.goto("/index")` 之后、填 `input[name="title"]` 之前）；断言默认收起/普通路径的测试则绝不能打开它
- **mock 外部依赖**：`page.route("**/api/v1/mikan/candidates", handler)` 拦截候选搜索等外部请求；handler 里对非 POST 请求要 `route.continue_()` 放行到真实 Flask 后端，只接管需要 mock 的 POST
- **共享 envelope**：候选搜索 mock 返回 `{"ok": true, "result": {"query", "candidates"}}`；每个 candidate 只含公开元数据（bangumi_id、title、mikan_url、poster_url、source_query、aliases）
- **严格定位器**：Seeds 区有两个 `.seed-details`（完整种子/排除种子），必须用 `.complete-seed-details` / `.excluded-seed-details` / `.effective-seed-group` / `.subgroup-seed-group` 限定；`button:has-text('确认')` 会误匹配列表项按钮，意图是"动作按钮消失"时限定到 `#request-detail-container .detail-actions`
- **折叠 `<details>`**：`inner_text()` 只含 summary；要断言内部种子标题/`无种子标题。`，先 `page.evaluate("el => el.open = true")` 展开
- **敏感值回归**：参照 `tests/browser/test_ui_quality.py` 的 Stage 14/15/18 模式——把 token/cookie/endpoint/raw_html/raw_rss_xml/raw_response_body/magnet 注入 mock 响应，跑完流程后断言 URL、`localStorage`、`sessionStorage`、可见 body 文本、保存的 Request JSON、`history/` 文件全部干净
- **tab 顺序/可访问性**：参考 `test_a11y.py`；主面板前置表单会推后 `input[name="title"]` 的 tab 次序，必要时提高 Tab 按键上限

## 手动验证替代路径（无 Playwright 或需要人工确认时）

```bash
uv run flask --app wsgi:app run    # 默认 http://127.0.0.1:5000
```

- `/` 重定向到 `/index`；`/settings` 是配置页
- 用 curl 检查关键页面 HTML 与 API：`curl -s http://127.0.0.1:5000/index`
- 手动验收清单见 README「本地验收」；完成后补一条手动验证记录到 Ralph progress.txt（注明无法截图时用 Playwright 套件覆盖）

## 安全边界（验证时同样适用）

- 不向任何输出（日志、trace、截图、保存文件）写入 token、完整 endpoint URL、cookie、原始 HTML、原始 RSS XML、原始响应体或本地绝对路径
- 真实外部调用（MiKan 搜索/详情、Auto Bangumi 提交、qBittorrent 连接测试）一律用 `page.route` mock 或显式 request-scoped 配置，测试默认不访问真实外部服务
