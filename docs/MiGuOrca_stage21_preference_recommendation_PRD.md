# MiGuOrca Stage 21 PRD: 用户偏好与智能推荐闭环

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | Stage 21 PRD: 用户偏好与智能推荐闭环 |
| 文档类型 | Stage PRD |
| 当前状态 | Planned |
| 创建日期 | 2026-08-19 |
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

