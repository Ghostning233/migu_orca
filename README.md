# MiGuOrca

MiGuOrca 是一个面向动画订阅场景的 RSS 编排工具，目标是在 MiKanProject 与 Auto Bangumi 之间提供一层自动化协作能力。

当前已完成 Stage 3：系统可以基于仓库内静态 MiKan/RSS fixture 生成 Request，支持确认/修改/取消，并在用户显式确认提交时通过离线 Auto Bangumi 契约输出 `ab_submit_result` 或降级 JSON。真实 Auto Bangumi HTTP 调用仍属于下一阶段。

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
- 已建立 Auto Bangumi 提交结果契约、Request 到 AB payload 映射、fake client、失败降级 JSON 和显式配置读取。
- 当前 CLI 的 AB 提交路径仍使用离线 fake client；真实 HTTP adapter、持久化和 Web UI 尚未实现。

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
- 显式执行离线 AB 提交：`uv run migu-orca "咒术回战第三季" --action accept --submit-ab --ab-config config/user/ab-config.example.json`

说明：

- 不要直接使用 `python` 执行测试或脚本。
- 需要新增依赖时，优先通过 `uv add` 或编辑 `pyproject.toml` 后再执行 `uv sync`。
- 所有后续自动化、验证和测试步骤都应默认通过 `uv` 完成。
- `--submit-ab` 必须和 `--action accept`、`--ab-config <path>` 显式组合使用；未传 `--submit-ab` 时不会触发 Auto Bangumi 提交流程。
- AB config JSON 字段为 `endpoint`、`token`、`fallback_enabled`。当前 token 只用于配置契约，不会用于真实网络请求；不要提交真实 token。

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
- 当前活跃阶段：Stage 4，真实 Auto Bangumi HTTP client adapter
- 已归档阶段记录：`scripts/ralph/archive/`
- Ralph 循环命令：`./scripts/ralph/ralph.sh --tool codex 6`

Stage 4 的目标是把 Stage 3 的 fake-client 提交流程替换为可测试的真实 AB HTTP adapter 注入点，同时保持默认 CLI 流程不隐式访问外部系统。

## 参考文档

- [主 PRD](docs/MiGuOrca_main_PRD.md)
- [Stage 1 实现规格](docs/design/stage1-spec.md)
- [架构与目录约定](docs/design/architecture.md)
