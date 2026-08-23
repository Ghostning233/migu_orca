# MiGuOrca Stage 21 PRD: 用户偏好与智能推荐闭环

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 21 PRD: 用户偏好与智能推荐闭环 |
| 文档类型 | Stage PRD |
| 当前状态 | 已完成 |
| 创建日期 | 2026-08-19 |
| 完成日期 | 2026-08-20 |
| 依赖阶段 | Stage 19、Stage 20 |

## 2. 背景

Stage 19 和 Stage 20 已经完成批量新番输入、MiKan 候选发现、订阅草案卡片、批量接受、Auto Bangumi 提交前队列和失败恢复。当前用户仍需要逐张卡片修改字幕组、筛选规则和文件夹名称，系统也没有把这些修改转化为下一批草案的默认建议。

Stage 21 的目标不是让 AI 自动替用户做最终决定，而是把用户明确保存的偏好和修正记录用于生成更接近最终结果的草案。用户仍然需要审核候选合集，并显式接受卡片。

## 3. 目标

1. 支持用户显式保存非敏感的字幕组、筛选和文件夹命名偏好。
2. 在批量草案生成时应用这些偏好，减少逐卡修改次数。
3. 展示偏好命中的来源和低置信度/多候选提醒，保持可审核性。
4. 记录用户对官方标题、季数、候选合集和规则的明确修正，用于搜索词增强。
5. 在 AI provider 不可用、偏好为空或搜索增强失败时保持 Stage 19 的手动候选和直连 fallback 能力。
6. 保持所有偏好和修正记录不包含外部服务 secret、原始 HTML/RSS 或完整敏感 URL。

## 4. 非目标

1. 不实现 AI 自动接受、自动选择最终 MiKan 合集或自动提交 Auto Bangumi。
2. 不在本阶段强制接入真实 LLM provider；真实 provider 的供应商选择、密钥管理和成本控制另行评估。
3. 不实现用户观看行为、下载行为或隐式行为追踪。
4. 不实现复杂账号、多人 profile、权限系统或云端同步。
5. 不创建 qBittorrent 下载任务，不绕过 Auto Bangumi，不引入后台 worker。
6. 不保存 endpoint、token、cookie、Authorization header、magnet、raw HTML、raw RSS XML、原始 HTTP 响应或本地绝对路径。

## 5. 产品决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D21-01 | 偏好必须显式保存 | 系统只能使用用户在 Settings 或偏好面板中主动保存的配置，不根据一次偶然修改静默改变长期偏好。 |
| D21-02 | 偏好只生成默认值 | 偏好可以预填字幕组、筛选和命名规则，但用户仍可逐卡修改并审核。 |
| D21-03 | AI 只生成候选 | 解析和搜索词增强可以提供多个候选与置信度，不能自动选择最终合集或接受卡片。 |
| D21-04 | 修正记录最小化 | 只记录用户明确提交的非敏感修正字段，不记录观看、下载或完整外部响应。 |
| D21-05 | 无偏好时保持旧流程 | 偏好为空或增强失败时，Stage 19 的 fake provider、手动候选选择和直连 URL/ID fallback 仍然可用。 |

## 6. 用户流程

```text
用户打开 Settings 或批量工作台的偏好面板
  ↓
显式保存字幕组、筛选和文件夹命名偏好
  ↓
用户输入一批简称
  ↓
系统解析标题并应用偏好生成草案默认配置
  ↓
系统展示偏好命中、低置信度、多候选和搜索词来源
  ↓
用户修改某张卡片的标题、合集、字幕组或筛选规则
  ↓
用户显式提交修正，系统保存非敏感修正记录
  ↓
下一批输入复用修正记录增强 search_queries
  ↓
用户仍需审核、接受并按 Stage 20 流程提交 Auto Bangumi
```

## 7. 偏好数据契约

偏好只允许保存以下非敏感字段，建议使用版本化 JSON：

```json
{
  "version": 1,
  "subtitle_groups": {
    "preferred": ["Loli", "喵萌"],
    "excluded": ["示例组"],
    "fallback": "next_preferred"
  },
  "filter_defaults": {
    "must_contain": "1080p",
    "must_not_contain": "合集版",
    "use_regex": false,
    "case_sensitive": false
  },
  "naming": {
    "strategy": "official_title_season",
    "template": "{title}"
  },
  "search": {
    "reuse_explicit_corrections": true
  }
}
```

修正记录只保存必要的结构化字段，例如 `raw_title`、用户确认的 `canonical_title`、`season_hint`、公开 `bangumi_id`、公开标题和搜索词，不保存完整 MiKan 页面、RSS URL、响应体或外部配置。

## 8. 推荐与应用规则

1. 字幕组推荐顺序为：用户排除列表过滤 -> 用户偏好列表优先 -> 现有 M05 推荐逻辑 fallback。
2. 偏好筛选规则只作为默认 `filter_rule`；用户可以清空或覆盖它，且使用现有 M06 字面匹配、正则和大小写语义。
3. 命名策略只生成 `expected_folder_name` 默认值，用户仍可修改。
4. 低置信度、多候选、搜索无结果或偏好冲突时，必须设置可审核提醒，不得静默标记为 READY 或 ACCEPTED。
5. 搜索词增强只追加或调整公开搜索词，并保留原始 search query 与增强来源，方便用户理解和修改。
6. 偏好应用失败时，当前 item 单独回退到 Stage 19 行为，不阻塞同批次其他 item。

## 9. Ralph 执行说明

实现必须按 `scripts/ralph/prd.json` 的优先级逐个完成 user story。每个 story 必须能在一次 Ralph 迭代内完成，验收条件必须可检查，并以 `Typecheck passes` 收尾；涉及 Web UI 的 story 还必须执行项目 Playwright 浏览器测试，并遵循 `.agents/skills/dev-browser/SKILL.md` 的验证要求。

Stage 21 完成标志：用户可以显式保存非敏感偏好；下一次批量输入会应用字幕组、筛选和命名默认值，展示低置信度与偏好来源；用户修正能形成安全的搜索词增强记录；无偏好或增强失败时旧的手动审核流程仍然可用。

## 11. 完成状态（2026-08-20）

Stage 21 的全部 8 个 user story（US-150..US-157）已完成并通过：

| Story | 内容 | 状态 |
| --- | --- | --- |
| US-150 | 新增非敏感用户偏好数据契约与存储 | 完成 |
| US-151 | 新增用户偏好 Web API | 完成 |
| US-152 | 新增偏好管理 Web UI | 完成 |
| US-153 | 将用户偏好应用到批量草案生成 | 完成 |
| US-154 | 增加偏好命中与低置信度审核元数据 | 完成 |
| US-155 | 记录用户修正并增强搜索词 | 完成 |
| US-156 | 在批量工作台展示偏好与修正结果 | 完成 |
| US-157 | Stage 21 文档与安全回归收尾 | 完成 |

### 实现要点

1. **偏好契约与存储边界**：`VersionedUserPreference`（`src/shared/models.py`）只允许非敏感的字幕组、筛选、命名和搜索修正字段；`preference_repository.py` 以固定文件名 `<storage>/preferences/user_preferences.json` 原子写入，`build_preferences_from_api` 拒绝未知键和敏感值，`load_user_preferences` 在读取时剥离未知键，因此手工编辑或旧版本文件中夹带的 endpoint/token/cookie 等敏感键永远不会进入应用或 API 响应。
2. **偏好 Web API 与 Web UI**：`GET/POST /api/v1/preferences` 读取/保存规范化非敏感偏好；`/settings` 新增 `#preference-settings-panel` 偏好面板，支持保存、恢复默认（`POST {preferences:{}}`），恢复默认只写偏好文件，不触碰 Stage 20 队列、Request 或 AB result 存储。偏好表单是纯非敏感表面，被拒绝的敏感输入会回退到上次有效值，不会残留或回显。
3. **偏好应用到批量草案**：`POST /api/v1/batches/parse` 每个 item 返回 `applied_preferences`（字幕组/筛选/命名字段默认配置）、`preference_hits`（偏好命中规则摘要）和 `preference_warnings`（偏好冲突/回退警告）。偏好读取或应用失败时当前 item 单独回退 Stage 19 默认流程，不阻塞同批次其他 item；字幕组偏好只作为单卡可编辑默认值，真实种子校验的 M05 `select_subtitle_group` 排除列表在应用时生效。
4. **低置信度审核元数据**：`build_review_metadata` 为低置信度、多候选、无候选、搜索回退、搜索失败、解析失败和偏好冲突 item 设置 `needs_user_review=true` 并生成中文 `review_hints`。审核元数据只注释卡片，绝不自动选择候选合集、绝不自动接受卡片。
5. **用户修正与搜索词增强**：`correction_repository.py` 保存非敏感 `TitleCorrection`（`raw_title`、公开 `canonical_title`、`season_hint`、公开 bangumi 元数据和 `query_correction`），采用同 raw_title 最新版本策略 + 全局 `MAX_STORED_CORRECTIONS=500` 上限；`search_enhancer.py` 纯函数把修正展开为可审核的 `{query, original_query, source}` 增强搜索词（`correction:query`/`correction:canonical`），保留原始 query 与来源标记。增强失败或修正为空时回退原 `search_queries`。
6. **批量工作台展示**：批量卡片展示偏好命中摘要、低置信度/多候选/冲突审核提示、当前默认配置和搜索词来源；单卡修改只更新当前卡片，其他卡片偏好/审核文本保持不变；所有渲染只读公开非敏感字段。
7. **安全回归**：单元测试、Web API 测试和端到端浏览器回归断言 endpoint、token、cookie、Authorization header、raw HTML、raw RSS XML、magnet、完整失败 URL、原始响应体和本地绝对路径不出现在偏好 JSON、API 响应、页面、URL、浏览器 storage、日志或 trace 中。

### 边界确认

- 偏好只保存非敏感字段：字幕组、筛选、命名和搜索修正开关；**不保存** endpoint、token、cookie、Authorization header、magnet、raw HTML、raw RSS XML、原始响应体或本地绝对路径。
- AI 只生成候选标题、搜索词和置信度，**不自动选择最终 MiKan 合集**；即使只有一个候选，也必须由用户显式点击选择。
- 用户仍需逐卡审核并显式接受；偏好命中、低置信度和审核提示**不会**改变候选合集，也**不会**自动把卡片标记为已接受。
- 无偏好、偏好读取失败或搜索增强失败时，回退到 Stage 19 默认流程：fake provider、手动候选选择和直连 URL/ID fallback 仍然可用。
- 批量提交继续复用 Stage 20 的前台顺序编排，不创建 qBittorrent 下载任务，不绕过 Auto Bangumi，不引入后台常驻 worker。

## 12. Stage 22 handoff

Stage 21 的偏好与修正闭环已经完成；后续人工验收发现，Stage 18/19 的单个与批量搜索虽然共用真实 MiKan candidate search，但界面、候选状态和草案生成语义仍未真正收敛。下一阶段调整为 Stage 22「Web UI 搜索工作台重构与真实候选闭环」（见 `docs/MiGuOrca_stage22_web_search_workbench_PRD.md`）：

1. 以“单个搜索 / 批量搜索”管理输入模式，并将结果移入独立结果面板。
2. 明确区分标题 `PARSED`、候选 FOUND/EMPTY/FAILED 和 DRAFT/READY 草案。
3. 无真实 MiKan 候选时不得根据输入或解析标题生成可接受的空壳草案。
4. 单个/批量入口复用候选展示、显式选择和 `mikan_bangumi` 详情到 preview 的链路。
5. 补齐真实生产状态形状、候选封面/占位和搜索反馈的浏览器回归。

Stage 21 的安全边界继续适用：偏好与修正只保存非敏感字段，外部 endpoint/token 只存在于请求上下文。原部署/配置向导顺延为 Stage 23 远期可选能力。
