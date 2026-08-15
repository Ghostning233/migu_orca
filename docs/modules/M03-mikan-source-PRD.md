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
      "subtitle_group": "Loli",
      "rss_url": "https://example.invalid/rss/loli.xml",
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
3. 静态 MiKan/RSS 数据必须纳入仓库并作为测试 fixture，保证离线验收可重复。
4. 静态数据需要表达番剧、别名、MiKan URL、字幕组、RSS URL、RSS fixture 路径或 RSS 内容的关系。
5. 不在第一阶段实现登录、反爬、页面结构兼容和访问频率控制。
6. 后续真实 MiKan 访问应通过同一模块接口替换，不影响 M00 编排。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 静态数据无法加载 | 返回数据源初始化失败 |
| raw_title 无候选 | 返回空候选列表 |
| matched_bangumi 无 RSS | 返回空 RSS 列表 |
| RSS URL 格式异常 | 返回数据源配置错误 |
| 静态数据重复 | 视为 fixture 配置错误 |

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
      "subtitle_group": "Loli",
      "rss_url": "https://example.invalid/rss/loli.xml",
      "source_type": "static_fixture",
      "fixture_path": "fixtures/rss/jujutsu_s3_loli.xml"
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

## 11. Stage 16/17 真实 MiKan 规划

真实 MiKan 能力按两个阶段拆分：

1. Stage 16：实现已选中合集详情页解析与直连 URL/ID 入口。输入为 MiKan `Home/Bangumi/<id>` URL、bangumi ID 或离线 HTML fixture；输出优先为字幕组级 `RssSource` 列表，番剧级 RSS 仅作为 fallback。
2. Stage 17：实现搜索候选合集展示与用户手动选择。MiKan 搜索页的 `相关推荐` 候选数量有限，不能保证覆盖所有季度或第一季，因此搜索结果只作为候选发现，最终必须由用户确认。

AI 番剧名解析不属于 M03 的必需能力。后续可作为独立可选增强模块生成多个搜索词，但不得替代用户对 MiKan 合集的最终选择。

真实 MiKan 安全边界：

1. 默认流程仍使用静态 fixture，不隐式访问真实 MiKan。
2. 真实 MiKan 访问必须由显式配置、直连 URL/ID 或用户选择触发。
3. 原始 HTML、原始 RSS XML、完整失败 URL、cookie、token、原始响应体和敏感路径不得写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或 trace。
4. 公共 RSS URL 仅在作为 Request 源元数据时可保存。

## 12. 已确认事项与待确认问题

### 12.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M03-01 | 第一阶段静态 MiKan/RSS 数据组织方式 | 纳入仓库并作为测试 fixture，保证离线验收可重复 |
| D-M03-02 | 静态 RSS 内容组织方式 | M03 输出 fixture_path 或等价静态内容标识，M04 负责按路径读取或接收测试传入内容 |

### 12.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M03-03 | 后续真实 MiKan 是否需要登录？ | 否 | 第一阶段不处理 |
| Q-M03-04 | 页面结构变化兼容策略是什么？ | 否 | 后续真实爬虫阶段定义 |
