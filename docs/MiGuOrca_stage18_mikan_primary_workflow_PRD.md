# MiGuOrca Stage 18 PRD: MiKan Primary Workflow and Preview Refinement

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 18 PRD: MiKan Primary Workflow and Preview Refinement |
| 文档类型 | Stage PRD |
| 当前状态 | Planned |
| 创建日期 | 2026-08-15 |
| 依赖阶段 | Stage 16、Stage 17 |

## 2. 背景

Stage 16 已完成真实 MiKan 合集详情页解析与直连 URL/ID 入口。Stage 17 已完成真实 MiKan 搜索候选合集展示、用户手动选择、直连 fallback、候选缓存和推荐标签。

Stage 17 后的 Web UI 仍存在产品方向偏差：页面叙事仍像是“默认 fixture 生成为主，真实 MiKan 是附属插件”。真实产品流程应相反：用户输入番剧名后，默认去 MiKan 搜索候选合集；fixture 只是开发、离线测试和回归使用的技术 seam，不应成为普通用户主流程。

当前 `/index` 还暴露了 `search_endpoint`、`timeout_seconds`、`query` 等技术字段。普通用户不应理解或填写 MiKan 搜索 URL、搜索超时秒数或英文技术名。系统应内置合理的 MiKan 默认搜索配置：搜索 URL 固定等价于 `https://mikanani.me/Home/Search?searchstr=<番剧名>`，超时由系统配置控制，不在主界面暴露。

预览流程也需要调整：用户选择候选或使用直连 fallback 后，默认先生成可编辑预览草案，用户可在预览中调整字幕组、筛选规则和文件夹名，确认后再保存为正式订阅方案。

## 3. 目标

1. 将真实 MiKan 候选搜索设为 Web `/index` 主生成流程。
2. 主生成区保留当前“Request 生成”和列表同一行的整体布局，但文案和行为改为真实 MiKan 候选搜索。
3. 普通 Web UI 不再要求用户填写 `search_endpoint`、`timeout_seconds` 或 `query`。
4. 系统提供默认 MiKan 搜索 endpoint 与 timeout；高级覆盖只保留为 API、测试 seam 或后续设置项。
5. 在主生成区增加“搜索无结果时使用直连合集”勾选框；勾选后在候选展示区域显示 MiKan 合集 URL 或 ID 输入框。
6. 直连 fallback 输入 MiKan 合集 URL 或 bare ID 后可直接生成预览草案，不依赖用户填写搜索 endpoint。
7. 候选选择和直连 fallback 默认生成可编辑预览草案，而不是立即保存。
8. 预览草案中允许修改字幕组、包含规则、排除规则、`使用正则`、`大小写敏感` 和文件夹名；保存时持久化修改后的草案。
9. 用户态文案中文化，避免直接展示泛化对象名 `Request` 和代码状态值。
10. Seeds 展示重排为“有效种子优先、完整种子第二、排除种子最后”，完整种子按 MiKan 详情页字幕组分组展示。
11. fixture 模式降级为开发/离线测试路径，不再作为普通 Web 主流程。

## 4. 非目标

1. 不实现 AI 番剧名解析或搜索词增强；该能力继续保留在 backlog。
2. 不移除 CLI、单元测试和浏览器测试所需的 fixture seam。
3. 不在本阶段新增 qBittorrent 下载、订阅创建或 Auto Bangumi 自动提交。
4. 不要求重命名内部 Python 类、API 字段或存储字段；本阶段优先修正用户界面、流程和文档命名。
5. 不承诺 MiKan 搜索可以列出所有合集；MiKan 搜索页可解析到什么，系统就展示什么。

## 5. 产品决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D18-01 | 真实 MiKan 搜索是 Web 主流程 | 用户输入番剧名后默认搜索 MiKan 候选合集，而不是先生成 fixture Request。 |
| D18-02 | fixture 是开发/离线测试路径 | fixture 继续存在，但普通用户主界面不应把它呈现为默认业务流程。 |
| D18-03 | 主界面不暴露 MiKan 搜索 URL | `search_endpoint` 使用系统默认值，普通用户只输入标题。 |
| D18-04 | timeout 是系统配置 | `timeout_seconds` 不在 `/index` 普通流程展示；后续可放到设置或配置文件。 |
| D18-05 | 直连 fallback 独立可用 | 输入 MiKan 合集 URL 或 ID 应直接进入详情解析，不需要填写 search endpoint。 |
| D18-06 | 默认先预览 | 候选选择或直连 fallback 默认 `save_request=false`，用户确认草案后再保存。 |
| D18-07 | 预览可编辑 | 预览阶段必须能调整字幕组、筛选规则和文件夹名；保存后再进入正式确认/提交链路。 |
| D18-08 | UI 优先中文化 | 用户界面避免直接显示 `Request`、`PENDING_CONFIRM`、`ACCEPTED`、`CANCELLED`、`query` 等技术词。 |

## 6. 目标流程

```text
用户在主生成区输入番剧标题
  ↓
系统使用默认 MiKan 配置请求 /Home/Search?searchstr=<标题>
  ↓
页面展示 MiKan 候选合集卡片
  ↓
用户选择一个合集
  ↓
系统解析合集详情页、字幕组 RSS 与种子
  ↓
生成可编辑订阅草案预览
  ↓
用户调整字幕组、筛选规则和文件夹名
  ↓
用户保存草案为正式订阅方案
  ↓
后续执行确认、修改、取消、删除或 Auto Bangumi 提交
```

搜索无结果或目标合集未出现在候选中时：

```text
用户勾选“搜索无结果时使用直连合集”
  ↓
输入 MiKan Home/Bangumi URL 或数字 ID
  ↓
系统使用默认 MiKan host 派生详情页 URL 或校验同源 URL
  ↓
生成可编辑订阅草案预览
```

## 7. 用户故事

### US-124: 新增默认 MiKan Web 配置

作为 Web 用户，我希望系统内置 MiKan 搜索配置，这样我只需要输入番剧标题。

验收标准：

1. 新增系统默认 MiKan Web 配置，默认搜索 endpoint 等价于 `https://mikanani.me/Home/Search`，候选搜索时由系统追加 `searchstr=<番剧名>`。
2. 新增默认 MiKan timeout 配置，例如 10 或 15 秒；普通 `/index` 页面不再要求用户填写 timeout。
3. 候选搜索 API 和 direct URL/ID fallback 在未传 request-scoped `mikan_config` 时可使用系统默认 MiKan 配置。
4. 现有显式 `mikan_config` 仍可作为测试 seam 或高级调用覆盖默认值。
5. 默认配置不得包含 secret，不得写入 browser storage、URL、Request snapshot 或 history。
6. 单元测试覆盖默认 endpoint、默认 timeout、显式 config 覆盖、候选搜索使用默认配置、direct ID 使用默认 host 派生详情页 URL。
7. Tests pass。
8. Typecheck passes。

### US-125: 将标题输入改为默认 MiKan 候选搜索

作为 Web 用户，我希望主生成区输入标题后直接搜索真实 MiKan 候选合集。

验收标准：

1. `/index` 主生成区保留与 Request 列表同一行的布局，但用户态标题改为“真实 MiKan 候选搜索”或等价中文文案。
2. 主输入只要求番剧标题；按钮触发候选搜索 API，而不是直接走 fixture 生成。
3. 候选卡片在主生成区附近展示，包含标题、MiKan ID、封面和推荐标签。
4. 普通可见 UI 不出现 `search_endpoint`、`timeout_seconds` 或 `query` 字样。
5. 搜索 loading、无结果、失败和重试状态使用中文文案。
6. 即使只有一个候选，也必须用户点击选择，不能自动生成草案。
7. 浏览器测试覆盖主标题搜索、多候选展示、单候选不自动选择、无结果状态和失败恢复。
8. Tests pass。
9. Typecheck passes。
10. Verify in browser using dev-browser skill。

### US-126: 新增主生成区直连兜底勾选框

作为 Web 用户，我希望 MiKan 搜索没找到目标合集时可以在同一区域输入合集 URL 或 ID。

验收标准：

1. 主生成区增加“搜索无结果时使用直连合集”复选框，默认不勾选。
2. 勾选后，在原候选展示区域或其附近显示“MiKan 合集 URL 或 ID”输入框和生成预览按钮。
3. 直连 URL/ID fallback 不要求用户填写 `search_endpoint` 或 timeout。
4. bare numeric ID 使用默认 MiKan host 派生 `Home/Bangumi/<id>` 详情 URL。
5. URL fallback 必须继续复用 Stage 16 `mikan_bangumi` 校验和详情解析链路。
6. 成功生成预览后可清空直连输入；失败时保留输入便于重试。
7. 直连输入不得写入 browser storage、URL、Request snapshot、history、日志、截图或 trace。
8. 浏览器测试覆盖勾选显示、取消隐藏、URL 成功、ID 成功、无效输入错误和无 endpoint 情况。
9. Tests pass。
10. Typecheck passes。
11. Verify in browser using dev-browser skill。

### US-127: 生成可编辑预览订阅草案

作为 Web 用户，我希望选择 MiKan 合集后先看到可编辑草案，而不是立即保存。

验收标准：

1. 候选选择和直连 fallback 默认发送 `save_request=false` 或等价预览参数。
2. 预览详情使用中文标识“订阅草案（未保存）”，不展示确认、取消、删除或 Auto Bangumi 提交动作。
3. 预览详情展示可编辑表单，允许修改 `selected_subtitle_group`、`filter_rule.must_contain`、`filter_rule.must_not_contain`、`filter_rule.use_regex`、`filter_rule.case_sensitive` 和 `expected_folder_name`。
4. 修改预览时在前端或后端重新计算当前选中字幕组的有效/排除种子展示；不得要求先保存再调用 modify API。
5. 点击保存草案时，持久化修改后的订阅方案，并刷新列表、详情和 URL `request_id`。
6. 保存后的对象进入现有待确认流程，可继续确认、取消、修改和删除。
7. 预览和保存流程不得泄露 raw HTML、raw RSS XML、cookie、token、完整失败 URL 或原始响应体。
8. 浏览器测试覆盖候选生成预览、预览修改字幕组、预览修改筛选规则、预览修改文件夹名、保存后保留修改。
9. Tests pass。
10. Typecheck passes。
11. Verify in browser using dev-browser skill。

### US-128: 中文化用户态名称和状态

作为普通用户，我希望页面展示业务含义，而不是内部代码对象和状态枚举。

验收标准：

1. 普通 Web UI 将用户态 `Request` 文案替换为“订阅方案”“订阅草案”或更合适的中文名称；内部字段、API 和测试 fixture 可继续使用 Request。
2. 状态展示映射为中文：`PENDING_CONFIRM` 显示为“待确认”，`ACCEPTED` 显示为“已确认”，`CANCELLED` 显示为“已取消”。
3. 列表、详情、通知、按钮、空状态和错误提示不直接暴露代码状态值。
4. 普通 UI 不展示 `query`、`search_endpoint`、`timeout_seconds` 等技术字段名。
5. 如保留开发/测试模式入口，必须明确标为开发/离线测试，不与主流程混淆。
6. 静态 UI 测试和浏览器测试覆盖主要页面文案与状态映射。
7. Tests pass。
8. Typecheck passes。
9. Verify in browser using dev-browser skill。

### US-129: 重构 Seeds 展示顺序和字幕组分组

作为 Web 用户，我希望先看当前选择字幕组的有效种子，再按字幕组查看完整种子和排除种子。

验收标准：

1. Seeds 区展示顺序改为：有效种子、完整种子、排除种子。
2. 有效种子区域明确显示“当前选中字幕组”和字幕组名称。
3. 完整种子区域按 MiKan 详情页解析到的字幕组分组展示；每组显示字幕组名、种子数量和可展开列表。
4. 排除种子区域放在最后，并展示中文排除原因。
5. 完整种子和排除种子默认可折叠；有效种子默认优先可见。
6. 修改预览或已保存方案的字幕组、包含规则、排除规则、匹配模式或大小写后，Seeds 展示同步更新。
7. Seeds 展示不得渲染 raw RSS XML、magnet、cookie、token 或原始响应体。
8. 浏览器测试覆盖展示顺序、字幕组分组、展开/收起、筛选更新和敏感字段不展示。
9. Tests pass。
10. Typecheck passes。
11. Verify in browser using dev-browser skill。

### US-130: 将 fixture 模式降级为开发离线测试路径

作为维护者，我希望 fixture 能继续用于测试，但普通用户不会误以为它是主流程。

验收标准：

1. `/index` 普通主流程不再默认生成 fixture 订阅方案。
2. fixture 生成能力保留在 CLI、API 测试 seam 和离线回归测试中。
3. 如果 Web UI 仍保留 fixture 入口，必须放入明确的开发/离线测试区域，默认隐藏或低优先级展示。
4. README 和模块文档说明：真实 MiKan 是 Web 主流程，fixture 是开发/离线测试路径。
5. 现有离线测试不因主流程切换而依赖真实 MiKan 网络。
6. 浏览器测试覆盖普通用户路径不触发 fixture 生成；如保留开发入口，覆盖其仍可用于离线测试。
7. Tests pass。
8. Typecheck passes。
9. Verify in browser using dev-browser skill。

### US-131: 补齐 Stage 18 文档与回归收尾

作为维护者，我希望 Stage 18 的行为、边界和测试结果同步到项目文档。

验收标准：

1. README 更新 Stage 18 的真实 MiKan 主流程、默认配置、直连 fallback、可编辑预览、中文状态和 Seeds 展示。
2. 主 PRD、Stage 18 PRD、M00、M03、M13、backlog 和 Ralph progress 更新 Stage 18 完成状态与后续事项。
3. 若修改 M01、M06 或 M11 行为，对应模块 PRD 同步更新。
4. 安全回归确认 MiKan endpoint、raw HTML、raw RSS XML、cookie、token、原始响应体、magnet 不进入 storage JSON、history、browser storage、URL、日志、截图或 trace。
5. `uv run pytest -q` 通过。
6. `uv run python -m compileall -q src` 通过。
7. `uv run pytest tests/browser/ -v` 通过；如果浏览器不可用，必须记录明确 skip 原因。
8. Typecheck passes。

## 8. 安全边界

1. 默认 MiKan 配置不包含 secret。
2. 用户在直连 fallback 中输入的 URL 或 ID 是 request-scoped，不写入 browser storage、URL、history 或持久配置。
3. 原始 HTML、原始 RSS XML、magnet、cookie、token、完整失败 URL、原始响应体和本地绝对路径不得写入 storage JSON、状态历史、浏览器 storage、URL、日志、截图或 trace。
4. 公共 RSS URL 仍可作为订阅方案源元数据保存；magnet 不保存。
5. 预览草案未保存时不得暴露确认、取消、删除或 Auto Bangumi 提交动作。

## 9. 验收汇总

Stage 18 完成后，普通 Web 用户应可以：

1. 在主生成区只输入番剧标题。
2. 看到真实 MiKan 候选合集。
3. 手动选择正确合集。
4. 在无结果时勾选直连 fallback 并输入 URL 或 ID。
5. 先得到可编辑订阅草案预览。
6. 在预览中修改字幕组、筛选规则和文件夹名。
7. 确认无误后保存为正式订阅方案。
8. 看到中文业务文案、中文状态和更合理的 Seeds 展示。
