# MiGuOrca Future Stages

## 1. 总体方向

MiGuOrca 后续方向是 Auto Bangumi 前置的批量新番订阅编排工作台，而不是 Auto Bangumi 或 qBittorrent 的替代执行系统。

核心用户流程：

```text
用户从季度新番推荐视频或清单中整理出一批想看的番剧
  ↓
输入简称、口语名或不完整标题
  ↓
MiGuOrca 使用 AI 名称解析和 MiKan 搜索生成可审核订阅草案
  ↓
用户逐项审核、修改、删除、接受
  ↓
接受后显式提交 Auto Bangumi
  ↓
下载执行由 Auto Bangumi / qBittorrent 负责
```

后续阶段必须遵守：

1. 不直接创建 qBittorrent 下载任务。
2. 不绕过 Auto Bangumi 建立长期订阅状态机。
3. 不复制 Auto Bangumi 已有的 MiKan 到下载链路。
4. 不让 AI 静默自动接受最终合集。
5. 所有外部配置和敏感值保持 request-scoped，不进入 storage JSON、浏览器 storage、URL、日志、截图或测试 trace。

## 2. Stage 19: 批量输入与订阅草案卡片工作台（已完成）

完成目标：

已建立新方向的最小可用形态。用户可以一次输入多行番剧简称，系统解析为候选标题和搜索词，逐项生成可审核订阅草案卡片。

已完成功能：

1. 批量输入入口：支持多行输入，每个非空行作为一个条目。
2. AI 名称解析 seam：先提供 fake provider 和稳定接口，后续再接真实 LLM provider。
3. 批量条目 API：返回每个条目的原始输入、解析结果、候选标题、搜索词、置信度和审核状态。
4. 逐项 MiKan 候选搜索：每个条目独立执行，单项失败不影响其他条目。
5. 订阅草案卡片：展示封面、番剧全名、源名称、有效种子数、展开控件和删除按钮。
6. 卡片展开摘要：展示当前字幕组、过滤器、有效种子和排除种子摘要。
7. 单卡修改回流：进入现有订阅方案详情与修改流程，保存后只更新当前卡片。
8. 单卡接受：复用现有 Request 接受能力，将当前卡片标记为已接受。

完成标志（已达成）：

用户可以完成“输入多行简称 -> 生成卡片 -> 删除错误项 -> 展开检查 -> 修改单卡 -> 接受单卡”的闭环。

不包含，移交后续 Stage：

1. 全接受后的并发 Auto Bangumi 提交队列。
2. 真实 LLM provider 的完整生产配置。
3. 部署 Auto Bangumi 或 qBittorrent。

## 3. Stage 20: 批量接受与 Auto Bangumi 提交前队列（已完成）

目标：

把 Stage 19 的单卡接受扩展为批量接受和 Auto Bangumi 提交前队列。

已完成功能：

1. 支持单个接受、批量接受和全接受；工具栏显示选中数量，不可接受项目逐项返回中文原因，单项失败不阻塞其他项。
2. 接受后的卡片进入独立追踪的提交前队列（`READY_TO_SUBMIT`/`SUBMITTING`/`SUCCEEDED`/`FAILED`/`RETRYABLE`），队列只保存非敏感元数据，endpoint/token/cookie/Authorization header/原始响应体/完整 RSS URL/magnet/本地绝对路径从不写入队列。
3. 队列面板展示待提交、提交中、提交成功、提交失败、可重试状态、尝试次数和脱敏结果摘要；刷新页面后通过 URL `batch_id` 恢复队列状态。
4. 继续要求用户显式配置或确认 Auto Bangumi endpoint/token/fallback；提交成功后清空敏感输入。
5. 单个提交失败不影响其他卡片；失败项可独立重试，成功项不会被重复提交。
6. 提交结果以脱敏形式写入现有 Request/AB result 存储。
7. 端到端安全回归覆盖 API 响应、页面、URL、浏览器 storage、队列 JSON、Request JSON、日志和 trace 的敏感值过滤。

完成标志（已达成）：

用户可以审核一批卡片，批量确认若干项目，查看提交前队列，显式配置并顺序提交 Auto Bangumi；成功和失败项目独立展示，失败项可独立重试，且所有外部敏感值都没有进入持久化或展示面。

不包含（仍成立）：

1. qBittorrent 下载任务创建。
2. 自动绕过 Auto Bangumi 的订阅执行。
3. 复杂调度器或后台常驻 worker；批量提交采用前台顺序编排。

## 4. Stage 21: 用户偏好与智能推荐闭环

前置条件（Stage 20 handoff）：Stage 20 已完成批量接受、提交前队列、Auto Bangumi 顺序提交和失败项独立重试（详见 `docs/MiGuOrca_stage20_batch_ab_queue_PRD.md` 的 Stage 21 handoff）。Stage 21 应在此之上把批量草案结果从“可审核”提升到“大部分可直接接受”，并保持 AI 只生成候选、不自动选择最终合集的边界。

目标：

让批量生成结果从“可审核”提升到“大部分可直接接受”。

主要功能：

1. 字幕组偏好：记录用户偏好的字幕组、排除字幕组和 fallback 规则。
2. 筛选偏好：按常见分辨率、字幕语言、简繁、合集/单集等维度生成默认规则。
3. 文件夹命名偏好：支持季度、官方译名、用户别名等命名策略。
4. 搜索词增强闭环：基于用户修正记录改进候选搜索词。
5. AI 解析质量回看：展示低置信度和多义结果，允许用户修正并复用。
6. 安全存储偏好：只保存非敏感偏好，不保存外部服务 secret。

完成标志：

用户每季度批量输入后，系统能根据偏好生成更接近最终配置的订阅草案，减少逐卡修改次数。

不包含：

1. AI 自动接受合集。
2. 对用户观看行为或下载内容做隐式追踪。
3. 复杂账号体系，除非后续出现多人使用或远程部署需求。

## 5. Stage 22: 部署/配置向导可行性验证

目标：

验证是否需要帮助用户降低 Auto Bangumi、qBittorrent 和 MiGuOrca 的初始配置成本。该阶段是远期可选能力，不阻塞批量订阅工作台。

主要功能候选：

1. 配置检查清单：检测 AB/qB/MiGuOrca 的连接配置是否完整。
2. 连接诊断：复用现有 qBittorrent test connection 和 Auto Bangumi submit seam，输出脱敏诊断。
3. 教程式向导：按步骤引导用户填写 endpoint、token、qB 地址和认证信息。
4. Docker Compose 模板：提供可读模板和安全说明，用户自行部署。
5. 配置导入/导出：只处理非敏感配置或明确脱敏后的示例。

完成标志：

用户能更快完成 AB/qB/MiGuOrca 的连接配置诊断，但 MiGuOrca 不接管用户机器或容器环境。

不包含：

1. 通用运维 Agent。
2. 默认接管 NAS、服务器或 Docker daemon。
3. 未经确认写入外部系统配置。
4. 自动创建下载任务或替代 Auto Bangumi 执行链路。

## 6. 阶段数量判断

新方向的核心产品闭环需要 3 个主要 Stage：

1. Stage 19：批量输入与订阅草案卡片工作台（已完成）。
2. Stage 20：批量接受与 Auto Bangumi 提交前队列（已完成）。
3. Stage 21：用户偏好与智能推荐闭环（下一个阶段）。

如果要覆盖“降低 Auto Bangumi/qBittorrent 配置门槛”，再增加 1 个远期可选 Stage：

1. Stage 22：部署/配置向导可行性验证。

因此，最小可用新方向需要 Stage 19 到 Stage 21，共 3 个 Stage；完整覆盖配置痛点则需要 Stage 19 到 Stage 22，共 4 个 Stage。当前 Stage 19 与 Stage 20 均已完成并归档，下一步为 Stage 21。
