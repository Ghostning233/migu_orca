# M00 入口与流程编排模块 PRD

## 1. 模块目标

M00 负责作为第一阶段 MVP 的业务入口，接收单个番剧名输入，按固定流程调用各模块，生成一条结构完整、状态为待确认的 Request。

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
| season_hint | string/null | 否 | 季数或季度提示，第一阶段可为空 |
| subtitle_group_hint | string/null | 否 | 字幕组提示，第一阶段可为空 |
| folder_name_hint | string/null | 否 | 用户指定文件夹名，第一阶段可为空 |
| output_format | string | 否 | Request 输出形式，待确认 |

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

1. error_code。
2. error_message。
3. failed_step。
4. request_id，如果已经创建。

## 5. 核心流程

1. 接收入口参数。
2. 调用 M01 创建 Request 初始对象，状态为 CREATED。
3. 将 Request 状态更新为 SEARCHING。
4. 调用 M02 根据 raw_title 匹配番剧条目。
5. 调用 M03 获取匹配番剧下的候选 RSS 源。
6. 对每个候选 RSS 调用 M04 解析种子信息。
7. 对每个 RSS 的种子调用 M06 计算有效种子和排除原因。
8. 调用 M05 选择推荐字幕组。
9. 调用 M07 生成预期文件夹名。
10. 调用 M01 组装 Request 并更新为 PENDING_CONFIRM。
11. 按指定输出形式返回 Request。

## 6. 规则定义

1. 第一阶段只处理单个番剧名，不处理批量输入。
2. 第一阶段流程只生成 Request，不调用 AB，不提交订阅。
3. 流程中任一 P0 模块失败，应中断当前流程并返回明确错误。
4. 候选 RSS 可以来自 M03 的静态 RSS 模拟数据。
5. 输出中的有效种子必须使用主 PRD 定义：去除重复种子、无效种子和不符合规则种子后保留的种子。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 输入为空 | 返回输入校验错误，不创建或不继续处理 Request |
| 未匹配到番剧 | 返回匹配失败错误，记录 raw_title |
| 匹配到番剧但无 RSS | 返回数据源无候选 RSS 错误 |
| RSS 解析失败 | 标记对应 RSS 失败；若全部失败，则流程失败 |
| 所有 RSS 有效种子数为 0 | 仍可生成 Request 草案或返回不可用结果，最终策略待确认 |
| 文件夹名生成失败 | 流程失败，保留前序诊断信息 |

## 8. 数据结构

```json
{
  "entry_request": {
    "raw_title": "咒术回战第三季",
    "season_hint": null,
    "subtitle_group_hint": null,
    "folder_name_hint": null,
    "output_format": "json"
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

CLI 入口可作为该能力的调用包装，但入口形态仍待确认。

## 10. 验收标准

1. 输入一个非空番剧名后，流程能调用各模块并生成 Request。
2. Request 状态为 PENDING_CONFIRM 或等价待确认状态。
3. Request 包含匹配番剧、候选 RSS、有效种子、推荐字幕组、预期文件夹名。
4. 第一阶段不依赖 Auto Bangumi 或 qBittorrent 在线可用。
5. 当任一关键步骤失败时，返回 failed_step 和可读错误原因。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M00-01 | 第一阶段入口形态是 CLI、库函数，还是两者都支持？ | 是 | 本文先按内部 generate_request 能力加可选 CLI 包装编写 |
| Q-M00-02 | Request 输出形式是终端、文件、JSON，还是多种都支持？ | 是 | 本文先按 JSON 对象为主，终端展示为包装能力 |
| Q-M00-03 | 所有 RSS 有效种子为 0 时是否仍生成待确认 Request？ | 否 | 暂作为异常策略待定 |
