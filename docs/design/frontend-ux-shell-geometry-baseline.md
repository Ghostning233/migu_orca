# Issue 109 共用壳层数值基线（已建立）

## 0. 状态与用途

| 项目 | 内容 |
| --- | --- |
| 状态 | **已建立（2026-09-24）**；本文件是三项一级导航共用壳层的正式数值基线 |
| 依据 | GitHub Issue #109（父规格 #107）；`docs/design/frontend-ux-design-tokens-v1.md`（冻结 Token V1） |
| 前置 | #108 设计修订经 PR #118 合并；设计门禁解除 |
| 范围 | 只交付共用壳层：导航、视口、页头与页面容器；不重做各业务页面内容 |
| 位图角色 | 设计 PNG 仅作人工对照。像素差异只输出诊断，不是硬门禁（裁决 3C，见 `tests/browser/visual_manifest.py`） |

数值来源规则：**所有间距/尺寸/颜色一律取冻结 Token**；Token 未覆盖的页面专属量只用
Token 阶梯组合得出，不引入第二套视觉常量。可审核断言是
`tests/browser/visual_manifest.py::shell_anchors_for(width)`，由
`tests/browser/test_app_shell_visual.py` 在真实 Chromium 中核对。

## 1. 冻结约束（不得改变）

| Token | 值 | 本基线用法 |
| --- | --- | --- |
| `--top-nav-height` / `--size-shell-header` | `72px` | 顶栏高度，页面内容自 y=72 起 |
| `--content-max` / `--size-content-max` | `1512px` | 页头与页面容器的最大宽度，超出后居中 |
| `--content-padding-inline` | `24 / 32 / 48px` | Token V1 §6.1 宽度档位，页头与页面容器共用 |
| `--control-height-md` | `44px` | 导航项最小高度，在 72px 顶栏内垂直居中 |
| `--control-height-sm` | `36px` | 连接状态胶囊高度 |
| `--space-2` | `8px` | 导航项间距、胶囊内部文字与圆点间距 |
| `--space-3` | `12px` | 导航项水平内边距 |
| `--space-4` | `16px` | 页头行内最小间距、导航项换行行距 |
| `--space-10` | `40px` | 品牌块与主导航之间的左组间距（页面专属，Token 阶梯组合） |
| `--radius-sm` / `--radius-pill` | `6px` / `999px` | 导航项上圆角、状态胶囊 |
| `--color-accent` | `#D9431F` | 当前一级导航文字与下划线（形状 + 可编程当前页语义） |
| `--focus-ring-width` / `--focus-ring-offset` | `3px` / `2px` | 统一焦点环，不被容器裁剪 |

## 2. 宽度档位与内边距（Token V1 §6.1）

| 档位 | 视口 | `--content-padding-inline` | 内容容器 |
| --- | --- | --- | --- |
| 紧凑桌面 | `1280～1439px` | `24px`（`--space-6`） | `min(100%, 1512px)` 居中 |
| 标准桌面（主验收画布） | `1440～1679px` | `32px`（`--space-8`） | `min(100%, 1512px)` 居中 |
| 宽桌面 | `1680～1920px` | `48px`（`--space-12`） | `1512px` 居中 |

档位由 `tokens.css` 的 `@media (min-width: 1440px)` / `@media (min-width: 1680px)`
在 `:root` 上覆写同一 Token；`.app-header-inner` 与 `.app-main` 都消费
`var(--content-padding-inline)`，因此品牌、页面标题与内容左缘始终同轴。`1280px`
以下不定义产品布局；桌面 200% 缩放等价的 720 CSS px 视口走 `max-width: 760px`
的纵向重排（品牌、主导航、状态胶囊分行），字段与操作保持可达。

## 3. 壳层锚点（CSS px，相对视口左上角）

顶栏高 72px；导航项 44px、状态胶囊 36px 均在顶栏内垂直居中。容器宽
`W' = min(W, 1512)`，容器左缘 `L = (W − W') / 2`，内边距 `P` 取第 2 节档位值。

| 锚点 | selector | 1280×900 | 1440×900 | 1920×1080 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `shell.header` | `.app-header` | x0 y0 1280×72 | x0 y0 1440×72 | x0 y0 1920×72 | 顶栏铺满视口，高 = `--size-shell-header` |
| `shell.content` | `.app-header-inner` | x0 y0 1280×72 | x0 y0 1440×72 | x204 y0 1512×72 | `min(100%, --size-content-max)` 居中 |
| `shell.brand` | `.brand-block` | x24 | x32 | x252 | 左缘 = `L + P` |
| `shell.nav-first` | `#shell-nav-1` | y14 | y14 | y14 | `(72 − 44) / 2` |
| `shell.status` | `.workspace-status` | y18 h36 | y18 h36 | y18 h36 | `(72 − 36) / 2` |
| `shell.status-right` | `.workspace-status` | right 1256 | right 1408 | right 1668 | 右缘 = `L + W' − P`；品牌与导航保持左组 |
| `shell.main` | `.app-main` | x0 y72 1280 | x0 y72 1440 | x204 y72 1512 | 与顶栏内容同宽同轴，内容自 y72 起 |

诊断量（不纳入门禁，因文本渲染环境而异）：品牌块宽度、导航项左缘、
首项导航与品牌右缘之间的实际间距。

## 4. 门禁形态

硬门禁（`tests/browser/test_app_shell_visual.py`，真实 Chromium）：

- `shell_anchors_for(width)` 的全部锚点在 1280／1440／1920 下偏差 ≤ 2 CSS px；
- 顶栏与页面容器 computed `padding-inline` 等于档位值，容器在 1920 下居中且不超 1512px；
- 品牌左缘、状态胶囊右缘分别对齐内容容器两端，导航左缘不早于品牌右缘；
- 全宽度无水平溢出（`body.scrollWidth ≤ viewportWidth`）；
- 顶栏结构：品牌 + 三项一级导航为左组，连接状态胶囊独占右端；
- 键盘：skip link 为第一个可聚焦元素，其后为品牌返回与 `shell-nav-1..3`；
  当前项以文字颜色 + 下划线共同表达（reduced-motion 下不回退）；
- 200% 缩放等价视口下导航重排且胶囊不遮挡，三页内容可达；
- 敏感边界：连接状态只呈现中文摘要，endpoint/凭据/内部代码不出现在 URL、history、
  存储、可见文本或属性中。

诊断（不设阈值）：`SHELL_REGION` 顶栏条带与归一化设计图的差异比例、现行设计图锚点偏差。

## 5. 与现行设计图的差异（仅记录）

`tests/visual/measure.py::measure_redesign_shell` 对
`docs/design/assets/frontend-ux/redesign-2026-09-23/添加番剧－单番－搜索首屏.png`
归一化到 1440×900 后实测：

| 量 | 设计图实测 | 本基线（Token 优先） |
| --- | --- | --- |
| 顶栏白底带 | 0..74（75px） | 72px |
| 品牌文本左缘 | 49px | 32px（1440 档内边距） |
| 首项导航字形左缘 | 263px | 品牌宽度 + `--space-10`，非独立常量 |
| 状态胶囊表面右缘 | 1394px | 1408px（容器右缘 − 32px） |

生成器取景非精确像素；上表只解释人工比对时的可见差异，不改变 Token 门禁。

## 6. 验证命令

```bash
# 纯 Python：档位映射、Token 源一致性与设计图测量可复现性
UV_CACHE_DIR=.uv-cache uv run pytest tests/visual/test_shell_baseline.py -q

# 前端静态与单测
cd frontend && npm run typecheck && npm run lint && npm run test:unit -- --run

# 真实 Chromium（需先 npm run build）
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_shell_visual.py -q
```
