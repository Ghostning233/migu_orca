# MiGuOrca Stage 19 PRD: Batch Draft Workbench

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 19 PRD: Batch Draft Workbench |
| 文档类型 | Stage PRD |
| 当前状态 | Completed |
| 创建日期 | 2026-08-19 |
| 依赖阶段 | Stage 16、Stage 17、Stage 18 |

## 2. 背景

Stage 18 已完成单番剧真实 MiKan 主流程：用户输入番剧标题，系统搜索 MiKan 候选合集，用户选择后生成可编辑订阅草案，再保存为正式订阅方案。

新的产品方向不再把 MiGuOrca 定位为 Auto Bangumi 或 qBittorrent 的替代品，也不追求“自己完成自动追番下载闭环”。MiGuOrca 应成为 Auto Bangumi 前置的批量新番订阅编排工作台，帮助用户在提交 Auto Bangumi 前完成名称解析、MiKan 合集选择、字幕组选择、筛选规则验证和批量审核。

目标用户通常从季度新番推荐视频或清单中得到一批想看的番剧，输入往往是简称或口语名，例如：

```text
萌王S4
路哥S4
杖剑谭S2
邻家天使S2
```

这些名称直接搜索 MiKan 通常不可靠。Stage 19 需要把 AI 名称解析、MiKan 搜索和现有订阅草案预览组合为批量工作台。

## 3. 目标

1. 支持用户批量输入多个番剧简称或不完整标题。
2. 对每个输入生成结构化解析结果，包括候选官方标题、季数提示、搜索词、置信度和是否需要人工审核。
3. 基于解析结果逐项搜索 MiKan 候选合集，并生成独立订阅草案卡片。
4. 卡片展示封面、番剧全名、源名称、有效种子数、展开控件和删除按钮。
5. 卡片展开后展示过滤器、当前字幕组、有效种子和排除种子摘要。
6. 卡片提供修改入口，进入现有订阅方案详情与修改流程；修改只影响当前卡片。
7. 支持单个卡片接受，为后续批量接受和 Auto Bangumi 提交队列打基础。
8. 保持 Stage 18 的手动候选选择、直连 URL/ID fallback 和可编辑预览能力。

## 4. 非目标

1. 不实现自己的 qBittorrent 下载任务创建。
2. 不绕过 Auto Bangumi 建立长期订阅状态机。
3. 不自动部署 Auto Bangumi 或 qBittorrent。
4. 不让 AI 静默决定最终 MiKan 合集。
5. 不要求 AI 解析 100% 正确。
6. 不在本阶段完成批量接受或 Auto Bangumi 提交前队列；该能力在 Stage 20 最终以显式前台顺序提交实现，不采用并发队列或后台 worker。

## 5. 产品决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D19-01 | 批量输入是下一阶段主流程 | 单番剧生成保留，但用户价值应转向季度批量新番整理。 |
| D19-02 | AI 只做解析和搜索词增强 | AI 输出候选，不自动接受、不自动选择最终合集。 |
| D19-03 | 每个条目是独立卡片 | 单个条目失败、删除或修改不影响同批次其他条目。 |
| D19-04 | 复用现有单番剧能力 | 卡片内订阅草案应复用 Stage 18 预览、修改和保存链路。 |
| D19-05 | 接受后进入 AB 提交流程 | 下载执行仍由 Auto Bangumi / qBittorrent 负责。 |

## 6. 目标流程

```text
用户打开批量获取对话框
  ↓
按行输入番剧简称或口语标题
  ↓
系统调用 AI 名称解析，生成候选官方标题和搜索词
  ↓
系统逐项搜索 MiKan 候选合集
  ↓
用户审核每个条目的解析结果和候选合集
  ↓
系统生成订阅草案卡片
  ↓
用户删除错误卡片、展开查看过滤器和有效种子
  ↓
用户进入单卡详情修改字幕组、筛选规则或文件夹名
  ↓
用户单个接受卡片
```

## 7. 数据概念

Stage 19 建议新增批量草案概念，不替换现有 Request：

```json
{
  "batch_draft": {
    "batch_id": "batch_xxx",
    "raw_input": "萌王S4\n路哥S4",
    "items": []
  }
}
```

```json
{
  "batch_draft_item": {
    "item_id": "item_xxx",
    "raw_title": "萌王S4",
    "parsed_titles": ["关于我转生变成史莱姆这档事 第四季"],
    "season_hint": "S4",
    "search_queries": [],
    "confidence": "medium",
    "needs_user_review": true,
    "selected_candidate": null,
    "request_snapshot": null,
    "status": "NEEDS_REVIEW"
  }
}
```

建议状态：

| 状态 | 含义 |
| --- | --- |
| PARSED | 已解析名称，但尚未生成订阅草案 |
| NEEDS_REVIEW | 解析或候选存在不确定性，需要用户审核 |
| DRAFT | 已生成订阅草案卡片 |
| READY | 用户已确认卡片内容可接受 |
| ACCEPTED | 已接受，后续可进入 Auto Bangumi 提交 |
| FAILED | 当前条目生成失败，可重试或删除 |

## 8. 用户故事

Stage 19 的 Ralph 执行队列见 `scripts/ralph/prd.json`。每个 story 必须能在一次 Ralph 迭代内完成。

### US-132: 新增批量草案数据模型与分行解析

作为开发者，我需要安全的批量草案数据契约，让多个原始番剧输入可以独立追踪。

验收标准：

1. 新增批量草案和批量条目的内部模型或等价数据结构，包含 `batch_id`、`raw_input`、`items`、`item_id`、`raw_title`、`status` 字段。
2. 批量输入解析会按行拆分文本，忽略空行和纯空白行，并保留每个非空行的原始文本。
3. 每个条目拥有独立 `item_id`，单个条目状态变化不影响其他条目。
4. 单元测试覆盖多行输入、空行忽略、原始文本保留和 `item_id` 唯一性。
5. Tests pass。
6. Typecheck passes。

### US-133: 新增 AI 名称解析 seam 与 fake provider

作为用户，我希望系统能把 `萌王S4` 这类简称解析为可搜索标题。

验收标准：

1. 新增 AI 名称解析接口 seam，支持 fake provider 和后续真实 provider。
2. 输出包含 `raw_title`、`canonical_title_candidates`、`season_hint`、`search_queries`、`confidence`、`needs_user_review`、`source`。
3. AI provider 失败时返回可恢复的安全错误，不包含 token、endpoint、cookie、本地路径或原始外部响应。
4. 低置信度或多候选结果会设置 `needs_user_review=true`。
5. 单元测试覆盖成功解析、低置信度、多候选和 provider 失败场景。
6. Tests pass。
7. Typecheck passes。

### US-134: 新增批量解析 Web API

作为 Web UI 调用方，我希望提交多行原始标题后得到逐项解析元数据。

验收标准：

1. 新增批量解析 API 端点，接收 `raw_input` 多行文本并返回 `batch_id`、`raw_input`、`items`。
2. 每个返回 item 包含 `raw_title`、解析候选标题、`season_hint`、`search_queries`、`confidence`、`needs_user_review` 和 `status`。
3. 空输入返回统一 `validation_error` envelope，错误消息为中文且不泄露本地路径。
4. provider 单项失败只标记该 item 为 `FAILED`，不阻塞其他 item 返回。
5. Web API 单元测试覆盖成功、多行、空输入和单项失败。
6. Tests pass。
7. Typecheck passes。

### US-135: 新增批量 MiKan 候选搜索编排

作为用户，我希望系统逐项搜索 MiKan 候选，而不是让我手动查每个官方名。

验收标准：

1. 批量候选搜索会对每个 item 使用 `search_queries` 中的查询词逐项调用现有 MiKan candidate search 能力。
2. 每个 item 的候选结果彼此独立，单项搜索失败只将该 item 标记为 `FAILED` 或 `NEEDS_REVIEW`。
3. 候选结果只返回 `bangumi_id`、`title`、`mikan_url`、`poster_url`、`source_query`、`aliases`、`recommendation` 等公开元数据。
4. 响应和日志不得包含 raw HTML、raw RSS XML、完整失败 URL、cookie、token、magnet 或原始响应体。
5. 单元测试覆盖多 item 成功、单 item 失败不阻塞、公开字段序列化和敏感字段过滤。
6. Tests pass。
7. Typecheck passes。

### US-136: 新增批量输入 Web UI 入口

作为用户，我希望在工作台一次粘贴多个季度新番简称。

验收标准：

1. `/index` 提供明确的批量获取入口或面板，包含多行输入框和提交按钮。
2. 输入框示例文案包含 `萌王S4`、`路哥S4`、`杖剑谭S2`、`邻家天使S2`。
3. 提交空输入时前端显示中文校验错误且不调用批量 API。
4. 提交有效多行输入时调用批量解析 API，并展示每个条目的 `raw_title` 和解析状态。
5. 浏览器测试覆盖入口可见、多行输入、空输入校验和提交 loading/结果状态。
6. Tests pass。
7. Typecheck passes。
8. Verify in browser using dev-browser skill。

### US-137: 渲染批量订阅草案卡片网格

作为用户，我希望用卡片方式审核一批订阅草案。

验收标准：

1. 批量工作区以卡片网格展示条目，桌面端通常一行 4 个，窄屏最低一行 1 个。
2. 每张卡片初始展示封面占位或 poster、番剧全名或候选标题、源名称、有效种子数、状态和展开控件。
3. 每张卡片右上角有删除按钮，删除只移除当前卡片。
4. 卡片区域支持长列表滚动，删除一个卡片后其他卡片内容和状态保持不变。
5. 浏览器测试覆盖卡片布局、删除单卡、窄屏布局和长列表可滚动。
6. Tests pass。
7. Typecheck passes。
8. Verify in browser using dev-browser skill。

### US-138: 卡片展开显示过滤器与种子摘要

作为用户，我希望展开批量卡片后检查过滤器和种子结果。

验收标准：

1. 每张 `DRAFT` / `READY` 卡片可展开和收起。
2. 展开区展示当前字幕组、包含规则、排除规则、匹配模式、大小写状态、有效种子摘要和排除种子摘要。
3. 有效种子摘要优先展示当前选中字幕组的有效种子，排除种子展示中文排除原因。
4. 展开区不得渲染 raw RSS XML、magnet、cookie、token、完整 endpoint 或原始响应体。
5. 浏览器测试覆盖展开/收起、过滤器文案、有效/排除种子摘要和敏感字段不展示。
6. Tests pass。
7. Typecheck passes。
8. Verify in browser using dev-browser skill。

### US-139: 单卡详情修改并回流当前卡片

作为用户，我希望通过现有订阅方案详情流程修改某一个批量卡片，并且不影响其他卡片。

验收标准：

1. 卡片展开区提供 `修改` 按钮，点击后进入或打开现有订阅方案详情修改流程。
2. 保存修改后只更新当前卡片的 `selected_subtitle_group`、`filter_rule`、`expected_folder_name`、有效种子数和种子摘要。
3. 同一批次中的其他卡片 request snapshot、状态和展示内容保持不变。
4. 修改失败时当前卡片保留原状态并显示中文错误。
5. 浏览器测试覆盖修改当前卡片、其他卡片不变和修改失败恢复。
6. Tests pass。
7. Typecheck passes。
8. Verify in browser using dev-browser skill。

### US-140: 单卡接受状态流转

作为用户，我希望先接受确定无误的单个卡片，让它后续进入 Auto Bangumi 提交队列。

验收标准：

1. 每张 `DRAFT` / `READY` 卡片提供单独 `接受` 动作。
2. 接受动作复用现有 Request accept 能力或等价状态转换，成功后当前卡片状态显示为 `已接受`。
3. 已接受卡片不再展示删除前无需确认的危险操作；如仍允许删除，必须经显式确认。
4. 接受某一卡片不改变同批次其他卡片状态。
5. 本 story 不实现全接受、批量接受或 Auto Bangumi 提交前队列；这些能力由 Stage 20 的前台顺序编排实现。
6. 浏览器测试覆盖单卡接受、状态中文展示和其他卡片不变。
7. Tests pass。
8. Typecheck passes。
9. Verify in browser using dev-browser skill。

### US-141: Stage 19 文档与安全回归收尾

作为维护者，我希望 Stage 19 行为完成后同步文档并补齐安全回归。

验收标准：

1. README、主 PRD、Stage 19 PRD、future stages 文档、M00、M13、backlog 同步 Stage 19 完成状态和 Stage 20 handoff。
2. 新增或更新安全回归，覆盖 AI 输入输出、批量解析、MiKan 候选、卡片展示和单卡接受不泄露 raw HTML、raw RSS XML、cookie、token、magnet、完整失败 URL、原始响应体或本地绝对路径。
3. `uv run python -m compileall -q src tests` 通过。
4. `uv run pytest -q` 通过。
5. `uv run pytest tests/browser/ -q` 通过；如果浏览器不可用，必须记录明确 skip 原因。
6. Typecheck passes。

## 9. 安全边界

1. AI 输入可以包含用户输入的番剧名，但不得包含 token、cookie、endpoint 密钥或本地路径。
2. AI 输出不得直接进入最终接受状态，必须可审核。
3. MiKan raw HTML、raw RSS XML、magnet、cookie、token、完整失败 URL、原始响应体和本地绝对路径不得写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或 trace。
4. 批量草案中可保存用户输入的番剧名、公开候选元数据、筛选规则和 Request snapshot。
5. Auto Bangumi endpoint/token 仍只在显式提交时 request-scoped 使用，不进入批量草案或浏览器 storage。

## 10. 完成情况

Stage 19 已完成批量新番订阅草案工作台的最小闭环：

1. `POST /api/v1/batches/parse` 支持多行输入解析，每个非空行作为独立 batch item。
2. AI 名称解析已提供 provider seam 和 fake provider，输出候选标题、季数提示、搜索词、置信度和人工审核标记；provider 或单项 MiKan 搜索失败只影响当前 item。
3. 批量 API 复用现有 MiKan candidate search 能力逐项搜索候选，响应只序列化公开候选元数据。
4. `/index` 已提供批量获取入口、示例输入、空输入前端校验、loading 状态和解析结果展示。
5. 批量工作区以可滚动卡片网格展示条目，支持删除单卡、窄屏单列、展开查看过滤器/种子摘要、进入现有预览详情修改并回流当前卡片。
6. 单卡接受已复用现有 Request 接受能力：未保存预览先通过 `preview-save` 持久化，再调用 Request accept；接受只更新当前卡片，已接受卡片隐藏无确认删除动作。
7. 安全回归覆盖 AI/批量解析/MiKan 候选/卡片展示/单卡接受链路，确保 raw HTML、raw RSS XML、cookie、token、magnet、完整失败 URL、原始响应体和本地绝对路径不进入 UI、浏览器 storage、URL 或持久化 JSON。

Stage 20 handoff：

1. 在 Stage 19 单卡接受基础上实现批量接受、全接受和提交前队列。
2. 队列应展示待提交、提交中、成功、失败、可重试状态，并复用现有 Auto Bangumi submit 能力。
3. Auto Bangumi endpoint/token/fallback 仍必须显式确认且 request-scoped；提交结果和错误继续保持脱敏。

## 11. 验收汇总

Stage 19 完成后，用户应可以：

1. 一次输入多行新番简称。
2. 看到每行输入的 AI 解析结果和搜索状态。
3. 逐项生成订阅草案卡片。
4. 删除错误卡片。
5. 展开卡片查看过滤器和有效种子。
6. 进入单卡详情修改并回流到当前卡片。
7. 单独接受确认无误的卡片。
