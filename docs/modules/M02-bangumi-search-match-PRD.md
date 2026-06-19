# M02 番剧搜索与匹配模块 PRD

## 1. 模块目标

M02 根据用户输入的单个番剧名，从 M03 提供的候选番剧数据中选择最匹配的番剧条目，并输出匹配结果和匹配诊断信息。

## 2. 模块边界

本模块负责：

1. 标准化用户输入标题。
2. 对候选番剧进行匹配评分。
3. 输出最匹配番剧。
4. 输出 aliases、match_score 等匹配信息。

本模块不负责：

1. 访问 MiKanProject 页面。
2. 管理静态 RSS 数据。
3. 解析 RSS。
4. 处理用户手动二次选择。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| raw_title | string | 是 | 用户输入番剧名 |
| season_hint | string/null | 否 | 季数提示 |
| candidates | array | 是 | M03 返回或提供的候选番剧条目 |

## 4. 输出数据

```json
{
  "matched_bangumi": {
    "title": "咒术回战 第三季",
    "mikan_url": "https://example.invalid/bangumi/1",
    "match_score": 0.91,
    "aliases": ["咒术回战", "咒回", "Jujutsu Kaisen"]
  },
  "match_diagnostics": {
    "candidate_count": 3,
    "strategy": "simple_similarity",
    "warnings": []
  }
}
```

## 5. 核心流程

1. 接收 raw_title 和候选番剧列表。
2. 对 raw_title 做基础标准化，例如去除首尾空白。
3. 对每个候选条目的 title 和 aliases 计算匹配分。
4. 选择分数最高的候选条目。
5. 若无候选或分数低于可接受阈值，则返回匹配失败。
6. 输出 matched_bangumi 和诊断信息。

## 6. 规则定义

1. 第一阶段直接选择系统判断最相似的匹配结果。
2. 第一阶段不提供候选番剧手动选择。
3. 匹配结果错误时，由用户取消 Request 并重新输入更准确番名。
4. 相似度算法、阈值、同分优先级尚未定稿，本文不强行指定。
5. 剧场版、OVA、重制版、Part 等复杂区分先作为待确认规则，不作为第一阶段强制完整能力。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| raw_title 为空 | 返回输入错误 |
| candidates 为空 | 返回无候选错误 |
| 最高分低于阈值 | 返回低置信度匹配失败，阈值待确认 |
| 多个候选同分 | 使用待确认优先级；第一阶段可返回歧义错误 |
| 匹配到错误番剧 | 不自动纠正，由用户取消后重新输入 |

## 8. 数据结构

### 8.1 BangumiCandidate

```json
{
  "title": "咒术回战 第三季",
  "aliases": ["咒术回战", "咒回", "Jujutsu Kaisen"],
  "mikan_url": "https://example.invalid/bangumi/1",
  "season": null,
  "part": null
}
```

### 8.2 MatchResult

```json
{
  "title": "咒术回战 第三季",
  "mikan_url": "https://example.invalid/bangumi/1",
  "match_score": 0.91,
  "aliases": []
}
```

## 9. 接口定义

```text
match_bangumi(raw_title, candidates, season_hint = null) -> match_result
```

## 10. 验收标准

1. 给定 raw_title 和候选列表时，能返回一个 matched_bangumi。
2. 输出包含 title、mikan_url、match_score、aliases。
3. 无候选时返回明确错误。
4. 第一阶段不依赖真实 MiKan 在线搜索。
5. 匹配策略未定稿部分必须体现在待确认问题中。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M02-01 | 相似度算法使用何种规则？ | 是 | 先写为 simple_similarity 占位 |
| Q-M02-02 | 最低匹配阈值是多少？ | 是 | 暂不固定 |
| Q-M02-03 | 别名表由静态数据提供、配置维护，还是运行时生成？ | 是 | 暂由候选数据携带 aliases |
| Q-M02-04 | 同分时优先级如何定义？ | 是 | 暂返回歧义或按候选顺序处理，需确认 |
| Q-M02-05 | TV、剧场版、OVA、重制版如何区分？ | 否 | 第一阶段先记录为待扩展规则 |
