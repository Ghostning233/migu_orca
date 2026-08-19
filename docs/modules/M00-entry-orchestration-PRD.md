# M00 入口与流程编排模块 PRD

## 1. 模块目标

M00 负责作为第一阶段业务入口，接收单个番剧名输入，按固定流程调用各模块，生成一条结构完整、状态为待确认的 Request。

Stage 19 后，M00 仍保留单番剧 Request 生成能力作为底层原子流程；批量新番输入应在其上编排多个独立条目，逐项调用名称解析、MiKan 搜索、候选选择和 Request/订阅草案生成。批量流程不应重写第二套单番剧业务逻辑。

第一阶段目标限定为：

1. 输入单个番剧名。
2. 编排番剧匹配、MiKan 数据源、RSS 解析、种子筛选、字幕组推荐、文件夹命名和 Request 组装。
3. 输出可人工查看或被后续程序消费的 Request。

## 2. 模块边界

本模块负责：

1. 定义单番剧 Request 生成流程。
2. 组织各模块调用顺序。
3. 汇总各模块输出并交给 M01 生成最终 Request。
4. 在流程失败时返回明确错误信息。
5. 后续批量工作台中，作为每个批量条目的订阅草案生成原子能力。

本模块不负责：

1. 番剧匹配算法本身。
2. RSS 解析规则本身。
3. 种子筛选规则本身。
4. 文件夹命名规则本身。
5. Auto Bangumi 对接。
6. 订阅提交。
7. 完整 Web UI。
8. AI 名称解析策略本身。
9. 跨卡片批量接受队列和 Auto Bangumi 提交调度。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| raw_title | string | 是 | 用户输入的单个番剧名 |

## 4. 输出数据

成功时输出 Request 对象，至少包含：

1. request_id。
2. status。
3. input。
4. source_info。
5. confirmable_config。
6. created_at。
7. updated_at。

失败时输出流程错误结果，至少包含：

1. error_message。
2. error_type，如果可识别。
3. failed_step。
4. request_id，如果已经创建。

## 5. 核心流程

1. 接收入口参数。
2. 调用 M03 加载静态候选番剧。
3. 调用 M02 根据 raw_title 匹配番剧条目。
4. 调用 M03 获取匹配番剧下的候选 RSS 源。
5. 对每个候选 RSS 调用 M04 解析种子信息。
6. 对每个 RSS 的种子调用 M06 计算有效种子和排除原因。
7. 调用 M05 选择推荐字幕组。
8. 调用 M07 生成预期文件夹名。
9. 调用 M01 组装状态为 PENDING_CONFIRM 的 Request 快照。
10. 返回 JSON；流程失败时返回独立错误结果。

## 6. 规则定义

1. 第一阶段只处理单个番剧名，不处理批量输入。
2. 第一阶段流程只生成 Request，不调用 AB，不提交订阅。
3. 流程中任一 P0 模块失败，应中断当前流程并返回明确错误。
4. 候选 RSS 可以来自 M03 的静态 RSS 模拟数据。
5. 输出中的有效种子必须使用 M06 定义：去除重复种子、无效种子和不符合规则种子后保留的种子。
6. 第一阶段同时支持内部 `generate_request` 能力和最小 CLI 包装。
7. 第一阶段以 JSON 对象为主输出，终端展示只作为展示包装，不作为核心数据结构。
8. 只从存在有效种子的 RSS 中选择默认字幕组。
9. 所有字幕组有效种子数均为 0 时仍生成 Request，但默认字幕组和 RSS 为 null，并输出 warning。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 输入为空 | 返回输入校验错误，不创建或不继续处理 Request |
| 未匹配到番剧 | 返回匹配失败错误，记录 raw_title |
| 匹配到番剧但无 RSS | 返回数据源无候选 RSS 错误 |
| RSS 解析失败 | 标记对应 RSS 失败；若全部失败，则流程失败 |
| 默认选中字幕组有效种子数为 0 | 不报错，正常生成 PENDING_CONFIRM Request，并附带有效种子数为 0 的提示 |
| 文件夹名生成失败 | 流程失败，保留前序诊断信息 |

## 8. 数据结构

```json
{
  "entry_request": {
    "raw_title": "咒术回战第三季"
  }
}
```

```json
{
  "entry_result": {
    "success": true,
    "request": {},
    "error": null
  }
}
```

## 9. 接口定义

第一阶段建议暴露一个入口能力：

```text
generate_request(entry_request) -> entry_result
```

CLI 入口作为该能力的调用包装。

## 10. 验收标准

1. 输入一个非空番剧名后，流程能调用各模块并生成 Request。
2. Request 状态为 PENDING_CONFIRM 或等价待确认状态。
3. Request 包含匹配番剧、候选 RSS、有效种子、推荐字幕组、预期文件夹名。
4. 第一阶段不依赖 Auto Bangumi 或 qBittorrent 在线可用。
5. 当任一关键步骤失败时，返回 failed_step 和可读错误原因。
6. 所有字幕组有效种子数为 0 时仍能生成 PENDING_CONFIRM Request，默认选择为空并输出可读提示。

## 11. Stage 16/17 真实 MiKan 编排状态

后续真实 MiKan 编排应收敛为：

```text
用户输入番剧名或 MiKan URL/ID
  ↓
可选：AI 番剧名解析或搜索词增强（低优先级，不是主链路依赖）
  ↓
Stage 17：搜索并展示 MiKan 候选合集，用户手动选择
  ↓
Stage 16：解析用户选中的 MiKan 合集详情页
  ↓
现有 RSS 解析、筛选、字幕组选择、目录命名和 Request 生成
```

Stage 16 已允许用户通过 CLI `--mikan-bangumi` 或 Web API `mikan_bangumi` 直接提供 MiKan `Home/Bangumi/<id>` URL 或 bangumi ID，从而绕过搜索候选选择，直接进入详情页解析。该参数只在当前请求中使用，不写入浏览器 storage、URL 或持久配置。bare ID 必须基于显式 MiKan config 的 `search_endpoint` 派生详情页 URL；URL 必须是同源 HTTP(S) `/Home/Bangumi/<numeric-id>`。

Stage 17 已将搜索结果候选卡片接入 Web UI `/index`，并且即使只有一个候选也要求用户显式点击确认，避免自动错选。Stage 17 的候选选择结果和直连 URL/ID fallback 都复用 Stage 16 direct-entry 编排路径（Web API `mikan_bangumi` 字段），而不是新增第二套详情页解析入口。候选搜索通过 request-scoped Web API `POST /api/v1/mikan/candidates` 完成，配合进程内候选缓存和 display-only 推荐标签；候选搜索、候选选择和直连 fallback 的 MiKan config 都是 request-scoped，不写入 storage JSON、浏览器 storage、URL、history、日志或截图。

AI 番剧名解析只允许作为后续可选增强模块生成多个搜索词；无 API key、无付费能力或 LLM 失败时，M00 仍必须可以通过 Stage 17 手动候选选择或 Stage 16 直连 URL/ID 完成真实 MiKan 流程。

## 12. Stage 18 编排状态（已完成）

Stage 18 已把真实 MiKan 收敛为 Web 主流程：

```text
用户输入番剧标题
  ↓
使用系统默认 MiKan 配置搜索候选合集
  ↓
用户手动选择合集
  ↓
解析选中合集详情页
  ↓
生成可编辑订阅草案预览
  ↓
用户调整字幕组、筛选规则和文件夹名
  ↓
保存为正式订阅方案
```

编排规则（Stage 18 已落地）：

1. Web `/index` 普通主流程以真实 MiKan 候选搜索为入口，不再默认生成 fixture Request。
2. fixture 生成能力保留给 CLI、API seam、离线开发和回归测试；Web UI 中的 fixture 入口放在 `/index` 底部「开发 / 离线测试」面板中并默认收起（`#dev-fixture-disclosure` 不带 `open`），普通用户路径不会触发 fixture 生成。
3. Web 候选搜索默认使用系统 MiKan 配置（`default_mikan_config()`，endpoint 等价于 `https://mikanani.me/Home/Search`，timeout 15 秒），普通 UI 不要求用户填写 `search_endpoint` 或 `timeout_seconds`。
4. 直连 URL/ID fallback 独立可用，输入 MiKan `Home/Bangumi/<id>` URL 或 bare ID 后直接复用 Stage 16 `mikan_bangumi` 链路。
5. 候选选择和直连 fallback 默认先生成未保存预览草案（`save_request=false`），保存动作必须由用户显式触发（`preview-save`）。
6. 预览阶段允许调整字幕组、筛选规则和文件夹名，通过 `preview-modify` dry-run 同步更新有效/排除种子展示。
7. AI 番剧名解析仍为可选增强，不是 Stage 18 依赖。

## 13. Stage 19 批量编排状态（已完成）

Stage 19 已在 M00 单番剧原子流程之上增加批量编排：

```text
用户按行输入多个简称或口语标题
  ↓
每个非空行创建独立 batch item
  ↓
AI 名称解析 provider seam 生成候选标题、季数提示和搜索词
  ↓
逐项复用 MiKan candidate search
  ↓
生成可审核订阅草案卡片
  ↓
单卡删除、展开、修改回流或接受
```

编排规则（Stage 19 已落地）：

1. 批量输入只负责拆分和编排多个独立 item，不替换现有 Request 模型。
2. AI provider 输出候选标题和搜索词，不自动选择最终 MiKan 合集，也不自动接受卡片。
3. 单项 provider 或 MiKan 搜索失败只标记当前 item 为 `FAILED` 或需要审核，不阻塞其他 item。
4. 批量候选搜索复用 Web API 内部的 `_search_mikan_candidates`，避免第二套 MiKan parser。
5. 单卡修改复用现有 `preview-modify` dry-run 详情流程，并只回流匹配 `item_id` 的卡片。
6. 单卡接受先持久化未保存预览，再复用现有 Request accept 能力；接受后只更新当前卡片。
7. 批量接受、全接受和 Auto Bangumi 提交队列不是 Stage 19 范围，已由 Stage 20 在单卡接受能力上完成编排。

Stage 21 handoff（已完成）：M00 继续作为单条订阅草案生成原子能力，接收 M08 生成的非敏感偏好结果（字幕组、筛选和命名默认值），并将其应用到每个批量条目。M00 不保存 LLM secret，不自动选择最终 MiKan 合集，也不自动接受批量卡片。具体编排状态见第 15 节。

## 14. Stage 20 批量接受与提交前队列编排状态（已完成）

Stage 20 已在 Stage 19 单卡接受基础上增加批量接受和 Auto Bangumi 提交前队列编排：

```text
用户审核批量草案卡片
  ↓
单卡接受 / 勾选批量接受 / 全接受
  ↓
复用现有 Request accept 能力，已接受项目入队 READY_TO_SUBMIT
  ↓
用户打开提交前队列，显式提供 AB config 并确认
  ↓
按队列顺序复用现有 build_ab_subscription_payload + AB client + 脱敏结果契约逐项提交
  ↓
单项成功/失败/可重试独立记录，失败项可独立重试
```

编排规则（Stage 20 已落地）：

1. 批量接受能力（`src/batch_engine/controllers/batch_accept_controller.py` 的 `accept_batch_items`）接收 `batch_id` 和 item 列表，通过注入的 `load_request`/`accept_one` 复用现有 Request 接受能力；已 `ACCEPTED` 项目幂等返回，不重复写入确认历史或队列；不可接受项目逐项返回中文原因；单项失败不阻塞其他项。
2. 提交前队列（`src/batch_engine/controllers/batch_queue_controller.py`）按 `request_id` 幂等入队，每个 item 独立记录状态、尝试次数、脱敏错误和脱敏结果摘要；队列只保存非敏感元数据，AB 配置永远不入队。
3. 批量顺序提交（`src/batch_engine/controllers/batch_submit_controller.py` 的 `submit_batch_queue_items`）使用 request-scoped `ab_config` 处理 `READY_TO_SUBMIT` 项目；提交前校验对应 Request 仍为 `ACCEPTED`，不满足条件标记 `FAILED`/`RETRYABLE` 并继续；单项成功/失败独立记录，成功项不会被重复提交；失败项通过 `retry_batch_queue_item` 独立重试，重试使用最新保存的 `ACCEPTED` Request 快照。
4. 队列持久化（`src/storage_engine/controllers/queue_repository.py`）写入 `<queue_dir>/<batch_id>.json`，只保留非敏感字段；`queue_dir` 是 `StorageConfig` 新字段，由 `ensure_storage_layout` 创建。
5. Web 层（`src/apps/migu_orca_web/views.py`）新增 `POST /api/v1/batches/<batch_id>/accept`、`GET /api/v1/batches/<batch_id>/queue`、`POST /api/v1/batches/<batch_id>/submit`、`POST /api/v1/batches/<batch_id>/retry`，把批量编排接到现有 Request 快照与接受流程。
6. 批量提交采用前台顺序编排，不创建 qBittorrent 下载任务，不绕过 Auto Bangumi，不引入后台常驻 worker 或复杂调度器。

## 15. Stage 21 偏好应用与搜索增强编排状态（已完成）

Stage 21 在 Stage 19/20 批量编排之上增加偏好应用、审核元数据和搜索词增强：

```text
用户显式保存非敏感偏好（字幕组/筛选/命名/搜索修正开关）
  ↓
批量输入多个简称
  ↓
每个 item 解析标题（AI 只生成候选）
  ↓
应用偏好生成默认配置（applied_preferences + preference_warnings）
  ↓
基于用户修正记录增强搜索词（enhanced_search_queries，失败回退原 search_queries）
  ↓
逐项搜索 MiKan 候选
  ↓
生成偏好命中摘要、低置信度/多候选/冲突审核提示（needs_user_review）
  ↓
用户逐卡审核、修改、接受（Stage 20 队列/提交语义不变）
```

编排规则（Stage 21 已落地）：

1. `POST /api/v1/batches/parse` 对每个 item（解析成功、搜索失败或解析失败）都返回 `applied_preferences`、`preference_hits`、`preference_warnings`、`review_hints` 和 `enhanced_search_queries` 公开字段；偏好读取或应用失败时当前 item 单独回退 Stage 19 默认流程，不阻塞同批次其他 item（`_load_preferences_for_batch` 损坏文件返回 `None`，`_load_corrections_for_batch` 损坏文件返回 `[]`）。
2. 偏好应用通过 `src/batch_engine/controllers/preference_applicator.py` 的纯函数完成：`build_preference_config` 生成 item 无关的非敏感默认配置，`apply_preferences_to_item` 附加命名默认目录名和 item 级警告，`build_review_metadata` 根据低置信度/多候选/无候选/搜索回退/搜索失败/解析失败/偏好冲突生成 `needs_user_review` 和中文 `review_hints`。审核元数据只注释卡片，绝不改变候选合集，绝不自动接受。
3. 字幕组偏好只作为单卡可编辑默认值；真实种子校验的字幕组选择仍在应用时由 M05 `select_subtitle_group(rss_results, priority, excluded=None)` 完成（排除列表先过滤、再按优先列表、最后 fallback）。
4. 搜索词增强通过 `src/batch_engine/controllers/search_enhancer.py` 纯函数把非敏感修正展开为 `{query, original_query, source}` 可审核条目，先用增强 query 搜索、失败再回退原 `search_queries`。
5. M00 不保存 LLM secret，不自动选择最终 MiKan 合集，不自动接受批量卡片，不引入后台 worker。

## 16. 已确认事项与待确认问题

### 16.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M00-03 | 所有字幕组有效种子数为 0 时是否仍生成 Request | 仍生成；默认字幕组和 RSS 为 null，并增加提示 |

### 16.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| 无 | 暂无 | 否 | - |
