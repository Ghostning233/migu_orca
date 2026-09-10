# MiGuOrca Stage 33 PRD：前端应用壳层与设计系统

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage | 33 |
| 工作包 | F-A：应用壳层与设计系统 |
| Backlog | BL-026 |
| 状态 | 已规划，待开发 |
| 目标分支 | `ralph/stage33-frontend-shell` |
| Ralph stories | US-257～US-265 |
| 实时基线 | `origin/main` 合并提交 `6f2a595`（Stage 32 已合入） |
| 前置 | Stage 27 前端工程基线、Gate 1～3 设计包、Stage 32 前端契约 handoff v1 |

Stage 33 原规划曾位于独立前端 clone，但该分支停在 Stage 30 基线且没有实现提交。当前规划已在
Stage 32 合入后的主仓重新落地；旧 clone 的环境脚本、符号链接和未完成代码不是执行事实来源。

## 2. 背景与阶段判断

Stage 27 已交付 Vue 3、TypeScript strict、Vite、Vue Router、统一 API transport、共享组件和真实
Chromium 基线；Stage 28～32 已完成 draft/save-confirm、tracking、Auto Bangumi 读写管理、兼容
迁移和最终生成契约。当前业务能力已经足以支撑后续页面，但 SPA 仍使用“工作台 / 订阅方案 /
提交队列 / Settings”的工程命名，视觉 Token、壳层层级和共享状态表达尚未落实 Gate 1～3。

本阶段只交付 F-A。Stage 32 已经解锁未来 F-F，不代表 Stage 33 应顺带制作正式追番管理页；
`/app/tracking` 本阶段仍挂载现有 `QueueView`，明确标注为兼容内容。

## 3. 目标

1. 一级导航固定为“添加番剧 | 追番方案 | 追番管理 | 设置”。
2. 新客户端路径固定为 `/app/add`、`/app/plans`、`/app/tracking`、`/app/settings`。
3. 旧路径通过安全 `replace` 重定向，保留目标页面实际理解的公开定位参数，丢弃其他 query。
4. 落地暖白、深海蓝、克制珊瑚橙的语义设计 Token，并让现有共享原语渐进消费。
5. 提供桌面应用壳层、跳到主要内容、当前项语义和路由切换焦点管理。
6. 无损挂载现有四个业务页，保持搜索、草案、方案、队列和设置功能对等。
7. 在 1280～1920 px、200% 缩放等效布局、键盘和 reduced motion 下保持可操作。
8. 使用真实 Chromium 验证路由、壳层、主要状态和敏感信息边界。

## 4. 非目标

1. 不实现 F-B～F-G，不重写单番三步、批量审核、追番方案或正式追番管理业务旅程。
2. 不把 `/tracking` 制作成 mock-only 管理页；仍挂载现有 `QueueView`。
3. 不修改 OpenAPI、`frontend/src/api/generated/api.ts` 或后端业务语义，不手写 API DTO。
4. 不新增 Auto Bangumi/qBittorrent 动作，不访问真实外部服务。
5. 不删除现有页面、兼容路由、store 或测试资产。
6. 不引入新 UI 框架、路由插件、持久化插件或第二套同义组件。
7. 不开发移动端；200% 缩放只属于桌面无障碍验收。
8. 不实现“已更新集数”，继续视为 `NOT_IMPLEMENTED`。

## 5. 冻结决策

### D33-01：信息架构与挂载关系

| 导航 | 新客户端路径 | Stage 33 挂载内容 |
| --- | --- | --- |
| 添加番剧 | `/app/add` | 现有 `WorkbenchView`（含单番与批量工作台） |
| 追番方案 | `/app/plans` | 现有 `RequestsView` |
| 追番管理 | `/app/tracking` | 现有 `QueueView` 兼容内容 |
| 设置 | `/app/settings` | 现有 `SettingsView` |

Vue Router base 保持 `/app/`。客户端 route record 使用 `/add`、`/plans`、`/tracking`、
`/settings`；`/app/` 安全重定向到 `/app/add`。

### D33-02：路由与 query 迁移矩阵

| 来源 | 目标 | 允许保留的 query |
| --- | --- | --- |
| `/app/workbench` | `/app/add` | `batch_id` |
| `/app/requests` | `/app/plans` | `request_id` |
| `/app/queue` | `/app/tracking` | `batch_id` |
| `/app/settings` | 原路径不变 | `request_id` |
| Flask `/`、`/index` | `/app/add` | `batch_id` |
| Flask `/settings`、`/Settings` | `/app/settings` | `request_id` |

`WorkbenchView` 内嵌的 `BatchWorkbenchView` 会读取并写入 `batch_id`，因此 `/add` 的白名单不能
为空。允许值只保留单个、非空字符串；数组、空值和未知 query 全部丢弃。搜索原文、draft、
candidate context、凭据、endpoint、storage profile、绝对路径及 `ab` 等目标页不消费的参数不得
迁移。重定向使用 `replace`，返回键不得形成循环。

前端建立一个可复用的 route catalog/query sanitizer，并由真实 router、导航和内部跳转消费；
不要创建只被测试读取、下一 story 必须推翻的“规划常量”。Flask 入口使用明确常量和表驱动测试，
不尝试在 Python 运行时读取 TypeScript 文件。

### D33-03：壳层

1. 顶部导航目标高度 72 px，内容最大宽度 1512 px，均通过 Token 表达。
2. 品牌区、四项导航和非敏感全局状态职责清晰；业务恢复动作不进入顶栏。
3. 当前项同时使用文案、视觉标记和 `aria-current="page"`，不能只靠颜色。
4. 提供“跳到主要内容”链接；路由切换后焦点进入主标题或主要内容起点。
5. 200% 缩放等效宽度下允许重新排布，但不能隐藏导航或主操作。

### D33-04：Token 与组件边界

1. `frontend/src/styles/tokens.css`（或等价单一入口）定义 surface、text、accent、danger、focus、
   space、radius、shadow、z-index 和 motion 等语义 Token。
2. 共享组件不得复制品牌色、阴影和焦点 magic value；feature 的业务布局可渐进迁移。
3. 继续复用现有 Base*、`CheckboxRow`、`PanelSection`、`FormField`、`ConfirmDialog`、
   `StatusAlert`、Loading/Empty/Error、Notification/GlobalLoading，不创建 V2 平行组件。
4. 允许调整样式和可访问属性，但保持既有 props、emit 和业务调用兼容。
5. 每个可见任务区最多一个强主操作；危险色只服务危险语义。

### D33-05：业务与契约边界

1. Stage 32 的 `docs/api/openapi.json`、generated client 和
   `docs/api/frontend-contract-handoff-v1.md` 是只读基线；`npm run api:check` 必须持续通过。
2. 新路径必须更新生产代码中的内部导航；旧路径只用于外部书签兼容，不得成为新代码依赖。
3. Request、draft、tracking、submit/retry/recover/management 语义保持不变。
4. endpoint、凭据、Cookie、完整 RSS/MiKan URL、原始响应和绝对路径不得进入持久化、URL、DOM、
   日志、截图或 trace。

## 6. User Stories

### US-257：冻结最新路由、query 与功能对等基线

基于 Stage 32 合入后的真实 router、Flask 入口和四个现有页面，建立可持久消费的 route catalog、
query sanitizer 与路由/页面/浏览器用例矩阵。覆盖 D33-02 的全部映射，特别是 `/add` 与
`/tracking` 均允许公开 `batch_id`；不得提交只适用于“迁移前”的临时断言。

### US-258：实现语义设计 Token

把设计 Token V1 转换为颜色、排版、间距、尺寸、圆角、阴影、层级、焦点和动效变量，接入全局
样式并提供现有组件可渐进消费的基线。不在本 story 重写页面或组件 API。

### US-259：实现新路由与安全兼容重定向

让真实 Vue router 消费 route catalog，新增四个新路径、根重定向和三个旧路径的安全 `replace`；
同步 Flask 入口及生产代码内部跳转，确保新代码只生成新路径。保留 SPA fallback、API、媒体和
静态资源边界。

### US-260：实现桌面应用壳层与四项导航

重构 `App.vue` 及必要 shell 组件，提供品牌区、四项导航、跳转链接、当前项语义、主内容容器和
路由切换焦点管理。壳层不得持有 draft、candidate context、凭据或外部响应。

### US-261：统一共享表单与动作原语

让现有按钮、输入、文本域、选择、复选、表单字段和面板消费 Token，统一尺寸、层级、hover、
focus、disabled、busy 和 error 状态；保持既有组件接口与业务调用兼容。

### US-262：统一反馈、弹窗与系统状态

让现有确认弹窗、状态提示、加载、空、错误、错误边界、通知和全局加载消费同一 Token 与可访问
语义。关键失败留在页面上下文，Toast 不作为唯一恢复入口。

### US-263：挂载现有业务页并证明功能对等

在新壳层中验证 Workbench、Requests、Queue、Settings 的搜索/草案、列表/详情、队列提交/恢复和
配置操作；只修复容器、样式或迁移路径造成的回归，不改领域流程，不用 mock-only 页面冒充完成。

### US-264：完成桌面可访问与真实浏览器回归

覆盖 1280、1440、1920 宽度、200% 缩放等效布局、键盘顺序、焦点恢复、跳转链接、当前项、
reduced motion 和关键内容无横向丢失；扩展现有 Playwright 用例并使用真实 Chromium。

### US-265：完成最终门禁、文档归档与 F-B handoff

只在本 story 运行一次完整前端、必要后端路由和完整 Chromium 门禁；同步文档与 Ralph 归档，记录
设计偏差和安全证据。F-B 只能复用本阶段 shell、Token、route catalog 与共享原语，不得重复实现。

## 7. 验收矩阵

| 风险 | 必须证明 |
| --- | --- |
| 路由漂移 | route catalog、真实 router、内部导航和 Flask 入口映射一致 |
| query 泄漏 | 只保留目标实际消费的公开 scalar ID，未知/敏感/数组 query 被丢弃 |
| 业务回归 | 四个现有页面仍使用相同组件、store、transport 和 generated contract |
| 设计分叉 | Token 是唯一品牌视觉基线，没有第二套同义组件 |
| 可访问性 | 键盘、焦点、跳转链接、aria-current、reduced motion 与 200% 缩放通过 |
| 安全 | URL、DOM、storage、截图和 trace 不出现敏感值 |

## 8. 迭代与成本控制

1. 每轮只完成一个最高优先级 story；US-257～US-264 每轮只跑受影响的 Vitest、Flask route 和
   单项/小组 Chromium 检查。
2. UI story 必须按 `dev-browser` skill 在真实 Chromium 中验证；jsdom 或静态截图不能替代。
3. 只有 US-265 运行一次完整前端 typecheck/lint/unit/build、必要非浏览器检查和完整 Chromium。
4. 测试失败后只复跑最小失败用例；无代码变化不得重复全量门禁。
5. 预计 9 个实现迭代，最多 2 个修复迭代；超过 11 轮立即停止并报告。
6. 不重新安装已有依赖、不生成或修改 OpenAPI、不连接真实外部服务。

## 9. 最终门禁

```bash
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run pytest -q src/apps/migu_orca_web/app_routes_test.py src/apps/migu_orca_web/views_test.py
cd frontend
npm run api:check
npm run typecheck
npm run lint
npm run test:unit -- --run
npm run build
cd ..
uv run pytest tests/browser/ -q
git diff --check
```

## 10. 完成定义与后续 handoff

1. US-257～US-265 全部 `passes=true`，每个 story 有独立提交和验证记录。
2. 新旧路径、query 白名单、四项导航和四个现有页面均通过真实 Chromium 验证。
3. 语义 Token 与共享原语成为后续页面唯一基线，没有新增 API、业务状态机或平行 UI 系统。
4. Stage 32 generated contract 保持无漂移，敏感信息不进入任何浏览器可观察面。
5. 下一候选 Stage 为 F-B“共享审核核心”；F-F 虽已被 Stage 32 解锁，仍必须按依赖在 F-B 后单独规划。
