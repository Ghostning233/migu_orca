# M05 字幕组评估模块 PRD

## 1. 模块目标

M05 负责从多个候选 RSS 源中推荐一个字幕组，作为 Request 的默认 selected_subtitle_group。

第一阶段使用用户配置的字幕组优先级，并且只从存在有效种子的 RSS 中选择。

## 2. 模块边界

本模块负责：

1. 接收各字幕组 RSS 的筛选结果。
2. 基于简单规则选择推荐字幕组。
3. 输出推荐原因。

本模块不负责：

1. RSS 解析。
2. 种子有效性计算。
3. 字幕组长期质量评分。
4. 历史学习。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| rss_sources | array | 是 | 包含字幕组、RSS、有效种子数 |
| user_preference | object | 是 | 包含用户配置的 subtitle_group_priority |

## 4. 输出数据

```json
{
  "selected_subtitle_group": "Loli",
  "selected_rss_url": "https://example.invalid/rss/loli.xml",
  "reason": "命中用户字幕组优先级"
}
```

## 5. 核心流程

1. 接收带 subtitle_group 和 rss_url 的 RSS 源列表。
2. 排除 `valid_seed_count = 0` 的候选。
3. 按用户配置的 `subtitle_group_priority` 选择第一个存在的字幕组。
4. 用户优先级未命中时，选择第一个存在有效种子的候选并输出 warning。
5. 所有候选均无有效种子时，不设置默认字幕组和 RSS，并输出 warning。

## 6. 规则定义

1. 字幕组优先级由用户 JSON 配置，不写死在代码中。
2. 只推荐至少有一个有效种子的字幕组。
3. 第一阶段不实现复杂质量评分或历史学习。
4. 推荐结果只是默认值，后续阶段用户可修改。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 候选为空 | 返回无可推荐字幕组 |
| 全部 valid_seed_count 为 0 | 不设置默认字幕组，生成带 warning 的 Request |
| 用户优先级没有命中候选 | 选择第一个有效候选，并输出 warning |

## 8. 数据结构

```json
{
  "selected_subtitle_group": "Loli",
  "selected_rss_url": "https://example.invalid/rss.xml",
  "reason": "命中用户字幕组优先级"
}
```

## 9. 接口定义

```text
recommend_subtitle_group(rss_sources, user_preference = null) -> subtitle_group_recommendation
```

## 10. 验收标准

1. 能从多个候选 RSS 中输出一个推荐字幕组。
2. 推荐结果包含 selected_subtitle_group 和 selected_rss_url。
3. 无候选时返回明确错误。
4. 不依赖真实历史数据。
5. 所有候选均无有效种子时返回空选择和 warning。

## 11. 已确认事项与待确认问题

### 11.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M05-01 | 第一阶段字幕组优先级 | 由用户 JSON 配置 |
| D-M05-02 | 有效种子数为 0 时是否可推荐 | 不推荐；全部为 0 时输出空选择和 warning |
| D-M05-03 | 优先级未命中 | 选择第一个有效候选并输出 warning |

### 11.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M05-04 | 后续复杂字幕组评分体系包含哪些指标？ | 否 | 后续阶段再定义 |
