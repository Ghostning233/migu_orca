# M14 系统配置模块 PRD

## 1. 模块目标

管理真正需要变化的系统运行配置，避免把代码常量过早建设成配置系统。

2026-09-13 产品修订：[Stage 39](../MiGuOrca_stage39_deployment_settings_PRD.md)目标为仅 AB 的专用
部署配置持久化，跨页/刷新/重启保留，秘密不进入业务文件或公开 DTO；MiKan 搜索由服务端封装，
qB 独立连接测试退役。该阶段尚未实现，下文“当前边界”仍描述既有代码，旧凭据全面禁止持久化
规则不适用于新增 AB 私有配置例外；不因此新增通用 system-config engine。

## 2. 当前边界

当前不建立独立 system config engine。Stage 1 提供默认规则读取；Stage 3 增加显式 Auto Bangumi JSON 配置读取；Stage 5 增加显式 MiKan JSON 配置读取；Stage 12 增加 qBittorrent 显式连接测试配置边界。

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
- qBittorrent 全局持久化配置；
- 配置管理 UI；
- 独立 M14 engine。

测试、库调用和 Web API 可以显式传入其他 fixture 路径或 request-scoped 外部系统配置，这属于依赖注入或当前请求配置，不属于配置合并系统。真实 MiKan、Auto Bangumi 与 qBittorrent 的 endpoint、token、username、password、cookie 或 SID 不应写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或测试 trace。

## 4. 错误处理

配置文件不存在、JSON 非法、字段类型错误或筛选正则非法时返回配置错误，不静默降级。

## 5. 验收

1. 默认路径可以完成离线端到端运行。
2. 测试可以传入临时 fixture 路径。
3. 配置错误具有明确的 ErrorResult。

## 6. 后续阶段

接入真实外部系统后，再根据部署方式确定用户配置目录、环境变量、密钥管理和配置优先级；相关配置/部署向导可行性登记为远期 backlog BL-014。

## 7. Stage 24 AutoBangumi request-scoped 配置（已完成）

1. `auth_mode=password` 为默认，字段为 `base_url`、`username`、`password`；`auth_mode=api_token` 字段为 `base_url`、`token`。
2. 两种模式字段互斥；base_url 仅允许 http/https 根地址，拒绝 userinfo、query、fragment，允许用户明确提供的局域网地址。
3. 凭据只存在于当前 Web/CLI 请求和 client session，不进入配置目录、Request、队列、AB result、浏览器 storage、URL、日志或 trace。
4. `fallback_enabled` 仍是 MiGuOrca 提交失败后的降级行为开关，不属于 AutoBangumi 认证字段。

## 8. Stage 26 Web storage 根目录配置（已完成）

1. Web API 的 `storage_dir` 只能选择服务端根目录下的**相对 profile**；未传时回落服务端根本身（默认 `.migu_orca/storage`）。
2. 服务端根可用 `MIGU_ORCA_WEB_STORAGE_ROOT` 环境变量覆盖（仅服务端可信配置，浏览器不可控）；绝对路径、`..` 穿越与符号链接逃逸统一返回 400 `invalid_storage_dir`，错误不回显原始路径。
3. CLI `--storage-dir` 是独立信任边界，接受显式本地路径，不受 Web 解析器约束。
