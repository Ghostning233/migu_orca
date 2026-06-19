# M06 种子筛选规则模块 PRD

## 1. 模块目标

M06 负责根据筛选规则从 RSS 种子列表中计算有效种子，并输出被排除种子的原因。

有效种子严格沿用主 PRD 定义：按筛选规则去除重复种子、无效种子和不符合规则种子后，最终保留下来的种子。

## 2. 模块边界

本模块负责：

1. 识别种子是否符合默认筛选规则。
2. 输出 valid_seed_names。
3. 输出 excluded_seed_names 及排除原因。
4. 统计 total_seed_count、valid_seed_count、invalid_seed_count。

本模块不负责：

1. RSS XML 解析。
2. 字幕组推荐。
3. 文件夹命名。
4. 下载种子。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| seeds | array | 是 | M04 输出的种子列表 |
| filter_rule | object | 是 | 当前筛选规则 |

## 4. 输出数据

```json
{
  "total_seed_count": 12,
  "valid_seed_count": 8,
  "invalid_seed_count": 4,
  "valid_seed_names": [
    "[拨雪] 咒术回战 第三季 - 01 [1080p][CHS].mkv"
  ],
  "excluded_seed_names": [
    {
      "name": "[拨雪] 咒术回战 第三季 - 01 [720p].mkv",
      "reason": "分辨率不符合默认规则"
    }
  ]
}
```

## 5. 核心流程

1. 接收一个 RSS 下的 seeds。
2. 对每个种子名称应用排除关键词规则。
3. 应用分辨率规则。
4. 应用字幕语言规则。
5. 识别正片候选。
6. 对同一集多版本进行去重。
7. 输出有效种子和排除原因。

## 6. 规则定义

主 PRD 示例默认规则如下：

```json
{
  "resolution": "1080p",
  "subtitle_language": "CHS",
  "exclude_keywords": ["合集", "总集篇", "NCOP", "NCED", "PV", "SP", "先行"],
  "include_keywords": [],
  "episode_strategy": "normal_episode"
}
```

第一阶段规则约束：

1. 默认分辨率按 1080p 处理，但最终是否固定待确认。
2. 默认字幕语言按 CHS 处理，但最终是否固定待确认。
3. 包含排除关键词的种子默认排除。
4. 多版本去重、v2/v3、重制版处理细则未定稿，不应写死为最终规则。
5. 每个被排除种子必须输出可读 reason。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| seeds 为空 | 返回 total_seed_count 为 0 |
| 种子名称为空 | 排除并标记名称缺失 |
| 无法识别集数 | 是否排除待确认 |
| 多版本冲突 | 按待确认规则处理 |
| 所有种子被排除 | 返回空 valid_seed_names 和排除原因 |
| filter_rule 缺字段 | 使用默认值或报错待确认 |

## 8. 数据结构

### 8.1 FilterRule

```json
{
  "resolution": "1080p",
  "subtitle_language": "CHS",
  "exclude_keywords": ["合集", "总集篇", "NCOP", "NCED", "PV", "SP", "先行"],
  "include_keywords": [],
  "episode_strategy": "normal_episode"
}
```

### 8.2 ExcludedSeed

```json
{
  "name": "[字幕组] 番名 - 01 [720p].mkv",
  "reason": "分辨率不符合默认规则",
  "rule": "resolution"
}
```

## 9. 接口定义

```text
filter_seeds(seeds, filter_rule) -> filtered_seed_result
```

## 10. 验收标准

1. 能输出有效种子名列表。
2. 能输出每个被排除种子的原因。
3. 统计数量满足 total = valid + invalid。
4. 默认规则与主 PRD 示例保持一致。
5. 不把 v2/v3 等未确认细则写死为最终规则。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M06-01 | 默认分辨率是否固定为 1080p？ | 是 | 暂沿用主 PRD 示例 |
| Q-M06-02 | 默认字幕语言是否固定为 CHS？ | 是 | 暂沿用主 PRD 示例 |
| Q-M06-03 | 规则优先级如何定义？ | 是 | 待确认 |
| Q-M06-04 | v2/v3 修正版是优先保留还是默认排除？ | 是 | 待确认 |
| Q-M06-05 | 合集是否一律排除？ | 是 | 暂按排除关键词处理 |
| Q-M06-06 | 重制版、先行版、SP、OVA 如何处理？ | 否 | 第一阶段先作为待确认细则 |
