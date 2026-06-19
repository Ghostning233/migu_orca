# M05 字幕组评估模块 PRD

## 1. 模块目标

M05 负责从多个候选 RSS 源中推荐一个字幕组，作为 Request 的默认 selected_subtitle_group。

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
| user_preference | object/null | 否 | 用户字幕组偏好，第一阶段可为空 |

## 4. 输出数据

```json
{
  "selected_subtitle_group": "拨雪",
  "selected_rss_url": "https://example.invalid/rss/bocchi.xml",
  "reason": "有效种子数最高"
}
```

## 5. 核心流程

1. 接收带 valid_seed_count 的 RSS 源列表。
2. 排除有效种子数为 0 的候选，是否强制排除待确认。
3. 应用用户偏好优先级，若配置存在。
4. 使用有效种子数、字幕语言、分辨率等已有信息进行简单排序。
5. 输出第一名作为推荐字幕组。

## 6. 规则定义

1. 第一阶段可使用固定优先级或有效种子数优先的简单规则。
2. 不实现复杂字幕组质量评分。
3. 不基于历史下载成功率评分。
4. 推荐结果只是默认值，后续阶段用户可修改。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 候选为空 | 返回无可推荐字幕组 |
| 全部 valid_seed_count 为 0 | 返回无有效字幕组或仍选择最高总数，待确认 |
| 用户偏好指定字幕组不存在 | 忽略偏好并输出 warning |
| 多个候选评分相同 | 按待确认优先级处理 |

## 8. 数据结构

```json
{
  "subtitle_group_score": {
    "subtitle_group": "拨雪",
    "rss_url": "https://example.invalid/rss.xml",
    "valid_seed_count": 8,
    "score": 8,
    "reasons": ["有效种子数 8"]
  }
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

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M05-01 | 默认字幕组优先级如何定义？ | 否 | 第一阶段可按有效种子数优先 |
| Q-M05-02 | 有效种子数为 0 的字幕组是否可被推荐？ | 否 | 待确认 |
| Q-M05-03 | 同分时按字幕组偏好、名称顺序还是 RSS 顺序？ | 否 | 待确认 |
