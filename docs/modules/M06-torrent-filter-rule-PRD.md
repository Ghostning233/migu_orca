# M06 种子筛选规则模块 PRD

## 1. 模块目标

M06 负责根据用户配置的筛选规则从 RSS 种子列表中计算有效种子，并输出被排除种子的原因。

有效种子由本模块统一定义：按筛选规则去除重复种子、无效种子和不符合规则种子后，最终保留下来的种子。

## 2. 模块边界

本模块负责：

1. 识别种子是否符合用户配置的筛选规则。
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
  "valid_seed_count": 11,
  "invalid_seed_count": 1,
  "valid_seed_names": [
    "[Loli] 咒术回战 第三季 - 04 [1080p][CHS].mkv"
  ],
  "excluded_seed_names": [
    {
      "name": "[Loli] 咒术回战 第三季 - 04 V2 [1080p][CHS].mkv",
      "reason": "命中排除规则：V2",
      "rule": "must_not_contain"
    }
  ]
}
```

## 5. 核心流程

1. 接收一个 RSS 下的 seeds。
2. 对每个种子名称应用“必须包含”规则。
3. 对每个种子名称应用“必须不含”规则。
4. 输出有效种子和排除原因。

## 6. 规则定义

M06 借用 qBittorrent 的“必须包含”和“必须不含”概念。Stage 15 起默认语义为**普通字符（字面文本）匹配且大小写不敏感**；正则匹配改为 `use_regex=true` 时的显式选项，不声明与 qBittorrent 完全兼容。

项目本身不内置默认筛选规则。筛选规则需要用户自行配置和管理。

用户配置示例：

```json
{
  "must_contain": "1080p",
  "must_not_contain": "[v2]",
  "use_regex": false,
  "case_sensitive": false
}
```

规则约束：

1. `must_contain` 为空时，不启用必须包含限制。
2. `must_not_contain` 为空时，不启用必须不含限制。
3. `use_regex=false`（默认）时，`must_contain` 和 `must_not_contain` 按字面子串匹配，不编译为正则；输入 `[`、`[v2]` 等字符不得触发正则错误。
4. `use_regex=true` 时，`must_contain` 和 `must_not_contain` 使用 Python `re.search`；非法正则返回统一校验错误。
5. `case_sensitive=false`（默认）时，字面匹配和正则匹配都大小写不敏感；`case_sensitive=true` 时区分大小写。
6. 先应用 `must_not_contain`，再应用 `must_contain`。
7. 项目不根据分辨率、字幕语言、集数、v2/v3、合集等内置默认筛选规则。
8. 如用户希望排除 V2、V3、合集等内容，应写入 `must_not_contain`。
9. 每个被排除种子必须输出可读 reason：命中排除规则为 `命中排除规则：<rule>`，未命中包含规则为 `未命中包含规则：<rule>`。
10. 旧配置或旧保存 Request 缺少 `use_regex` / `case_sensitive` 时，按默认 `false` 兼容加载。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| seeds 为空 | 返回 total_seed_count 为 0 |
| 种子名称为空 | 排除并标记名称缺失 |
| must_contain 不匹配 | 排除并标记 `未命中包含规则：<rule>` |
| must_not_contain 命中 | 排除并标记 `命中排除规则：<rule>` |
| 所有种子被排除 | 返回空 valid_seed_names 和排除原因 |
| filter_rule 缺字段 | 返回配置错误 |
| use_regex=true 且规则为非法正则 | 返回统一校验错误 |
| use_regex=false 且输入含 `[` 等字符 | 按字面匹配处理，不触发正则错误 |

## 8. 数据结构

### 8.1 FilterRule

```json
{
  "must_contain": "1080p",
  "must_not_contain": "[v2]",
  "use_regex": false,
  "case_sensitive": false
}
```

### 8.2 ExcludedSeed

```json
{
  "name": "[字幕组] 番名 - 04 V2.mkv",
  "reason": "命中排除规则：V2",
  "rule": "must_not_contain"
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
4. 项目不内置默认筛选规则。
5. 能通过用户配置的 `must_contain` 和 `must_not_contain` 完成筛选。
6. 不把 v2/v3 等规则写死为项目默认规则。

## 11. 已确认事项与待确认问题

### 11.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M06-01 | 筛选逻辑 | 默认按普通字符（字面文本）子串匹配且大小写不敏感；`use_regex=true` 时使用 Python `re.search` |
| D-M06-02 | 项目默认筛选规则 | 项目不内置默认筛选规则，规则由用户自行配置和管理 |
| D-M06-03 | 用户规则示例 | `must_contain = "1080p"`、`must_not_contain = "[v2]"`、`use_regex=false`、`case_sensitive=false` |

### 11.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M06-04 | qBittorrent 规则语义在代码中采用正则还是完全兼容 qBittorrent 实现？ | 否 | 已确认：默认字面匹配，正则由 `use_regex` 显式启用，不声明与 qBittorrent 完全兼容 |
