# MiGuOrca Stage 25 PRD：正式番名与季数解析

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 25 PRD：正式番名与季数解析 |
| 文档类型 | Stage PRD |
| 当前状态 | 已规划，待开发 |
| 创建日期 | 2026-08-26 |
| Backlog | BL-018 |
| 依赖阶段 | Stage 19、Stage 21、Stage 22、Stage 23、Stage 24 |
| 规划分支 | `agent/stage25-title-season-parsing` |
| Ralph stories | US-181～US-188 |

## 2. 背景与问题

Stage 19 已建立 `AnimeTitleParsingProvider` 和离线 fake provider，Stage 21 已支持用户明确保存的非敏感标题修正与搜索词增强，Stage 22/23 已把单个和批量入口收敛到真实 MiKan 候选选择链路。但当前名称解析仍不是可供普通用户依赖的正式能力：

1. Web 批量入口固定使用 `FakeAnimeTitleParsingProvider`，只对 `萌王S4`、`路哥S4` 等少量开发示例有硬编码结果。
2. `无职转生s4` 等“标题/简称 + 季数”输入不能稳定拆成基础标题、结构化季数和有序搜索词。
3. `S4`、`第4季`、`第四季`、`Season 4`、`第4期` 等表达的解析与变体生成分散在 title parser、search enhancer、命名和 AutoBangumi payload 中，边界不一致。
4. 单个搜索直接把原输入交给 MiKan；批量搜索先过 fake provider。两种入口没有共享同一解析和 fallback 契约。
5. API 只有不透明的 `source`、`season_hint` 和字符串数组，不能解释“识别了什么、依据是什么、实际搜索了什么”。
6. UI 存在“源名称：搜索词：...”标签叠加，低置信度、冲突季数和原始输入 fallback 的说明不够清楚。
7. 标题解析成功不能证明 MiKan 合集真实存在，更不能直接证明最终 Request 或 AutoBangumi 的季数；仍必须由用户显式选择真实候选并确认。

## 3. 目标

1. 用确定性、离线可测的规则解析器替换普通 Web 流程中的 fake 默认实现；fake provider 只保留为测试 seam。
2. 建立单个与批量入口共用的结构化标题解析结果，明确原始输入、规范化标题、基础标题、季数、来源、置信度、审核提示和有序查询计划。
3. 支持常见季数表达第一至第九十九季，并对冲突、越界、Part/分割放送等无法证明的表达保持人工审核，不猜测。
4. 复用用户已保存的公开标题修正和可维护的别名规则，生成有界、去重、可解释的搜索词；没有修正或别名时安全回退规范化基础标题和原始输入。
5. 单个与批量搜索使用同一查询计划和逐级 fallback，真实候选仍只来自 M03，最终合集仍由用户显式选择。
6. 收敛 Web UI 的解析来源、识别标题、识别季度、实际搜索词和审核提示，不向用户展示内部 source code 或重复标签。
7. 只有真实候选标题或用户显式确认能证明的季数才进入 Request/命名/AutoBangumi 映射；无法证明时保持缺失或 fail closed。

## 4. 非目标

1. 不接入真实 LLM provider；BL-021 继续独立评估供应商、密钥、成本与 fallback。
2. 不自动选择 MiKan 候选，不自动保存或接受草案，不自动提交 AutoBangumi。
3. 不抓取或推断当前最新播出集数；BL-020 仍未排期。
4. 不实现新版 AutoBangumi API Token/Bearer 写契约；BL-022 继续 fail closed。
5. 不把 `Part 2`、分割放送、剧场版、OVA、重制版或罗马数字静默解释为季数。
6. 不引入后台 worker、远程别名服务、付费 API、用户账号体系或数据库迁移。
7. 不保证 MiKan 搜索返回所有季度；手动搜索和 MiKan URL/ID 直连 fallback 必须保留。

## 5. 产品与技术决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D25-01 | 默认使用确定性规则解析器 | 普通 Web 流程不再依赖 fake 映射；fake provider 仅供离线测试与显式注入。 |
| D25-02 | 解析结果与真实候选严格分层 | 解析只生成搜索计划；只有 M03 返回 `bangumi_id` 与规范化 `mikan_url` 的结果才是真实候选。 |
| D25-03 | 季数使用结构化证据 | 至少包含 `number`、`raw`、`normalized`、`source`；冲突/越界不生成可信 number。 |
| D25-04 | 季数范围为 1～99 | 支持常见中文、阿拉伯数字、S/Season/期表达；0、100 以上及无法证明的形式进入审核。 |
| D25-05 | 查询计划有界且可解释 | 查询项含 `query`、`source`、`priority`；规范化去重，默认最多 8 项，禁止无界网络请求。 |
| D25-06 | correction 优先但不自动定案 | 用户明确保存的公开修正优先于内置别名/规则；仍只影响搜索词，不自动选择合集。 |
| D25-07 | fallback 按层执行 | 优先修正/别名与正式季度词；无候选或单条查询失败时再尝试规则变体和原始输入。 |
| D25-08 | 单个与批量共享编排 | `/api/v1/mikan/candidates` 与 `/api/v1/batches/parse` 复用同一 parser/query planner/search seam。 |
| D25-09 | 已确认数据才能下游传播 | parser 的提示不能直接成为 AB season；必须由选中候选公开标题、结构化公开元数据或用户确认建立证据。 |
| D25-10 | 用户态来源使用中文白名单 | 页面显示“规则解析”“已保存修正”“别名规则”“原始输入回退”等稳定中文，不拼接内部枚举。 |

## 6. 结构化解析契约

### 6.1 解析结果

公开 API 的标题解析摘要至少表达：

```json
{
  "raw_title": "无职转生s4",
  "normalized_title": "无职转生 S4",
  "base_title": "无职转生",
  "canonical_title_candidates": ["无职转生"],
  "season": {
    "number": 4,
    "raw": "s4",
    "normalized": "第四季",
    "source": "rule"
  },
  "query_plan": [
    {"query": "无职转生 第四季", "source": "rule:canonical-season", "priority": 1},
    {"query": "无职转生 第4季", "source": "rule:season-variant", "priority": 2},
    {"query": "无职转生 S4", "source": "rule:season-variant", "priority": 3},
    {"query": "无职转生s4", "source": "fallback:raw", "priority": 4}
  ],
  "confidence": 0.8,
  "needs_user_review": false,
  "review_hints": [],
  "source": "rule"
}
```

迁移期间可以保留现有 `season_hint` 和 `search_queries` 兼容字段，但必须由结构化 `season` / `query_plan` 单向派生，不能形成第二套规则。

### 6.2 季数语义

应识别并规范化：

- `S4`、`s4`、`S 4`；包括紧贴中文标题的 `无职转生s4`。
- `Season 4`、大小写和合理空白变体。
- `第4季`、`第四季`、`第4期`、`第四期`。
- 第一至第九十九季；全角数字先做 NFKC 等价规范化。

必须进入人工审核且不得伪造可信季数：

- `S0`、`第零季`、`第100季` 等越界值。
- 同一输入出现互相冲突的季数标记。
- `Part 2`、上下篇、分割放送、剧场版、OVA、重制版等非季数语义。
- 不完整或无法证明的显式季数标记。

完全没有季数标记时 `season` 为 `null`；不得默认第一季。AutoBangumi 3.1 的默认第一季兼容行为仍由 M10 在已确认标题边界内处理，不由搜索 parser 伪造。

### 6.3 标题与别名来源

来源优先级：

1. 用户明确保存且通过安全校验的 `TitleCorrection`。
2. 仓库内版本化、可审查的公开别名规则。
3. 确定性规则从原输入剥离季数后的基础标题。
4. 规范化原始输入 fallback。

内置别名必须有公开来源说明或至少以测试 fixture/人工验收案例证明，不得把未知简称高置信度映射为单一正式标题。多候选、低置信度、来源冲突都必须设置 `needs_user_review=true`。

## 7. 查询计划与搜索 fallback

1. query planner 只接受结构化解析结果和通过安全校验的公开修正/别名，不接收 endpoint、token、cookie、原始 HTML/RSS 或响应体。
2. 对查询文本做 Unicode/空白规范化和稳定去重；保留展示所需原文，不把不同语义的标题粗暴 casefold 合并。
3. 默认最多生成 8 个查询项，每项有稳定 `source` 和 `priority`；超限按来源/优先级截断并产生审核提示。
4. 搜索按优先级逐层执行：高优先级层得到真实候选后停止向更弱 fallback 扩散；该层内候选按现有 M03 顺序去重。
5. 单个查询超时/失败不阻断同 item 后续 fallback；全部查询失败为 FAILED，至少一次正常返回但均为空为 EMPTY。
6. 候选保留实际 `source_query`，API 另返回已尝试查询摘要；不得伪造服务端逐项进度。
7. 用户可以用原始标题重新手动搜索，或使用现有 MiKan URL/ID 直连入口。

## 8. Request 与下游证据边界

1. parser 的 `canonical_title_candidates` 和 season 只是可审核建议，不得在未选择真实候选时生成可接受 Request。
2. 用户选择真实 MiKan 候选后，以候选公开标题、aliases、MiKan ID/URL 和可验证元数据构造 preview；parser 证据可以作为审核摘要，但不能覆盖候选标题。
3. 结构化季数只有在候选公开标题/元数据与解析结果一致，或用户在候选/草案审核中通过明确的季数确认控件确认后，才能写入 `matched_bangumi.season` / `season_raw`；确认值限制为 1～99 并记录公开来源。
4. 候选与解析季数冲突时必须显示审核提示，不自动修正文件夹名或 AutoBangumi season。
5. M07 命名和 M10 payload 只消费已确认 Request 中的可证明数据；无法证明的非第一季继续 fail closed。
6. correction 存储继续只保存允许的公开非敏感字段，并保持同 raw title 最新版本与全局上限。

## 9. Web UI 契约

1. 单个与批量结果使用统一解析摘要：识别标题、识别季度、解析来源、实际搜索词和需人工核对原因。
2. 候选卡来源只显示一次，例如 `搜索词：无职转生 第四季`；不得再出现“源名称：搜索词：...”嵌套标签。
3. `source` / query source 内部枚举通过白名单映射为中文；未知值显示“其他解析来源”，不直接回显任意字符串。
4. 低置信度、多别名、冲突季数、截断查询计划、原始输入 fallback 和候选季数冲突均显示“需人工核对”。
5. EMPTY/FAILED 继续提供重试/手动搜索和 MiKan URL/ID fallback，不展示草案接受动作。
6. 解析或搜索不会自动打开、选择、保存或接受候选；即使只有一个真实候选也要求用户点击“选择此合集”。
7. 桌面和窄屏布局、键盘操作、ARIA 状态与 Stage 22/23 的单实例浮层和统一详情行为保持不变。

## 10. 安全与隐私

1. raw title、公开别名和查询计划只用于当前搜索与现有非敏感修正流程；不新增外部凭据或远程 provider。
2. endpoint、token、Cookie、Authorization、账号密码、raw HTML、raw RSS XML、magnet、原始响应体、完整失败 URL和本地绝对路径不得进入解析结果、查询计划、API、页面、storage、日志、截图或 trace。
3. provider/规则异常只返回稳定 error type、步骤、来源类别、输入长度和 `recoverable`；不得回显异常原文或完整输入。
4. 查询数量、标题长度、候选数量继续有界；不得让一个恶意输入制造无界 MiKan 请求。
5. 自动化只使用 fixture、fake transport 和 Playwright route，不访问真实 MiKan、AutoBangumi 或 qBittorrent。

## 11. Ralph User Stories

### US-181：建立结构化标题解析与查询计划契约

作为开发者，我希望标题解析结果具有统一、可演进且可审核的数据结构，使单个、批量、UI 和下游不再各自解释字符串。

验收标准：

1. 扩展 `AnimeTitleParseResult` 或等价模型，表达 normalized/base title、结构化 season、query plan、来源、置信度和 review hints。
2. 定义稳定来源枚举与中文展示白名单；未知来源安全降级，不回显任意 provider 字符串。
3. 兼容字段 `season_hint` / `search_queries` 如保留，只能从新结构单向派生，并有迁移测试。
4. 模型校验标题/查询长度、季数范围、查询数量、priority 与空值，输出不可变且可 JSON 序列化。
5. Tests pass。
6. Typecheck passes。

### US-182：实现确定性季数解析与规范化

作为用户，我希望系统正确理解标题中的常见季数表达，并在冲突或无法证明时要求我核对。

验收标准：

1. 纯函数支持 1～99 的 `S/s`、`Season`、`第N季/期`、中文数字季/期及合理空白/全角数字。
2. `无职转生s4` 能拆成基础标题 `无职转生` 和 season 4，并生成规范化 `第四季`。
3. 无季数标记返回 null，不默认第一季；0、100+、不完整标记、Part/分割放送不得静默映射。
4. 多个一致标记可去重；冲突标记返回审核提示且不生成可信 season number。
5. title parser、search enhancer、命名和 AB 所需季数工具复用同一原语或明确适配层，不保留互相矛盾的复制逻辑。
6. Tests pass。
7. Typecheck passes。

### US-183：实现正式标题、别名与有界查询计划

作为用户，我希望简称和季数被转换成一组有序、可解释的 MiKan 搜索词，同时未知简称仍能安全回退。

验收标准：

1. 新增默认确定性 rule provider；普通 Web 流程不再默认 fake provider，fake 只保留测试/显式注入。
2. 按 correction → 版本化别名 → 基础标题 → 原始输入生成查询，输出来源与 priority，Unicode/空白规范化后稳定去重。
3. 季数查询至少覆盖中文正式形式、阿拉伯数字季、S 和 Season 形式，整体默认不超过 8 项。
4. 未知别名、多个 canonical candidates、低置信度或查询截断设置审核提示，不伪造高置信度正式标题。
5. `萌王S4`、`无职转生s4`、中日文/罗马字修正、普通无季标题和恶意超长输入有行为测试。
6. Tests pass。
7. Typecheck passes。

### US-184：统一单个与批量候选搜索编排

作为用户，我希望单个搜索和批量搜索对相同输入使用相同解析与 fallback，从而得到一致结果。

验收标准：

1. 抽取共享 parse → query plan → M03 candidate search 编排，供单个 candidates API 与批量 parse API 复用。
2. 按 query priority 分层 fallback；高优先级得到候选后停止弱 fallback，单条查询失败不阻断后续查询。
3. 全部查询失败返回 FAILED；至少一次成功但全空返回 EMPTY；候选按公开 identity 稳定去重并保留实际 source query。
4. 每个 item 最多执行有界查询数；批量单项失败不阻断其他 item，缓存与 Stage 23 提前停止行为保持不变。
5. 不自动选择唯一候选，不生成空壳 preview，不访问真实外部服务。
6. Tests pass。
7. Typecheck passes。

### US-185：扩展单个与批量 API 的可审核解析摘要

作为 API/UI 使用者，我希望看到系统识别的标题、季数、来源和实际查询，从而可以判断结果是否可信。

验收标准：

1. 单个与批量响应共享解析摘要和 attempted query 结构，同时保持现有候选公开字段兼容。
2. API 明确区分 PARSED/FOUND/EMPTY/FAILED；解析成功不等于候选存在，EMPTY 不附带可接受 preview。
3. correction、rule、alias、fallback 来源通过固定枚举输出；错误 details 只含稳定类别、字段、长度和 recoverable。
4. 旧客户端需要的 `query`、`search_queries` 等字段如保留，有明确兼容测试；不得出现相互矛盾的数据。
5. API 响应、日志与测试证明不包含外部敏感值、raw HTML/RSS、完整失败 URL或本地绝对路径。
6. Tests pass。
7. Typecheck passes。

### US-186：约束候选选择后的季数证据与下游传播

作为用户，我希望搜索提示不会被误当成已确认季数，从而避免文件夹名或 AutoBangumi 订阅到错误季度。

验收标准：

1. 选择真实 MiKan 候选后，preview 以候选公开 title/aliases/ID/URL 为准，不允许 parser canonical title 覆盖。
2. 只有候选公开标题/结构化元数据与解析一致或用户显式确认时，才写入 matched_bangumi season/season_raw。
3. 候选缺少季数证据但 parser 有可信 season 时，UI/API 提供默认未确认的 1～99 季数确认字段；只有用户显式确认才写入，不能由候选选择动作隐式勾选。
4. 候选与解析季数冲突时保留公开证据和审核提示，不自动修改 folder name 或 AB season；用户必须先明确解决冲突。
5. M07 与 M10 继续只消费 accepted Request 中的可证明字段；无法证明的显式非第一季 fail closed。
6. 单个、批量、保存草案、接受、retry 使用同一证据规则并有回归测试。
7. Tests pass。
8. Typecheck passes。

### US-187：收敛解析与搜索结果 Web UI

作为用户，我希望清楚看到系统如何理解标题和季数，并在不确定时方便手动纠正。

验收标准：

1. 单个与批量结果展示统一的识别标题、识别季度、中文解析来源、实际搜索词和审核提示。
2. 修复“源名称：搜索词：...”标签叠加；候选来源只显示一次且不泄露内部枚举。
3. 低置信度、多别名、季数冲突、原始输入 fallback、查询截断和候选冲突显示“需人工核对”。
4. EMPTY/FAILED 保留手动重试与 MiKan URL/ID fallback；任何结果都不会自动选择、保存、接受或提交。
5. Playwright 覆盖单个/批量、`无职转生s4`、无季标题、冲突季数、EMPTY/FAILED、窄屏、键盘与敏感值过滤。
6. `node --check src/apps/migu_orca_web/static/app.js` 通过。
7. Verify in browser using dev-browser skill。
8. Tests pass。
9. Typecheck passes。

### US-188：Stage 25 文档、安全回归与收尾

作为维护者，我希望 Stage 25 的实现、文档和测试一致，并留下可直接审查的 Ralph 归档。

验收标准：

1. 同步 README、主 PRD、Future Stages、backlog、Stage 25 PRD 与 M00/M02/M03/M07/M10/M12/M13；BL-018 标记实际完成状态。
2. README 手动验收覆盖规则解析、季数冲突、单个/批量一致性、来源展示、EMPTY/FAILED 和直连 fallback。
3. 安全回归证明查询数量有界，解析/API/UI/storage/log/trace 不泄露外部敏感值或原始外部内容。
4. 将最终 `prd.json` 与 `progress.txt` 归档到 `scripts/ralph/archive/<date>-stage25-title-season-parsing/`，不创建下一 Stage PRD。
5. `uv run python -m compileall -q src tests` 通过。
6. `node --check src/apps/migu_orca_web/static/app.js` 通过。
7. `uv run pytest -q -m "not browser"` 通过。
8. `uv run pytest tests/browser/ -q` 在真实 Chromium 全部通过，不得整体 skip。
9. `uv run pytest -q` 通过。
10. `git diff --check`、工作区和提交历史检查通过。
11. Verify in browser using dev-browser skill。
12. Tests pass。
13. Typecheck passes。

## 12. Ralph 执行说明

1. 按 `scripts/ralph/prd.json` priority 顺序执行 US-181～US-188，一次只完成一个 story，一 story 一提交。
2. 开发 Agent 使用 Codex、`gpt-5.6-terra` 和 `scripts/ralph/ralph.sh`。
3. US-181/182 先完成结构和纯函数，不得在多个模块各写一套季数正则。
4. US-184/185 必须以共享编排收敛单个与批量入口，不得复制第二套 MiKan parser 或候选序列化。
5. US-187/188 必须读取并使用 `.agents/skills/dev-browser/SKILL.md`，外部系统由 fixture/route 隔离。
6. 每个 story 完成后更新自身 `passes` 并追加 progress；不得提前把后续 story 标记完成。
7. 自动化不访问真实 MiKan、AutoBangumi 或 qBittorrent，不创建真实订阅或下载任务。

Stage 25 完成标志：单个和批量输入能通过同一确定性解析与有界查询计划理解常见标题/季数表达；公开 API 的 season 使用不可变 `number/raw/normalized/source` 契约，兼容字段仅单向派生；用户可以看见识别依据和实际搜索词，在歧义、混合不支持标记或冲突时得到明确人工审核提示；真实候选仍由用户显式选择，缺少非第一季公开证据时须明确确认，只有可证明季数才进入 Request、命名与 AutoBangumi 映射。AutoBangumi 3.1.18 的可选海报字段只传播服务端校验后的 MiKan 原始公开 URL。
