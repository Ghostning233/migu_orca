# MiGuOrca Stage 1 实现规格

## 1. 文档职责

本文是 Stage 1 唯一的技术行为基线。主 PRD 定义产品范围，模块 PRD 定义职责边界，
本文定义本阶段的代码结构、数据契约、规则和验收行为。

发生冲突时按以下顺序处理：

1. 主 PRD 的范围与非范围；
2. 本文的 Stage 1 行为；
3. 模块 PRD 的职责边界；
4. 架构文档的一般性建议。

## 2. 验证目标

Stage 1 是最小离线技术探针：

```text
番剧名称
  -> 静态候选匹配
  -> 静态 RSS 解析
  -> 用户规则筛选
  -> 默认字幕组与文件夹名
  -> PENDING_CONFIRM Request 快照
```

它只证明输入能够稳定转换为 Request，不追求完整、长期扩展的系统架构。

## 3. 范围

必须支持：

1. 接收一个非空番剧名称。
2. 从仓库内 JSON fixture 读取候选番剧和 RSS 来源。
3. 按第 7 节规则匹配番剧。
4. 从仓库内 XML fixture 解析 RSS。
5. 按用户 JSON 中的正则规则筛选条目。
6. 按用户配置选择默认字幕组。
7. 生成安全的预期文件夹名。
8. 输出 `PENDING_CONFIRM` Request 快照。
9. 失败时输出独立的结构化 ErrorResult。
10. 提供最小 CLI。

明确不做：

- 真实 MiKan、Auto Bangumi 或 qBittorrent 调用；
- Request 持久化及完整状态机；
- 用户确认、修改、取消和提交；
- Web UI、批量输入、历史学习；
- 完全兼容 qBittorrent 的筛选语义；
- 模板化文件夹命名和季数推断。

## 4. 代码结构

保留 `apps -> engine -> controllers/models` 的总体结构，Stage 1 只使用四个 engine：

```text
src/
  apps/
    migu_orca_entry/
      controllers/
        entry_controller.py

  catalog_engine/       # M02 + M03：候选数据与标题匹配
    controllers/
    models/

  rss_engine/           # M04 + M06：RSS 解析与条目筛选
    controllers/
    models/

  subscription_engine/  # M05 + M07：字幕组选择与目录命名
    controllers/
    models/

  request_engine/       # M01：Request 契约与组装
    controllers/
    models/

  shared/               # 跨 engine 契约、配置、错误和日志
```

配置和日志是普通基础模块，不建立 M12、M14 engine。后续只有在出现独立变化边界时，
才新增或拆分 engine。

## 5. 输入与输出

入口输入：

```json
{
  "raw_title": "咒术回战第三季"
}
```

成功输出的关键结构：

```json
{
  "success": true,
  "request": {
    "request_id": "UUID",
    "status": "PENDING_CONFIRM",
    "input": {"raw_title": "咒术回战第三季"},
    "source_info": {
      "matched_bangumi": {},
      "rss_sources": []
    },
    "confirmable_config": {
      "selected_subtitle_group": "Loli",
      "selected_rss_url": "https://example.invalid/rss/loli.xml",
      "filter_rule": {
        "must_contain": "",
        "must_not_contain": ""
      },
      "effective_seed_names": [],
      "expected_folder_name": "咒术回战 第三季",
      "warnings": []
    },
    "ab_submit_result": null,
    "created_at": "ISO-8601",
    "updated_at": "ISO-8601"
  },
  "error": null
}
```

失败输出：

```json
{
  "success": false,
  "request": null,
  "error": {
    "error_type": "bangumi_match_failed",
    "error_message": "未找到可靠的番剧匹配",
    "failed_step": "match_bangumi",
    "details": {}
  }
}
```

Stage 1 Request 是一次计算产生的待确认快照，不是完整生命周期或持久化状态机。
`CREATED`、`SEARCHING` 和 `FAILED` 不作为本阶段 Request 状态。

## 6. Fixture 和用户配置

静态候选：`config/system/static_mikan_sources.json`。

RSS fixture：`fixtures/rss/*.xml`。

用户配置：`config/user/default_rules.json`，结构固定为：

```json
{
  "filter_rule": {
    "must_contain": "",
    "must_not_contain": ""
  },
  "subtitle_group_priority": ["Loli", "喵萌"]
}
```

系统默认路径写在代码中。Stage 1 不实现环境变量覆盖、配置 profile、单番覆盖和命名模板。

## 7. 已确认规则

### 7.1 番剧匹配

1. 标题标准化：去除首尾空白、转小写、移除所有空白字符。
2. 先对候选 `title` 和 `aliases` 做标准化后的精确匹配。
3. 精确匹配失败时使用 `difflib.SequenceMatcher`。
4. 每个候选取标题及别名中的最高分。
5. 最低模糊匹配阈值为 `0.6`。
6. 最高分低于阈值时失败。
7. 多个候选最高分相同时返回歧义错误。
8. aliases 由静态候选数据提供。

### 7.2 RSS 解析

1. 只读取 `static_fixture`。
2. 使用 Python 标准库 XML 解析。
3. `title` 和 `link` 是 item 必需字段。
4. 缺少任一必需字段的 item 被跳过并产生 warning。
5. `published_at` 和 `guid` 可选。
6. 不保留未使用的原始字段。
7. 没有有效 item 时该 RSS 失败；所有 RSS 均失败时流程失败。

### 7.3 条目筛选

1. 使用 Python `re.search`，不声称完全兼容 qBittorrent。
2. 空字符串表示不启用对应规则。
3. 非法正则是配置错误。
4. 先应用 `must_not_contain`，再应用 `must_contain`。
5. 每个被排除条目包含可读原因。

### 7.4 字幕组选择

1. 优先级来自用户配置，不写死在代码中。
2. 只从存在有效种子的 RSS 中选择。
3. 优先级未命中时选择第一个有有效种子的候选并产生 warning。
4. 所有 RSS 均无有效种子时仍生成 Request，但默认字幕组和 RSS 均为 `null`，
   同时产生 warning。

### 7.5 文件夹名

1. 使用匹配后的完整标题。
2. 去除首尾空白。
3. 将 `/`、`\`、NUL 等路径危险字符替换为 `_`。
4. 不使用模板、简称、季数推断或用户覆盖。

## 8. 日志和错误

1. 使用标准库 `logging`。
2. CLI 默认输出控制台日志。
3. 文件日志通过 CLI 参数显式启用。
4. 日志失败不得掩盖原始业务错误。
5. 可预期业务失败转换为 ErrorResult；不建立错误码注册表。

## 9. 验收用例

至少覆盖：

1. 精确标题和别名均可生成 Request。
2. 低于阈值和同分匹配返回错误。
3. RSS 缺字段 item 被跳过且有 warning。
4. 非法 XML 或没有有效 item 时该 RSS 失败。
5. `must_contain`、`must_not_contain` 和非法正则行为正确。
6. 字幕组选择来自用户优先级。
7. 所有 RSS 无有效种子时仍生成未选择字幕组的 Request。
8. 文件夹名危险字符被替换。
9. 端到端离线生成 `PENDING_CONFIRM`。
10. `uv run pytest` 全部通过。

## 10. 完成定义

Stage 1 完成需要同时满足：

- fixture 和用户配置纳入仓库；
- 单元及端到端验收测试通过；
- `uv run migu-orca "番剧名"` 输出 JSON；
- 运行不依赖网络；
- 输出符合第 5 节契约；
- README 能指导开发者运行示例。
