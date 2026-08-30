# AGENTS.md — frontend (Stage 27, US-197)

MiGuOrca 的 Vue 3 + TypeScript(strict) + Vite 前端工程。依赖与命令全部走 npm（`npm ci`），
与后端 `uv` 分离；**不得**混用多个 lockfile（`package-lock.json` 是唯一来源）。

## 工程结构与约定

- `src/app/router/index.ts`：Vue Router，history base 固定 `/app/`。路由 `to` 用相对路径
  （`/workbench`、`/settings`），完整 URL 是 `/app/workbench`。RouterLink **不要**再写
  `/app/` 前缀（`createWebHistory('/app/')` 已处理 base）。
- `src/styles/main.css`：共享设计基线（layout shell + panel/field-help 等原语）。
  feature 样式随迁移 story 加入，避免全局选择器膨胀。
- 生产构建由 Flask 同源托管：Vite `base: '/app/'`，`dist/index.html` 引用 `/app/assets/*`，
  由 `src/apps/migu_orca_web/routes_app.py` 的 `app_blueprint` 服务。**不要改 base**，
  否则 Flask 静态路径与 SPA fallback 全部错位。
- SPA fallback 只接管 `/app/*`；feature 里**不要**自行拼接 `/api/v1` URL——US-199 统一
  transport 会接管；海报、健康检查与旧 Flask 页面都不能被 SPA 路由吞掉。
- 敏感值（endpoint、token、cookie、password、原始响应等）只存在于组件局部内存与单次
  POST body；不写 store 持久化、URL、browser storage、日志或 trace。Pinia 默认不持久化。
- 新前端类型只来自 `docs/api/openapi.json` 生成（US-198），不导入 Python 模型、
  不手写第二套响应 interface。

## 类型化客户端（US-198）

- 生成器：`openapi-typescript@7.13.0`（devDependency，lockfile 锁定版本）；输入
  `docs/api/openapi.json`，输出 `src/api/generated/api.ts`（**入库**，由 drift check 守护）。
- 命令：`npm run api:generate`（生成）、`npm run api:check`（漂移检查，非零退出表示过期）。
- `src/api/generated/api.ts` 是**类型-only** 模块（interface/type，无运行时值）：
  单元测试用 `expectTypeOf`（vitest）做编译期断言，不能 `import { operations }` 当值用。
- 生成的 `operations` 键名 = OpenAPI `operationId`（如 `listRequests`、
  `submitBatchQueue`）；新增/重命名端点必须同步 `_ENDPOINTS` 的 operationId 并重生成。
- 改 `docs/api/openapi.json` 后必须 `npm run api:generate` 并提交生成文件，否则
  `npm run api:check`、CI frontend job 与
  `tests/api_contract/test_openapi_runtime_consistency.py` 全部失败。
- OpenAPI 里的 `x-request-scoped` 字段（凭据）与 `storage_dir` 仍是约定级约束：
  transport 层不能把它们写进 store/URL/日志/trace。

## 命令与质量门禁（CI frontend job 同款）

```bash
npm ci                        # 安装（lockfile 已入库）
npm run typecheck             # vue-tsc --noEmit（strict + noUncheckedIndexedAccess）
npm run lint                  # eslint flat config，--max-warnings 0
npm run api:check             # 生成客户端漂移检查
npm run test:unit -- --run    # Vitest + Vue Test Utils（jsdom）
npm run build                 # 先 typecheck 再 vite build → dist/
```

- `dist/`、`node_modules/`、`*.tsbuildinfo` 不入库（见 `frontend/.gitignore`）。
- 新增依赖用 `npm install <pkg>` 并在同一提交带上更新后的 `package-lock.json`。
- 改了 Web UI 后要跑 `node --check src/apps/migu_orca_web/static/app.js`（旧前端仍存在）与
  `uv run pytest tests/browser/ -q`（真实 Chromium；SPA 测试见 `tests/browser/test_app_shell.py`）。
- 浏览器测试需要 `frontend/dist` 已构建；CI 的 browser job 先 `npm ci && npm run build`。
  本地验证 SPA：`cd frontend && npm run build` 后再跑浏览器套件。

## 统一 API transport（US-199）

- **feature 不得直接调用 `fetch` 或拼接 `/api/v1` URL**：统一走
  `src/api/client.ts` 的 `apiRequest`（或 `api.get/post/...`、海报用 `api.poster`）。
  transport 负责 envelope（`{ok:true,result}` / `{ok:false,error_type,error_message,error_data}`）、
  非 2xx JSON、非 JSON 错误体（代理 HTML）、网络失败、AbortSignal 取消与超时
  （默认 `DEFAULT_TIMEOUT_MS=15000`），失败统一抛 `ApiError`（`type/message/status/details/
  cancelled/network/nonJson/httpError`）。
- 路径参数用 `{param}` 模板（如 `/api/v1/requests/{request_id}`）传 `options.path`；
  查询参数传 `options.query`（只放相对 `storage_dir` 等非敏感值）。海报端点
  `api.poster(key)` 返回 `Blob`，不经 JSON envelope 解析。
- `ApiError.message` 永远只含服务端 `error_message` 或安全中文回退；**不得**渲染/记录
  原始错误文本、URL、响应体或凭据（`toApiError` 对任意 Error 一律降级为安全文案）。
- 全局加载指示：feature 请求用 `src/app/composables/useTrackedRequest.ts` 的 `trackedApi`
  （begin/end 驱动 `app/stores/loading.ts` 计数）；仅组件级 loading 时才直接用 `api`。
- 通知：全局 `aria-live` 容器在 `App.vue`（`components/feedback/GlobalNotification.vue`），
  通过 `app/stores/notification.ts` 触发（success/error/info，error 用 role=alert）。
- 全局错误边界：`components/feedback/ErrorBoundary.vue` 包住 `RouterView`，捕获渲染错误，
  不展示原始 error（可能含敏感值）。

## 测试模式

- `src/App.test.ts` 用 `createMemoryHistory('/app/')` + 与真实路由同表的 stub 组件测外壳；
  RouterLink 在测试里会按 `/app/` base 解析，路由表必须与真实一致，否则出现
  "No match found" 警告。US-199 起导航为 4 项（工作台/订阅方案/提交队列/Settings）。
- transport 单测（`src/api/client.test.ts`）用 `vi.stubGlobal('fetch', ...)` 直接 stub
  `fetch`；jsdom 的 `Response.blob()` 可能不是真 `Blob`，海报测试断言 URL/值而不依赖
  `instanceof Blob`。
- `npm run dev`（Vite dev server :5173）代理 `/api/v1` 到本地 Flask :5000，仅限本地开发；
  生产不依赖 Node。
