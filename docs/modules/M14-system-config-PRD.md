# M14 系统配置模块 PRD

## 1. 模块目标

管理真正需要变化的系统运行配置，避免把代码常量过早建设成配置系统。

## 2. 当前边界

当前不建立独立 system config engine。Stage 1 提供默认规则读取；Stage 3 增加显式 Auto Bangumi JSON 配置读取；Stage 5 增加显式 MiKan JSON 配置读取。

代码内固定默认路径：

```text
config/system/static_mikan_sources.json
config/user/default_rules.json
```

用户 JSON 只包含：

```json
{
  "filter_rule": {
    "must_contain": "",
    "must_not_contain": ""
  },
  "subtitle_group_priority": ["Loli", "喵萌"]
}
```

## 3. 明确不做

- 环境变量覆盖；
- 多 profile 和配置合并；
- qBittorrent 配置；
- 配置管理 UI；
- 独立 M14 engine。

测试和库调用可以显式传入其他 fixture 路径，这属于依赖注入，不属于配置合并系统。

## 4. 错误处理

配置文件不存在、JSON 非法、字段类型错误或筛选正则非法时返回配置错误，不静默降级。

## 5. 验收

1. 默认路径可以完成离线端到端运行。
2. 测试可以传入临时 fixture 路径。
3. 配置错误具有明确的 ErrorResult。

## 6. 后续阶段

接入真实外部系统后，再根据部署方式确定用户配置目录、环境变量、密钥管理和配置优先级。
