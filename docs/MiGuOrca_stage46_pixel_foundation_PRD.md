# MiGuOrca Stage 46 执行 PRD：像素基线、应用壳层与共享控件

## 1. 执行信息

| 项目 | 内容 |
| --- | --- |
| 状态 | 历史执行 PRD；US-358～US-362 已完成并由 PR #75 合并 |
| 日期/基线 | 2026-09-20；Stage 45 PR #74 merge `75e144194644b920c446080c7becaca4a14f3704` |
| 分支 | `ralph/stage46-pixel-foundation`；开始开发前重新核对实时 HEAD、工作区与目标 diff |
| 总体依据 | [添加番剧页面像素级复刻总体 PRD](MiGuOrca_add_anime_pixel_parity_PRD.md) |
| 设计依据 | [六张效果图说明](design/frontend-ux-review-mockups-2026-09-17.md)、[Design Token V1](design/frontend-ux-design-tokens-v1.md) |
| Ralph | 历史快照位于 `scripts/ralph/archive/2026-09-21-stage46-pixel-foundation/`；不作为现行入口 |

本阶段建立了后续单番/批量页面复刻所需的可信测量基线，并只实现六图共享的应用壳层与基础控件。
下文记录当时的范围和约束，仅供追溯；不得据此启动开发、团队或发布。

## 2. 目标、范围与规格优先级

### 2.1 目标

1. 将 `1586×992` 的不可变源 PNG 按确定性算法归一化为 `1440×900` 标准桌面参考。
2. 建立测试期 PNG 比较、命名掩码、关键锚点和稳定截图工具；六个设计状态都能由真实 Chromium
   通过 mock/held route 确定性进入，但 Stage 47/48 前不强行让页面专属视觉门禁变绿。
3. 复刻六图共用的顶栏、品牌、四项导航、连接状态胶囊，以及共享按钮、输入、选择、加载、
   状态和模式切换视觉；四个一级页面必须保持可用。

规格冲突依次采用：安全/业务状态机/无障碍硬约束 → 交互规格与 Design Token V1 明确数值 →
归一化六图的布局、密度与状态表达 → 示例文案、虚构封面和生成瑕疵。

### 2.2 允许改动

- 测试基础：`pyproject.toml`、`uv.lock`、`tests/visual/` 下的纯图像比较 helper/单元测试，及
  `tests/browser/` 下的 fixture helper 与定向用例。
- 壳层与共享视觉：`frontend/src/App.vue`、`frontend/src/styles/{tokens,main}.css`、
  `frontend/src/components/forms/`、必要的共享反馈/布局组件、`AnimeModeSwitch.vue`，以及对应测试。
- 只为稳定定位补充语义 class、公开安全 `data-*` 或测试 id；属性不得包含秘密、URL、原始响应、
  草案能力、幂等键、绝对路径或完整 Request。
- Ralph 状态、progress 和本阶段直接相关文档。

### 2.3 禁止改动

- 不重排 `WorkbenchView`、候选卡、单番草案、批量双栏或固定确认栏的页面专属结构；这些分别属于
  Stage 47/48。只有为 fixture 稳定定位所需的无行为标记允许进入本阶段。
- 不改后端、API、OpenAPI、generated client、路由业务语义、草案 authority、CAS、scheduler、
  save-confirm、unknown 冻结恢复、D-02/D-04、safe-info、外部写或持久化。
- 不下载或提交未经核实许可的 Logo、图标、字体或海报；不引入在线运行时资源。
- 不修改六张源 PNG，不提交运行时 screenshot、diff、trace、`dist/`、sourcemap 或浏览器产物。
- 不把 AI 生成图的错字、假数据、细小装饰瑕疵实现成产品行为。

## 3. 共同验收边界

- 标准像素环境为项目固定 Linux Chromium、viewport `1440×900`、100% 缩放、固定中文脱敏 fixture；
  等待 `document.fonts.ready`、图片、目标响应和两个 `requestAnimationFrame`，禁止用任意 sleep 猜稳定。
- 源图以 Pillow LANCZOS 归一化；页面截图必须原生 `1440×900`。PNG helper 只进 dev dependency，
  不能进入生产 wheel/前端 bundle。
- **像素门禁裁决 3C（2026-09-21）**：Stage 46 **不对现有六张设计 PNG 启用 `<=0.5%` 像素硬门禁**。
  实测设计图与冻结 Design Token V1 存在系统性几何冲突（顶栏 `86` vs `72px`、品牌左缘 `121` vs
  `20px`、导航字号 `≈20` vs `15px`、首页控件 `70` vs `52px`），两者差异带的并集需要 `55.14%`
  命名掩码，超过 35% 上限，而 PRD 同时禁止整卡掩码；按总体 PRD 2.1 的规格优先级采用冻结 Token。
  完整测量见 `tests/browser/visual_manifest.py` 的 `MOCKUP_VS_TOKEN_DELTAS`。
- 六张 PNG 只用于归一化、fixture 状态诊断和非冲突视觉方向核对；fixture 保留连续三次诊断值，
  不设阈值，也不得把诊断值写成通过。
- Stage 46 的硬门禁为：比较器确定性（合成图边界）、fixture 连续三次稳定、冻结 Token 的
  computed style、控件尺寸（默认 44px／首页 52px／主要目标 `>=44x44px`）、可访问性（键盘、
  焦点环、对比度、reduced-motion）、关键 DOM 几何（token 派生锚点，误差 `<=2 CSS px`）、
  路由与安全 canary。
- 锚点、控件与壳层的目标值按总体 PRD 2.1 取冻结 Token 派生值；设计图实测值只作诊断记录。
- Stage 47/48 若要恢复「设计图像素级验收」，必须先提供并审批一套与冻结 Token V1 一致的新参考图
  或正式测量基线；在此之前不得把现有六张 PNG 的 `<=0.5%` 写成硬门禁。
- shared 掩码能力仍保留在 US-358 helper 中（命名、裁剪、去重、35% 上限），供后续阶段在获批的
  新基线上使用。
- 四个一级路由、skip link、键盘焦点、中文状态、reduced-motion、`1280×720`、`1920×1080` 和
  桌面 200% 缩放继续可用；截图通过不替代 DOM、交互、安全 canary 或响应式验证。
- 自动化一律 mock 外部依赖并使用临时 storage；不访问真实 MiKan、Auto Bangumi 或 qBittorrent。

## 4. 原子工作包、依赖与预算

| 工作包 | 故事/priority | 前置 | 迭代上限与停止点 |
| --- | --- | --- | --- |
| WP-46-A | US-358/1 | 基线与依赖核对 | 1 个开发 story turn；独立审核 |
| WP-46-B | US-359/2、US-360/3 | A 闭环 | 2 个开发 story turn；同一开发 Agent 连续完成后统一审核 |
| WP-46-C | US-361/4 | B 闭环 | 1 个开发 story turn；独立审核 |
| WP-46-D | US-362/5 | C 闭环 | 1 个开发 story turn；独立审核、Stage 收尾门禁 |

每次只实现一个 story，不运行 `ralph.sh`。同一工作包保持开发 Agent 连续；审核发现问题后先由测试
Agent 固化最小红测，再交同一修复 Agent 集中修复。每包最多 3 轮集中修复；到达上限仍未闭环则保留
问题、红测和 progress 并报告，不开始下一包、不把 `passes` 伪设为 true。

## 5. WP-46-A／US-358：确定性像素比较基础

用户故事：作为视觉实现与审核者，我需要一个可重复、可解释的比较器，知道差异来自像素、几何还是样式，
而不是依赖主观目测。

### 可观察 AC

1. 将 Pillow 作为 Python `dev` dependency 加入并更新 `uv.lock`；生产 dependencies、wheel 内容和前端
   bundle 不包含 Pillow。
2. helper 验证源图/实际图尺寸和模式，保留源 PNG 不变，使用明确的 LANCZOS 参数归一化参考图；
   对 RGB/RGBA 输入统一只比较可见 RGB，尺寸/损坏 PNG 给出固定、安全的分类错误。
3. 输出至少包含参与像素数、差异像素数、差异比例、最大通道差、掩码面积与每个命名掩码面积；
   不输出像素内容、绝对路径、响应原文或 fixture 载荷。
4. 阈值实现为任一 RGB 通道差值 `>12`；相同图片为零差异，单点/边界差异计数准确。
5. 掩码使用显式命名矩形并裁剪到画布；重叠只计一次；空/越界/负尺寸拒绝；默认总掩码面积上限
   为画布 35%，超过立即失败，不允许调用者静默关闭上限。
6. 可选 diff 图只能写入 pytest `tmp_path`，退出后不留仓库文件；仓库跟踪文件检查拒绝视觉运行产物。
7. 纯合成图片单元测试覆盖归一化、阈值边界、RGBA、重叠掩码、面积上限、尺寸错误和三次运行结果一致。

### 文件与验证

建议文件：`tests/visual/compare.py`、`tests/visual/test_compare.py`、`pyproject.toml`、`uv.lock`。
纯图像边界测试不得因 Chromium 缺失而 skip；实现者可调整 helper 文件名，但不得落入生产 `src/`。

最小验证：目标 pytest 文件、`uv lock --check` 等价锁文件核对、Ruff；按 Ralph JSON 要求补跑前端
typecheck。此故事没有页面变化，不要求把六图跑绿，也不以浏览器截图代替合成图片边界测试。

## 6. WP-46-B／US-359：单番三状态视觉 fixture

用户故事：作为单番页面开发者，我需要一键进入图 01～03 的确定性业务状态，为下一 Stage 提供可信红线。

### 可观察 AC

1. 图 01 fixture 打开 `/app/add` 单番初始态：无结果/救援面板，无外部请求，连接状态使用固定公开摘要。
2. 图 02 fixture 搜索固定标题，返回三条公开候选；点击第一条后以 held route 停在候选详情生成中，
   第一条就地 loading、其他候选防重复，候选阶段不出现资源数。
3. 图 03 fixture 释放真实 envelope 后进入未保存草案审核；候选摘要、字幕组、过滤规则、有效/排除资源
   均来自固定安全数据，revision 与阻断状态真实，不调用已保存 Request safe-info。
4. 三状态共享一套构造器，禁止复制与真实 DTO 不符的简化 envelope；canary 实际进入客户端边界后仍不落
   DOM/属性、URL/history、storage、console、截图或 diff 输出。
5. 每态完成字体/图片/网络/双帧稳定化后，在 `tmp_path` 产生恰为 `1440×900` 的截图并调用 US-358 helper；
   记录诊断值但暂不对页面专属区域设置必须通过的最终阈值。
6. 建立图 01～03 的命名区域/锚点 manifest；坐标来自归一化参考图并附用途，不用运行时截图反写目标值。
7. 测试分别证明准确到达三个状态、无真实外部访问、连续三次截图尺寸/锚点/比较统计稳定。

### 文件与验证

建议新增 `tests/browser/workbench_visual_fixtures.py`、`tests/browser/test_app_workbench_visual.py`；复用现有
`tests/browser/test_app_workbench.py` envelope/held-route 模式，不把 helper 搬入生产。

最小验证：新增单番视觉用例、现有单番初始/候选/草案各一条关键用例，真实 Chromium；前端 build、
typecheck。若 fixture 为稳定定位补了 DOM 标记，补对应 Vitest 并证明没有业务行为变化。

## 7. WP-46-B／US-360：批量三状态视觉 fixture

用户故事：作为批量页面开发者，我需要一键进入图 04～06 的确定性业务状态，同时保留 Stage 45 的真实范围语义。

### 可观察 AC

1. 图 04 fixture 使用固定六行原文，以 held batch parse 停在整体搜索中；显示 6/36 和诚实不定进度，
   不伪造逐条百分比，输入保持原样。
2. 图 05 fixture 返回六项混合状态：三项待选合集、两项草案待审核、一项搜索失败；当前查看第一项，
   held 其候选详情生成，其他 item 仍可查看/操作。状态与操作只能来自现有服务端契约。
3. 图 06 fixture 当前查看已选真实合集的草案，完整批次中恰有两项手工勾选且可确认；右栏和固定栏
   使用 Stage 45 的真实派生，不能为贴图伪造计数、勾选或资格。
4. 三状态复用批量构造器和真实 envelope；D-02 的隐藏手工勾选、可见全选及确认全部集合语义不变，
   D-04 导航不在 fixture 中触发。
5. 每态按与 US-359 相同的安全、稳定、截图和诊断规则执行；不新增单项重搜、实时进度、后端或 API。
6. 建立图 04～06 的命名区域/锚点 manifest；连续三次尺寸、锚点和统计稳定，截图/diff 只在 `tmp_path`。
7. 覆盖 6 项基准外，再证明构造器不会改变既有 1/12/36 边界和敏感 canary。

### 文件与验证

建议新增 `tests/browser/batch_visual_fixtures.py`、`tests/browser/test_app_batch_visual.py`；复用既有批量
route mock、held route、临时 storage 和 scope helper。

最小验证：新增批量视觉用例、Stage 45 的紧凑列表/范围关键类、前端 build/typecheck；真实 Chromium。
不得为了截图稳定删除异常、禁用原因、隐藏参与说明或 fixed-toolbar 空间预留。

## 8. WP-46-C／US-361：共享应用壳层复刻

用户故事：作为任一页面用户，我希望顶部品牌、导航和连接状态与设计稿一致，并保持四页导航与状态可访问。

### 可观察 AC

1. 在 `1440×900` 下复刻六图共用顶栏：白色表面、文本式 `MiGuOrca` 品牌、四项固定导航、珊瑚红当前项
   与下划线、右侧浅色连接胶囊；移除设计图没有的可见 `M` 方块和品牌 eyebrow，但保留可访问返回名称。
2. 未配置时胶囊可见文案为“未配置”；其他状态使用既有中文连接摘要，完整语义留在 accessible name，
   不显示 endpoint、凭据或内部代码。待处理数量仍可辨且不改变链接目的地。
3. 顶栏高度、内容最大宽度、左右内边距、品牌/导航/状态锚点**按冻结 Token 派生目标**误差 `<=2 CSS px`
   （设计图实测值仅作诊断）；颜色、字号、边框、阴影和 active 状态消费语义 token，不在 `App.vue`
   散落第二套色值。
4. 当前路由判定、`/app/` history、skip link、品牌返回、query-only 不抢焦点和设置入口行为不变。
5. `1280×720`、`1920×1080` 和 200% 缩放可达；导航不被状态胶囊覆盖，焦点环不裁剪；
   reduced-motion 不影响当前项识别。
6. 添加番剧启用共享壳层硬像素/锚点/style 门禁；追番方案、追番管理、设置分别做导航、正常内容、
   错误/禁用态定向回归，不进行三页像素改版。

### 文件与验证

文件：`App.vue`、`styles/{tokens,main}.css`、`App.test.ts`、`tokens.test.ts`、视觉 fixture/manifest，
以及实际受影响的 shell/全局状态 Chromium 用例。

最小验证：相关 Vitest、typecheck、lint、build；`test_app_shell.py`、`test_stage39_global_status.py`、
`test_app_responsive_a11y.py` 的实际受影响节点及四路由定向真实 Chromium；壳层三层视觉门禁连续三次稳定。

## 9. WP-46-D／US-362：共享控件与模式切换复刻

用户故事：作为添加番剧用户，我希望模式切换、输入、按钮和状态反馈使用一致的尺寸与层级，为后续页面复刻提供稳定组件。

### 可观察 AC

1. `BaseButton`、`BaseInput`、`BaseTextarea`、`BaseSelect`、Checkbox、共享状态/加载反馈和
   `AnimeModeSwitch` 使用同一 token；不在单番/批量宿主复制色值、圆角、阴影或控件高度。
2. 默认控件高度 44px、首页大控件 52px、主要点击目标至少 44×44px；分段控件为浅色轨道和明确选中块，
   支持鼠标、方向键、Enter/空格，模式切换不清输入或未保存现场。
3. primary 深海蓝、secondary 白底强边框、disabled 仍可读且附近保留原因；loading 保留按钮尺寸与文字，
   不能退化为只有旋转图标。珊瑚红不变成第二套普通主按钮。
4. hover/focus/active/error/disabled/loading 状态按 token computed style 断言；焦点环 3px 且不被裁剪，
   正文对比度至少 4.5:1、控件边界至少 3:1。
5. reduced-motion 取消非必要位移/旋转并保留进行文字；长中文、200% 缩放和 1280 桌面不溢出操作区。
6. 图 01/04 的模式切换和共享控件区域启用冻结 Token 硬门禁（computed style、控件尺寸、可访问性；
   不启用设计图像素硬门禁，见第 3 节裁决）；不在本故事重排英雄区、多行面板、候选卡或审核区。
7. 四个一级页面所有调用者完成定向回归；改动文案、class 或 DOM 时同步搜索并更新真实受影响断言，
   不删测试或放宽业务/敏感边界来换取通过。

### 文件与验证

文件：受影响共享表单/反馈组件、`AnimeModeSwitch.vue`、token/main CSS、对应 Vitest 和 Chromium。

最小验证：共享控件 Vitest、模式切换 Vitest、typecheck、lint、build；四路由控件状态、键盘、焦点、
缩放、reduced-motion 与视觉区域真实 Chromium。完成独立审核/修复/复审后执行 Stage 收尾门禁。

## 10. 审核矩阵

| 风险 | WP-46-A | WP-46-B | WP-46-C | WP-46-D |
| --- | --- | --- | --- | --- |
| 比较算法/尺寸/掩码 | 合成图边界与三次稳定 | 六态诊断、manifest | 壳层硬门禁 | 控件硬门禁 |
| 状态真实性 | 不适用 | held route、真实 envelope | 连接状态投影 | 控件真实状态 |
| 业务状态机 | 不改生产 | 单番/批量关键回归 | 路由/焦点不变 | 模式/输入不丢 |
| 安全 | 输出不含路径/载荷 | canary、临时 storage | 连接秘密不展示 | DOM/属性无秘密 |
| 无障碍 | 错误可解释 | 稳定等待不抢焦点 | skip/nav/200% | 键盘/焦点/对比度 |
| 跨页影响 | 无 | 无生产或仅标记 | 四页 shell | 四页调用者 |

审核必须检查：参考图没有被修改；目标坐标不是从实现截图反写；掩码有名称、理由、面积且没有覆盖整卡；
比较器失败不会暴露本地路径；测试实际进入目标业务状态；共享样式未把其他三页改成添加页专属布局。

## 11. Stage 收尾门禁与交接

US-362 完成并经过独立审核、问题红测、集中修复和复审后，隔离运行数据并执行一次完整门禁：

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
仓库根，构建后：
uv run pytest tests/browser/ -q
git diff --check
```

额外收尾：六个 fixture 连续三次稳定；壳层/共享控件的 Token 几何／computed style／控件尺寸／可访问性门禁通过；
设计图像素诊断值如实记录（按裁决 3C 不设 0.5% 硬阈值）；所有 screenshot/diff/trace 仅在临时目录；
依赖锁文件一致；源 PNG 哈希不变；`git status` 无 `dist/`、浏览器产物、凭据或本地 storage 改动。

Stage 47 只在本阶段闭环且其执行 PRD另行编写后开始。交接必须列出已冻结 helper API、六态 fixture 名称、
锚点 manifest、像素门禁裁决 3C 的记录、诊断值、字体环境、剩余页面差异和真实验证命令；不得把诊断值冒充
图 01～06 页面专属像素验收已通过。
