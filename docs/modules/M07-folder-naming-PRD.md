# M07 文件夹命名模块 PRD

## 1. 模块目标

M07 根据匹配番剧生成 Request 中的 expected_folder_name。

第一阶段直接使用匹配番剧全名作为文件夹名，用于跑通核心逻辑。

## 2. 模块边界

本模块负责：

1. 生成预期文件夹名。
2. 第一阶段直接使用匹配番剧全名。
3. 为后续命名模板、简称、季度编号和用户覆盖预留扩展空间。

本模块不负责：

1. 创建真实文件夹。
2. 检查本地媒体库是否存在。
3. 管理历史命名数据库。
4. AB 提交。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| matched_bangumi | object | 是 | 匹配番剧 |
| selected_subtitle_group | string | 否 | 推荐字幕组，第一阶段不参与命名 |
| folder_name_hint | string/null | 否 | 用户指定文件夹名，第一阶段暂不覆盖系统命名 |
| naming_rule | object | 否 | 命名规则配置，第一阶段暂不使用 |

## 4. 输出数据

```json
{
  "expected_folder_name": "咒术回战 第三季",
  "naming_parts": {
    "title": "咒术回战 第三季"
  }
}
```

## 5. 核心流程

1. 接收匹配番剧。
2. 读取 matched_bangumi.title。
3. 将 matched_bangumi.title 作为 expected_folder_name。
4. 返回文件夹名和组成部分。

## 6. 规则定义

1. 第一阶段直接使用番剧全名作为文件夹名。
2. 番剧全名来源为 M02 输出的 matched_bangumi.title。
3. 第一阶段不使用番剧简称、字幕组简称、季度编号、季数、Part 或命名模板。
4. 第一阶段不使用 folder_name_hint 覆盖系统命名。
5. 不在第一阶段实现历史命名复用。
6. 去除标题首尾空白，将 `/`、`\`、NUL 等路径危险字符替换为 `_`。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 缺少番剧标题 | 返回命名失败 |
| 缺少字幕组 | 不影响第一阶段命名 |
| matched_bangumi.title 为空 | 返回命名失败 |
| 文件夹名包含危险路径字符 | 替换为 `_` |

## 8. 数据结构

### 8.1 NamingRule

```json
{
  "template": "{title}",
  "title_short_name_map": {},
  "subtitle_group_short_name_map": {}
}
```

### 8.2 FolderNameResult

```json
{
  "expected_folder_name": "咒术回战 第三季",
  "warnings": []
}
```

## 9. 接口定义

```text
generate_folder_name(matched_bangumi, selected_subtitle_group, folder_name_hint = null, naming_rule = null) -> folder_name_result
```

## 10. 验收标准

1. 能输出非空 expected_folder_name。
2. 默认输出等于匹配番剧全名。
3. 不创建真实文件夹。
4. 缺少必要字段时返回明确错误。
5. 危险路径字符会被安全替换。

## 11. 已确认事项与待确认问题

### 11.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M07-01 | 第一阶段文件夹命名规则 | 直接使用 matched_bangumi.title，即番剧全名 |
| D-M07-06 | 危险字符处理 | 去除首尾空白，将 `/`、`\`、NUL 替换为 `_` |

### 11.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| Q-M07-02 | 后续番剧简称由系统生成还是用户维护？ | 否 | BL-018 定义解析与人工审核边界 |
| Q-M07-03 | 后续季数、Part、分割放送如何识别和表达？ | 否 | BL-018 定义稳定季数契约；不能证明时人工审核 |
| Q-M07-04 | 后续 AB 季度编号如何生成？ | 否 | BL-018 只提供可证明的结构化季数，M10 继续 fail closed |
| Q-M07-05 | 后续 folder_name_hint 是否直接覆盖系统命名？ | 否 | 后续阶段定义 |
