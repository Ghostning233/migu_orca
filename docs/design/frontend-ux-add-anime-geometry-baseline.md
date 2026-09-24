# 添加番剧数值基线（Issue 110 起）

## 0. 状态与用途

| 项目 | 内容 |
| --- | --- |
| 状态 | **已建立（2026-09-24，#110）**；本文件是「添加番剧」页面族的数值布局基线 |
| 依据 | GitHub Issue #110（父规格 #107）；冻结 Token V1；壳层基线见[壳层数值基线](frontend-ux-shell-geometry-baseline.md) |
| 范围 | 单番搜索首屏 + 候选工作台的上下两屏结构；批量工作台与草案审核在本文件后续小节扩展 |
| 位图角色 | 设计 PNG 仅作人工对照，不设像素差硬门禁（裁决 3C） |

数值来源规则：所有间距/尺寸/字号取冻结 Token；Token 未覆盖的页面专属量在本文逐项标注，
只用 Token 阶梯组合得出。可审核断言是 `tests/browser/test_app_single_candidate_geometry.py`
与 `tests/browser/test_app_single_two_screen.py`。

## 1. 两屏结构与滚动

| 量 | 值（1440×900） | 来源 |
| --- | --- | --- |
| 顶栏 | `y 0..72` | `--size-shell-header` |
| 两屏滚动容器 | `x 32..1408`（宽 1376）、高 `100vh − 72 − 2×--space-6` = 780 | 壳层档位内边距 + Token |
| 滚动吸附 | `scroll-snap-type: y proximity`；每屏 `scroll-snap-align: start` | 设计「轻柔吸附」 |
| 模块内滚动 | `overflow-y: auto` + `overscroll-behavior: contain` | 内部滚到边界不触发切屏 |
| 搜索首屏 | 720px 宽居中（`x 360..1080`），内容在屏内垂直居中 | Stage 47 获批页面专属宽度 |
| 候选工作台屏 | 宽 1376、高 780；内容自屏顶起 | 内容容器宽 |

成功后自动滚到第二屏并把键盘焦点移到结果标题（`#candidate-search-heading`，`tabindex="-1"`）；
「返回搜索首屏」（`#mikan-back-to-search`，高 44）只滚动与聚焦，**不清空**下方未保存的候选。
失败与无候选都留在首屏：就地反馈 + 一个 44px 的次级动作（重试／重新搜索），直连救援入口默认收起。
缩减动态效果下滚动行为为 `auto`。

## 2. 候选行（1～4 项同排居中）

| 量 | 值 | 来源 |
| --- | --- | --- |
| 卡片宽 | `332px` | 页面专属：`(1376 − 3×--space-4) / 4` |
| 卡片间距 | `--space-4` 16px | Token |
| 行对齐 | `justify-content: center`，卡片同宽、不拉伸 | 设计「同排居中、宽度不拉伸」 |
| 卡片布局 | 竖排：封面在上，标题/证据/主操作在下 | 设计图 02 |
| 封面 | 宽 300（332 − 2×15 内边距 − 2×1 边框）、`aspect-ratio: 16 / 9` | 页面专属比例 |
| 主操作 | 「选择此合集」占满卡片内容宽 | 设计图 02 |
| 数量上限 | 最多渲染 4 项；超出只显示前 4 项 + 简短截断提示 | 用户故事 10 |
| 窄视口 | 卡片最小 240px，不足时换行；不横向溢出 | 200% 缩放可达性 |

1280 档内容宽 1232，三张 332px 卡片仍同排居中；1920 档内容宽 1416，四张卡片保持 332px 居中不拉伸。

## 3. 草案审核屏（Issue 111）

| 量 | 值 | 来源 |
| --- | --- | --- |
| 屏高 | 与第二屏一致（780） | 同 `.add-screen` |
| 内容面板 | `.draft-scroll-panel`：`flex: 1`、`overflow-y: auto`、`overscroll-behavior: contain` | 长草案在面板内滚动 |
| 面板几何 | 身份区 `x 32`、`y 96`、宽 1376；左栏 480、右栏 872、间距 24 | Stage 47 获批审核几何，Issue 111 保留 |
| 屏内边距 | 草案屏 `padding-block: 0` | 不改变既有审核锚点 |
| 主操作 | 「保存并确认」`#single-review-save-button` | 既有契约 |

选择候选只把第二屏从候选状态切换为草案状态，不新开路由或第三屏；草案资源数只在草案阶段出现；
「重新选择合集」（`#single-review-back-candidates`）确认后回到同屏候选状态并保留搜索结果。
长草案不撑长整页：整页高度等于视口，滚动发生在内容面板内部。

## 4. 与现行设计图的差异（仅记录）

| 量 | 设计图实测（归一化 1440） | 本基线 |
| --- | --- | --- |
| 结果标题字号 | 约 40px 视觉 | `--type-display` 40px |
| 卡片宽度 | 图 02 四张铺满内容宽 | 332px × 4 = 1328，居中留白 |
| 图 03 尺寸标注 | 仅示意，未按比例 | 以本表实现测量为准 |

## 5. 验证命令

```bash
cd frontend && npm run typecheck && npm run lint && npm run test:unit -- --run
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_single_candidate_geometry.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_single_two_screen.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_single_draft_screen.py -q
```
