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
    "strategy": "exact_then_sequence_matcher",
    "warnings": []
  }
}
```

## 5. 核心流程

1. 接收 raw_title 和候选番剧列表。
2. 标准化 raw_title：去除首尾空白、转小写并移除所有空白字符。
3. 先对候选 title 和 aliases 做标准化后的精确匹配。
4. 精确匹配失败时使用 SequenceMatcher 计算相似度。
5. 选择唯一最高分且分数不低于 0.6 的候选。
6. 低于阈值或最高分同分时返回明确错误。
7. 输出 matched_bangumi 和诊断信息。

## 6. 规则定义

1. 第一阶段直接选择系统判断最相似的匹配结果。
2. 第一阶段不提供候选番剧手动选择。
3. 匹配结果错误时，由用户取消 Request 并重新输入更准确番名。
4. 模糊匹配使用 `difflib.SequenceMatcher`，最低阈值为 0.6。
5. 多个候选最高分同分时返回歧义错误，不按输入顺序静默选择。
6. 剧场版、OVA、重制版、Part 等复杂区分不作为第一阶段强制完整能力。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| raw_title 为空 | 返回输入错误 |
| candidates 为空 | 返回无候选错误 |
| 最高分低于 0.6 | 返回低置信度匹配失败 |
| 多个候选同分 | 返回歧义错误 |
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
5. 精确匹配、模糊阈值和同分错误均有测试覆盖。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M02-01 | 相似度算法使用何种规则？ | 否 | 已确认：精确匹配后使用 SequenceMatcher |
| Q-M02-02 | 最低匹配阈值是多少？ | 否 | 已确认：0.6 |
| Q-M02-03 | 别名表由静态数据提供、配置维护，还是运行时生成？ | 否 | 已确认：由候选数据携带 aliases |
| Q-M02-04 | 同分时优先级如何定义？ | 否 | 已确认：返回歧义错误 |
| Q-M02-05 | TV、剧场版、OVA、重制版如何区分？ | 否 | 第一阶段先记录为待扩展规则 |

## 12. Stage 22 搜索结果语义补充（已完成）

Stage 22 已明确 M02 的标题解析/本地匹配与 M03 真实 MiKan 候选发现是不同层级：

1. 标题解析或相似度匹配成功只表示得到了候选标题/搜索词，不表示 MiKan 已返回真实合集。
2. M03 返回空候选是正常 EMPTY 结果；M02 不得把 raw title、canonical title candidate 或 aliases 包装成伪 MiKan 候选。
3. 只有带公开 `bangumi_id` 与规范化 `mikan_url` 的 M03 候选才可供用户显式选择。
4. 低置信度、歧义或无候选必须保留人工审核语义，不得自动进入订阅草案或接受状态。
5. 单个与批量入口复用同一边界，批量模式不能放宽候选真实性要求。
