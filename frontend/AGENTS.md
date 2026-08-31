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
- US-208/209 起 `/index`、`/settings` 入口路由重定向到 `/app/workbench`、`/app/settings`
  （Flask `views.py` 入口路由，保留 `request_id`/`batch_id` query；旧 Jinja 页面与
  `web_entry_mode()` 已在 US-209 删除）。SPA 各 feature 已从 URL query 读
  `request_id`/`batch_id`（RequestsView/QueueView/BatchWorkbenchView），旧书签直接可用；
  **不要**再往 URL 拼 `/index` 或 `/settings`。
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
- 改了 Web UI 后要跑 `uv run pytest tests/browser/ -q`（真实 Chromium；SPA 测试见
  `tests/browser/test_app_shell.py`）。旧 `static/app.js` 已在 US-209 删除，
  不再需要 `node --check`。
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

## 共享组件原语（US-200）

- 布局：`components/layout/PanelSection.vue`（标题面板 + actions slot）、
  `components/layout/FormField.vue`（label + 可选 help + required 指示；用 `inputId`
  指定 label 的 `for`，注意不能用 `for` 作为 prop 名——Vue 模板里是保留字，eslint
  vue/no-parsing-error 会报错）。
- 表单控件：`components/forms/BaseButton.vue`（variant: primary/secondary/danger，
  `loading` 显示「处理中…」并禁用）、`BaseInput.vue` / `BaseTextarea.vue`（v-model +
  `aria-label`/`aria-invalid` + `$attrs` 透传）、`BaseSelect.vue`（options 支持
  `string | {value,label}`，显示中文 label、value 只作内部码）、`CheckboxRow.vue`
  （label + 原生 checkbox，id 用 `useId()` 生成唯一值；支持 `v-model:checked`）。
- CheckboxRow 是带包装 div 的组件：必须 `defineOptions({ inheritAttrs: false })` 并手动把
  `id`/`name` 等 attrs 转发到原生 input，否则 `id` 同时落在包装 div 和 input 上
  （Playwright strict mode 报 2 元素，且 `label for` 指向重复 id 无效）。`v-model:checked`
  需要显式 `checked` prop + `update:checked` emit（原生 checkbox 的 change 不会自动触发）。
- 连接测试/提交类表单（qB/AB）失败时只显示**固定中文反馈**，绝不把服务端
  `error_message` 拼进 UI——服务端原始错误可能含 endpoint/凭据（与旧 app.js 行为一致）。
- 偏好保存失败要回退到「上次成功加载/保存的值」并清空被拒绝的敏感输入，而不是保留表单
  当前值（legacy `renderPreferenceSettings(currentPreferenceValues)` 行为）。
- 确认对话框：`components/feedback/ConfirmDialog.vue` 是 `window.confirm` 的可访问替代
  （`role="alertdialog"` + `aria-modal` + focus trap + inert 背景 + Escape/backdrop 取消 +
  关闭后焦点恢复到触发元素）。**用 ref + `confirm({title,message,confirmLabel,cancelLabel,
  danger})` 返回 Promise<boolean>**；`danger: true` 渲染 `.danger-button`。
- 焦点陷阱：`app/composables/useFocusTrap.ts`（Tab/Shift+Tab 循环、Escape 回调、
  兄弟元素 `inert`、deactivate 时焦点恢复）。**trap 锚点要放在 Teleport 根（backdrop）上**，
  否则 `inert` 会标到对话框内部而不是 `#app`。
- 敏感凭据：`app/composables/useSensitiveFields.ts`（`field/set/reset/clearAll/snapshot/
  firstMissing/get`）。字段只存在组件局部 reactive 内存，**切换认证模式/成功/取消/卸载时
  必须 `reset()`/`clearAll()`**；`snapshot()` 只返回非空值用于单次 POST body；
  `onUnmounted` 用 `getCurrentInstance()` 守卫（无组件实例时不注册，便于纯单测）。
- 状态反馈：`components/feedback/StatusAlert.vue`（success/info/empty → `role=status`
  polite，error → `role=alert` assertive；状态不只靠颜色表达）。
- US-209 已删除 `/app/components-demo` 原语演示路由与
  `tests/browser/test_components_primitives.py`（迁移脚手架）；共享组件原语本身
  继续由各 feature 的 Vitest/浏览器套件覆盖。

## 测试模式

- `src/App.test.ts` 用 `createMemoryHistory('/app/')` + 与真实路由同表的 stub 组件测外壳；
  RouterLink 在测试里会按 `/app/` base 解析，路由表必须与真实一致，否则出现
  "No match found" 警告。US-199 起导航为 4 项（工作台/订阅方案/提交队列/Settings）。
- transport 单测（`src/api/client.test.ts`）用 `vi.stubGlobal('fetch', ...)` 直接 stub
  `fetch`；jsdom 的 `Response.blob()` 可能不是真 `Blob`，海报测试断言 URL/值而不依赖
  `instanceof Blob`。
- `npm run dev`（Vite dev server :5173）代理 `/api/v1` 到本地 Flask :5000，仅限本地开发；
  生产不依赖 Node。

## Request 列表（US-202）

- 列表逻辑在 `features/requests/requestsList.ts`（纯函数：`requestLabel`/`searchableText`/
  `filterRequests`/`sortRequests`/`availableStatuses`/`statusLabel`），与旧 `app.js`
  `filteredAndSortedRequests` 语义一致；feature 与测试复用同一份，不复制第二套。
- 状态码内部值（`PENDING_CONFIRM`/`ACCEPTED`/`CANCELLED`）只作 option value 与内部比较，
  用户可见文案走 `statusLabel`（待确认/已确认/已取消）；未知状态按原样渲染（不回退为
  「未设置」，避免掩盖服务端新状态）。
- 列表加载用 `api.get<ListResult>('/api/v1/requests', { query })`，`query.storage_dir` 只放
  localStorage 里的**相对 profile**（`sanitizeStorageProfile` 已挡绝对路径/穿越）；
  `result.requests ?? []` 兜底空数组，避免 200 无字段时崩溃。
- 选择状态由 URL query `request_id` 驱动（`router.push({ path, query })`），刷新恢复；
  清空/点空项用 `router.push({ path: '/requests' })` 去掉 query。`request_id` 是公开已保存
  标识符，可进 URL；凭据/endpoint 永远不进 URL。
- 浏览器测试：`tests/browser/test_app_requests.py`（SPA `/app/requests`），fixture 用
  conftest `create_saved_request` 预置 + `set_storage_preferences` 设相对 profile；错误态
  用 `page.route("**/api/v1/requests**")` mock 500 后断言脱敏文案（error_type/error_data
  不得进 DOM）。断言列表项用 `.request-list-item`（含 `data-request-id`）、状态用
  `.request-list-item.is-selected`，不要用裸 `[data-request-id]`（详情页动作也用同属性）。

## Request 详情与管理动作（US-203）

- 详情面板在 `features/requests/RequestDetailPanel.vue`（挂载于 `/app/requests` 列表下方，
  选中项即渲染；`RequestDetailPanel` 用 `:key="selectedRequestId"` 保证切换请求时重挂载）。
- 纯展示逻辑收敛到 `features/requests/requestDetail.ts`（`displayValue`/`actionLabel`/
  `selectedRssSource`/`effectiveSeeds`/`excludedSeeds`/`completeSeedGroups`/
  `totalCompleteSeedCount`/`scrubConfig`，与旧 `app.js` `renderDetailPayload` parity）；
  `displayValue` 会把 URL 样式字符串脱敏成 `[redacted_url]`，原始 `rss_url`/`mikan_url`/
  `poster_url` 永远不渲染（RSS 来源只显示已选择/未选择）。
- 详情加载走 `api.get('/api/v1/requests/{request_id}', { path, query })`；相对 storage
  profile 查询参数统一从 `features/requests/requestStorage.ts` 的 `storageQuery()` 读
  （列表与详情共用，不复制第二套）。
- 管理动作按状态分派：PENDING_CONFIRM → 确认/取消/修改；ACCEPTED → 修改/删除/去
  Settings 提交 AB；CANCELLED → 只读提示。所有破坏性动作走共享 ConfirmDialog
  （`confirm()` 返回 Promise<boolean>，danger 用 `.danger-button`）。
- 动作成功后面板用服务端返回的 `request` 立即更新内存快照并重新 `loadDetail()`，列表
  `@changed` 重新加载；删除成功后 `@deleted` 清空 URL 选择并卸载面板。
- 修改表单 `modify-clear-*` checkbox 勾选时通过 watch 清空对应输入（legacy
  `appendClearControl` 行为），patch 里发显式空字符串；空 patch 前端拦截并显示
  「请至少修改或清空一个字段」。
- 动作失败只显示固定中文反馈（确认失败/取消失败/修改失败/删除失败），绝不渲染服务端
  `error_message`（可能含凭据）。详情加载失败显示 `订阅方案详情加载失败`（role=alert），
  不泄漏 `error_type`/`error_data`。
- Settings AB 面板的「返回订阅方案详情」链接指向 `/requests?request_id=...`（US-203 起
  详情在列表页而非工作台）；AB 提交成功后 `@changed` 由详情面板刷新。
- 浏览器测试：`tests/browser/test_app_request_detail.py`（23 例真实 Chromium）：分区渲染/
  URL 状态恢复/缺失 request_id 安全错误/确认/取消/删除/修改 patch/脱敏/360px/中文状态码/
  AB 入口跳转。断言详情区用 `#request-detail-container`，动作按钮用
  `#detail-accept-button` 等 id（不要裸用 `[data-request-id]`，列表项与动作共用）。

## 单个搜索与服务端草案（US-204）

- 工作台在 `features/workbench/WorkbenchView.vue`（`/app/workbench`）：单个搜索
  （`POST /api/v1/mikan/candidates`）、直连 fallback（`POST /api/v1/requests` 带
  `mikan_bangumi`）与 DraftPreviewPanel（`features/workbench/DraftPreviewPanel.vue`）。
  纯函数逻辑收敛到 `features/workbench/candidateSearch.ts`（`validateCandidateQuery`/
  `validateFallbackValue`/`candidateSelectionIsBlocked`/`needsSeasonConfirmation`/
  `parseSeasonNumber`/`parseSourceLabel`/`collectPreviewEditPatch`/`buildCandidateCreatePayload`/
  `buildFallbackCreatePayload`），feature 与 Vitest 共用，不复制第二套。
- 候选卡片（`features/workbench/CandidateCard.vue`）只渲染公开白名单字段；**绝不自动选候选**
  （即使只有一个）；NEEDS_CONFIRMATION 候选显示「我确认此合集为第N季」checkbox 勾选后才可
  选择，CONFLICT 候选显示警告并禁用（`candidateSelectionIsBlocked`）。
- `candidate_context` 与 `draft_id` 只存在于组件内存（`seasonConfirmations` ref /
  DraftPreviewPanel 的局部 ref），**永不进 URL、browser storage、history 或日志**；候选
  搜索/选择/fallback 成功后都不设置 URL query（与旧 `/index` parity）。
- 生成草案走 `POST /api/v1/requests`（`save_request: false`）→ 服务端签发 `draft_id`；
  编辑走 `preview-modify`（只发 `draft_id` + 允许 patch，绝不回传完整 Request 快照），
  保存走 `preview-save`（一次性消费，draft_expired/evicted/replayed → 固定中文
  「请重新生成订阅草案后再试」并清空面板）。
- 直连 fallback 用 CheckboxRow（`#mikan-fallback-enabled`，id 直接落在原生 input）门控；
  本地只做「数字 ID 或 HTTP(S) URL」预校验，服务端仍执行权威规则；成功后清空输入。
- 标题解析摘要（`renderTitleParseSummary` 迁移）只显示识别标题/识别季度/解析来源
  （中文 label）/实际搜索词/需人工核对；原始 `source` 代码（alias/rule 等）绝不进 DOM。
- 浏览器测试：`tests/browser/test_app_workbench.py`（18 例真实 Chromium）。mock 候选搜索
  用 `page.route("**/api/v1/mikan/candidates", ...)`；生成捕获用 conftest
  `_register_generation_capture`（注意 `**/api/v1/requests` 只匹配精确路径，preview-modify/
  preview-save 仍走真实后端）；SPA 通知断言用 `.global-notification:not(:empty)`（不是旧页的
  `#page-notification`）。
- 保存草案成功后面板 `@saved` 由工作台 `router.push('/requests?request_id=...')` 跳转到
  已保存 Request 列表/详情（US-203 面板）。

## 批量工作台（US-205）

- 批量工作台在 `features/workbench/BatchWorkbenchView.vue`（挂在 `/app/workbench` 的
  `WorkbenchView.vue` 底部，`<BatchWorkbenchView class="batch-workbench-section">`）。
  纯函数逻辑收敛到 `features/workbench/batchWorkbench.ts`（`batchStatusLabel`/
  `batchCardTitle`/`batchCardPreferenceSummary`/`batchCardSeedSummary`/
  `canExpandBatchCard`/`canAcceptBatchCard`/`collectBatchAcceptDescriptors`/
  `buildBatchAcceptPayload`/`postBatchAccept`/`batchAcceptNotification`/
  `queueStatusLabel`/`queueItemSummary` 等），feature 与 Vitest 共用，不复制第二套。
- 批量卡片复用共享组件：FOUND 卡片的候选浮层是
  `BatchCandidatePopover.vue`（内部复用 `CandidateCard`，`role="dialog"`，Escape/
  关闭后焦点回触发器）；DRAFT 卡片的详情面板是 `BatchDraftPreviewPanel.vue`（复用
  `DraftPreviewPanel` + 批量专属「接受当前批量草案 / 删除当前批量卡片」动作行）。
  **不要为批量再造第二套候选卡片或草案详情实现。**
- 批量接受统一走 `POST /api/v1/batches/{batch_id}/accept`（US-146：单卡接受与批量接受
  同端点）。「批量接受」只发选中的 reviewable 卡片并带 `item_ids`；「全接受」按 legacy
  parity 发送**所有卡片**（含 FOUND/EMPTY/FAILED，不带 `item_ids`），让服务端对不可
  接受的卡片返回中文 reason（`unacceptable`）。accept payload 只含公开字段
  （item_id/request_id/title）+ `storage_dir`（相对 profile）。
- 批量接受前若卡片仍持有未保存草案，先经 `DraftPreviewPanel.saveDraftAndReturn()` 走
  preview-save（一次性消费 draft_id）再 accept；成功后的卡片置 `status: ACCEPTED`、
  `draft_id: null`（已消费的 draft 绝不重复引用）、`queue_status` 从 accept 响应的
  queue 同步。
- `batch_id` 是公开标识符，可进 URL query（`router.replace({ path: '/workbench',
  query: { batch_id } })`）供提交队列刷新恢复；批量卡片本身服务端不持久化，刷新后
  不恢复卡片（与旧 `/index` parity）。`candidate_context`/`draft_id` 仍只在组件内存。
- 浏览器测试：`tests/browser/test_app_batch_workbench.py`（13 例真实 Chromium）。mock
  批量解析用 `page.route("**/api/v1/batches/parse", ...)`；卡片 draft 用 conftest
  `issue_draft_id(preview)` 签发真实 draft_id 让 preview-modify/save 走真实后端；
  accept 用 `_accept_route_handler(accepted_ids)`。ConfirmDialog Teleport 到 body，
  断言用全局 `.confirm-dialog .primary-button`（不要限定到 toolbar）。
- CheckboxRow 在批量卡片里用 `class="batch-card-checkbox-row"`（inheritAttrs 会把
  class 落到原生 input 上），浏览器测试直接 `.batch-card-checkbox-row` 即可，
  不要写成 `.batch-card-checkbox-row input`；全选用 `#batch-select-all-checkbox`。

## 提交队列（US-206）

- 提交队列在 `features/queue/QueueView.vue`（`/app/queue`）。纯函数逻辑收敛到
  `features/queue/queueWorkbench.ts`（`queueStatusLabel`/`queueStatusClass`/
  `queueItemSummary`/`queueItemCanRetry`/`queueItemCanRecover`/`buildAbConfig`/
  `validateAbConfig`/`batchSubmitSummaryMessage`/`batchSubmitNotification`/
  `recoverOutcomeNeedsManual` + transport wrappers），feature 与 Vitest 共用，
  不复制第二套（legacy `batchQueueStatusLabel`/`buildAbConfig` parity）。
- `batch_id` 是公开标识符，从 URL query 读取（`/app/queue?batch_id=...`）驱动队列
  加载与刷新恢复；批量工作台（US-205）解析后把 `batch_id` 推入 URL，因此从批量
  接受 → 提交队列是同一条链路。无 `batch_id` 时显示空状态并禁用刷新。
- 队列项按状态分派动作：`FAILED`/`RETRYABLE` → 单项「重试」
  （`POST /api/v1/batches/{batch_id}/retry`，带 `request_id`）；`SUBMITTING`/
  `RESULT_PERSIST_FAILED` → 「恢复」（`POST .../recover`：先 `action=auto`，服务端
  返回 `needs_manual` 时用共享 ConfirmDialog 让用户人工核验，确认=已创建订阅→
  `succeeded`，取消=未创建→`failed`，均带 `confirm: true`）。已成功项绝不重复提交。
- 提交/重试/恢复共用**同一个** Auto Bangumi 凭据表单（auth mode + endpoint +
  password/token + fallback + 显式 confirm 勾选）：凭据走 `useSensitiveFields`
  （组件内存），`queuePayload()` 在单次 POST body 里构造 `ab_config`；成功后
  `ab.clearAll()` + `abConfirm=false`，切换认证模式 `ab.reset()`，卸载自动清空。
- 失败语义（legacy parity）：HTTP 级失败**保留敏感输入与确认勾选**便于重试，只显示
  固定中文反馈（绝不渲染服务端 `error_message`/`error_type`）；队列读取失败显示
  脱敏错误态 + 重试。
- 浏览器测试：`tests/browser/test_app_queue.py`（真实 Chromium）。mock 队列读取用
  `page.route("**/api/v1/batches/{batch_id}/queue*", ...)`（注意 `*` 通配 storage_dir
  query）；in-flight 用 conftest 的 `test-slow-submit`/`test-slow-retry` 延迟路由
  （不 mock，真实返回 400）；SPA 通知断言用 `.global-notification:not(:empty)`。

## 跨功能收敛（US-207）

- 键盘可达性：App.vue 有 `#skip-link`（`.skip-link`）——Tab 首个聚焦目标，
  href=`#app-main`，聚焦时才可见（main.css）；`main#app-main` 带 `tabindex="-1"`
  是 skip 的焦点落点。新增 feature 路由不要移除 main landmark。
- 批量候选浮层 `BatchCandidatePopover.vue`（US-207）：打开时焦点移入 dialog
  （close 按钮），Escape 关闭，父组件（BatchWorkbenchView）在关闭时**同步**把
  焦点恢复到触发按钮（`candidateTrigger` 在 open 时捕获 `$event.currentTarget`
  或 `document.activeElement`；不要在 `requestAnimationFrame` 里恢复——popover
  卸载会先把焦点丢到 body）。
- 响应式：`top-nav` 是 `flex-wrap`（360px 下 4 个导航链接换行不溢出）；所有 feature
  路由 360/768/1280 无横向溢出由 `tests/browser/test_app_responsive_a11y.py` 守护
  （`body.scrollWidth <= innerWidth`）。
- 状态不只靠颜色：status chip 必须带中文文本 label（如 `提交成功`）+ 状态 class，
  不能只改背景色。
- reduced-motion：LoadingState/BaseButton spinner 在 `prefers-reduced-motion:
  reduce` 下停动画但文本与 `aria-busy`/disabled 保留。浏览器测试用 conftest 的
  服务端延迟路由（`test-slow-queue` 等）观察 loading——`time.sleep` 不能写在
  `page.route` handler 里（会阻塞 Playwright 分发线程，loading 永远不可见）。
- production build：vite.config.ts 用 functional `manualChunks` 把 `node_modules`
  打进 `vendor-*.js`（不要用 object 形式，会把全部依赖并成一个 chunk 破坏懒加载）；
  `sourcemap: false` 且 dist 永不提交 `.map`（`*.map` 已 gitignore）。
- Flask 静态缓存：`/app/assets/*` 返回 `public, max-age=31536000, immutable`
  （Vite 内容哈希文件名不可变），SPA shell 与其它 `/app/*` 返回 `no-cache`
  （部署换哈希后不会 pin 旧资源）。改 `routes_app.py` 后同步
  `src/apps/migu_orca_web/app_routes_test.py` 的缓存头断言。
- 浏览器收敛测试文件：`tests/browser/test_app_responsive_a11y.py`（22 例）——
  四路由 × 三视口无横向溢出、skip link、popover 焦点、状态文本、reduced-motion、
  vendor chunk、无 sourcemap、缓存头。它**不重复**各 feature 的业务断言。
