# M04 RSS 解析模块 PRD

## 1. 模块目标

M04 负责读取 M03 提供的 RSS 数据，解析出种子条目，供 M06 进行有效种子筛选。

## 2. 模块边界

本模块负责：

1. 读取 RSS XML 或等价静态内容。
2. 提取种子名称、链接、发布时间等字段。
3. 返回结构化种子列表。
4. 识别 RSS 格式异常。

本模块不负责：

1. 判断种子是否有效。
2. 判断字幕组优劣。
3. 访问真实 MiKan 页面。
4. 下载种子文件。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| rss_url | string | 是 | RSS 地址或静态数据标识 |
| source_type | string | 是 | static_fixture、remote 等 |
| rss_content | string/null | 否 | 静态 RSS 内容；第一阶段优先从仓库内 fixture 读取，也可由 M03 直接传入 |
| fixture_path | string/null | 否 | 仓库内 RSS fixture 路径，source_type 为 static_fixture 时可用 |

## 4. 输出数据

```json
{
  "rss_url": "https://example.invalid/rss/loli.xml",
  "subtitle_group": "Loli",
  "total_seed_count": 12,
  "seeds": [
    {
      "title": "[Loli] 咒术回战 第三季 - 04 [1080p][CHS].mkv",
      "link": "https://example.invalid/torrent/1",
      "published_at": "2026-06-18T00:00:00+08:00",
      "guid": "torrent-1"
    }
  ]
}
```

## 5. 核心流程

1. 接收 RSS 源信息。
2. 根据 source_type 读取静态 RSS fixture、静态 RSS 内容或远程内容。
3. 解析 XML。
4. 遍历 item 节点并提取种子字段。
5. 返回结构化种子列表。
6. item 缺少 title 或 link 时跳过并输出 warning。
7. 没有任何有效 item 时该 RSS 解析失败。

## 6. 规则定义

1. 第一阶段至少需要解析 title 和 link。
2. published_at、guid 可解析则保留，否则置空。
3. RSS 中 item 的 title 作为种子名称来源。
4. 不在本模块识别集数、分辨率和字幕语言。
5. 不在本模块去重。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| RSS 内容为空 | 返回 RSS_EMPTY |
| XML 格式非法 | 返回 RSS_PARSE_FAILED |
| 没有 item | 返回空 seeds |
| item 缺少 title | 跳过并记录 warning |
| item 缺少 link | 跳过并记录 warning |
| 发布时间格式异常 | 置空 |

## 8. 数据结构

### 8.1 RssSeed

```json
{
  "title": "[字幕组] 番名 - 01 [1080p][CHS].mkv",
  "link": "https://example.invalid/torrent/1",
  "published_at": null,
  "guid": null
}
```

### 8.2 ParsedRss

```json
{
  "rss_url": "https://example.invalid/rss.xml",
  "subtitle_group": "字幕组",
  "total_seed_count": 1,
  "seeds": []
}
```

## 9. 接口定义

```text
parse_rss(rss_source) -> parsed_rss
```

## 10. 验收标准

1. 能解析静态 RSS 样例并输出 seeds。
2. 至少能提取 title 和 link。
3. RSS 格式错误时返回明确错误。
4. 空 RSS 不导致程序崩溃。
5. 输出可直接交给 M06 处理。

## 11. 已确认事项与待确认问题

### 11.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M04-01 | 静态 RSS 读取方式 | 第一阶段优先由 M03 提供 fixture_path，M04 按路径读取；测试可直接传入 rss_content |

### 11.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M04-01 | 第一阶段必须支持哪些 RSS 字段？ | 否 | 已确认：title、link 必需，published_at、guid 可选 |
| Q-M04-02 | item 缺少 title 或 link 时跳过还是失败？ | 否 | 已确认：跳过并记录 warning |
| Q-M04-04 | 是否需要保留 RSS 原始字段 raw？ | 否 | 已确认：Stage 1 不保留 |
