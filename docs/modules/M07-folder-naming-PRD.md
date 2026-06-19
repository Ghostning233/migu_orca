# M07 文件夹命名模块 PRD

## 1. 模块目标

M07 根据匹配番剧、推荐字幕组和命名规则生成 Request 中的 expected_folder_name。

## 2. 模块边界

本模块负责：

1. 生成预期文件夹名。
2. 应用番剧简称、季数、Part、字幕组简称等命名信息。
3. 支持用户提供 folder_name_hint 时的覆盖策略，细节待确认。

本模块不负责：

1. 创建真实文件夹。
2. 检查本地媒体库是否存在。
3. 管理历史命名数据库。
4. AB 提交。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| matched_bangumi | object | 是 | 匹配番剧 |
| selected_subtitle_group | string | 是 | 推荐字幕组 |
| folder_name_hint | string/null | 否 | 用户指定文件夹名 |
| naming_rule | object | 否 | 命名规则配置 |

## 4. 输出数据

```json
{
  "expected_folder_name": "[26Win-咒回S3P1-拨雪 (26)]",
  "naming_parts": {
    "season_code": "26Win",
    "title_short_name": "咒回",
    "season_part": "S3P1",
    "subtitle_group_short_name": "拨雪",
    "ab_season_number": "26"
  }
}
```

## 5. 核心流程

1. 接收匹配番剧和字幕组。
2. 若 folder_name_hint 存在，按待确认策略直接使用或校验后使用。
3. 获取季度代码、番剧简称、季数、Part、字幕组简称。
4. 按命名模板生成 expected_folder_name。
5. 返回文件夹名和组成部分。

## 6. 规则定义

1. 第一阶段默认命名格式为 `[26Win-咒回S3P1-拨雪 (26)]`。
2. 第一阶段可以先使用模板化命名。
3. 番剧简称、字幕组简称、季度编号的来源未定稿。
4. 不在第一阶段实现历史命名复用。
5. 生成结果不应包含明显非法路径字符，非法字符处理规则待确认。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 缺少番剧标题 | 返回命名失败 |
| 缺少字幕组 | 返回命名失败 |
| 无法生成简称 | 使用原始标题或返回待确认错误 |
| 季数无法识别 | 可省略季数或使用默认值，待确认 |
| 文件夹名包含非法字符 | 替换或报错待确认 |

## 8. 数据结构

### 8.1 NamingRule

```json
{
  "template": "[{season_code}-{title_short_name}{season_part}-{subtitle_group_short_name} ({ab_season_number})]",
  "title_short_name_map": {},
  "subtitle_group_short_name_map": {}
}
```

### 8.2 FolderNameResult

```json
{
  "expected_folder_name": "[26Win-咒回S3P1-拨雪 (26)]",
  "warnings": []
}
```

## 9. 接口定义

```text
generate_folder_name(matched_bangumi, selected_subtitle_group, folder_name_hint = null, naming_rule = null) -> folder_name_result
```

## 10. 验收标准

1. 能输出非空 expected_folder_name。
2. 默认输出与本文档第一阶段默认命名格式兼容。
3. 不创建真实文件夹。
4. 缺少必要字段时返回明确错误。
5. 未确认命名细则进入待确认问题。

## 11. 已确认事项与待确认问题

### 11.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M07-01 | 第一阶段默认命名模板 | `[26Win-咒回S3P1-拨雪 (26)]` 结构 |

### 11.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M07-02 | 番剧简称由系统生成还是用户维护？ | 是 | 待确认 |
| Q-M07-03 | 季数、Part、分割放送如何识别和表达？ | 是 | 待确认 |
| Q-M07-04 | AB 季度编号如何生成？ | 是 | 待确认 |
| Q-M07-05 | folder_name_hint 是否直接覆盖系统命名？ | 否 | 待确认 |
