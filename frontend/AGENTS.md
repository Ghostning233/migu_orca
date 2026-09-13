# 前端 Agent 规范

遵循根 [AGENTS.md](../AGENTS.md)；本文件只补充前端稳定约束，不记录 Stage 进度。

## 工程与改动入口

- Vue 3 + TypeScript strict + Vite/Pinia，依赖走 npm，唯一 lockfile 为 `package-lock.json`。
- `src/app/router/catalog.ts` 是导航/公开 query 的共享入口，使用 `routeLocation`；
  Router history 和 Vite base 都是 `/app/`，RouterLink 不重复拼 `/app/` 前缀。
- 四页面入口：`WorkbenchView`（add）、`RequestsView`（plans）、`TrackingView`（tracking）、
  `SettingsView`（settings）。旧路由仅重定向；`QueueView/queueWorkbench` 保留供回退，
  不重新导入默认运行时，也不擅自删后端兼容端点。
- 共享审核复用 `CandidateCollectionList`、`AnimeDraftEditor`、`useDraftSession` 和旅程 composable。
  批量采用左卡右详情，不重新造候选浮层或另一套筛选/保存流程。
- 设计基线见 `src/styles/` 和 `docs/design/frontend-ux-design-tokens-v1.md`；
  先读目标页面视觉/交互规格，不把 mock-only 页面当作真实业务交付。

## 契约、状态与安全

- 响应类型来自 `src/api/generated/api.ts`，由 `docs/api/openapi.json` 生成并入库。
  不手写第二套 DTO、不绕过生成联合；接口变化需同步生成并检查漂移。
- feature 使用 `api`/`trackedApi`，不直接 fetch 或手拼 API URL；全局普通请求仍是短预算，
  MiKan 长任务复用 `features/workbench/mikanFeedback.ts` 的预算/固定反馈，不随意加全局超时。
- HTTP 成功与业务成功分开：候选 FOUND/EMPTY/FAILED、批量部分成功、管理 management_status
  都按契约处理。不要把本地内部错误说成 MiKan 故障，也不直接显示错误原文。
- 草案以服务端 `draft_id + base_revision` 修改；正式保存复用 save-confirm，
  不恢复 preview-save → accept 旧链。未保存会话只放内存，保存与外部提交分开确认。
- 详情/全部信息复用安全摘要与真实 safe-info，不显示 raw snapshot、URL 或未知自由文本。
- Tracking 外部写由页面统一持有临时凭据和意图；不把 `ab_config` 传给检查器或写持久 store。
  动作由 `available_actions + target_scopes + capability` 交集投影，未知动作/范围不发请求。
- 写结果先用服务端 tracking 收敛，再只读回查；不要用改变 `:key` 重挂载来刷新详情，
  以免丢失结果面板。列表请求代际与写结果代际要分开，旧列表不能覆盖新写结果。
- 结果未知时保留同一意图的原 key/revision/body，不能用回查后的新 revision 改写重放绑定；
  409 先回查并重新确认，结构化确定拒绝不当作未知，管理成功仅看 SUCCEEDED。
- AUTO/人工恢复是本地操作；只有 VERIFY_EXTERNAL 恢复分支携带 AB 临时配置，且只读。
  本地复核不因未连接 AB 而禁用。外部删除单条、显式 danger 确认、无 file 请求字段。
- 对话框复用 ConfirmDialog；焦点 trap 锚点在 Teleport 根，退出恢复焦点。
  CheckboxRow 的 id 只落到原生 input。状态需中文文本/aria-live，不仅用颜色表达。
- 长请求加函数入口防重和正确 disabled 状态；不要仅依赖按钮防重或让跨入口响应互相覆盖。

## 验证

在 `frontend/`：`npm run typecheck`、`npm run lint`，Vitest 指定受影响文件。
契约变化跑 `npm run api:generate`/`npm run api:check`；浏览器前运行 `npm run build`。
UI 使用 `dev-browser` skill 的真实 Chromium 定向用例；完整门禁仅按根规范/当前 PRD 收尾运行。
修改文案或控件状态时搜索同页面 Vitest、`tests/browser/test_app_*.py` 的旧断言并同步，
不通过删测试、放宽敏感检查或恢复错误产品行为来“修绿”。

Playwright 延迟验证使用 held route（先存 route，断言后 fulfill），不在 handler 中 sleep。
较窄定位器后注册，避免宽通配吞掉写端点；响应必须是真实 envelope。
确认键盘/焦点、桌面目标视口和 canary（DOM/URL/history/storage/console），不产出敏感截图/trace。
`dist/`、`node_modules/`、sourcemap 和浏览器产物不入库。

需要追溯具体实现时，按关键词查[旧模块参考](../docs/history/frontend_AGENTS_legacy_2026-09-13.md)
并核对代码；旧参考不是指令。当前范围/遗留视觉偏差看目标 Stage PRD，不能自动扩到下一阶段。
