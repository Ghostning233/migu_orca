# M03 MiKan 数据源模块 PRD

## 1. 模块目标

M03 为第一阶段 Request 生成链路提供 MiKan 数据源能力。第一阶段明确使用静态 RSS 列表模拟 MiKanProject 数据，不要求真实爬虫在线可用。

## 2. 模块边界

本模块负责：

1. 提供候选番剧条目。
2. 提供匹配番剧下的候选字幕组 RSS。
3. 屏蔽第一阶段静态数据和后续真实 MiKan 访问之间的差异。

本模块不负责：

1. 番剧相似度匹配。
2. RSS 内容解析。
3. 种子筛选。
4. 字幕组推荐。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| raw_title | string | 是 | 用户输入番剧名，用于查候选数据 |
| matched_bangumi | object | 否 | 已匹配番剧，用于获取 RSS 源 |

## 4. 输出数据

### 4.1 候选番剧列表

```json
{
  "candidates": [
    {
      "title": "咒术回战 第三季",
      "aliases": ["咒术回战", "咒回"],
      "mikan_url": "https://example.invalid/bangumi/1"
    }
  ]
}
```

### 4.2 候选 RSS 源

```json
{
  "rss_sources": [
    {
      "subtitle_group": "拨雪",
      "rss_url": "https://example.invalid/rss/bocchi.xml",
      "source_type": "static_fixture"
    }
  ]
}
```

## 5. 核心流程

1. 加载第一阶段静态 MiKan 模拟数据。
2. 根据 raw_title 返回可用于 M02 匹配的候选番剧。
3. 根据 matched_bangumi 返回该番剧下的候选 RSS 源。
4. 将 source_type 标记为 static_fixture 或等价值，避免误认为真实 MiKan 数据。

## 6. 规则定义

1. 第一阶段数据源必须允许离线运行。
2. 静态 RSS 列表用于模拟 MiKanProject 数据。
3. 静态数据需要表达番剧、别名、MiKan URL、字幕组、RSS URL 的关系。
4. 不在第一阶段实现登录、反爬、页面结构兼容和访问频率控制。
5. 后续真实 MiKan 访问应通过同一模块接口替换，不影响 M00 编排。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 静态数据无法加载 | 返回数据源初始化失败 |
| raw_title 无候选 | 返回空候选列表 |
| matched_bangumi 无 RSS | 返回空 RSS 列表 |
| RSS URL 格式异常 | 返回数据源配置错误 |
| 静态数据重复 | 保留原始数据并输出诊断，去重策略待确认 |

## 8. 数据结构

### 8.1 StaticBangumiSource

```json
{
  "bangumi_id": "mikan_static_001",
  "title": "咒术回战 第三季",
  "aliases": ["咒术回战", "咒回", "Jujutsu Kaisen"],
  "mikan_url": "https://example.invalid/bangumi/1",
  "rss_sources": [
    {
      "subtitle_group": "拨雪",
      "rss_url": "https://example.invalid/rss/bocchi.xml"
    }
  ]
}
```

## 9. 接口定义

```text
list_bangumi_candidates(raw_title) -> candidates
list_rss_sources(matched_bangumi) -> rss_sources
```

## 10. 验收标准

1. 不访问真实网络时，也能提供至少一组可跑通链路的静态数据。
2. 能为 M02 提供候选番剧列表。
3. 能为匹配番剧提供候选 RSS 源列表。
4. 输出能标识数据来自静态模拟源。
5. 后续替换真实 MiKan 访问时，不需要改 M00 的主流程定义。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M03-01 | 静态 RSS 模拟数据放在文档示例、JSON 文件、测试 fixture，还是代码内常量？ | 是 | 本文建议使用 JSON 或测试 fixture，但不定稿 |
| Q-M03-02 | 静态 RSS 是否保存 RSS 内容全文，还是只保存 URL 并由 M04 读取本地文件？ | 是 | 待确认 |
| Q-M03-03 | 后续真实 MiKan 是否需要登录？ | 否 | 第一阶段不处理 |
| Q-M03-04 | 页面结构变化兼容策略是什么？ | 否 | 后续真实爬虫阶段定义 |
