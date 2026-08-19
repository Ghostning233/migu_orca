# MiGuOrca Stage 20 PRD: 批量接受与 Auto Bangumi 提交前队列

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 20 PRD: 批量接受与 Auto Bangumi 提交前队列 |
| 文档类型 | Stage PRD |
| 当前状态 | 已完成 |
| 创建日期 | 2026-08-19 |
| 完成日期 | 2026-08-19 |
| 依赖阶段 | Stage 19 |

## 2. 背景

Stage 19 已完成批量输入、简称解析、MiKan 候选搜索、订阅草案卡片、单卡修改和单卡接受。用户已经可以把一批季度新番整理成可审核的订阅方案，但仍需要逐张卡片确认，并逐个进入 Settings 执行 Auto Bangumi 提交。

Stage 20 把这条链路扩展为批量确认和提交前队列：用户可以选择若干审核完成的卡片，统一确认后进入队列，再在明确提供 Auto Bangumi endpoint/token 并确认提交后，逐项调用现有 `submit-ab` 能力。MiGuOrca 只负责编排、状态展示和结果记录，下载执行继续由 Auto Bangumi 与 qBittorrent 负责。

## 3. 目标

1. 支持单卡接受、批量接受和全接受，并保证只处理可接受的草案卡片。
2. 将已接受的 Request 映射到当前批次的提交前队列。
3. 展示待提交、提交中、成功、失败、可重试等队列状态。
4. 使用现有 `build_ab_subscription_payload`、Auto Bangumi client 和 `submit-ab` 结果契约，不复制提交链路。
5. 让单项提交失败不阻塞同批次其他项，并允许失败项独立重试。
6. 将脱敏后的提交结果写入现有 Request 和 AB result storage，支持刷新后查看。
7. 保持 endpoint、token、Authorization header、cookie、原始响应体等敏感值只存在于单次请求上下文。

## 4. 非目标

1. 不创建 qBittorrent 下载任务。
2. 不绕过 Auto Bangumi 建立长期订阅状态机。
3. 不实现后台常驻 worker、复杂调度器或自动轮询。
4. 不保存 endpoint、token、cookie 或完整失败 URL 到队列、Request snapshot、浏览器 storage、URL、日志、截图或 trace。
5. 不让批量接受绕过用户审核；低置信度、失败或没有可用候选的卡片不能被静默接受。
6. 不在本阶段接入真实 LLM provider 或部署向导。

## 5. 产品决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D20-01 | 接受与提交分离 | 批量接受只完成 Request 确认；Auto Bangumi 提交需要用户显式提供配置并确认。 |
| D20-02 | 队列按 Request 独立追踪 | 每个 item 有独立状态、尝试次数和结果；一个失败不改变其他 item。 |
| D20-03 | 复用现有单项提交链路 | 批量编排调用现有 payload builder、client、脱敏和 AB result repository。 |
| D20-04 | 本阶段采用前台顺序提交 | 不引入后台 worker；提交中的批次由当前请求完成，刷新后以持久化结果恢复状态。 |
| D20-05 | 失败项可重试 | 只有失败或可重试状态允许重试；成功项不会被重复提交。 |

## 6. 用户流程

```text
用户在批量工作台审核多张草案卡片
  ↓
选择若干卡片，或点击全接受
  ↓
系统逐项复用现有 accept 能力，卡片进入已接受/待提交
  ↓
用户打开提交前队列，检查本批次项目
  ↓
用户填写 Auto Bangumi endpoint、token 和 fallback 选项
  ↓
用户显式确认批量提交
  ↓
系统顺序提交每个 ACCEPTED Request
  ↓
每项展示成功、失败或可重试结果，失败项可单独重试
```

## 7. 队列数据契约

队列记录可以持久化批次和项目的非敏感元数据，但不得持久化 AB 配置：

```json
{
  "queue_id": "queue_xxx",
  "batch_id": "batch_xxx",
  "items": [
    {
      "item_id": "item_xxx",
      "request_id": "request_xxx",
      "title": "关于我转生变成史莱姆这档事 第四季",
      "status": "READY_TO_SUBMIT",
      "attempts": 0,
      "last_error": null,
      "ab_result_summary": null
    }
  ]
}
```

建议队列状态：

| 状态 | 含义 |
| --- | --- |
| READY_TO_SUBMIT | Request 已接受，等待用户显式提交 |
| SUBMITTING | 当前请求正在调用 Auto Bangumi |
| SUCCEEDED | Auto Bangumi 已返回成功且已保存脱敏结果 |
| FAILED | 本次提交失败，可按结果决定是否重试 |
| RETRYABLE | 失败且允许再次提交 |

队列只保存 `request_id`、`item_id`、公开标题、状态、计数、时间和脱敏摘要。endpoint、token、Authorization header、cookie、原始 HTTP 响应、完整 RSS URL 和 fallback 中的敏感字段必须被过滤。

## 8. API 与行为边界

1. 批量接受 API 接收 `batch_id` 和选中的 `item_id`，只接受有有效 `request_id` 且处于 `PENDING_CONFIRM` 的项目；已接受项目应幂等返回，不重复追加队列。
2. 全接受 API 或同一 API 的 `all=true` 只能接受当前批次中可接受的项目，FAILED、删除和缺少候选的项目必须保留原状态并返回逐项结果。
3. 创建/读取队列 API 只返回脱敏队列项目和结果摘要，不返回 AB 配置。
4. 批量提交 API 接收 request-scoped `ab_config` 和显式确认字段，顺序处理队列中的 `READY_TO_SUBMIT` 或明确指定的 `RETRYABLE` 项目。
5. 单项调用必须复用现有 Auto Bangumi 提交流程，并将单项成功或失败结果写入现有 Request snapshot 和 `ab_results/`。
6. 批量响应按 item 返回结果，不能因为一项失败而返回整体成功或中断其余项目。
7. 重试必须使用最新保存的 ACCEPTED Request；不允许使用队列中复制的完整 RSS、token 或原始外部响应。

## 9. UI 要求

1. 批量卡片提供单卡接受、选择后批量接受、全接受入口，并明确显示选中数量和不可接受原因。
2. 已接受卡片显示 `已接受 / 待提交`，不得误显示为已提交成功。
3. `/index` 或独立队列区域展示队列项目、标题、状态、尝试次数、脱敏结果摘要和单项重试按钮。
4. 批量提交前必须展示 endpoint/token 输入和确认动作；提交后清空敏感输入，不写入 URL 或浏览器 storage。
5. 状态文案使用中文业务词：待提交、提交中、提交成功、提交失败、可重试。
6. 提交中按钮需要禁用，单项完成后实时或请求结束后刷新对应项目，其他项目保持可见。
7. 页面不得展示 token、完整 endpoint、cookie、原始响应体、magnet、raw RSS XML 或本地绝对路径。

## 10. Ralph 执行说明

实现必须按 `scripts/ralph/prd.json` 的优先级逐个完成 user story。每个 story 都必须包含可验证的验收条件，并以 `Typecheck passes` 收尾；涉及 Web UI 的 story 还必须执行项目 Playwright 浏览器测试，并遵循 `.agents/skills/dev-browser/SKILL.md` 的验证要求。

Stage 20 完成标志：用户可以从一批 Stage 19 草案卡片中批量确认若干项目，查看提交前队列，显式配置并提交 Auto Bangumi；成功和失败项目独立展示，失败项可重试，且所有外部敏感值都没有进入持久化或展示面。

## 11. 完成状态（2026-08-19）

Stage 20 的全部 8 个 user story（US-142..US-149）已完成并通过：

| Story | 内容 | 状态 |
| --- | --- | --- |
| US-142 | 新增批量提交前队列数据契约 | 完成 |
| US-143 | 实现批量接受与全接受编排 | 完成 |
| US-144 | 实现批量 Auto Bangumi 顺序提交服务 | 完成 |
| US-145 | 新增批量队列与提交 Web API | 完成 |
| US-146 | 新增批量接受与全接受 Web UI 操作 | 完成 |
| US-147 | 新增提交前队列结果界面 | 完成 |
| US-148 | 实现失败项独立重试与安全回归 | 完成 |
| US-149 | Stage 20 文档与收尾回归 | 完成 |

### 实现要点

1. **队列契约与存储边界**：`BatchQueueItem`/`BatchSubmissionQueue` 只保存 `queue_id`、`batch_id`、`item_id`、`request_id`、公开标题、状态、尝试次数、脱敏错误和脱敏结果摘要；endpoint、token、Authorization header、cookie、原始响应体、完整 RSS URL、magnet 和本地绝对路径永远不写入队列模型、队列 JSON 或公开序列化。
2. **批量接受与全接受**：`accept_batch_items` 复用现有 Request accept 能力，只接受有有效 `request_id` 且处于 `PENDING_CONFIRM` 的项目；已接受项目幂等返回，单项失败不阻塞其他项；全接受只处理当前批次中可接受的项目，并逐项返回不可接受原因。
3. **顺序提交服务**：`submit_batch_queue_items` 使用 request-scoped `ab_config` 按队列顺序处理 `READY_TO_SUBMIT` 项目，复用 `build_ab_subscription_payload` + Auto Bangumi client + 脱敏 `ab_submit_result` 契约；提交前校验 Request 仍为 `ACCEPTED`，不满足条件标记 `FAILED`/`RETRYABLE` 并继续；单项成功标记 `SUCCEEDED`，单项失败标记 `FAILED`/`RETRYABLE` 并保留脱敏摘要；已成功项目不会被重复提交。
4. **Web API**：`POST /api/v1/batches/<batch_id>/accept`、`GET /api/v1/batches/<batch_id>/queue`、`POST /api/v1/batches/<batch_id>/submit`、`POST /api/v1/batches/<batch_id>/retry`。批量提交与重试都要求 request-scoped `ab_config` 和显式确认字段；缺失时返回中文 `validation_error` envelope。API 响应、错误 details 和日志不包含任何敏感外部值。
5. **Web UI**：批量工作台支持单卡接受、选中批量接受、全接受；`#batch-queue-panel` 展示队列项目、中文状态（待提交/提交中/提交成功/提交失败/可重试）、尝试次数和脱敏结果摘要；提交前表单包含 endpoint、token、fallback 和显式确认，提交成功后清空敏感输入；刷新后通过 URL `batch_id` 恢复队列状态。
6. **失败项独立重试**：只有 `FAILED`/`RETRYABLE` 项目显示单项重试；重试使用最新保存的 `ACCEPTED` Request 快照，从不使用队列中复制的完整 RSS、token、cookie、magnet 或原始响应；成功项永远不会显示重试按钮，也不会被重复提交。
7. **安全回归**：端到端浏览器安全回归注入 endpoint、token、Authorization header、cookie、raw HTML、raw RSS XML、原始响应体、完整失败 URL 和本地绝对路径，断言这些值不出现在 API 响应、页面、URL、浏览器 storage、队列 JSON、Request JSON、日志或 trace 中。

### 边界确认

- MiGuOrca **不创建 qBittorrent 下载任务**；下载执行继续由 Auto Bangumi / qBittorrent 负责。
- MiGuOrca **不绕过 Auto Bangumi** 建立长期订阅状态机。
- **不引入后台常驻 worker 或复杂调度器**；批量提交采用前台顺序编排，刷新后以持久化队列和 Request/AB result storage 恢复状态。
- 敏感 AB 配置只存在于单次请求上下文，从不持久化。

## 12. Stage 21 handoff

下一阶段为「用户偏好与智能推荐闭环」（见 `docs/MiGuOrca_future_stages.md` 和 `docs/backlog.md`）。建议方向：

1. 在 Stage 19/20 批量草案基础上记录用户偏好（字幕组、筛选、文件夹命名），减少逐卡修改次数。
2. 搜索词增强闭环：基于用户修正记录改进候选搜索词；AI 名称解析仍只生成候选，不自动选择最终合集。
3. AI 解析质量回看：展示低置信度和多义结果，允许用户修正并复用。
4. 安全存储偏好：只保存非敏感偏好，不保存外部服务 secret。
