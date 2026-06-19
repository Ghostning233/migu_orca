# MiGuOrca 主 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | MiGuOrca 主 PRD |
| 文档类型 | 主 PRD |
| 当前版本 | v0.2 |
| 文档状态 | 优化中 |
| 适用阶段 | 需求讨论、模块拆分、开发规划 |
| 相关系统 | MiKanProject、Auto Bangumi、qBittorrent |
| 简称约定 | Auto Bangumi 简称为 AB |

### 1.1 项目命名规范

本项目正式名称确定为 MiGuOrca。

MiGu 来源于 Mikan + Bangumi。ORCA 表示 Orchestrated RSS Coordination for Anime，即面向动画 RSS 的自动编排与协调系统。

统一命名如下：

| 类型 | 名称 |
| --- | --- |
| 正式项目名 | MiGuOrca |
| 仓库名 | migu_orca |
| Python 包名 | migu_orca |
| CLI 命令 | migu-orca |
| 配置目录 | ~/.config/migu_orca |
| 环境变量前缀 | MIGU_ORCA_ |
| 日志名 | migu_orca |

### 1.2 开发与工具约定

本项目使用 `UV` 进行 Python 包管理和命令执行。

统一约定如下：

1. 安装依赖使用 `uv sync`。
2. 运行测试使用 `uv run pytest`。
3. 运行项目入口或脚本时优先使用 `uv run <command>`。
4. 不要直接使用 `python` 运行测试或脚本，避免绕过项目统一环境。

该约定适用于后续的开发、测试、验收和自动化执行流程。

### 1.3 术语说明

本 PRD 中的关键术语约定如下：

| 术语 | 含义 |
| --- | --- |
| Request | 系统根据用户输入、规则和数据源生成的番剧订阅确认对象 |
| 有效种子 | 按筛选规则去除重复种子、无效种子和不符合规则种子后，最终保留下来的种子 |
| 第一阶段 | 项目最小可用阶段，目标是输入单个番剧名后生成 Request |
| 一期 | 与第一阶段同义，本文档中优先使用“第一阶段” |

## 2. 项目背景

用户有观看、收藏番剧的需求，目前主要通过 MiKanProject 获取番剧 RSS，并使用 Auto Bangumi 配合 qBittorrent 实现自动下载。

现有成熟工作流大致为：

1. 用户通过番剧推荐视频、季度新番导视等渠道确定想看的新番。
2. 用户手动在 MiKanProject 中搜索番剧。
3. 用户在多个字幕组提供的 RSS 中选择一个符合偏好的 RSS。
4. 用户将 RSS 配置到 Auto Bangumi 中。
5. 用户手动填写订阅名称、目录名称、季度编号、筛选规则等信息。
6. Auto Bangumi 根据 RSS 与用户规则将符合条件的种子添加到下载任务中。
现有流程虽然可用，但每个季度都需要重复执行大量人工操作。每季度用户可能至少需要整理 6 部以上新番，手动搜索、判断字幕组、配置 RSS、命名目录会耗费较多时间，导致整理成本较高。

因此，需要构建一个位于 MiKanProject 与 Auto Bangumi 之间的自动化编排系统，用于自动完成番剧搜索、RSS 分析、字幕组评估、种子筛选、目录命名和 AB 调用前的确认流程。

## 3. 项目目标

本项目目标是实现 MiGuOrca，即一个“新番自动订阅编排系统”。

用户只需要输入自己想看的番剧名称，系统根据预设规则、用户偏好和搜索结果，自动生成一条可确认的订阅 Request。

Request 中需要包含：

1. 系统搜索到的源信息。
2. 系统推荐的可确认配置。
3. 用户可执行的接受、修改、取消操作。
用户确认后，系统调用 Auto Bangumi 完成番剧自动下载配置。

### 3.1 MVP 定义

MVP 是 Minimum Viable Product，即“最小可用产品”。

对本项目而言，MVP 不是完整闭环，而是能够验证核心价值的最小功能集合。

MiGuOrca 的第一阶段 MVP 目标如下：

1. 用户输入单个番剧名。
2. 系统完成番剧搜索、RSS 获取、RSS 解析、种子筛选和文件夹命名。
3. 系统生成一条结构完整、可确认的 Request。
4. 系统输出 Request 的结果可被人工查看，或以命令行、文件、JSON 等形式导出。

第一阶段不要求：

1. 对接 Auto Bangumi。
2. 执行订阅提交。
3. 提供完整 Web UI。
4. 实现复杂的用户交互和长期状态管理。

### 3.2 第一阶段验收标准

第一阶段是否完成，以“能否稳定生成 Request”为准。

建议验收标准如下：

1. 输入一个单番剧名后，系统能输出一条 Request。
2. Request 至少包含匹配到的番剧信息、候选 RSS 信息、有效种子信息、推荐字幕组和预期文件夹名。
3. Request 的状态能够明确表示为“已生成、待确认”或等价状态。
4. 第一阶段可以使用静态 RSS 数据源模拟 MiKanProject 数据，不要求真实爬虫。
5. 第一阶段不依赖 Auto Bangumi 或 qBittorrent 在线可用。

## 4. 项目边界

### 4.1 本项目负责的事情

本项目负责：

1. 通过入口与流程编排模块接收用户输入的单个番剧名称。
2. 搜索并匹配 MiKanProject 中的番剧资源。
3. 获取候选字幕组 RSS。
4. 解析 RSS 中的种子信息。
5. 根据默认种子筛选规则计算有效种子。
6. 根据用户偏好推荐字幕组。
7. 根据命名规则生成预期文件夹名。
8. 生成一条待用户确认的 Request。
9. 支持用户接受、修改、取消 Request。
10. 记录 Request 状态、用户修改历史和关键日志。

说明：

1. 第一阶段只做到 Request 生成，不包含 Auto Bangumi 提交。
2. 第一阶段如果需要数据源，可以使用静态 RSS 列表模拟 MiKanProject 返回结果。
3. 第一阶段可以先不实现持久化和复杂交互，优先把核心链路跑通。

### 4.2 本项目暂不负责的事情

第一阶段暂不负责：

1. 自动从推荐视频中提取用户想看的番剧。
2. 自动判断用户是否真的喜欢某部番剧。
3. 完整的本地媒体库刮削与整理。
4. 视频文件重命名。
5. 播放器集成。
6. 跨平台客户端。
7. 完整字幕组质量评分体系。
8. 复杂 AI 推荐系统。
9. 批量季度清单输入。
10. Auto Bangumi 订阅提交。
11. Web UI。
上述能力可作为后续扩展模块处理。

## 5. 用户场景

### 5.1 核心用户场景

用户看到某部季度新番后，只需要向系统输入：

咒术回战第三季

系统自动执行：

1. 入口与流程编排模块接收输入并启动单番剧订阅流程。
2. 搜索 MiKanProject。
3. 匹配最相似的番剧条目。
4. 获取该番剧下多个字幕组 RSS。
5. 解析每个 RSS 中的种子。
6. 使用默认筛选规则计算有效种子数。
7. 推荐一个字幕组。
8. 生成有效种子名列表。
9. 生成预期文件夹名。
10. 返回一条待确认 Request。
用户看到 Request 后，可以选择：

1. 接受。
2. 修改。
3. 取消。

如果用户发现系统匹配到了错误番剧，则取消当前 Request，并重新输入更准确的番剧名称。

## 6. 核心概念

### 6.1 Request

Request 是本系统的核心业务对象。

一条 Request 表示：

系统根据用户输入、搜索结果、规则和偏好生成的一份“番剧订阅确认单”。

Request 不是一次性展示结果，而是需要有状态、有生命周期、可被修改、可被确认、可被取消的业务对象。

### 6.2 源信息 source_info

源信息是系统搜索、解析、分析后得到的客观信息。

源信息包括：

1. 匹配到的 MiKan 番剧信息。
2. 候选字幕组。
3. 每个字幕组 RSS 地址。
4. 每个 RSS 下的种子总数。
5. 默认筛选规则下的有效种子数。
6. 被排除的种子及排除原因。
7. 有效种子名列表。

### 6.3 有效种子

有效种子是指，在应用用户设定的筛选规则后，去除了重复种子、不符合规则种子、无法被选中的种子之后，最终保留下来的种子。

举例：

1. 同一集里存在正常版本和 v2 版本。
2. 用户规则设定为优先使用不带 `v` 的版本。
3. 系统筛选后，正常版本会被保留并视为有效种子。
4. 被规则排除的 v2 版本不属于有效种子。

### 6.4 待确认配置 confirmable_config

待确认配置是用户可以确认或修改的部分。

包括：

1. 当前选择的字幕组。
2. 当前种子筛选规则。
3. 当前规则下计算出的有效种子名列表。
4. 预期文件夹名。
5. Auto Bangumi 所需的相关配置字段。
其中，有效种子名列表不允许用户直接修改，只能通过修改字幕组或种子筛选规则间接改变。

## 7. Request 信息结构

整体结构暂定如下：

```json
{
  "request_id": "req_20260615_0001",
  "status": "PENDING_CONFIRM",
  "input": {
    "raw_title": "咒术回战第三季",
    "season_hint": null,
    "subtitle_group_hint": null,
    "folder_name_hint": null
  },
  "source_info": {
    "matched_bangumi": {
      "title": "咒术回战 第三季",
      "mikan_url": "待填充",
      "match_score": 0.91,
      "aliases": ["咒术回战", "咒回", "Jujutsu Kaisen"]
    },
    "rss_sources": [
      {
        "subtitle_group": "拨雪",
        "rss_url": "待填充",
        "total_seed_count": 12,
        "valid_seed_count": 8,
        "invalid_seed_count": 4,
        "valid_seed_names": [
          "[拨雪] 咒术回战 第三季 - 01 [1080p][CHS].mkv",
          "[拨雪] 咒术回战 第三季 - 02 [1080p][CHS].mkv"
        ],
        "excluded_seed_names": [
          {
            "name": "[拨雪] 咒术回战 第三季 - 01 [720p].mkv",
            "reason": "分辨率不符合默认规则"
          }
        ]
      }
    ]
  },
  "confirmable_config": {
    "selected_subtitle_group": "拨雪",
    "selected_rss_url": "待填充",
    "filter_rule": {
      "resolution": "1080p",
      "subtitle_language": "CHS",
      "exclude_keywords": ["合集", "总集篇", "NCOP", "NCED", "PV", "SP", "先行"],
      "include_keywords": [],
      "episode_strategy": "normal_episode"
    },
    "effective_seed_names": [
      "[拨雪] 咒术回战 第三季 - 01 [1080p][CHS].mkv",
      "[拨雪] 咒术回战 第三季 - 02 [1080p][CHS].mkv"
    ],
    "expected_folder_name": "[26Win-咒回S3P1-拨雪 (26)]"
  },
  "ab_submit_result": null,
  "created_at": "2026-06-15T00:00:00",
  "updated_at": "2026-06-15T00:00:00"
}
```

## 8. Request 状态流转

Request 状态暂定如下：

```text
CREATED
  ↓
SEARCHING
  ↓
PENDING_CONFIRM
  ├── ACCEPTED
  │     ↓
  │   AB_SUBMITTING
  │     ↓
  │   AB_SUBMITTED
  │
  ├── MODIFIED
  │     ↓
  │   PENDING_CONFIRM
  │
  ├── CANCELLED
  │
  └── EXPIRED
```

### 8.1 状态说明

| 状态 | 含义 |
| --- | --- |
| CREATED | Request 已创建，但尚未开始搜索 |
| SEARCHING | 系统正在搜索 MiKan、解析 RSS、计算结果 |
| PENDING_CONFIRM | Request 已生成，等待用户确认 |
| MODIFIED | 用户修改了可修改字段，系统需要重新生成 Request |
| ACCEPTED | 用户已接受 Request |
| AB_SUBMITTING | 系统正在调用 AB |
| AB_SUBMITTED | AB 调用成功，订阅已创建 |
| CANCELLED | 用户取消 Request |
| EXPIRED | Request 过期，需要重新生成 |

### 8.2 后续阶段的接受前校验

该节仅面向后续阶段，不属于第一阶段 MVP 范围。

用户点击接受时，系统需要重新校验 RSS 信息。

原因：

1. RSS 内容可能发生变化。
2. 有效种子列表可能增加或减少。
3. 字幕组可能更新了修正版。
4. 用户看到的 Request 可能已经不是最新状态。
后续阶段再定义：

1. 是否需要重新拉取 RSS。
2. 如何判断种子列表变化。
3. 如何决定继续提交 AB 或重新生成 Request。

## 9. 用户操作定义（后续阶段）

本节用于后续阶段的交互闭环定义，不属于第一阶段 MVP 范围。

### 9.1 接受

用户接受当前 Request。

系统行为：

1. 将 Request 状态更新为 ACCEPTED。
2. 执行接受前校验。
3. 校验通过后调用 Auto Bangumi。
4. 调用成功后更新为 AB_SUBMITTED。
5. 调用失败后记录失败原因。

### 9.2 修改

用户修改当前 Request 的可修改信息。

可修改字段包括：

1. 选择的字幕组。
2. 种子筛选规则。
3. 预期文件夹名。
4. 部分 AB 所需配置项。
不可直接修改字段包括：

1. 有效种子名列表。
2. RSS 中原始种子信息。
3. MiKan 原始搜索结果。
系统行为：

1. 接收用户提交的修改补丁。
2. 应用修改补丁。
3. 重新计算有效种子列表。
4. 重新生成 Request。
5. 返回新的待确认 Request。

### 9.3 取消

用户取消当前 Request。

常见原因：

1. 用户输入的番剧名未正确匹配。
2. 系统匹配到了错误番剧。
3. 匹配到了番剧，但没有合适字幕组。
4. RSS 中没有有效种子。
5. 用户暂时不想订阅该番剧。
系统行为：

1. 将 Request 状态更新为 CANCELLED。
2. 记录取消原因。
3. 不调用 AB。

## 10. 模块划分

本项目按模块拆分，每个子模块需要单独编写模块 PRD。

### 10.1 整体模块列表

| 模块编号 | 模块名称 | 说明 | 模块 PRD |
| --- | --- | --- | --- |
| M00 | 入口与流程编排模块 | 作为当前第一阶段入口，调用其他模块完成单番剧 Request 生成编排 | docs/modules/M00-entry-orchestration-PRD.md |
| M01 | 用户输入与 Request 管理模块 | 接收用户输入，创建和管理 Request 生命周期 | docs/modules/M01-request-management-PRD.md |
| M02 | 番剧搜索与匹配模块 | 根据用户输入匹配 MiKan 中的番剧条目 | docs/modules/M02-bangumi-search-match-PRD.md |
| M03 | MiKan 数据源模块 | 第一阶段使用静态 RSS 列表模拟 MiKanProject 数据，后续再对接真实访问 | docs/modules/M03-mikan-source-PRD.md |
| M04 | RSS 解析模块 | 解析 RSS，提取种子名称、发布时间、链接等信息 | docs/modules/M04-rss-parser-PRD.md |
| M05 | 字幕组评估模块 | 根据用户偏好和 RSS 质量推荐字幕组 | docs/modules/M05-subtitle-group-evaluation-PRD.md |
| M06 | 种子筛选规则模块 | 根据规则筛选有效种子，并输出排除原因 | docs/modules/M06-torrent-filter-rule-PRD.md |
| M07 | 文件夹命名模块 | 根据季度、番名简称、季数、字幕组生成预期文件夹名 | docs/modules/M07-folder-naming-PRD.md |
| M08 | 用户偏好与规则配置模块 | 管理字幕组偏好、命名偏好、筛选默认规则 | docs/modules/M08-user-preference-rule-PRD.md |
| M09 | Request 确认交互模块 | 向用户展示 Request，并支持接受、修改、取消；不负责完整 Web UI | 暂缓 |
| M10 | Auto Bangumi 集成模块 | 调用 AB 创建订阅任务；调用失败时输出降级配置 | 暂缓 |
| M11 | 存储与状态管理模块 | 持久化 Request、配置、历史记录和调用结果 | 暂缓 |
| M12 | 日志与错误处理模块 | 独立记录系统行为、异常原因、排错信息和失败结果 | docs/modules/M12-log-error-PRD.md |
| M13 | Web UI / 管理界面模块 | 后续扩展模块，第一阶段不实现 | 暂缓 |
| M14 | 系统配置模块 | 管理静态数据路径、日志配置和运行环境配置 | docs/modules/M14-system-config-PRD.md |

## 11. 子模块 PRD 编写计划

后续需要为每个模块补充独立 PRD。

建议文件结构如下：

```text
docs/
  prd/
    00-overall-prd.md
    modules/
      M00-entry-orchestration-prd.md
      M01-request-management-prd.md
      M02-bangumi-search-match-prd.md
      M03-mikan-source-prd.md
      M04-rss-parser-prd.md
      M05-subtitle-group-evaluation-prd.md
      M06-torrent-filter-rule-prd.md
      M07-folder-naming-prd.md
      M08-user-preference-rule-prd.md
      M09-request-confirmation-prd.md
      M10-auto-bangumi-integration-prd.md
      M11-storage-state-prd.md
      M12-log-error-prd.md
      M13-web-ui-prd.md
      M14-system-config-prd.md
```

模块 PRD 需要至少包含：

1. 模块目标。
2. 模块边界。
3. 输入数据。
4. 输出数据。
5. 核心流程。
6. 规则定义。
7. 异常场景。
8. 数据结构。
9. 接口定义。
10. 验收标准。
11. 待确认问题。

## 12. 模块级开发进度管理

### 12.1 状态定义

| 状态 | 说明 |
| --- | --- |
| 未开始 | 尚未开始设计或开发 |
| PRD 编写中 | 正在编写模块 PRD |
| PRD 已完成 | 模块 PRD 已完成，可进入设计 |
| 设计中 | 正在进行技术方案设计 |
| 待开发 | 技术方案完成，等待开发 |
| 开发中 | 正在开发 |
| 待测试 | 开发完成，等待测试 |
| 测试中 | 正在测试 |
| 已完成 | 模块已完成并通过验收 |
| 暂缓 | 当前阶段不实现 |

### 12.2 当前进度表

| 模块编号 | 模块名称 | 当前状态 | 优先级 | 备注 |
| --- | --- | --- | --- | --- |
| M00 | 入口与流程编排模块 | PRD 编写中 | P0 | 模块 PRD 初稿已存在，需关闭入口形态和输出形式问题 |
| M01 | 用户输入与 Request 管理模块 | PRD 编写中 | P0 | 模块 PRD 初稿已存在，需确认状态集合和一致性校验 |
| M02 | 番剧搜索与匹配模块 | PRD 编写中 | P0 | 模块 PRD 初稿已存在，需确认匹配算法、阈值和同分策略 |
| M03 | MiKan 数据源模块 | PRD 编写中 | P0 | 模块 PRD 初稿已存在，第一阶段限定为静态数据源 |
| M04 | RSS 解析模块 | PRD 编写中 | P0 | 模块 PRD 初稿已存在，需确认静态 RSS 组织方式和缺字段策略 |
| M05 | 字幕组评估模块 | PRD 编写中 | P1 | 模块 PRD 初稿已存在，第一阶段可按有效种子数优先 |
| M06 | 种子筛选规则模块 | PRD 编写中 | P0 | 模块 PRD 初稿已存在，需确认默认规则和 v2/v3 策略 |
| M07 | 文件夹命名模块 | PRD 编写中 | P1 | 模块 PRD 初稿已存在，需确认命名模板、简称和季度编号来源 |
| M08 | 用户偏好与规则配置模块 | PRD 编写中 | P1 | 模块 PRD 初稿已存在，第一阶段可使用内置默认配置 |
| M09 | Request 确认交互模块 | 暂缓 | P2 | 第一阶段不做完整确认交互 |
| M10 | Auto Bangumi 集成模块 | 暂缓 | P2 | 第一阶段不对接 AB |
| M11 | 存储与状态管理模块 | 暂缓 | P2 | 第一阶段先聚焦 Request 生成 |
| M12 | 日志与错误处理模块 | PRD 编写中 | P0 | 模块 PRD 初稿已存在，需确认日志格式和错误码注册方式 |
| M13 | Web UI / 管理界面模块 | 暂缓 | P2 | 后续可能实现，第一阶段不考虑 |
| M14 | 系统配置模块 | PRD 编写中 | P1 | 模块 PRD 初稿已存在，第一阶段只保留静态数据和日志相关配置 |

### 12.3 推荐开发顺序

第一阶段建议按以下顺序开发：

```text
M08 默认规则配置
  ↓
M03 MiKan 静态数据源
  ↓
M04 RSS 解析
  ↓
M06 种子筛选规则
  ↓
M02 番剧搜索与匹配
  ↓
M05 字幕组评估
  ↓
M07 文件夹命名
  ↓
M01 Request 管理
  ↓
M00 入口与流程编排
  ↓
M12 日志与错误处理
```

说明：

1. 第一阶段以可测试的底层规则和静态数据为先，避免入口编排过早绑定未稳定接口。
2. 第一阶段先用静态 RSS 数据模拟 MiKanProject，先验证完整 Request 生成链路。
3. Request 管理是系统核心对象，但应在上游模块输出结构基本稳定后实现。
4. 入口与流程编排模块最后串联各模块，并提供 CLI 或库函数包装。
5. 日志用于排错，第一阶段保留最小实现即可。
6. 确认交互、持久化和 AB 对接全部后置，第一阶段不纳入范围。

## 13. 整体架构设计

### 13.1 架构目标

系统整体架构需要满足：

1. 模块边界清晰。
2. 规则可配置。
3. 外部系统可替换。
4. Request 状态可追踪。
5. 搜索、解析、筛选、确认、提交流程可拆分。
6. 后续可以从当前入口与流程编排模块平滑扩展到 Web UI。
7. 后续可以扩展更多数据源，不强绑定 MiKan。
8. 后续可以替换 AB 集成方式，不强绑定某一种调用方式。

### 13.2 初步分层

系统暂定采用以下分层：

```text
用户交互层
  ↓
应用服务层
  ↓
领域逻辑层
  ↓
基础设施适配层
  ↓
外部系统
```

### 13.3 各层职责

#### 13.3.1 用户交互层

负责：

1. 作为入口与流程编排模块的外部触发入口。
2. 接收单个番剧名称输入。
3. 展示 Request。
4. 提供接受、修改、取消操作。
5. 展示错误信息和操作结果。
初期形态：

1. 入口与流程编排模块。
后续形态：

1. 完整 Web UI。
2. 移动端适配页面。
3. Bot 交互。

#### 13.3.2 应用服务层

负责组织业务流程。

典型流程：

1. 入口模块启动单番剧订阅流程。
2. 创建 Request。
3. 调用番剧搜索模块。
4. 调用 MiKan 数据源模块。
5. 调用 RSS 解析模块。
6. 调用种子筛选模块。
7. 调用字幕组评估模块。
8. 调用命名模块。
9. 生成待确认 Request。
10. 处理用户接受、修改、取消。
11. 调用 AB 集成模块。
12. AB 调用失败时触发降级配置生成。
应用服务层不直接实现具体规则，只负责流程编排。

#### 13.3.3 领域逻辑层

负责核心业务规则。

包括：

1. Request 状态流转规则。
2. 番剧匹配规则。
3. 字幕组推荐规则。
4. 种子筛选规则。
5. 文件夹命名规则。
6. 用户偏好合并规则。
7. 接受前校验规则。
领域逻辑层应尽量不依赖具体外部系统。

#### 13.3.4 基础设施适配层

负责对接外部系统和底层能力。

包括：

1. MiKanProject 访问适配器。
2. RSS 拉取适配器。
3. Auto Bangumi 调用适配器。
4. 配置文件读写。
5. 数据库存储。
6. 日志系统。
7. 缓存系统。

#### 13.3.5 外部系统

包括：

1. MiKanProject。
2. Auto Bangumi。
3. qBittorrent。
4. 本地文件系统。
5. 后续可能扩展的其他番剧数据源。

## 14. 初版目录结构规划

本项目目录结构参考 auto_miio_ctrl 的 Python 项目组织方式，但需要结合 MiGuOrca 的模块化编排特点进行调整。

目录规划原则：

1. 根目录保留项目入口、依赖配置、运行配置、文档、脚本、工具。
2. 业务代码统一放在 src/ 下。
3. 各 engine 直接放在 src/ 下，每个 engine 遵循 MVC 风格组织。
4. src/apps/ 存放统一 API 管理层，按 engine 模块拆分 services 和 clients。
5. Controller 是 engine 的业务能力入口，入口编排模块通过调用各 engine 的 Controller 串联业务能力。
6. Services 是 Controller 业务能力的 API 封装，主要供内部 API 层复用。
7. Clients 是带用户认证或权限边界的 API 接口，用户侧能力调用应通过 clients 暴露。
8. services 和 clients 主要为后续 Web UI 或 API 化预留，第一阶段只需在框架中定义清楚。
9. 测试文件与被测逻辑文件放在同一目录下，测试文件名以 _test 结尾。
10. 项目整体采用 TDD 方式开发，新增或修改业务逻辑前应先补充对应测试。
11. 目录结构只表达项目架构，不在主 PRD 中列举所有具体代码文件。
12. tools/ 只表示外部服务调试脚本目录，不在主 PRD 中绑定具体脚本文件名。

当前只是目录规划，不代表立即创建全部目录。

```text
migu_orca/
  README.md
  pyproject.toml
  uv.lock
  main.py
  .python-version

  docs/
    modules/
    design/
    api/
    test_manual/

  config/
    user/
    rules/
    system/

  logs/

  script/

  tools/

  src/
    request_engine/
      models/
      controllers/

    mikan_engine/
      models/
      controllers/

    rss_engine/
      models/
      controllers/

    torrent_filter_engine/
      models/
      controllers/

    auto_bangumi_engine/
      models/
      controllers/

    apps/
      migu_orca_entry/
        controllers/

      request_engine/
        services/
        clients/

      mikan_engine/
        services/
        clients/

      rss_engine/
        services/
        clients/

      auto_bangumi_engine/
        services/
        clients/

  bin/
```

### 14.1 根目录说明

| 路径 | 说明 |
| --- | --- |
| README.md | 项目说明、快速开始、开发说明 |
| pyproject.toml | Python 项目元信息、依赖、命令入口 |
| uv.lock | 依赖锁定文件 |
| main.py | 本地开发入口，负责启动入口编排模块 |
| .python-version | Python 版本声明 |
| docs/ | PRD、设计文档、接口文档、测试手册 |
| config/ | 用户配置、规则配置、系统配置 |
| logs/ | 日志文件目录 |
| script/ | 同步、部署、环境辅助脚本 |
| tools/ | 外部服务调试脚本目录 |
| src/ | 项目源码 |
| bin/ | Windows 或其他平台辅助启动脚本 |

### 14.2 src 分层说明

src/ 下分为 engine 模块和 apps 两类目录。

| 路径 | 职责 |
| --- | --- |
| src/*_engine/ | 核心业务能力实现层，按业务 engine 拆分 |
| src/apps/ | 统一 API 管理层，按 engine 模块封装 services 和 clients |
| src/apps/migu_orca_entry/ | 入口与流程编排模块，负责串联完整业务流程 |

分层原则：

1. engine 模块直接位于 src/ 下，负责实现业务能力。
2. apps 负责把业务能力封装成可调用 API。
3. 入口编排模块可以直接调用 engine Controller 完成第一阶段流程。
4. 后续做 Web UI 或 API 服务时，由 apps 层统一对外提供 services 和 clients。
5. 业务规则不应写在 apps 层，apps 层只做参数传递、调用编排、权限边界和返回包装。

### 14.3 engine 内部结构规范

每个 engine 内部遵循 MVC 风格组织。

| 目录 | 职责 |
| --- | --- |
| models/ | 定义该 engine 的数据模型、值对象、状态对象 |
| controllers/ | 定义该 engine 的业务能力入口，供入口编排模块或 apps 层调用 |

Controller 的职责：

1. 作为 engine 的唯一或主要业务能力入口。
2. 屏蔽 engine 内部 models 和具体实现细节。
3. 向入口编排模块提供稳定的业务能力接口。
4. 承担本 engine 内部业务流程组织，但不处理用户认证或用户侧 API 暴露。

入口编排模块职责：

1. 接收单番剧业务流程启动请求。
2. 调用 Request、MiKan、RSS、筛选、命名、确认、AB、存储、日志等 engine 的 Controller。
3. 串联各 engine 能力，形成完整业务流程。
4. 不直接实现各 engine 的内部业务规则。

### 14.4 apps API 层结构规范

apps 层用于统一管理 API 封装能力。

| 目录 | 职责 |
| --- | --- |
| services/ | Controller 业务能力的 API 封装，仅供系统内部使用 |
| clients/ | 带用户认证、权限边界或用户侧调用约束的 API 接口 |

Services 的定义：

1. Services 封装 Controller 的业务能力。
2. Services 负责接收必要参数、调用对应 Controller、整理返回结果。
3. Services 只允许在系统内部使用，不直接作为用户侧调用入口。
4. Services 不承载核心业务规则，核心规则仍归属于 engine。

Clients 的定义：

1. Clients 是带用户认证或权限边界的 API 接口。
2. 用户侧能力调用只能通过 Clients 暴露。
3. Clients 可以调用 Services，但不应直接绕过 Services 操作 engine 内部结构。
4. Clients 主要服务后续 Web UI、API 服务或外部调用场景。

第一阶段处理原则：

1. 当前第一阶段不实现 Web UI。
2. apps 层先定义目录职责和边界。
3. 如当前流程不需要 API 化，可以暂不实现具体 services 和 clients。
4. 等 Web UI 或 API 服务进入范围后，再补充具体接口设计。

### 14.5 engine 与 apps 示例

主 PRD 只展示少量核心 engine 示例，具体文件和内部函数由各模块 PRD 或技术设计文档定义。

```text
src/
  request_engine/
    models/
    controllers/

  mikan_engine/
    models/
    controllers/

  auto_bangumi_engine/
    models/
    controllers/

  apps/
    migu_orca_entry/
      controllers/

    request_engine/
      services/
      clients/

    mikan_engine/
      services/
      clients/

    auto_bangumi_engine/
      services/
      clients/
```

其他 engine 按同样规则扩展，例如：

1. bangumi_match_engine。
2. rss_engine。
3. subtitle_group_engine。
4. torrent_filter_engine。
5. folder_naming_engine。
6. user_config_engine。
7. request_confirm_engine。
8. storage_engine。
9. log_engine。
10. system_config_engine。

M13 Web UI / 管理界面模块暂缓，不在第一阶段创建源码包。

### 14.6 测试文件规范

测试文件不单独集中到 tests/ 目录，而是与被测逻辑文件放在同一目录下。

项目整体采用 TDD 开发方式。

TDD 规则：

1. 新增业务能力前，先编写能够描述预期行为的测试。
2. 修改已有业务规则前，先补充或调整能复现目标行为的测试。
3. 修复缺陷前，先补充能复现缺陷的失败测试。
4. 测试通过后再整理实现代码。

命名规则：

1. 被测逻辑文件与测试文件同目录。
2. 测试文件名在被测逻辑文件名后追加 _test。
3. 每个 engine 自己维护自己的测试文件。

示例：

```text
src/
  request_engine/
    models/
      request_model
      request_model_test
    controllers/
      request_controller
      request_controller_test
```

说明：上方示例只表达命名关系，不代表最终文件后缀或具体文件必须在主 PRD 中固定。

### 14.7 docs 目录说明

| 路径 | 说明 |
| --- | --- |
| docs/MiGuOrca_main_PRD.md | 主 PRD，记录项目级目标、边界、第一阶段范围、模块拆分 |
| docs/modules/ | 各模块 PRD |
| docs/design/ | 技术设计文档 |
| docs/api/ | 外部接口、内部接口、数据结构说明 |
| docs/test_manual/ | 手动测试步骤、真实环境验证记录 |

### 14.8 config 目录说明

| 路径 | 说明 |
| --- | --- |
| config/user/ | 用户偏好配置，例如字幕组偏好、默认分辨率、默认字幕语言 |
| config/rules/ | 筛选规则、命名规则等规则配置 |
| config/system/ | 系统级配置，例如 MiKan 访问配置、AB 地址、路径配置 |

配置文件用于记录用户的部分信息和规则偏好。第一阶段可先使用内置默认配置或 JSON，后续如有需要再迁移到数据库或管理界面。

### 14.9 运行数据目录说明

第一阶段不要求持久化 Request、状态历史或 AB 调用结果。

第一阶段如需保存输出，可由 CLI 将生成的 Request 导出为 JSON 文件；该能力属于输出包装，不等同于 M11 存储与状态管理。

后续在实现 M11 存储与状态管理模块时，再确定 Request、AB 降级配置、缓存等运行数据的具体目录结构。

### 14.10 tools 目录说明

tools/ 用于放置开发阶段调试外部服务的测试脚本。

使用边界：

1. tools/ 可以访问 MiKan、RSS、AB 等外部服务做可行性验证。
2. tools/ 不承载正式业务流程。
3. tools/ 中沉淀出的稳定逻辑，需要按职责迁移到对应 engine 的 controllers，或迁移到 apps 层的 services、clients 中。
4. 主 PRD 不固定 tools/ 下的具体脚本文件名。

### 14.11 与 auto_miio_ctrl 的对应关系

| auto_miio_ctrl 结构 | MiGuOrca 规划 | 说明 |
| --- | --- | --- |
| docs/main.prd | docs/MiGuOrca_main_PRD.md | 主 PRD |
| docs/engines/ | docs/modules/ | 模块 PRD |
| config/ | config/ | MiGuOrca 第一阶段可使用 JSON 配置或内置默认配置 |
| src/*_engine/ | src/*_engine/ | 按业务能力拆分 engine |
| engine/controllers/ | src/*_engine/controllers/ | Controller 作为 engine 业务能力入口 |
| 无明确 apps 层 | src/apps/ | 统一 API 管理层，后续服务 Web UI 或 API 化 |
| tools/ | tools/ | 外部服务调试脚本目录 |
| script/ | script/ | 同步与辅助脚本 |
| main.py | main.py | 本地开发入口 |
| pyproject.toml | pyproject.toml | Python 项目配置 |

## 15. 第一阶段范围

### 15.1 第一阶段必须支持

第一阶段目标是验证核心 Request 生成链路，不追求完整订阅闭环。

第一阶段必须支持：

1. 入口与流程编排模块可以启动单番剧 Request 生成流程。
2. 用户输入单个番剧名称。
3. 系统从静态 MiKan 模拟数据中获取候选番剧。
4. 系统自动选择最相似的番剧匹配结果。
5. 系统从静态数据中获取该番剧下的候选字幕组 RSS。
6. 系统解析静态 RSS 内容或等价 fixture。
7. 系统根据默认筛选规则计算有效种子。
8. 系统推荐一个字幕组。
9. 系统生成预期文件夹名。
10. 系统生成结构完整、状态为 PENDING_CONFIRM 的 Request。
11. 系统可以将 Request 以 JSON 或终端可读形式输出。
12. 系统失败时可以返回明确错误信息。
13. 系统具备最小日志或错误结构，用于开发排错。

### 15.2 第一阶段明确不做

第一阶段明确不做：

1. 不访问真实 MiKanProject 页面。
2. 不实现真实 MiKan 爬虫。
3. 不提供候选番剧手动选择。
4. 不提供完整 Request 接受、修改、取消交互。
5. 不调用 Auto Bangumi。
6. 不生成 AB 降级配置。
7. 不直接调用 qBittorrent。
8. 不持久化 Request、状态历史或 AB 调用结果。
9. 不做 Web UI。
10. 不做批量季度清单输入。
11. 不做本地媒体库管理。
12. 不做复杂历史学习。

### 15.3 后续阶段边界

第一阶段之后的能力按阶段推进：

1. 第二阶段：Request 确认交互，包括接受、修改、取消和修改后重新计算。
2. 第三阶段：Auto Bangumi 集成，包括提交订阅和失败时生成降级 JSON。
3. 第四阶段：持久化、真实 MiKan 访问、运行数据管理和更完整的配置体系。
4. 第五阶段：Web UI、批量订阅、历史偏好学习和更多自动化能力。

## 16. 全局规则规划

以下规则需要在模块 PRD 中详细定义。

### 16.1 番剧匹配规则

由 M02 番剧搜索与匹配模块定义。

需要处理：

1. 中文名。
2. 日文名。
3. 英文名。
4. 简称。
5. 季数。
6. Part。
7. 续作。
8. 重制版。
9. 剧场版与 TV 版区分。

### 16.2 字幕组推荐规则

由 M05 字幕组评估模块定义。

需要处理：

1. 用户偏好的字幕组优先级。
2. 用户不希望使用的字幕组。
3. 有效种子数量。
4. 更新稳定性。
5. 字幕语言。
6. 分辨率。
7. 命名规范程度。

### 16.3 种子筛选规则

由 M06 种子筛选规则模块定义。

需要处理：

1. 分辨率。
2. 简中/繁中。
3. 正片/合集/SP/PV/NCOP/NCED。
4. 修正版 v2/v3。
5. 先行版。
6. 多版本去重。
7. 集数识别。
8. 排除原因输出。

### 16.4 文件夹命名规则

由 M07 文件夹命名模块定义。

需要处理：

1. 季度代码。
2. 番剧简称。
3. 季数。
4. Part。
5. 字幕组简称。
6. AB 季度编号。
7. 用户自定义覆盖。
8. 历史命名复用。

### 16.5 用户偏好规则

由 M08 用户偏好与规则配置模块定义。

需要处理：

1. 默认分辨率。
2. 默认字幕语言。
3. 字幕组偏好。
4. 命名模板。
5. 排除关键词。
6. 包含关键词。
7. 规则优先级。
8. 单番特殊配置。

## 17. 数据存储规划

第一阶段不要求业务持久化。

第一阶段只要求：

1. 可以读取内置默认配置或静态配置。
2. 可以读取静态 MiKan/RSS 模拟数据。
3. 可以将生成的 Request 输出到控制台或由调用方保存为 JSON。

后续实现 M11 存储与状态管理模块时，至少需要规划存储：

1. Request。
2. Request 状态。
3. 用户修改历史。
4. 用户偏好配置。
5. 番剧简称配置。
6. 字幕组简称配置。
7. AB 调用结果。
8. AB 降级配置生成结果。
9. 用户配置文件。

日志不作为普通业务数据混入 Request 存储，应由独立日志系统负责记录。

后续持久化阶段优先使用本地 JSON 文件，暂不接入数据库系统。

可选方案：

1. 本地 JSON 文件。
2. SQLite。
3. PostgreSQL。
4. 其他轻量数据库。
数据库方案作为后续扩展，不进入第一阶段。

## 18. 外部系统集成规划

### 18.1 MiKanProject 集成

第一阶段不访问真实 MiKanProject，只使用静态数据模拟候选番剧和 RSS 源。

后续真实 MiKanProject 集成需要确认：

1. 如何通过爬虫搜索番剧。
2. 如何通过爬虫获取番剧详情。
3. 如何通过爬虫获取字幕组 RSS。
4. 是否需要登录。
5. 是否有访问频率限制。
6. 页面结构变化后的兼容策略。
详细内容由 M03 MiKan 数据源模块 PRD 定义。

### 18.2 Auto Bangumi 集成

第一阶段不调用 Auto Bangumi，不要求 AB 配置可用。

后续 Auto Bangumi 集成需要确认：

1. AB 是否提供可用 API。
2. AB 需要哪些字段创建订阅。
3. 是否需要认证。
4. 创建订阅后如何确认成功。
5. 创建失败如何处理。
6. AB 调用失败时生成什么格式的降级配置。
7. 是否需要回滚。
详细内容由 M10 Auto Bangumi 集成模块 PRD 定义。

### 18.3 qBittorrent 集成

第一阶段原则上不直接调用 qBittorrent。

qBittorrent 由 AB 间接管理。

后续如需绕过 AB，可新增 qBittorrent 集成模块。

## 19. 异常场景

系统需要处理以下异常：

1. 搜索不到番剧。
2. 搜索到多个相似番剧时，系统选择了错误匹配。
3. 匹配到错误番剧。
4. 静态数据无法加载。
5. 匹配番剧没有候选 RSS。
6. RSS 内容为空。
7. RSS 格式异常。
8. RSS 中没有种子。
9. 默认规则下有效种子数为 0。
10. 所有字幕组均不符合偏好。
11. 文件夹名生成失败。
12. 日志写入失败。

后续阶段还需要处理：

1. MiKan 无法访问。
2. MiKan 页面结构变化导致爬虫解析失败。
3. RSS 无法拉取。
4. 用户修改后规则冲突。
5. 用户接受时 RSS 内容发生变化。
6. AB 调用失败。
7. AB 调用失败后降级配置生成失败。
8. AB 返回成功但订阅未实际创建。
9. 持久化写入失败。
10. Request 过期。

第一阶段失败处理原则：

1. 系统记录失败原因。
2. 系统不自动重试完整流程。
3. 如果用户希望重试，需要重新输入番剧名并重新跑一遍完整流程。

## 20. 第一阶段验收标准

第一阶段验收标准：

1. 入口与流程编排模块可以接收一个番剧名称，并启动单番剧 Request 生成流程。
2. 用户输入一个番剧名称后，系统可以生成一条 Request。
3. Request 中包含匹配到的番剧信息。
4. Request 中包含候选字幕组列表。
5. Request 中包含每个字幕组 RSS 下的种子总数。
6. Request 中包含默认规则下的有效种子数。
7. Request 中包含当前选择字幕组。
8. Request 中包含当前筛选规则。
9. Request 中包含当前有效种子名列表。
10. Request 中包含预期文件夹名。
11. Request 状态为 PENDING_CONFIRM 或等价待确认状态。
12. Request 中 ab_submit_result 为 null。
13. 系统不依赖 Auto Bangumi 或 qBittorrent 在线可用。
14. 系统不依赖真实 MiKanProject 在线可用。
15. 系统可以根据当前执行场景向控制台输出必要信息。
16. 系统失败时可以记录明确失败原因，但不自动重试完整流程。
17. 系统可以在关键失败场景下给出明确错误原因。

## 21. 非功能需求

### 21.1 可维护性

1. 每个模块必须有清晰边界。
2. 核心规则不能散落在流程代码中。
3. 外部系统访问必须通过适配器封装。
4. Request 状态流转必须集中管理。
5. 用户偏好必须可配置。

### 21.2 可测试性

1. 项目整体采用 TDD 开发方式。
2. 新增或修改业务逻辑前，应先补充对应测试。
3. 规则模块需要可单独测试。
4. MiKan、AB 等外部系统调用需要可替换为测试适配器。
5. Request 状态流转需要有单元测试。
6. 种子筛选规则需要覆盖典型命名格式。
7. 文件夹命名规则需要覆盖用户自定义场景。
8. 测试文件与被测逻辑文件放在同一目录下，测试文件名以 _test 结尾。

### 21.3 可扩展性

1. 后续可以新增其他番剧数据源。
2. 后续可以新增其他下载管理器。
3. 后续可以新增更多字幕组评分指标。
4. 后续可以支持批量季度番剧订阅。
5. 后续可以支持历史偏好学习。

### 21.4 可观测性

1. 每条 Request 需要有完整状态记录。
2. 每次外部系统调用需要记录结果。
3. 每次筛选种子需要记录排除原因。
4. 每次用户修改需要记录修改内容。
5. 失败场景需要有可读错误信息。

## 22. 合规说明

本系统定位为 RSS 订阅自动化与下载流程编排工具。

用户需要自行确保订阅源、下载内容、收藏行为符合当地法律法规及内容授权要求。

系统本身不内置受版权保护内容，不提供资源分发能力，只对用户配置的数据源进行流程编排。

## 23. 待确认事项

本节只记录主 PRD 层面需要确认的项目级问题，以及需要下放到模块 PRD 中细化的问题。

原则：

1. 影响第一阶段范围、用户入口、系统边界、模块优先级的问题，应在主 PRD 中确认。
2. 影响单个模块内部规则、字段、接口、异常细节的问题，应下放到对应模块 PRD 中确认。
3. 已经确定的问题不再作为待确认问题保留，只记录为已确认事项。

### 23.1 已确认事项

| 事项 | 当前结论 |
| --- | --- |
| 项目正式名称 | MiGuOrca |
| 仓库名 | migu_orca |
| Python 包名 | migu_orca |
| CLI 命令 | migu-orca |
| 第一阶段核心对象 | Request |
| 第一阶段核心闭环 | 用户输入番名 -> 静态数据匹配和分析 -> 生成 PENDING_CONFIRM Request -> 输出 JSON 或终端结果 |
| 第一阶段用户入口 | 使用独立入口与流程编排模块，不在第一阶段实现 Web UI |
| 第一阶段输入范围 | 仅实现单个番剧的 Request 生成流程，批量清单功能后续通过循环调用单次流程实现 |
| 第一阶段数据源 | 使用静态 MiKan/RSS 模拟数据，不访问真实 MiKanProject |
| 番剧匹配策略 | 当前直接选择系统判断最相似的匹配结果；若用户发现匹配错误，则取消 Request 并重新输入番剧名 |
| AB 提交策略 | 第一阶段不提交 AB；后续阶段再定义直接提交和降级配置策略 |
| AB 降级配置格式 | 第一阶段不生成；后续 M10 中定义 JSON schema |
| 持久化要求 | 第一阶段不要求业务持久化 |
| 持久化方案 | 后续 M11 优先使用本地 JSON 文件，暂不接入数据库系统 |
| 用户配置 | 第一阶段可使用内置默认配置，用户配置文件作为后续增强 |
| 用户配置最小字段 | 后续配置至少包含默认分辨率、默认字幕语言、字幕组偏好、排除关键词、包含关键词、命名模板、本地路径配置 |
| 日志要求 | 第一阶段需要最小日志或统一错误结构，用于开发排错和问题追踪 |
| 日志输出 | 第一阶段可先输出必要控制台信息；文件日志格式由 M12 确认 |
| 失败处理 | 记录失败原因，不自动重试；用户若想重试，需要重新输入番剧名并重新跑完整流程 |
| Request 清理策略 | 第一阶段无持久化 Request，因此不考虑清理逻辑 |
| 开发方式 | 项目整体采用 TDD 开发方式 |
| qBittorrent 集成边界 | 第一阶段不直接调用 qBittorrent，后续由 AB 间接管理 |
| 本地媒体库管理 | 不进入第一阶段范围 |

### 23.2 主 PRD 需要优先确认的问题

以下问题会影响整体范围、第一阶段交付方式和模块拆分，应优先在主 PRD 中确认。

| 编号 | 问题 | 影响范围 | 建议确认方向 |
| --- | --- | --- | --- |
| Q-MAIN-01 | 第一阶段入口形态是 CLI、库函数，还是两者都支持？ | M00 | 建议同时支持内部 generate_request 能力和最小 CLI 包装 |
| Q-MAIN-02 | 第一阶段 Request 输出形式是终端、文件、JSON，还是多种都支持？ | M00 | 建议以 JSON 对象为主，终端展示作为包装能力 |
| Q-MAIN-03 | 第一阶段静态数据是否纳入仓库并作为测试 fixture？ | M03/M04 | 建议纳入仓库，保证离线验收可重复 |

### 23.3 下放到模块 PRD 的待确认问题

以下问题不应在主 PRD 中展开为最终规则，只需要在主 PRD 中标记归属模块。

| 问题 | 归属模块 PRD | 说明 |
| --- | --- | --- |
| AB 具体可调用接口是什么？ | M10 Auto Bangumi 集成模块 | 后续阶段外部接口验证和字段映射问题 |
| AB 需要哪些字段创建订阅？ | M10 Auto Bangumi 集成模块 | 后续阶段集成字段定义 |
| AB 是否需要认证？ | M10 Auto Bangumi 集成模块 | 后续阶段集成配置和安全策略 |
| AB 降级 JSON 的具体字段结构是什么？ | M10 Auto Bangumi 集成模块 | 后续阶段定义 JSON schema，并尽量与 AB API 字段保持一致 |
| 创建订阅后如何确认成功？ | M10 Auto Bangumi 集成模块 | 后续阶段集成验收和回查策略 |
| MiKan 搜索是否稳定可用？ | M03 MiKan 数据源模块 | 后续真实数据源可行性验证 |
| MiKan 是否需要登录？ | M03 MiKan 数据源模块 | 后续真实数据源访问策略 |
| MiKan 页面结构变化后如何兼容？ | M03 MiKan 数据源模块 | 后续真实适配器健壮性设计 |
| 默认字幕组优先级如何定义？ | M05 字幕组评估模块 | 属于推荐规则细节 |
| 默认分辨率是否固定为 1080p？ | M06 种子筛选规则模块、M08 用户偏好与规则配置模块 | 属于筛选默认值和用户偏好 |
| 默认字幕语言是否固定为简中？ | M06 种子筛选规则模块、M08 用户偏好与规则配置模块 | 属于筛选默认值和用户偏好 |
| v2/v3 修正版如何处理？ | M06 种子筛选规则模块 | 属于种子筛选和去重策略 |
| 合集是否一律排除？ | M06 种子筛选规则模块 | 属于默认筛选规则 |
| SP、OVA、剧场版是否进入第一版范围？ | M06 种子筛选规则模块、M02 番剧搜索与匹配模块 | 主 PRD 只定义第一阶段以 TV 正片为主，细节由模块确认 |
| 文件夹命名中的季度编号如何生成？ | M07 文件夹命名模块 | 属于命名规则细节 |
| 番剧简称由系统生成还是用户维护？ | M07 文件夹命名模块、M08 用户偏好与规则配置模块 | 属于命名与偏好配置问题 |
| 用户偏好配置使用 JSON、YAML、数据库还是界面管理？ | M08 用户偏好与规则配置模块、M11 存储与状态管理模块 | 主 PRD 只确认第一阶段可以先使用内置默认配置 |
| Request 过期时间如何定义？ | M01 用户输入与 Request 管理模块 | 属于 Request 生命周期细节 |
| 接受前 RSS 变化时如何提示用户？ | M09 Request 确认交互模块 | 属于交互展示和变更说明 |
| 失败日志记录哪些字段？ | M12 日志与错误处理模块 | 属于可观测性字段设计 |

### 23.4 当前最需要用户确认的决策

为了推进第一阶段技术方案和实现，当前最需要先确认以下事项：

1. 第一阶段入口形态。
2. 第一阶段输出形式。
3. 静态数据和 RSS fixture 的组织方式。

## 24. 后续工作计划

下一步建议按以下顺序推进：

1. 关闭第 23.4 节的第一阶段阻塞决策。
2. 根据已确认决策更新 M00、M03、M04、M06、M07、M12 模块 PRD。
3. 编写第一阶段最小技术方案，明确目录结构、数据模型、fixture 和模块接口。
4. 补齐静态 MiKan/RSS fixture。
5. 按第 12.3 节顺序实现默认规则、静态数据源、RSS 解析、种子筛选、匹配、推荐、命名和 Request 组装。
6. 实现入口编排和最小 CLI 输出。
7. 使用 `uv run pytest` 完成第一阶段单元测试和链路测试。
8. 第一阶段完成后，再启动 M09、M10、M11 等后续阶段 PRD 和技术验证。

## 25. 当前结论

本项目应优先围绕 Request 这一核心对象进行设计。

第一阶段不要追求完全自动化，而是先完成：

```text
入口与流程编排模块接收单个番名
  ↓
系统基于静态 MiKan/RSS 数据匹配和分析
  ↓
生成 PENDING_CONFIRM Request
  ↓
输出 JSON 或终端结果
```

只要这个链路稳定，后续确认交互、AB 集成、持久化、真实 MiKan 访问、批量季度整理、历史偏好学习和 Web UI 都可以逐步扩展。
