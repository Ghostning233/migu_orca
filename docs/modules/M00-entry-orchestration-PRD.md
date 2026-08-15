# M00 入口与流程编排模块 PRD

## 1. 模块目标

M00 负责作为第一阶段业务入口，接收单个番剧名输入，按固定流程调用各模块，生成一条结构完整、状态为待确认的 Request。

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

本模块不负责：

1. 番剧匹配算法本身。
2. RSS 解析规则本身。
3. 种子筛选规则本身。
4. 文件夹命名规则本身。
5. Auto Bangumi 对接。
6. 订阅提交。
7. 完整 Web UI。

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

## 13. 已确认事项与待确认问题

### 13.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M00-03 | 所有字幕组有效种子数为 0 时是否仍生成 Request | 仍生成；默认字幕组和 RSS 为 null，并增加提示 |

### 13.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| 无 | 暂无 | 否 | - |
