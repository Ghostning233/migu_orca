# 我的追番数值基线（Issue 115 起）

## 0. 状态与用途

| 项目 | 内容 |
| --- | --- |
| 状态 | **已建立（2026-09-24，#115）**；本文件是「我的追番」页面族的数值布局基线 |
| 依据 | GitHub Issue #115（父规格 #107）；冻结 Token V1；壳层基线见[壳层数值基线](frontend-ux-shell-geometry-baseline.md) |
| 范围 | 状态总览、左侧追番列表、右侧追番详情的固定高度与内部滚动；提交与外部管理层级在 #116 扩展 |
| 位图角色 | 设计 PNG 仅作人工对照，不设像素差硬门禁（裁决 3C） |

## 1. 布局与滚动

| 量 | 值 | 来源 |
| --- | --- | --- |
| 页面外壳 | 沿用一级页面容器（壳层档位内边距，导航与状态总览留在滚动区外） | 壳层基线 |
| 状态总览 | 固定五项分类卡片 + 服务端总数，位于工作台之上，不随列表/详情滚动 | 既有 #85/#99 语义 |
| 双栏 | `minmax(0, 3fr)` / `minmax(18rem, 2fr)`，间距 `--space-5` | 既有页面几何 |
| 列表/详情可用高度 | `--tracking-panel-max-height: clamp(320px, calc(100vh - 420px), 640px)` | 由视口推导；420 为导航、状态总览与页内边距的固定 chrome 余量 |
| 列表滚动 | `#tracking-list-container`（面板标题与筛选在其外）：`max-height: var(--tracking-panel-max-height)`、`overflow-y: auto`、`overscroll-behavior: contain` | 长列表只在栏内滚动 |
| 详情滚动 | `.tracking-inspector`：同样的 `max-height`、`overflow-y: auto`、`overscroll-behavior: contain`，桌面下 `position: sticky; top: --space-4` | 长详情只在栏内滚动 |
| 窄视口 | `max-width: 800px` 时单列堆叠，栏高降为 320px，详情不再 sticky | 可达性 |

列表达到可用高度后整页不再增长；展开记录、操作记录或诊断只改变栏内滚动位置，
另一列与状态总览的屏幕位置保持不变。

## 2. 状态与占位

- 代表状态「追番中／待提交／结果未知」与提交前复核失败继续使用既有服务端安全投影的中文摘要，不合并成统一警告。
- 总集数与「已更新集数」在无可信服务端值时都显示「未知」（Issue #131），绝不从有效资源数、种子、RSS 或下载数量推断。
- 状态、允许动作与作用范围全部来自服务端投影；未知值 fail closed，不显示外部 ID、完整 RSS URL 或秘密。

## 3. 外部写的连接门控（Issue 116）

| 状态 | 行为 |
| --- | --- |
| 无已保存 AB 连接或所需凭据 | 「提交方案」「重试提交」、批量提交、修改／启停／刷新／删除外部订阅**可见但禁用**，原处提示「先在设置中连接 Auto Bangumi；缺少已保存连接时不会发起任何外部写。」不弹确认、不发请求 |
| 已有已保存连接 | 一律可用；最近一次探测失败或能力诊断为空**不**作为前端准入门槛，由服务端在请求内复核连接、认证、精确版本与能力 |
| 纯本地操作 | 修改本地方案、本地复核等不依赖连接，继续可用 |
| 结果未知／未决外部意图 | 只提供核验与恢复；只读外部核验需要已保存连接，其余恢复分支不依赖探测结果 |

危险操作（外部删除）保留显式确认，请求固定 `file=false`，绝不删除已下载媒体。

## 4. 验证命令

```bash
cd frontend && npm run typecheck && npm run lint && npm run test:unit -- --run
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_tracking_overview.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_tracking_workbench.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_tracking_submit_hierarchy.py -q
```
