# M01 用户输入与 Request 管理模块 PRD

## 1. 模块目标

M01 负责接收标准化后的用户输入，创建、组装和管理 Request 对象。第一阶段重点是生成状态明确、结构完整、可被人工确认的 Request。

## 2. 模块边界

本模块负责：

1. 校验单番剧输入结构。
2. 创建 request_id。
3. 组装 source_info 和 confirmable_config。
4. 输出状态为 PENDING_CONFIRM 的 Request 快照。

本模块不负责：

1. 真实持久化实现。
2. 完整用户确认交互。
3. Auto Bangumi 提交状态。
4. RSS 拉取、解析和筛选规则。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| raw_title | string | 是 | 用户原始番剧名 |
| matched_bangumi | object | 是 | M02 输出的匹配番剧 |
| rss_sources | array | 是 | M03/M04/M06 汇总后的 RSS 源信息 |
| selected_subtitle_group | string/null | 是 | M05 推荐的字幕组；无有效种子时为 null |
| selected_rss_url | string/null | 是 | 推荐字幕组对应 RSS；无有效种子时为 null |
| filter_rule | object | 是 | 当前筛选规则 |
| effective_seed_names | array | 是 | 当前有效种子名列表 |
| expected_folder_name | string | 是 | M07 输出的文件夹名 |

## 4. 输出数据

输出 Request 对象。

```json
{
  "request_id": "req_20260618_0001",
  "status": "PENDING_CONFIRM",
  "input": {},
  "source_info": {},
  "confirmable_config": {},
  "ab_submit_result": null,
  "created_at": "2026-06-18T00:00:00+08:00",
  "updated_at": "2026-06-18T00:00:00+08:00"
}
```

第一阶段 Request 完整结构建议如下：

```json
{
  "request_id": "req_20260618_0001",
  "status": "PENDING_CONFIRM",
  "input": {
    "raw_title": "咒术回战第三季"
  },
  "source_info": {
    "matched_bangumi": {
      "title": "咒术回战 第三季",
      "mikan_url": "https://example.invalid/bangumi/1",
      "match_score": 0.91,
      "aliases": ["咒术回战", "咒回", "Jujutsu Kaisen"]
    },
    "rss_sources": [
      {
        "subtitle_group": "Loli",
        "rss_url": "https://example.invalid/rss/loli.xml",
        "source_type": "static_fixture",
        "total_seed_count": 12,
        "valid_seed_count": 8,
        "invalid_seed_count": 4,
        "valid_seed_names": [
          "[Loli] 咒术回战 第三季 - 04 [1080p][CHS].mkv"
        ],
        "excluded_seed_names": [
          {
            "name": "[Loli] 咒术回战 第三季 - 04 V2 [1080p][CHS].mkv",
            "reason": "命中必须不含规则：V2|V3|1-|2-|3-|Fin|合集",
            "rule": "must_not_contain"
          }
        ]
      }
    ]
  },
  "confirmable_config": {
    "selected_subtitle_group": "Loli",
    "selected_rss_url": "https://example.invalid/rss/loli.xml",
    "filter_rule": {
      "must_contain": "",
      "must_not_contain": "V2|V3|1-|2-|3-|Fin|合集"
    },
    "effective_seed_names": [
      "[Loli] 咒术回战 第三季 - 04 [1080p][CHS].mkv"
    ],
    "expected_folder_name": "咒术回战 第三季",
    "warnings": []
  },
  "ab_submit_result": null,
  "created_at": "2026-06-18T00:00:00+08:00",
  "updated_at": "2026-06-18T00:00:00+08:00"
}
```

## 5. 核心流程

1. 校验 raw_title 非空。
2. 接收流程编排模块传入的源信息和可确认配置。
3. 创建 request_id。
4. 组装 source_info。
5. 组装 confirmable_config。
6. 创建状态为 PENDING_CONFIRM 的 Request 快照。
7. 返回 Request。

## 6. 规则定义

1. 第一阶段成功输出的 Request 只使用 `PENDING_CONFIRM`。
2. 第一阶段 Request 是一次计算得到的待确认快照，不是完整生命周期或持久化状态机。
3. 流程失败使用独立 ErrorResult，不创建 `FAILED` Request。
4. CREATED、SEARCHING 等内部过程不建模为 Request 状态。
5. ACCEPTED、MODIFIED、CANCELLED、EXPIRED、AB_SUBMITTING、AB_SUBMITTED 等状态保留给 M09、M10、M11 后续阶段。
6. effective_seed_names 不允许直接编辑，只能由字幕组或筛选规则变化后重新计算。
7. ab_submit_result 在第一阶段固定为 null。
8. request_id 需要全局唯一，具体生成规则由 Stage 1 短规格确认。

后续阶段扩展（Stage 10 起）：

- M09/M10 引入确认流程：`accept_request` 将 `PENDING_CONFIRM` 变更为 `ACCEPTED`，`cancel_request` 变更为 `CANCELLED`。
- 受限修改（`modify_request`）自 Stage 15 起同时接受 `PENDING_CONFIRM` 与 `ACCEPTED`，修改后保持原状态不变（`ACCEPTED` 不会回落为 `PENDING_CONFIRM`），只允许修改 `selected_subtitle_group`、`filter_rule`、`expected_folder_name`，并记录 `MODIFY` history 事件；`CANCELLED` 与未知状态继续拒绝修改。
- `ACCEPTED` Request 仍需要用户显式执行 `submit-ab` 才会提交到 Auto Bangumi，修改本身不会隐式触发提交。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| raw_title 为空 | 返回输入校验失败 |
| 缺少 matched_bangumi | 不生成 PENDING_CONFIRM Request |
| 缺少 rss_sources | 返回流程失败，不生成 Request |
| selected_rss_url 不在 rss_sources 中 | 返回配置组装错误 |
| effective_seed_names 与选中 RSS 不一致 | 返回数据一致性错误 |

## 8. 数据结构

### 8.1 RequestInput

```json
{
  "raw_title": "咒术回战第三季"
}
```

### 8.2 RequestStatus

```text
PENDING_CONFIRM
```

该枚举仅表示第一阶段成功输出状态，不代表完整 Request 状态集合。

### 8.3 ConfirmableConfig

```json
{
  "selected_subtitle_group": "Loli",
  "selected_rss_url": "https://example.invalid/rss.xml",
  "filter_rule": {},
  "effective_seed_names": [],
  "expected_folder_name": "咒术回战 第三季",
  "warnings": []
}
```

### 8.4 SourceInfo

```json
{
  "matched_bangumi": {},
  "rss_sources": []
}
```

### 8.5 Request

```json
{
  "request_id": "req_20260618_0001",
  "status": "PENDING_CONFIRM",
  "input": {},
  "source_info": {},
  "confirmable_config": {},
  "ab_submit_result": null,
  "created_at": "2026-06-18T00:00:00+08:00",
  "updated_at": "2026-06-18T00:00:00+08:00"
}
```

## 9. 接口定义

```text
build_pending_request(input, source_info, confirmable_config) -> request
```

第一阶段不实现持久化，上述接口返回内存对象。失败由入口流程返回独立 ErrorResult。

## 10. 验收标准

1. 能基于输入和各模块结果生成完整 Request。
2. Request 中 ab_submit_result 为 null。
3. Request 状态能明确表示待确认。
4. 输入、源信息、可确认配置三类字段边界清晰。
5. 缺少关键字段时能返回明确错误。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M01-01 | 第一阶段是否需要持久化 Request？ | 否 | 当前按可不持久化处理 |
| Q-M01-02 | Request 过期时间如何定义？ | 否 | 第一阶段暂不实现自动过期 |
| Q-M01-03 | FAILED 是否纳入主状态流转表？ | 否 | 已确认不纳入；失败使用独立 ErrorResult |
