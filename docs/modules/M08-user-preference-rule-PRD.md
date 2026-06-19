# M08 用户偏好与规则配置模块 PRD

## 1. 模块目标

M08 负责提供第一阶段 Request 生成所需的用户偏好和规则配置。第一阶段项目不内置默认筛选规则，筛选规则由用户自行配置和管理。

## 2. 模块边界

本模块负责：

1. 提供用户筛选规则读取能力。
2. 提供默认命名规则。
3. 提供字幕组偏好配置。
4. 提供单番特殊配置的预留结构。

本模块不负责：

1. Web UI 配置管理。
2. 数据库持久化。
3. 真实用户认证。
4. 规则执行本身。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| profile_name | string | 否 | 配置 profile 名，第一阶段可固定 default |
| raw_title | string | 否 | 用于读取单番特殊配置 |

## 4. 输出数据

```json
{
  "filter_rule": {
    "must_contain": "",
    "must_not_contain": ""
  },
  "naming_rule": {
    "template": "{title}"
  },
  "subtitle_group_preference": []
}
```

## 5. 核心流程

1. 加载默认配置。
2. 如存在用户配置，则覆盖默认配置。
3. 如存在单番特殊配置，则覆盖全局配置。
4. 返回合并后的规则对象。

## 6. 规则定义

1. 第一阶段项目不内置默认筛选规则。
2. 第一阶段可使用内置空规则；如使用配置文件，优先使用 JSON。
3. 规则合并优先级建议为：单番特殊配置 > 用户配置 > 系统默认配置。
4. M08 只提供规则，不执行筛选或命名。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 配置文件不存在 | 使用内置默认配置 |
| 配置格式错误 | 返回配置错误或降级默认配置，待确认 |
| 配置字段类型错误 | 返回校验错误 |
| 单番配置冲突 | 按优先级覆盖或报错待确认 |

## 8. 数据结构

### 8.1 UserPreference

```json
{
  "must_contain": "",
  "must_not_contain": "",
  "preferred_subtitle_groups": [],
  "blocked_subtitle_groups": [],
  "naming_template": "{title}"
}
```

## 9. 接口定义

```text
load_user_preference(profile_name = "default") -> user_preference
get_filter_rule(raw_title = null) -> filter_rule
get_naming_rule(raw_title = null) -> naming_rule
```

## 10. 验收标准

1. 无用户配置时能返回空筛选规则。
2. 筛选规则结构与 M06 第一阶段 `must_contain` / `must_not_contain` 结构一致。
3. 配置错误时能给出明确错误或降级行为。
4. 输出可供 M05、M06、M07 使用。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M08-01 | 用户偏好配置文件放在哪个路径？ | 否 | 暂参考 `~/.config/migu_orca` |
| Q-M08-02 | 配置格式是否固定 JSON？ | 否 | 暂按 JSON 草案 |
| Q-M08-03 | 配置错误时应失败还是降级默认配置？ | 否 | 待确认 |
| Q-M08-04 | 单番特殊配置第一阶段是否实现？ | 否 | 暂作为预留 |
