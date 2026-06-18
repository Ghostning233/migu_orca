# MiGuOrca

MiGuOrca 是一个面向动画订阅场景的 RSS 编排工具，目标是在 MiKanProject 与 Auto Bangumi 之间提供一层自动化协作能力。

当前项目仍处于需求与 PRD 优化阶段，功能开发尚未开始。本仓库的主需求文档位于 [docs/MiGuOrca_main_PRD.md](docs/MiGuOrca_main_PRD.md)。

## 项目目标

MVP 聚焦单番剧的订阅闭环：

1. 接收一个番剧名称。
2. 搜索并分析 MiKanProject 数据。
3. 生成可确认的 Request。
4. 用户确认后提交到 Auto Bangumi，或在失败时导出 JSON 形式的降级配置。

## 目前状态

- 项目处于规划阶段，核心模块尚未实现。
- 需求定义以主 PRD 为准，后续模块 PRD 会在此基础上拆分。
- 现阶段优先完善需求、边界、数据结构和流程定义，再进入开发。

## 关键约定

- Python 包名：`migu_orca`
- CLI 命令：`migu-orca`
- 配置目录：`~/.config/migu_orca`
- 环境变量前缀：`MIGU_ORCA_`
- 日志名：`migu_orca`

## 开发约定

本项目使用 `UV` 进行 Python 包管理和命令执行。

- 安装依赖：`uv sync`
- 运行测试：`uv run pytest`
- 运行入口命令：`uv run migu-orca`

说明：

- 不要直接使用 `python` 执行测试或脚本。
- 需要新增依赖时，优先通过 `uv add` 或编辑 `pyproject.toml` 后再执行 `uv sync`。
- 所有后续自动化、验证和测试步骤都应默认通过 `uv` 完成。

## 参考文档

- [主 PRD](docs/MiGuOrca_main_PRD.md)

