# MiGuOrca Stage 47 执行 PRD：单番三状态页面复刻

## 1. 执行信息

| 项目 | 内容 |
| --- | --- |
| 状态 | 已完成；US-363～US-365 已验收并由 PR #79 合并至 `main`（2026-09-22 收口） |
| 前置 Stage | Stage 46 已经 PR #75 合并至 `origin/main`，merge `be2f1cf` |
| 建议基线 | 启动时从实时 `origin/main` 创建；不得基于本地陈旧 `main` 猜测基线 |
| 总体依据 | [添加番剧页面像素级复刻总体 PRD](MiGuOrca_add_anime_pixel_parity_PRD.md) |
| 设计与 Token | [六张效果图说明](design/frontend-ux-review-mockups-2026-09-17.md)、[Design Token V1](design/frontend-ux-design-tokens-v1.md) |
| 复用基础 | Stage 46 的 `tests/visual/` 比较器、单番 fixture、Token 几何与可访问性门禁 |

本阶段只复刻单番添加旅程的图 01～03：搜索首页、候选选择加载、未保存草案审核。它扩展真实已有旅程的页面专属布局和信息层级，不重写服务端草案、候选选择或保存确认语义。

本 PRD 是执行材料，不授予 push、建 PR、合并、真实外部访问或外部写权限。

## 2. 开工决策门：视觉基线

### G-47-01（2026-09-21 已满足）

产品方已批准 `docs/design/frontend-ux-stage47-single-anime-geometry-baseline.md` 的全部事项，
**本阶段门禁口径正式确定为**：

- **形态 B（数值型正式测量基线）**：图 01～03 的门禁为**锚点（`<=2 CSS px`）+ computed style（冻结 Token）+ 几何（容器盒 / 行数与截断 / 居中）**，**不启用 `<=0.5%` 像素层**。
- 依据：现有六张设计 PNG 与冻结 Design Token V1 存在结构性几何冲突（Stage 46 裁决 3C，差异带并集需 55.14% 掩码 > 35% 上限），而形态 A 所需的设计工具参考图资产**未提供**。
- **图 03** 采用 6.4 节路径 3：只做锚点 + computed style + 几何门禁，不设像素硬阈值。
- `.app-main` 页内边距改为 Token 档位（1440 -> 32px 水平 / `--space-6` 垂直），属共享壳层改动，以四个一级页面的定向回归为交换条件。
- 若后续提供与冻结 Token V1 一致的新参考图，可为图 01/02 **追加**像素门禁；届时须另行审批并在本 PRD 记录。

下列原始阻断描述保留为历史，说明该门为何存在：

**（历史）** 产品方必须提供并审批一套与冻结 Design Token V1 一致的单番视觉参考（图 01～03），或提供等效的正式测量基线。它至少应明确：

- 1440×900 Linux Chromium 的参考资产、字体与归一化方法；
- 顶栏 72px、页面边距、字号、44/52px 控件等 Token V1 约束；
- 可参与 `<=0.5%` 像素比较的稳定区域、命名掩码和每项理由；
- 文本容器、基线、换行/截断及关键锚点，不能只给文字字形截图。

基线还必须逐图覆盖下列页面专属信息，否则对应 story 的布局目标不唯一：

| 图/Story | 必须定义的页面专属基线 |
| --- | --- |
| 图 01 / US-363 | 英雄区标题/说明、模式切换、输入与 52px 搜索按钮、三步预告的容器几何、间距、文本换行/截断与稳定像素区；搜索前不得包含结果、救援或草案区域。 |
| 图 02 / US-364 | 三列候选卡网格、卡片尺寸/间距、封面占位边界、标题/季数证据/总集数文本容器、首项 held loading、其余项防重复状态，以及 1280×720 与 200% 缩放下的重排规则。 |
| 图 03 / US-365 | 合集身份区、筛选区与资源摘要双栏、完整种子/高级信息折叠容器、“保存修改”与“保存并确认”的操作层级、阻断/恢复信息容器、文本换行/截断和焦点顺序。 |

上述定义只决定可测量的视觉容器与层级，不能删除或伪造现有业务状态：图 02 的季数证据与局部 loading、图 03 的草案 revision、筛选重算、save-confirm、unknown 恢复和安全信息边界仍以当前契约为准。

在 G-47-01 获批前，不得把 `docs/design/assets/frontend-ux/review-2026-09-17/` 的现有 PNG 当作图 01～03 的 `<=0.5%` 硬门禁，也不得以大面积掩码、实现截图反写坐标或局部魔法值回避冲突。

该门来自 Stage 46 的裁决 3C：现有 PNG 与冻结 Token 存在结构性几何冲突，差异带需要 55.14% 掩码，超过 35% 上限。它们在本阶段只保留为信息层级与状态方向的诊断参考。

冲突时遵循：安全、真实业务状态机、无障碍硬约束 → 现行交互规格与冻结 Token V1 明确数值 → 获批的 Stage 47 视觉基线 → 旧效果图示例文案、虚构封面和生成瑕疵。

## 3. 范围与边界

### 允许改动

- `frontend/src/features/workbench/` 中单番首页、候选卡/集合、未保存草案审核相关组件及局部样式；
- 必要的共享组件扩展，但须由四页调用者回归证明没有回归；
- `tests/browser/workbench_visual_fixtures.py`、`test_app_workbench_visual.py`、既有单番 Vitest/浏览器用例，以及获批基线对应 manifest；
- 仅为稳定定位增加无敏感语义 class、`data-*` 或测试 id；
- Stage 47 专属 PRD、Ralph 状态与 progress。

### 禁止改动

- 不改后端、API/OpenAPI、generated client、持久化、外部写、路由业务语义或草案 authority。
- 不改变 `draft_id + base_revision`、CAS、scheduler、筛选防抖、save-confirm、unknown 恢复，以及“保存并确认”和 Auto Bangumi 外部提交的两次确认边界。
- 不自动选择 MiKan 合集；候选季数证据、`CONFLICT` 人工确认、候选阶段无资源数和服务端草案计算均不放宽。
- 不新增单条重搜、伪实时进度、未保存草案 safe-info、在线字体/图标/海报，或真实 MiKan、Auto Bangumi、qBittorrent 调用。
- 不修改设计源 PNG，不提交截图、diff、trace、`dist/`、sourcemap、浏览器产物、秘密或本地运行数据。
- 不修改批量页面专属布局、批量固定确认栏、D-02/D-04 或追番方案/管理页面。

## 4. 共用实现与验证规则

- 标准环境是项目固定 Linux Chromium、1440×900、100% 缩放、固定脱敏中文 fixture。截图前等待字体、图片、目标响应和两个 `requestAnimationFrame`，不得用任意 sleep 猜稳定。
- 复用 Stage 46 的 Pillow 比较器、`tmp_path` 截图、命名掩码与 35% 总面积上限，供后续获批像素基线时使用；按 G-47-01 的批准结论，**本阶段不启用像素硬阈值**。
- Playwright 使用真实契约 envelope、临时 storage 与 held route；外部依赖一律 mock。handler 内不得 sleep。
- canary 即使进入客户端内存，也不得进入 DOM/属性、URL/history、storage、console、截图、diff、trace、Request JSON 或日志。
- 每个目标态连续三次验证截图尺寸、锚点与统计稳定；文字掩码不能覆盖文本容器、基线、换行或截断。
- 页面专属 CSS 消费语义 Token；不为贴旧图而修改冻结 Token 或复制第二套视觉常量。

## 5. 工作包与故事

每次只实现一个 `passes=false` story，不运行 `ralph.sh`。每个工作包完成后必须经历定向验证、独立审核、问题红测、集中修复和复审，才可进入下一包；每包集中修复最多三轮。

| 工作包 | Story | 前置 | 停止点 |
| --- | --- | --- | --- |
| WP-47-A | US-363 单番搜索首页 | G-47-01、Stage 46 闭环 | 独立审核 |
| WP-47-B | US-364 候选选择与生成加载 | A 闭环 | 独立审核 |
| WP-47-C | US-365 未保存草案审核 | B 闭环 | 独立审核与 Stage 收尾门禁 |

### WP-47-A／US-363：单番搜索首页（图 01）

作为首次添加番剧的用户，我需要聚焦单一搜索任务的首页，清楚地开始“输入名称 → 人工选合集 → 审核并确认”旅程。

验收标准：

1. `/app/add` 单番初始态不显示结果区、救援面板、资源数或旧工作台空态；输入、52px 搜索按钮和模式切换符合冻结 Token 与获批基线。
2. 首页只组织任务标题/说明、模式切换、搜索组合和三步预告；不将批量结构、候选卡或草案审核区提前渲染。
3. 单番/批量切换支持鼠标、方向键、Enter/空格，且不清除任一输入或未保存现场；搜索保持既有防重、禁用理由与中文反馈。
4. 初始 fixture 不发候选/外部请求，连接状态保持安全公开摘要；稳定截图、Token 锚点和浏览器安全边界通过。
5. 按 G-47-01 批准结论通过锚点、computed style 与几何门禁（形态 B，本阶段不启用像素层）；初始态不得渲染结果区、救援面板、候选卡或有效资源数。

最小验证：受影响 Vitest、单番初始与模式切换 Chromium 用例、`npm run typecheck`、`npm run lint`、`npm run build`。

### WP-47-B／US-364：候选选择与就地生成（图 02）

作为搜索番剧的用户，我需要看到真实可审核的 MiKan 候选，并在选择一个合集时获得诚实、局部的生成反馈。

验收标准：

1. 固定 fixture 搜索后显示三条真实契约形状的公开候选；标题、季度证据、总集数和人工选择动作符合获批基线，虚构海报不得成为业务证据。
2. 点击首候选后用 held route 停在草案生成中：仅该项显示 loading，其余候选防重复但不被误标为 loading；候选阶段不展示有效/排除资源数。
3. `PROVEN`、`NEEDS_CONFIRMATION`、`CONFLICT` 与空/失败状态继续使用既有人工核对规则；不得把布局重构变成自动选择或放宽季数证据。
4. 释放真实草案 envelope 后正确进入审核态；候选态不调用 saved Request safe-info，不访问真实外部系统。
5. 三次截图、目标锚点与文本容器稳定；canary 不泄漏；长标题、1280×720、200% 缩放和 reduced-motion 可用。

最小验证：候选卡/集合 Vitest、既有单番候选浏览器关键用例、Stage 46 单番 fixture 定向用例、真实 Chromium。

### WP-47-C／US-365：未保存草案审核（图 03）

作为已选合集的用户，我需要先判断“选对了吗、筛选后有什么、能否确认”，再以清楚的层级保存本地方案。

验收标准：

1. 未保存草案审核由真实服务端 draft envelope 进入；合集身份、字幕组、规则、有效/排除资源摘要和阻断状态来自安全 DTO，不显示技术 ID、raw snapshot、URL、磁链、原始响应或完整种子标题。
2. 审核区按获批基线组织合集身份、筛选和资源摘要；完整种子/高级信息保持按需展开，文本容器和焦点顺序可测，不通过隐藏恢复信息换取视觉一致。
3. “保存修改”为次操作，仅在存在待提交修改时可用；“保存并确认”为唯一强主操作，仍走既有 save-confirm。外部 Auto Bangumi 提交不得出现在此页面。
4. 保留筛选重算、冲突、零资源、保存失败、已保存待确认、定位失败和 unknown 恢复的真实可达性；不使用重挂载或前端副本覆盖服务端 revision。
5. 未保存草案不调用 saved safe-info；保存与确认、外部写、追番定位的边界不变。三次稳定、canary、安全、键盘、200% 缩放、reduced-motion 与 G-47-01 批准的锚点/几何/computed style 门禁通过。

最小验证：审核面板 Vitest、草案修改与 save-confirm 关键浏览器用例、Stage 46 单番 fixture、真实 Chromium。

## 6. 审核矩阵

| 风险 | US-363 | US-364 | US-365 |
| --- | --- | --- | --- |
| 视觉与基线 | 首页锚点/控件/获批像素区 | 卡片、loading、文本容器 | 审核层级、资源摘要、操作层级 |
| 状态真实性 | 初始无请求 | held route、真实 envelope、季数证据 | 服务端 draft、revision、safe-info 边界 |
| 安全 | 状态摘要无秘密 | canary、无真实外部调用 | DTO 脱敏、无 URL/原始数据/秘密 |
| 交互与无障碍 | 模式/搜索/焦点/缩放 | 单项 loading、防重复、键盘 | 保存层级、阻断原因、恢复、焦点 |
| 回归 | 单番初始与共享控件 | 既有候选旅程 | save-confirm、unknown 与定位恢复 |

审核必须确认：视觉基线已获批；掩码有名称、理由、面积且没有覆盖整卡/文本容器；fixture 实际达到目标业务状态；没有用 CSS 或测试删减掩盖业务、安全或恢复能力回归。

## 7. Stage 收尾门禁与交接

本阶段已按迁移期的 Matt 工作流验收并合并。下列门禁保留为当时的收尾基线与历史追溯：

```text
仓库根：
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run pytest -q -m "not browser"
uv run migu-orca-openapi --check

frontend/：
npm run api:check
npm run typecheck
npm run lint
npm run test:unit -- --run
npm run build

仓库根（构建后）：
uv run pytest tests/browser/ -q
git diff --check
```

历史交接记录应列出：获批基线标识（形态 B）与字体环境、图 01～03 的 fixture 名称、锚点/几何 manifest、门禁实际结果、非设计异常状态回归、真实验证命令和仍存风险，并说明像素层未启用的批准依据。本阶段已验收归档，不追加门禁或以其阻塞后续 GitHub Issue；若未来提供获批参考图，应在新的 Issue 中单独讨论像素门禁。
