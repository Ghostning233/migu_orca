# MiGuOrca

MiGuOrca 是一个面向动画订阅场景的 RSS 编排工具，目标是在 MiKanProject 与 Auto Bangumi 之间提供一层自动化协作能力。

当前已完成 Stage 4：系统可以基于仓库内静态 MiKan/RSS fixture 生成 Request，支持确认/修改/取消，并在用户显式确认提交时通过真实 Auto Bangumi HTTP adapter 输出 `ab_submit_result` 或降级 JSON。默认生成和确认流程仍不会隐式访问外部系统。

## 项目目标

MVP 聚焦单番剧的订阅闭环：

1. 接收一个番剧名称。
2. 搜索并分析 MiKanProject 数据。
3. 生成可确认的 Request。
4. 用户确认后提交到 Auto Bangumi，或在失败时导出 JSON 形式的降级配置。

## 目前状态

- 默认流程不访问真实 MiKanProject、Auto Bangumi 或 qBittorrent。
- 已支持标题匹配、RSS 解析、正则筛选、字幕组选择、目录命名和 JSON 输出。
- 已支持 Request 确认、取消和受限修改；确认后的 Request 可以进入显式 AB 提交流程。
- 已建立 Auto Bangumi 提交结果契约、Request 到 AB payload 映射、fake client、真实 HTTP client adapter、失败降级 JSON 和显式配置读取。
- 当前 CLI 只有在显式传入 `--submit-ab` 和 `--ab-config` 时才会构造真实 Auto Bangumi HTTP client；真实 MiKan 访问、持久化和 Web UI 尚未实现。

## 关键约定

- Python 包名：`migu_orca`
- CLI 命令：`migu-orca`
- 配置目录：`~/.config/migu_orca`
- 日志名：`migu_orca`

## 开发约定

本项目使用 `UV` 进行 Python 包管理和命令执行。

- 安装依赖：`uv sync`
- 运行测试：`uv run pytest`
- 运行入口命令：`uv run migu-orca "咒术回战第三季"`
- 接受 Request：`uv run migu-orca "咒术回战第三季" --action accept`
- 显式执行真实 AB 提交：`uv run migu-orca "咒术回战第三季" --action accept --submit-ab --ab-config config/user/ab-config.example.json`

说明：

- 不要直接使用 `python` 执行测试或脚本。
- 需要新增依赖时，优先通过 `uv add` 或编辑 `pyproject.toml` 后再执行 `uv sync`。
- 所有后续自动化、验证和测试步骤都应默认通过 `uv` 完成。
- `--submit-ab` 必须和 `--action accept`、`--ab-config <path>` 显式组合使用；未传 `--submit-ab` 时不会触发 Auto Bangumi 提交流程，也不会实例化真实 HTTP client。
- AB config JSON 字段为 `endpoint`、`token`、`fallback_enabled`：
  - `endpoint`：Auto Bangumi 创建订阅的 HTTP endpoint，由部署方显式提供。
  - `token`：用于 `Authorization: Bearer <token>` 请求头。不要提交真实 token，错误 details、日志和测试快照也不得包含 token 明文。
  - `fallback_enabled`：提交失败时是否在 `ab_submit_result.fallback_config` 中输出可人工处理的降级 JSON。
- 真实 AB client 当前发送的创建订阅 payload 字段为 `title`、`rss_url`、`save_path`、`filter_rule`，并要求响应中包含 `id`、`subscription_id` 或 `ab_subscription_id` 之一。真实 Auto Bangumi API 的 endpoint、请求字段和响应字段仍需要按实际部署版本验证。

示例 AB 配置：

```json
{
  "endpoint": "http://auto-bangumi.local",
  "token": "replace-with-token",
  "fallback_enabled": true
}
```

## Ralph 开发流

- 当前活跃 Ralph PRD：`scripts/ralph/prd.json`
- 当前活跃阶段：Stage 5，真实 MiKanProject 数据源 adapter PRD
- 已归档阶段记录：`scripts/ralph/archive/`
- Ralph 循环命令：`./scripts/ralph/ralph.sh --tool codex 6`

Stage 5 的目标是在 Stage 4 真实 AB 提交链路基础上，增加显式启用、可注入 transport、离线可测的真实 MiKanProject 数据源 adapter，同时保持默认 CLI 流程继续使用静态 fixture。

## 参考文档

- [主 PRD](docs/MiGuOrca_main_PRD.md)
- [Stage 1 实现规格](docs/design/stage1-spec.md)
- [架构与目录约定](docs/design/architecture.md)
