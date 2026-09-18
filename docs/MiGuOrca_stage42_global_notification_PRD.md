# MiGuOrca Stage 42 PRD：悬浮全局提示收尾

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 状态 | **已完成并经 PR #70 合并至 `main`（merge `cb45b245e774e05121b109b8c47229ae615164dc`）；三项 CI 全绿。** |
| 决策日期 | 2026-09-18 |
| 基线 | `origin/main`：`ab333cf612a6a4c56c39db8ee97a4245430bddf0`（Stage 41 PR #69 已合并） |
| 工作包 | WP-42-A / US-346，F5 悬浮全局提示收尾 |
| 依赖 | Stage 41 已完成；既有字段、候选、草案和批量就地反馈已稳定 |
| 允许落点 | `frontend/src/app/stores/notification.ts`、`frontend/src/components/feedback/GlobalNotification.vue`、`frontend/src/App.vue`、受影响 Vitest 与 `tests/browser/` |
| 禁止落点 | API/OpenAPI/generated client/后端、请求/草案契约、追番管理/设置业务、外部写、数据库、worker、移动端 |

本 PRD 把 [Stage 40～42 添加番剧可靠性与体验改版](MiGuOrca_stage40_add_anime_reliability_and_ux_PRD.md)
的 WP-42-A 变成可执行的单一前端工作包。它只处理短时、非关键的全局反馈；关键操作结果与
恢复路径仍由原页面就地表达。

## 2. 现状与问题

当前 `useNotificationStore` 只持有一个内存中的 `current` 消息，`GlobalNotification` 在 App 的
`main` 流中渲染，因此通知会占据页面空间、推动正文。它已有中文文案、单一 store 和 `aria-live`
边界，但没有按 kind 自动关闭、替换 timer 隔离或组件卸载清理规则。

| 现状 | Stage 42 决策 |
| --- | --- |
| success/info/error 共用单一 `current` | 继续复用，禁止增加第二个 store 或并行 Toast 通道 |
| 提示在文档流内 | 变为固定悬浮层，不挤压正文 |
| 无生命周期 | success/info 10 秒；error 20 秒；手动关闭立即清理 |
| 页面有字段/候选/草案/批量错误与重试 | 一律保留在原位置，Toast 仅作全局摘要 |
| 当前没有独立 loading notification API | 先核对真实调用需求；只有确实存在短时全局进行中提示时才在同一 store 内增加可终结的 kind，不能用它替代页面 loading 或伪进度 |

## 3. 工作包 WP-42-A / US-346

### 目标

将非关键的成功、信息与全局错误摘要收敛为不会推动页面布局的悬浮 Toast，并让替换、自动关闭、
手动关闭与卸载的生命周期可测试、可恢复且不抢焦点。

### 非目标

- 不移走字段校验、候选生成失败、草案重算失败、零资源阻断、批量条目失败、部分成功明细、
  save-confirm 结果未知或外部写确认；它们仍须有就地文案和恢复入口。
- 不修改通知调用处的业务成功判定，不把 HTTP 200 当作业务成功，不批量改写既有页面文案。
- 不新增通知持久化、队列/历史、跨标签页同步、后端推送、worker、实时百分比、声音或移动布局。
- 不改变 API、OpenAPI、generated client、敏感信息脱敏、draft_id + revision、保存确认、
  Auto Bangumi 外部写和 MiKan 人工选择边界。

### 状态矩阵

| 事件 | 可见结果 | 生命周期 | 必须保留的就地反馈 |
| --- | --- | --- | --- |
| 非关键 success/info | 固定悬浮、`role=status`、`aria-live=polite` | 10 秒或手动关闭 | 无需复制为页面错误 |
| 全局 error 摘要 | 固定悬浮、`role=alert`、`aria-live=assertive` | 20 秒或手动关闭 | 对应字段/候选/条目错误与重试 |
| 新消息替换旧消息 | 只显示新消息 | 旧 timer 不得清掉新 id | 原页面状态不被重置 |
| 显式关闭 | 立即移除当前消息 | timer 清理 | 不改页面操作结果 |
| 页面卸载/离开 | 不留 orphan timer 或旧消息 | 生命周期按 id 清理 | 页面自己的 loading/恢复语义不被 Toast 接管 |
| 进行中短时提示（若经调用点证明需要） | 同一悬浮通道的非伪进度文案 | 对应成功、失败、失效或离开即结束 | 原位置 loading/disabled/失败原因 |

### 可观察验收条件

1. `useNotificationStore` 是唯一消息来源；每条消息有唯一 id。success/info 自动关闭为 10 秒，
   error 为 20 秒，手动关闭立即清理；未定义 kind 不能静默取得不安全默认时长。
2. 新消息替换旧消息时，旧 timer 以捕获的消息 id 检查当前消息，只能清理自身；连续替换、
   clear、组件卸载不留旧 timer 或清掉后来的消息。
3. `GlobalNotification` 使用固定定位的悬浮层且不参加 `main` 正文布局。它在 1280、1440、
   1920 宽桌面下不造成横向滚动、不遮挡主要确认操作；卡片自身仍允许鼠标点击关闭。
4. success/info 维持 `status` + polite，error 维持 `alert` + assertive，所有消息 `aria-atomic=true`；
   关闭按钮具备中文名称、键盘可达，Toast 出现/替换/消失不主动移动焦点。
5. 关键反馈仍就地存在：至少对字段校验、候选/草案失败与重试、保存确认阻断或批量部分成功选取
   现有用例回归，证明关闭/超时 Toast 后页面仍可恢复，不能只依赖短时文案。
6. Toast 不进入浏览器存储、URL 或 history；不显示 URL、RSS、magnet、绝对路径、Cookie、
   凭据、原始响应、草案能力或完整 Request。继续只接收调用方经既有边界脱敏后的中文文本。
7. 若开发发现生命周期需求必须改变页面操作语义、需要持久队列/新后端事件，或固定浮层在目标
   桌面宽度必然遮住唯一确认操作，停止并报告；不得以延长 timeout、覆盖 CSS 或移除就地反馈规避。

## 4. AC—代码—测试矩阵

| AC | 预计代码 | 最小自动化证据 | Chromium 证据 |
| --- | --- | --- | --- |
| 10/20 秒、替换 id、clear/unmount | notification store 与 store test | Vitest fake timers：到期、手动关闭、A→B 替换后 A timer 无效、卸载 | 不依赖真实等待 |
| 固定悬浮和无位移 | GlobalNotification/App 样式与组件 test | class/style/role/关闭断言 | route mock 操作触发 Toast，比对 main 尺寸/主要操作位置/横向 overflow |
| a11y 与不抢焦点 | GlobalNotification/App test | role、aria-live、aria-atomic、button label | Tab/Enter 关闭，出现与自动消失前后焦点不跳转 |
| 关键反馈留在原地 | 只更新必要旧断言 | 现有 Workbench/Batch/App tests | 候选或批量失败 route mock，Toast 关闭后就地错误/重试仍在 |
| 脱敏与无持久化 | store/component/browser canary | 文本 sanitizer 既有边界回归 | DOM/URL/history/localStorage/sessionStorage/console canary |

## 5. 验证与审核

开发期间只运行受影响 Vitest、`npm run typecheck`、`npm run lint`、`npm run build` 与项目
`dev-browser` skill 的定向真实 Chromium。浏览器必须 route mock 外部系统、使用隔离 tmp storage、
不生成含敏感值的 screenshot/trace，timer 用 fake timers 或受控时钟，不用 sleep 伪造通过。

Stage 收尾由主 Agent 独立执行一次完整门禁：后端非浏览器测试与 Ruff/OpenAPI 检查、前端
api/typecheck/lint/unit/build、完整 Chromium 和 `git diff --check`。审核重点为 timer id 隔离、
fixed 布局、焦点、关键反馈不被移走、敏感边界与测试真实性。

## 6. 工作流与停止条件

一个原子工作包包含 US-346 的开发、定向验证、独立审核、最小红测、同一修复 Agent 收口与复审。
开发 Agent 不得提交或发布；C Agent 只在用户另行授权且已审核 HEAD 时处理提交、PR 与合并。
本 PRD 创建后不自动启动开发，也不自动进入任何后续阶段。

## 7. 完成记录

US-346 于 2026-09-17 通过 PR #70 合并。CI 的静态/非浏览器测试、前端 typecheck/lint/unit/build
与真实 Chromium browser suite 均成功。实现没有引入 API、OpenAPI、生成客户端、后端或外部写变更；
未发现 Stage 42 范围内的遗留阻断问题。
