# MiGuOrca Stage 22 PRD：Web UI 搜索工作台重构与真实候选闭环

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 22 PRD：Web UI 搜索工作台重构与真实候选闭环 |
| 文档类型 | Stage PRD |
| 当前状态 | 已完成 |
| 创建日期 | 2026-08-23 |
| 依赖阶段 | Stage 18、Stage 19、Stage 20、Stage 21 |

## 2. 背景与问题

人工验收 `/index` 后确认，现有单番剧候选搜索和批量番剧工作台虽然都调用真实 MiKan candidate search，但产品语义和界面结构没有真正收敛：

1. `#generate-panel` 同时承载 Storage 摘要、批量输入、单番剧输入、直连 fallback 和两套搜索结果，输入与结果混排，信息层级杂乱。
2. 标题“真实 MiKan 候选搜索”是实现术语，不是用户目标；用户实际是在创建订阅方案。
3. 批量链路先通过 fake title parsing provider 生成标题与搜索词，再逐项调用 `_search_mikan_candidates`；但即使 MiKan 候选为空，当前实现仍以原始输入/解析标题生成 `preview_request` 空壳并显示“已解析”，容易被误解为找到了真实番剧。
4. 后端批量成功路径返回 `PARSED`，前端 `canExpandBatchCard` 只允许 `DRAFT` / `READY`，导致真实返回的卡片无法展开、修改或接受。现有部分浏览器测试把 mock 状态写成 `DRAFT`，掩盖了真实契约错误。
5. 单番剧候选卡和批量卡没有共享统一结果结构；封面缺失、无候选、搜索失败和“仅完成标题解析”之间缺少清晰区别。
6. 搜索期间只有单一 loading 文案，没有利用现有状态容器提供简洁且真实的阶段反馈。

Stage 22 必须先恢复搜索结果的可信度，再重构布局。标题解析成功不等于找到 MiKan 候选，找到候选也不等于已经生成订阅草案；只有用户显式选择真实候选并完成现有详情解析链路后，才能进入可展开、可修改、可接受的草案状态。

## 3. 目标

1. 将 `/index` 主入口重构为用户可理解的“创建订阅方案”工作台。
2. 使用“单个搜索 / 批量搜索”分段切换管理两个输入模式，一次只展示当前模式。
3. 新增与“订阅方案详情”同级、独占一行的搜索结果 section，两种模式统一向该区域输出结果。
4. 明确区分标题解析状态、MiKan 候选结果状态和订阅草案状态。
5. 批量模式复用单番剧的候选搜索、候选展示、候选选择和草案生成原子能力；批量层只负责拆分、逐项编排和汇总。
6. 无候选时展示明确空结果，不得根据用户输入构造可接受的空壳草案。
7. 单番剧与批量候选卡统一展示公开标题、MiKan ID、封面或占位，以及显式“选择此合集”动作。
8. 在现有状态容器中展示简洁、真实、可验证的搜索反馈，不伪造不可观测的内部步骤。
9. 使用真实后端状态形状补齐 Playwright 浏览器回归，避免理想化 mock 掩盖契约错误。

## 4. 非目标

1. 不实现 AI 自动选择最终 MiKan 合集、自动接受卡片或自动提交 Auto Bangumi。
2. 不接入真实 LLM provider；继续保留 provider seam 和 fake provider。
3. 不重新实现 MiKan parser、详情解析、RSS 解析、筛选、命名或 Request 生命周期。
4. 不创建 qBittorrent 下载任务，不绕过 Auto Bangumi，不引入后台 worker。
5. 不在本阶段实现 SSE/WebSocket 等流式基础设施；除非现有请求可观测到真实逐项进度，否则只展示请求级真实状态。
6. 不把 endpoint、token、cookie、Authorization header、raw HTML、raw RSS XML、magnet、原始响应体、完整失败 URL或本地绝对路径带入 API、页面、URL、浏览器 storage、日志、截图或测试 trace。
7. 不实施部署/配置向导；该远期可选方向顺延至 Stage 23。

## 5. 产品决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D22-01 | 工作台标题使用“创建订阅方案” | 标题描述用户目标；MiKan 作为数据源在帮助文本和结果元数据中出现。 |
| D22-02 | 单个/批量是同一搜索能力的两种入口 | 单个处理一条输入，批量编排多条输入；两者共享候选契约、候选卡和选择后草案链路。 |
| D22-03 | 输入与结果物理分区 | 输入保留在 `#generate-panel`；结果进入同级、独占一行的 `#search-results-panel`。 |
| D22-04 | `PARSED` 只表示标题解析成功 | 它不能显示为找到 MiKan 结果，也不能直接提供展开、修改、接受动作。 |
| D22-05 | 候选结果使用明确状态 | 每个搜索项至少可区分 `FOUND`、`EMPTY`、`FAILED`（或语义等价的稳定字段）；`EMPTY` 是正常无结果，`FAILED` 是脱敏错误。 |
| D22-06 | 真实候选选择后才产生草案 | 只有用户点击真实候选并复用现有 `mikan_bangumi` 详情链路后，才生成 `DRAFT`/可编辑预览。 |
| D22-07 | 封面是可选公开元数据 | 有 `poster_url` 时展示封面；缺失时展示稳定占位，不把无封面误判为搜索失败。 |
| D22-08 | 进度文案必须真实 | 长请求只能显示“正在搜索并整理结果”等请求级状态；不得用定时器伪造“页面解析完成”等服务端内部事件。 |

## 6. 用户流程

```text
用户打开“创建订阅方案”
  ↓
选择“单个搜索”或“批量搜索”
  ↓
输入一个标题或多行标题并提交
  ↓
状态框显示真实的搜索中反馈
  ↓
独立搜索结果区展示每个输入的 FOUND / EMPTY / FAILED 结果
  ↓
FOUND：用户查看封面、标题、MiKan ID，并显式选择一个合集
EMPTY：用户修改搜索词或使用已有直连 fallback
FAILED：用户查看脱敏提示并重试，其他批量条目不受影响
  ↓
选择真实合集后复用现有详情解析，生成可编辑订阅草案
  ↓
用户展开、修改、保存、接受，继续 Stage 20 队列与提交流程
```

## 7. 搜索与草案状态契约

单个和批量入口必须共享以下语义：

| 层级 | 示例状态 | 用户态含义 | 允许动作 |
| --- | --- | --- | --- |
| 标题解析 | `RAW` / `PARSED` / `FAILED` | 输入是否被拆分并形成搜索词 | 不直接允许接受 |
| 候选搜索 | `FOUND` | 找到一个或多个公开 MiKan 合集 | 查看并选择候选 |
| 候选搜索 | `EMPTY` | 搜索成功但没有匹配合集 | 修改输入、重试或直连 |
| 候选搜索 | `FAILED` | 搜索请求或解析失败 | 查看脱敏错误并重试 |
| 订阅草案 | `DRAFT` / `READY` | 已显式选择真实合集并生成可编辑草案 | 展开、修改、保存、接受 |
| 已接受 | `ACCEPTED` | 用户已显式接受 | 进入 Stage 20 提交前队列 |

约束：

1. `PARSED` 不能被翻译为“已找到番剧”或“草案”，不能附带可接受的 `preview_request`。
2. `EMPTY` 不包含候选选择按钮、草案展开按钮或接受按钮。
3. `FAILED` 的 details 只允许稳定错误类别、字段和状态码等脱敏信息。
4. 批量条目可分别处于 `FOUND`、`EMPTY`、`FAILED`，单项失败不阻塞其他项。
5. 候选选择后复用现有 `/api/v1/requests` `mikan_bangumi`、preview modify/save 和 Request accept 链路，不另造批量版详情解析器。

## 8. UI 与交互要求

1. `#generate-panel` 标题为“创建订阅方案”。
2. 提供可键盘操作且有明确选中态的“单个搜索 / 批量搜索”分段控件；选中模式高亮，只展示相应输入模块。
3. Storage 偏好摘要不得夹在两个搜索模式之间，可保留为次要说明或移到更合适的位置。
4. 新增 `#search-results-panel`，与现有列表/详情 panel 同级并独占布局一行；搜索前显示空状态，搜索后显示当前模式结果。
5. 单个搜索展示候选卡；批量搜索按原始输入分组，每组展示真实候选、明确空结果或脱敏失败。
6. 候选卡展示封面、标题、MiKan ID、可理解的匹配提示和“选择此合集”；无封面时展示统一占位。
7. 模式切换不得把另一模式的旧结果冒充当前结果；可保留各自非敏感输入，但结果区必须明确当前模式和搜索上下文。
8. loading 时禁用会造成重复请求或模式混淆的输入、切换和提交控件；成功、空结果或异常后恢复。
9. 状态框推荐文案：单项“正在搜索「标题」的候选合集……”；完成后“找到 N 个候选合集”或“未找到匹配的 MiKan 合集”；批量长请求使用“正在搜索并整理 N 个条目的结果……”。
10. 桌面、窄屏、键盘焦点和 screen-reader 语义由 Playwright 回归覆盖。

## 9. Ralph User Stories

### US-158：建立批量真实候选结果状态契约

作为用户，我希望系统区分“标题已解析”“找到候选”“没有候选”和“搜索失败”，从而不会把无效输入误认为真实番剧草案。

验收标准：

1. 批量 API 为每个条目输出稳定、公开的候选搜索结果状态，至少可区分 FOUND、EMPTY、FAILED 或语义等价值。
2. `PARSED` 仅表示标题解析完成；MiKan 候选为空时不得返回可接受的 `preview_request`。
3. 搜索成功但无候选返回正常 EMPTY 结果；网络/页面解析异常返回 FAILED 和脱敏错误，单项失败不阻塞其他项。
4. API/控制器测试覆盖不存在标题、有候选、空候选、异常和敏感字段过滤。
5. `uv run python -m compileall -q src tests` 通过。
6. `uv run pytest -q` 通过。

### US-159：收敛候选选择与订阅草案生成链路

作为用户，我希望单个和批量搜索都在我选择真实 MiKan 合集后才生成订阅草案，从而保证草案来自可审核的真实候选。

验收标准：

1. 单个与批量入口复用 `_search_mikan_candidates`、公开候选序列化和现有候选缓存，不新增第二套 MiKan 搜索/parser。
2. 批量模式仅负责编排多个搜索项；每个 FOUND 条目允许用户选择实际候选。
3. 候选选择复用现有 `mikan_bangumi` 详情解析与 preview modify/save 链路；只有选择成功后条目进入 DRAFT/READY 并获得可编辑 Request。
4. EMPTY/FAILED/PARSED 条目不能展开、修改、保存或接受。
5. API、控制器和前端静态测试覆盖候选选择到草案的状态迁移。
6. `uv run python -m compileall -q src tests` 通过。
7. `uv run pytest -q` 通过。

### US-160：重构创建订阅方案工作台信息架构

作为用户，我希望在单个搜索和批量搜索之间清晰切换，并在独立区域查看结果，从而避免输入与大量卡片混排。

验收标准：

1. `#generate-panel` 标题改为“创建订阅方案”。
2. 页面提供“单个搜索 / 批量搜索”分段切换，选中项高亮且一次只显示对应输入模块。
3. 新增与订阅方案详情同级、独占一行的 `#search-results-panel`；两种模式的结果和批量结果工具栏迁入该面板。
4. 切换模式不会把另一模式的旧结果显示为当前结果，焦点、ARIA 选中态和键盘操作正确。
5. 桌面和窄屏布局保持可读。
6. `node --check src/apps/migu_orca_web/static/app.js` 通过。
7. 使用 `dev-browser` skill 在真实 Chromium 验证。
8. `uv run pytest tests/browser/ -q` 通过。
9. `uv run python -m compileall -q src tests` 通过。
10. `uv run pytest -q` 通过。

### US-161：统一单个与批量真实候选卡片

作为用户，我希望两种搜索模式都展示一致的真实候选信息和封面，从而能判断并选择正确合集。

验收标准：

1. 单个和批量结果复用统一候选卡渲染或共享渲染原语。
2. FOUND 卡片展示公开标题、MiKan ID、匹配提示、封面或明确占位，以及“选择此合集”按钮。
3. 批量结果按原始输入分组；每个分组可包含多个真实候选，不默认选择第一个候选。
4. EMPTY 显示“未找到匹配的 MiKan 合集”且无草案动作；FAILED 显示可重试的脱敏错误且不影响其他分组。
5. `poster_url` 缺失只触发占位，不改变 FOUND 状态。
6. 使用 `dev-browser` skill 验证有封面、无封面、多候选、空结果和部分失败。
7. `node --check src/apps/migu_orca_web/static/app.js` 通过。
8. `uv run pytest tests/browser/ -q` 通过。
9. `uv run python -m compileall -q src tests` 通过。
10. `uv run pytest -q` 通过。

### US-162：增加简洁真实的搜索状态反馈

作为用户，我希望在等待搜索时知道系统正在处理什么，并在结束后看到明确结果摘要。

验收标准：

1. 复用现有状态容器展示搜索开始、完成、无结果和失败反馈。
2. 单个搜索开始文案包含经安全渲染的当前标题，完成文案包含候选数量或明确无结果。
3. 批量搜索在单一长请求下仅展示请求级真实状态和条目总数；除非实现可观测逐项请求，否则不得伪造第 N 项或页面解析进度。
4. loading 期间禁用相关输入、模式切换和提交操作，完成或失败后恢复。
5. 状态变化使用 `aria-live` 且不会造成焦点跳失。
6. 使用 `dev-browser` skill 验证成功、空结果、失败和慢请求。
7. `node --check src/apps/migu_orca_web/static/app.js` 通过。
8. `uv run pytest tests/browser/ -q` 通过。
9. `uv run python -m compileall -q src tests` 通过。
10. `uv run pytest -q` 通过。

### US-163：补齐真实状态与共享链路浏览器回归

作为维护者，我希望浏览器测试使用生产 API 的真实状态形状，从而防止 mock 再次掩盖前后端契约错误。

验收标准：

1. 审计并替换关键测试中用理想化 `DRAFT` 代替真实 `PARSED`/候选状态的 mock。
2. Playwright 覆盖单个和批量 FOUND/EMPTY/FAILED、有封面/无封面、模式切换和独立结果面板。
3. Playwright 覆盖“真实候选选择 → DRAFT → 展开 → 修改/接受”的完整交互。
4. 至少一组 Flask API + Playwright 联合路径使用生产序列化结果，只 mock 外部 MiKan transport，不 mock 成理想化前端状态。
5. 外部访问继续通过测试 seam 或 Playwright route mock，测试不依赖实时 MiKan 网站。
6. 使用 `dev-browser` skill 在真实 Chromium 验证。
7. `node --check src/apps/migu_orca_web/static/app.js` 通过。
8. `uv run pytest tests/browser/ -q` 通过。
9. `uv run python -m compileall -q src tests` 通过。
10. `uv run pytest -q` 通过。

### US-164：Stage 22 文档、安全回归与收尾（已完成）

作为维护者，我希望 Stage 22 的实现、文档和安全边界保持一致，从而可以可靠交接下一阶段。

验收标准：

1. 同步 README、主 PRD、Future Stages、backlog、Stage 22 PRD 和受影响的 M00/M02/M03/M13 模块 PRD，标记 Stage 22 实际完成状态。
2. Stage 21 历史完成事实保持不变；部署/配置向导继续作为 Stage 23 远期可选方向。
3. 端到端安全回归断言新结果面板、API、URL、localStorage、sessionStorage、Request/队列 JSON、日志与 trace 不包含 endpoint、token、cookie、Authorization header、raw HTML、raw RSS XML、magnet、原始响应体、完整失败 URL或本地绝对路径。
4. README 本地验收清单覆盖模式切换、独立结果面板、真实候选选择、EMPTY/FAILED、封面占位和搜索状态反馈。
5. `node --check src/apps/migu_orca_web/static/app.js` 通过。
6. 使用 `dev-browser` skill 在真实 Chromium 验证。
7. `uv run pytest tests/browser/ -q` 通过。
8. `uv run python -m compileall -q src tests` 通过。
9. `uv run pytest -q` 通过。

## 10. Ralph 执行说明

1. 按 `scripts/ralph/prd.json` 的 priority 顺序执行 US-158 至 US-164，每次迭代只完成一个 story。
2. UI story 必须读取并使用 `.agents/skills/dev-browser/SKILL.md`，通过项目 Playwright + 真实 Chromium 验证。
3. 不得通过把后端 mock 状态改成前端期望值来绕过契约问题；测试数据应匹配生产序列化形状。
4. 每个 story 完成后运行其验收标准列出的质量检查，更新 `passes` 并追加 `scripts/ralph/progress.txt`。
5. Stage closeout 前必须运行全量测试、安全回归和文档一致性检查。

Stage 22 完成标志（已达成）：用户能在一个清晰的创建订阅方案工作台中切换单个/批量搜索，两种入口在独立结果面板展示真实 MiKan 候选；无效输入明确显示无结果，不产生空壳草案；用户选择真实候选后才能生成并操作草案；搜索状态简洁真实，生产状态形状有浏览器回归保护。

## 11. Stage 23 handoff

原 Stage 22「部署/配置向导可行性验证」顺延为 Stage 23，仍为远期可选能力，不阻塞搜索工作台和批量订阅闭环。候选方向保持不变：配置检查清单、脱敏连接诊断、教程式向导、Docker Compose 示例，以及仅处理非敏感配置或明确脱敏示例的导入/导出。

Stage 23 不得将 MiGuOrca 扩展为通用运维 Agent，不默认接管用户机器、NAS、Docker daemon 或外部系统配置，也不得改变“不直接创建 qBittorrent 下载任务、不绕过 Auto Bangumi”的边界。
