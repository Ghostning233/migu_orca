# M08 用户偏好与规则配置模块 PRD

## 1. 模块目标

M08 负责提供 Request 生成和 Stage 21 批量草案工作台所需的用户偏好和规则配置。第一阶段项目不内置默认筛选规则；Stage 21 允许用户显式保存非敏感默认偏好，并将其作为草案生成的默认值。

## 2. 模块边界

本模块负责：

1. 提供用户筛选规则读取能力。
2. 提供默认命名规则和 Stage 21 文件夹命名策略。
3. 提供字幕组偏好配置、排除列表和 fallback 规则。
4. 提供单番特殊配置的预留结构。

本模块不负责：

1. Web UI 配置管理。
2. 数据库持久化；当前继续使用安全的本地 JSON 偏好存储。
3. 真实用户认证。
4. 规则执行本身。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| path | string | 是 | Stage 1 用户 JSON 路径 |

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

1. 从固定仓库路径加载用户 JSON。
2. 校验筛选规则和字幕组优先级。
3. 返回用户规则对象。

## 6. 规则定义

1. 第一阶段项目不内置默认筛选规则。
2. Stage 1 固定使用 JSON。
3. 配置不存在或非法时返回配置错误，不静默降级。
4. Stage 1 不实现 profile、单番覆盖和命名模板；Stage 21 只实现单一用户默认偏好，不引入复杂 profile。
5. M08 只提供规则，不执行筛选。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 配置文件不存在 | 返回配置错误 |
| 配置格式错误 | 返回配置错误 |
| 配置字段类型错误 | 返回校验错误 |

## 8. 数据结构

### 8.1 UserPreference

```json
{
  "filter_rule": {
    "must_contain": "",
    "must_not_contain": ""
  },
  "subtitle_group_priority": ["Loli", "喵萌"]
}
```

## 9. 接口定义

```text
load_user_preference(path) -> user_preference
```

## 10. 验收标准

1. 合法用户配置能返回筛选规则和字幕组优先级。
2. 筛选规则结构与 M06 第一阶段 `must_contain` / `must_not_contain` 结构一致。
3. 配置错误时返回明确错误。
4. 输出可供 M05、M06 使用。
5. Stage 21 偏好存储只允许字幕组、筛选、命名和搜索修正等非敏感字段，不允许外部 endpoint、token、cookie、Authorization header 或原始响应。

## 11. 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M08-01 | 用户偏好配置文件放在哪个路径？ | 否 | 已确认：仓库内 config/user/default_rules.json |
| Q-M08-02 | 配置格式是否固定 JSON？ | 否 | 已确认：Stage 1 固定 JSON |
| Q-M08-03 | 配置错误时应失败还是降级默认配置？ | 否 | 已确认：失败 |
| Q-M08-04 | 单番特殊配置第一阶段是否实现？ | 否 | 已确认：不实现 |
