# M14 系统配置模块 PRD

## 1. 模块目标

M14 负责管理系统级配置。第一阶段仅保留 Request 生成链路必要配置，例如静态数据路径、日志配置和运行环境配置。

第一阶段系统配置文件固定按 JSON 处理，默认配置目录为 `~/.config/migu_orca`。静态数据路径由 M14 统一提供，M03 只消费配置结果。

## 2. 模块边界

本模块负责：

1. 提供系统级配置读取能力。
2. 提供环境变量覆盖规则。
3. 提供静态 RSS 模拟数据路径配置。
4. 提供日志配置。
5. 提供第一阶段默认输出格式配置。

本模块不负责：

1. Auto Bangumi 地址配置的实际使用。
2. qBittorrent 配置。
3. 用户偏好规则。
4. 配置管理 UI。
5. 第一阶段 AB、qBittorrent 配置校验。

## 3. 输入数据

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| config_path | string/null | 否 | 系统配置路径 |
| env | object | 否 | 环境变量 |

## 4. 输出数据

```json
{
  "config_dir": "~/.config/migu_orca",
  "config_format": "json",
  "static_mikan_data_path": "config/system/static_mikan_sources.json",
  "log_dir": "logs/",
  "log_level": "INFO",
  "log_console_enabled": true,
  "output_default_format": "json"
}
```

## 5. 核心流程

1. 加载默认系统配置。
2. 读取配置文件。
3. 应用 `MIGU_ORCA_` 前缀环境变量覆盖。
4. 校验第一阶段必要字段。
5. 不校验 AB、qBittorrent 配置。
6. 返回系统配置对象。

## 6. 规则定义

1. 环境变量前缀沿用主 PRD：`MIGU_ORCA_`。
2. 配置目录沿用主 PRD：`~/.config/migu_orca`。
3. 第一阶段不要求 AB、qBittorrent 配置可用。
4. 第一阶段必须支持静态数据源相关配置或默认路径。
5. 第一阶段配置格式固定为 JSON。
6. 静态数据路径由 M14 统一管理，M03 不自行决定系统配置来源。
7. AB、qBittorrent 配置不作为第一阶段必要字段。

## 7. 异常场景

| 场景 | 处理方式 |
| --- | --- |
| 配置文件不存在 | 使用默认配置 |
| 配置格式错误 | 返回配置错误 |
| 必要路径不存在 | 返回配置校验错误或由调用方决定是否创建 |
| 环境变量值非法 | 返回配置校验错误 |

## 8. 数据结构

```json
{
  "system_config": {
    "config_dir": "~/.config/migu_orca",
    "config_format": "json",
    "static_mikan_data_path": "config/system/static_mikan_sources.json",
    "log_dir": "logs/",
    "log_level": "INFO",
    "log_console_enabled": true,
    "output_default_format": "json"
  }
}
```

## 9. 接口定义

```text
load_system_config(config_path = null) -> system_config
validate_system_config(system_config) -> validation_result
```

## 10. 验收标准

1. 无配置文件时能返回第一阶段可用默认配置。
2. 能通过环境变量覆盖关键配置。
3. 不要求 AB 或 qBittorrent 配置存在。
4. 配置错误时返回明确错误。
5. 输出可供 M03、M12、M00 使用。
6. 静态数据路径由 M14 输出，并可被 M03 消费。

## 11. 已确认事项与待确认问题

### 11.1 已确认事项

| 编号 | 事项 | 当前结论 |
| --- | --- | --- |
| D-M14-01 | 系统配置文件路径和格式 | 第一阶段按 JSON 和 `~/.config/migu_orca` 处理 |
| D-M14-02 | 静态数据路径归属 | 由 M14 提供，M03 消费配置结果 |
| D-M14-03 | AB、qBittorrent 配置是否进入第一阶段必要字段 | 不作为第一阶段必要字段，也不做可用性校验 |

### 11.2 待确认问题

| 编号 | 问题 | 是否阻塞定稿 | 当前处理 |
| --- | --- | --- | --- |
| 无 | 暂无 | 否 | - |
