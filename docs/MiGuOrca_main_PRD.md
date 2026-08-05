# MiGuOrca 主 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | MiGuOrca |
| 文档名称 | MiGuOrca 主 PRD |
| 文档类型 | 主 PRD |
| 当前版本 | v0.4 |
| 文档状态 | Stage 3 已完成，Stage 4 待开发 |
| 适用阶段 | 需求讨论、模块拆分、开发规划 |
| 相关系统 | MiKanProject、Auto Bangumi、qBittorrent |
| 简称约定 | Auto Bangumi 简称为 AB |

### 1.1 命名约定

| 类型 | 名称 |
| --- | --- |
| 正式项目名 | MiGuOrca |
| 仓库名 | migu_orca |
| Python 包名 | migu_orca |
| CLI 命令 | migu-orca |
| 配置目录 | ~/.config/migu_orca |
| 环境变量前缀 | MIGU_ORCA_ |
| 日志名 | migu_orca |

MiGu 来源于 Mikan + Bangumi。ORCA 表示 Orchestrated RSS Coordination for Anime，即面向动画 RSS 的自动编排与协调系统。

### 1.2 开发约定

本项目使用 `UV` 进行 Python 包管理和命令执行。

1. 安装依赖使用 `uv sync`。
2. 运行测试使用 `uv run pytest`。
3. 运行项目入口或脚本时优先使用 `uv run <command>`。
4. 不要直接使用 `python` 运行测试或脚本，避免绕过项目统一环境。

## 2. 项目背景

用户目前主要通过 MiKanProject 获取番剧 RSS，并使用 Auto Bangumi 配合 qBittorrent 实现自动下载。

现有流程通常是：

1. 用户确定想看的季度新番。
2. 用户手动在 MiKanProject 搜索番剧。
3. 用户在多个字幕组 RSS 中选择一个符合偏好的源。
4. 用户将 RSS 配置到 Auto Bangumi。
5. 用户手动填写订阅名称、目录名称、季度编号、筛选规则等信息。
6. Auto Bangumi 根据 RSS 与规则将种子添加到下载任务。

这个流程可用，但每季度会重复大量人工操作。MiGuOrca 的目标是在 MiKanProject 与 Auto Bangumi 之间提供一层自动化编排能力，降低搜索、判断字幕组、筛选种子和命名目录的成本。

## 3. 项目目标

MiGuOrca 是一个面向动画 RSS 的自动订阅编排系统。

项目长期目标是：

1. 用户输入想看的番剧名称。
2. 系统搜索并分析番剧 RSS。
3. 系统根据规则和偏好生成可确认 Request。
4. 用户确认后，系统调用 Auto Bangumi 或生成降级配置。

当前已完成前三个阶段：离线 Request 生成、Request 确认交互、Auto Bangumi 离线提交契约与 CLI 显式提交路径。真实 Auto Bangumi HTTP adapter、持久化、Web UI 和真实 MiKan 访问仍属于后续阶段。

## 4. 第一阶段范围

第一阶段目标是：**输入单个番剧名后，基于静态 MiKan/RSS 数据生成一条结构完整、状态为待确认的 Request。**

### 4.1 第一阶段必须支持

1. 接收单个番剧名称。
2. 从静态 MiKan 模拟数据中获取候选番剧。
3. 自动选择最相似的番剧匹配结果。
4. 从静态数据中获取候选字幕组 RSS。
5. 解析静态 RSS 内容或等价 fixture。
6. 根据当前用户筛选规则计算有效种子。
7. 推荐一个字幕组。
8. 生成预期文件夹名。
9. 生成结构完整、状态为 `PENDING_CONFIRM` 的 Request。
10. 将 Request 以 JSON 或终端可读形式输出。
11. 失败时返回明确错误信息。

### 4.2 第一阶段明确不做

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

## 5. 第一阶段验收标准

第一阶段以“能否离线稳定生成 Request”为验收核心。

1. 输入一个番剧名称后，系统可以生成一条 Request。
2. Request 中包含匹配到的番剧信息。
3. Request 中包含候选字幕组列表。
4. Request 中包含每个字幕组 RSS 下的种子总数。
5. Request 中包含当前筛选规则下的有效种子数。
6. Request 中包含当前选择字幕组。
7. Request 中包含当前筛选规则。
8. Request 中包含当前有效种子名列表。
9. Request 中包含预期文件夹名。
10. Request 状态为 `PENDING_CONFIRM` 或等价待确认状态。
11. Request 中 `ab_submit_result` 为 `null`。
12. 系统不依赖 Auto Bangumi 或 qBittorrent 在线可用。
13. 系统不依赖真实 MiKanProject 在线可用。
14. 关键失败场景可以返回明确错误原因。
15. 项目测试通过 `uv run pytest`。

## 6. 核心概念

| 概念 | 含义 | 详细定义 |
| --- | --- | --- |
| Request | 系统根据用户输入、规则和数据源生成的番剧订阅确认对象 | M01 |
| source_info | 系统搜索、解析、分析后得到的客观源信息 | M01、M03、M04、M06 |
| confirmable_config | 用户后续可以确认或修改的配置集合 | M01 |
| 有效种子 | 按筛选规则去除重复、无效和不符合规则的种子后保留的种子 | M06 |
| 字幕组推荐 | 从候选 RSS 中选出默认字幕组 | M05 |
| 预期文件夹名 | 第一阶段根据匹配番剧全名生成的目录名 | M07 |

主 PRD 只定义概念边界，不维护完整字段结构。字段、状态、错误和接口定义由对应模块 PRD 维护。

第一阶段输出的 Request 是一次计算得到的“待确认快照”，只承诺成功结果状态为
`PENDING_CONFIRM`。它不是完整的 Request 生命周期或持久化状态机。确认、修改、
取消、过期、提交及失败历史等状态，在后续实现 M09、M10、M11 时再定义。

## 7. 模块划分

| 模块编号 | 模块名称 | 当前状态 | 优先级 | 模块 PRD |
| --- | --- | --- | --- | --- |
| M00 | 入口与流程编排模块 | Stage 3 已实现 CLI 显式 AB 提交流程 | P0 | docs/modules/M00-entry-orchestration-PRD.md |
| M01 | 用户输入与 Request 管理模块 | Stage 2 已实现确认、取消和受限修改 | P0 | docs/modules/M01-request-management-PRD.md |
| M02 | 番剧搜索与匹配模块 | Stage 1 已确认 | P0 | docs/modules/M02-bangumi-search-match-PRD.md |
| M03 | MiKan 数据源模块 | Stage 1 已确认 | P0 | docs/modules/M03-mikan-source-PRD.md |
| M04 | RSS 解析模块 | Stage 1 已确认 | P0 | docs/modules/M04-rss-parser-PRD.md |
| M05 | 字幕组评估模块 | Stage 1 已确认 | P1 | docs/modules/M05-subtitle-group-evaluation-PRD.md |
| M06 | 种子筛选规则模块 | Stage 1 已确认 | P0 | docs/modules/M06-torrent-filter-rule-PRD.md |
| M07 | 文件夹命名模块 | Stage 1 已确认 | P1 | docs/modules/M07-folder-naming-PRD.md |
| M08 | 用户偏好与规则配置模块 | Stage 1 已确认 | P1 | docs/modules/M08-user-preference-rule-PRD.md |
| M09 | Request 确认交互模块 | Stage 2 已实现 | P2 | docs/modules/M09-request-confirmation-PRD.md |
| M10 | Auto Bangumi 集成模块 | Stage 3 已实现离线契约；Stage 4 待实现真实 HTTP adapter | P2 | docs/modules/M10-auto-bangumi-integration-PRD.md |
| M11 | 存储与状态管理模块 | 暂缓 | P2 | docs/modules/M11-storage-state-PRD.md |
| M12 | 日志与错误处理模块 | Stage 1 最小化 | P1 | docs/modules/M12-log-error-PRD.md |
| M13 | Web UI / 管理界面模块 | 暂缓 | P2 | docs/modules/M13-web-ui-PRD.md |
| M14 | 系统配置模块 | Stage 3 已支持显式 AB JSON 配置读取 | P1 | docs/modules/M14-system-config-PRD.md |

## 8. 第一阶段开发顺序

第一阶段按可运行的纵向链路推进，避免先建设尚未验证的基础设施。

```text
共享数据契约与 fixture
  ↓
M02 + M03 候选读取与匹配
  ↓
M04 + M06 RSS 解析与筛选
  ↓
M05 + M07 订阅默认值
  ↓
M01 Request 快照
  ↓
M00 CLI 与流程编排
  ↓
最小配置与日志收尾
```

说明：

1. 每一步先补行为测试，再实现最小功能。
2. M02 与 M03 合入 catalog_engine，M04 与 M06 合入 rss_engine。
3. M05 与 M07 合入 subscription_engine。
4. M08、M12、M14 在 Stage 1 只提供普通基础模块，不建立独立 engine。
5. 确认交互、持久化和 AB 对接全部后置。

## 9. 后续阶段路线图

| 阶段 | 目标 | 主要模块 |
| --- | --- | --- |
| 第一阶段 | 离线生成 `PENDING_CONFIRM` Request | M00、M01、M02、M03、M04、M05、M06、M07、M08、M12、M14 |
| 第二阶段 | 支持 Request 确认、修改、取消 | M09、M01、M06、M07 |
| 第三阶段 | 建立 Auto Bangumi 离线提交契约、fake client、失败降级 JSON 和显式 CLI 提交路径 | M10、M14、M12 |
| 第四阶段 | 实现真实 Auto Bangumi HTTP client adapter、网络错误标准化和 CLI 真实 client 注入 | M10、M14、M12 |
| 第五阶段 | 持久化 Request、状态、历史和结果 | M11、M01、M12 |
| 第六阶段 | 扩展真实 MiKan 访问、Web UI、批量订阅和历史偏好 | M03、M13、M08 |

## 10. 主 PRD 已确认事项

主 PRD 只记录影响阶段范围、用户入口、模块优先级的项目级决策。模块内部规则由模块 PRD 维护。

| 编号 | 事项 | 影响范围 | 当前结论 |
| --- | --- | --- | --- |
| D-MAIN-01 | 第一阶段入口形态 | M00 | 同时支持内部 `generate_request` 能力和最小 CLI 包装 |
| D-MAIN-02 | 第一阶段 Request 输出形式 | M00 | 以 JSON 对象为主，终端展示作为包装能力 |
| D-MAIN-03 | 第一阶段静态数据组织方式 | M03、M04 | 静态 MiKan/RSS 数据纳入仓库并作为测试 fixture，保证离线验收可重复 |
| D-MAIN-04 | 第一阶段实现定位 | 全部 | 最小离线技术探针，不提前建设完整长期架构 |
| D-MAIN-05 | Stage 1 代码结构 | 全部 | 保留 apps/engine/controllers/models，总量收敛为 4 个 engine |
| D-MAIN-06 | Stage 1 Request 状态 | M00、M01 | Request 是 PENDING_CONFIRM 快照，不是完整状态机；失败使用独立 ErrorResult |

## 11. 文档职责边界

| 文档 | 职责 |
| --- | --- |
| docs/MiGuOrca_main_PRD.md | 项目级目标、第一阶段范围、模块划分、验收标准、路线图 |
| docs/modules/*.md | 模块目标、边界、输入输出、流程、规则、异常、接口、验收 |
| docs/design/architecture.md | 技术架构、目录结构、分层原则、测试组织规范 |
| docs/design/stage1-spec.md | Stage 1 唯一技术行为基线、数据契约、规则与验收用例 |
| docs/api/ | 后续接口、数据结构和对外 API 说明 |
| docs/test_manual/ | 后续真实环境验证、手动测试记录 |

维护原则：

1. 主 PRD 不维护模块字段级细节。
2. 主 PRD 不维护具体算法规则。
3. 主 PRD 不维护完整技术目录和代码结构。
4. 模块 PRD 与主 PRD 冲突时，以主 PRD 的阶段范围和模块边界为准。
5. 模块内部细节以对应模块 PRD 为准。

## 12. 合规说明

本系统定位为 RSS 订阅自动化与下载流程编排工具。

用户需要自行确保订阅源、下载内容、收藏行为符合当地法律法规及内容授权要求。

系统本身不内置受版权保护内容，不提供资源分发能力，只对用户配置的数据源进行流程编排。

## 13. 下一步工作

1. 按 `scripts/ralph/prd.json` 启动 Stage 4，优先实现真实 Auto Bangumi HTTP client adapter 边界。
2. 保持 `--submit-ab` 为显式动作，默认生成、确认、修改、取消路径不得访问外部系统。
3. 使用 `uv run pytest` 和 `uv run python -m compileall -q src` 验证每个 Ralph story。
