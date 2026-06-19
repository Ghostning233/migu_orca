# MiGuOrca 架构与目录设计

## 1. 文档目标

本文档承接主 PRD 中不适合长期放在项目级需求文档里的技术结构内容。

本文档用于描述：

1. 初步架构分层。
2. 源码目录规划。
3. engine 与 apps 的职责边界。
4. 测试文件组织规范。
5. 配置、日志、工具目录的规划原则。

第一阶段只要求结构方向清晰，不要求立即创建全部目录。

## 2. 架构目标

系统整体架构需要满足：

1. 模块边界清晰。
2. 规则可配置。
3. 外部系统可替换。
4. Request 状态可追踪。
5. 搜索、解析、筛选、确认、提交流程可拆分。
6. 后续可以从入口与流程编排模块平滑扩展到 Web UI。
7. 后续可以扩展更多数据源，不强绑定 MiKanProject。
8. 后续可以替换 AB 集成方式，不强绑定某一种调用方式。

## 3. 初步分层

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

### 3.1 用户交互层

负责：

1. 作为入口与流程编排模块的外部触发入口。
2. 接收单个番剧名称输入。
3. 展示 Request。
4. 后续提供接受、修改、取消操作。
5. 展示错误信息和操作结果。

第一阶段形态：

1. CLI 或内部入口函数。

后续形态：

1. Web UI。
2. API 服务。
3. Bot 或其他交互入口。

### 3.2 应用服务层

负责组织业务流程。

第一阶段典型流程：

1. 入口模块启动单番剧 Request 生成流程。
2. 创建 Request 初始对象。
3. 调用番剧搜索与匹配模块。
4. 调用 MiKan 静态数据源模块。
5. 调用 RSS 解析模块。
6. 调用种子筛选模块。
7. 调用字幕组评估模块。
8. 调用文件夹命名模块。
9. 生成待确认 Request。

应用服务层不直接实现具体规则，只负责流程编排。

### 3.3 领域逻辑层

负责核心业务规则。

包括：

1. Request 状态流转规则。
2. 番剧匹配规则。
3. 字幕组推荐规则。
4. 种子筛选规则。
5. 文件夹命名规则。
6. 用户偏好合并规则。
7. 后续接受前校验规则。

领域逻辑层应尽量不依赖具体外部系统。

### 3.4 基础设施适配层

负责对接外部系统和底层能力。

包括：

1. MiKanProject 访问适配器。
2. RSS 拉取或静态 RSS 读取适配器。
3. Auto Bangumi 调用适配器。
4. 配置文件读写。
5. 数据库存储。
6. 日志系统。
7. 缓存系统。

第一阶段只需要静态数据读取、最小配置和最小日志能力。

### 3.5 外部系统

包括：

1. MiKanProject。
2. Auto Bangumi。
3. qBittorrent。
4. 本地文件系统。
5. 后续可能扩展的其他番剧数据源。

第一阶段不要求任何外部系统在线可用。

## 4. 初版目录结构规划

目录规划原则：

1. 根目录保留项目入口、依赖配置、运行配置、文档、脚本、工具。
2. 业务代码统一放在 `src/` 下。
3. 各 engine 直接放在 `src/` 下，每个 engine 遵循 MVC 风格组织。
4. `src/apps/` 存放统一 API 管理层，按 engine 模块拆分 services 和 clients。
5. Controller 是 engine 的业务能力入口，入口编排模块通过调用各 engine 的 Controller 串联业务能力。
6. Services 是 Controller 业务能力的 API 封装，主要供内部 API 层复用。
7. Clients 是带用户认证或权限边界的 API 接口，用户侧能力调用应通过 clients 暴露。
8. services 和 clients 主要为后续 Web UI 或 API 化预留，第一阶段只需在框架中定义清楚。
9. 测试文件与被测逻辑文件放在同一目录下，测试文件名以 `_test` 结尾。
10. 项目整体采用 TDD 方式开发，新增或修改业务逻辑前应先补充对应测试。
11. 目录结构只表达项目架构，不要求立即创建全部目录。

规划结构：

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

## 5. 根目录说明

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

## 6. src 分层说明

`src/` 下分为 engine 模块和 apps 两类目录。

| 路径 | 职责 |
| --- | --- |
| src/*_engine/ | 核心业务能力实现层，按业务 engine 拆分 |
| src/apps/ | 统一 API 管理层，按 engine 模块封装 services 和 clients |
| src/apps/migu_orca_entry/ | 入口与流程编排模块，负责串联完整业务流程 |

分层原则：

1. engine 模块直接位于 `src/` 下，负责实现业务能力。
2. apps 负责把业务能力封装成可调用 API。
3. 入口编排模块可以直接调用 engine Controller 完成第一阶段流程。
4. 后续做 Web UI 或 API 服务时，由 apps 层统一对外提供 services 和 clients。
5. 业务规则不应写在 apps 层，apps 层只做参数传递、调用编排、权限边界和返回包装。

## 7. engine 内部结构规范

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

## 8. apps API 层结构规范

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

## 9. engine 与 apps 示例

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

## 10. 测试文件规范

测试文件不单独集中到 `tests/` 目录，而是与被测逻辑文件放在同一目录下。

项目整体采用 TDD 开发方式。

TDD 规则：

1. 新增业务能力前，先编写能够描述预期行为的测试。
2. 修改已有业务规则前，先补充或调整能复现目标行为的测试。
3. 修复缺陷前，先补充能复现缺陷的失败测试。
4. 测试通过后再整理实现代码。

命名规则：

1. 被测逻辑文件与测试文件同目录。
2. 测试文件名在被测逻辑文件名后追加 `_test`。
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

说明：上方示例只表达命名关系，不代表最终文件后缀或具体文件必须在本文档中固定。

## 11. docs 目录说明

| 路径 | 说明 |
| --- | --- |
| docs/MiGuOrca_main_PRD.md | 主 PRD，记录项目级目标、边界、第一阶段范围、模块拆分 |
| docs/modules/ | 各模块 PRD |
| docs/design/ | 技术设计文档 |
| docs/api/ | 外部接口、内部接口、数据结构说明 |
| docs/test_manual/ | 手动测试步骤、真实环境验证记录 |

## 12. config 目录说明

| 路径 | 说明 |
| --- | --- |
| config/user/ | 用户偏好配置，例如字幕组偏好、默认分辨率、默认字幕语言 |
| config/rules/ | 筛选规则、命名规则等规则配置 |
| config/system/ | 系统级配置，例如 MiKan 访问配置、AB 地址、路径配置 |

配置文件用于记录用户的部分信息和规则偏好。第一阶段可先使用内置默认配置或 JSON，后续如有需要再迁移到数据库或管理界面。

## 13. 运行数据目录说明

第一阶段不要求持久化 Request、状态历史或 AB 调用结果。

第一阶段如需保存输出，可由 CLI 将生成的 Request 导出为 JSON 文件；该能力属于输出包装，不等同于 M11 存储与状态管理。

后续在实现 M11 存储与状态管理模块时，再确定 Request、AB 降级配置、缓存等运行数据的具体目录结构。

## 14. tools 目录说明

`tools/` 用于放置开发阶段调试外部服务的测试脚本。

使用边界：

1. `tools/` 可以访问 MiKan、RSS、AB 等外部服务做可行性验证。
2. `tools/` 不承载正式业务流程。
3. `tools/` 中沉淀出的稳定逻辑，需要按职责迁移到对应 engine 的 controllers，或迁移到 apps 层的 services、clients 中。
4. 本文档不固定 `tools/` 下的具体脚本文件名。
