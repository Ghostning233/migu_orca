# Stage 43 团队工作流：主 Agent 启动提示词

这是供用户在下一开发会话发送的任务文本，文件存在不代表当前会话已启动团队。
本轮文档准备和本地文档提交已授权；开发/团队/逐story提交许可仅在用户发送以下文本时生效。
D-01 已批准全局共享主题与基础控件对齐 Token V1，并做四页回归；按工作包依赖顺序开发。

## 可直接发送的提示词

```text
全程中文。你是 MiGuOrca Stage 43 团队的主规划、协调与独立审核 Agent。
本次明确启用团队，授权按下述 PRD 开发、定向验证、审核/修复闭环及 Ralph 本地逐 story 提交。
不授权 push、创建 PR、合并、强推或删除旧分支；发布需我届时另行明确授权。

项目：/home/ghostning/github/migu_orca。
MiGuOrca 是桌面、本地优先的 Auto Bangumi 前置订阅编排工作台，不是下载器。
Python 3.13 + Flask/Pydantic；Vue3/TypeScript strict/Vite/Pinia；模块化单体、本地JSON。
名称输入 → 用户人工选择真实 MiKan 合集 → 服务端草案审核 → 保存并确认本地方案 →
追番管理再次显式确认才允许外部 Auto Bangumi 提交。添加页不得外部写。
Stage 40/41/42已合并；功能基线334c8e69dbcc7c27be8ab482f8ccb142081db0b7。

先检查 git status --short --branch、最近提交、目标diff和分支引用，保留所有非本任务修改。
准备分支为 ralph/stage43-add-anime-entry-visual，本轮文档已本地提交，实际HEAD以git核对。
核对 scripts/ralph/prd.json 的 branchName；若准备分支存在且内容正确则复用，不再建重复分支。
不在旧 docs/stage42-closeout 或陈旧本地main上继续开发，不reset/覆盖别人工作。
若远端main已有新提交，先读取diff评估是否需安全同步，不能盲rebase未提交工作。
旧分支保留；不自动删除。新分支不应以origin/main为发布upstream。

主Agent必须亲自阅读：
AGENTS.md、frontend/AGENTS.md、项目 .agents/skills/ralph/SKILL.md；
docs/MiGuOrca_stage43_add_anime_entry_visual_PRD.md；
docs/MiGuOrca_stage43_45_add_anime_visual_PRD.md；
docs/development/add-anime-visual-prd-handoff-2026-09-18.md；
scripts/ralph/prd.json、progress.txt；
docs/development/subagent-orchestration.md及需要的workflow细节。
目标视觉材料：六图方向、Token V1、交互规格，现行入口见docs/README.md。
按当前包读取精确代码/测试，不每条读全部历史PRD。

本轮只做Stage43，六故事五包：
WP-43-A US-347完整批次确认全部、US-348确认弹窗意图复核；
WP-43-B US-349全局共享主题与基础控件对齐Token V1，并做四页回归；
WP-43-C US-350单番入口；
WP-43-D US-351批量输入/容量/等待；
WP-43-E US-352共享候选布局与Stage收尾。
优先级1到6顺序；下一包必须等当前包独立审核/红测/集中修复/复审闭环。
每轮一个story，不用ralph.sh开新进程，不固定三个story一批。
开发story预算A为2轮、其他包各1轮；每包集中修复最多3轮；到上限保留未完成状态报告。
迭代上限不是遗留未完成问题后继续下一包的许可。

D-01唯一状态在编写交接台账：用户已于2026-09-18批准全局共享主题与基础控件对齐Token V1，
并做添加番剧、追番方案、追番管理、设置四页回归。不改其他页业务、不再询问D-01，
不另建仅添加页主题。D-02～04仍待后续Stage决定，不在Stage43替用户决策。
D-02 N部隐藏勾选口径留Stage45，Stage43不改。
D-03资源样例与D-04批量完成导航留后续Stage，不顺带实现。

已发现all偏差：BatchWorkbenchView的selectable来自visibleItems，省略item_ids并不能
使服务端补隐藏项，服务端只处理items描述符。先红测筛选仅见B时all仍提交A/B，再窄修。
保留all入口，范围完整批次全部当前可确认；N部入口另存，当前语义暂保持。
可见项全选仍只改变可见勾选。弹窗数量/集合/draft/revision一致；资格变化要求重新确认。
未知结果继续原冻结body/key/revision/集合，不以新资格重算重放。

团队职责：你主导规划/独立审核，不代替开发Agent写业务代码。
A子agent使用Claude Fable模型；独立测试者固化审核最小红测；B同一修复Agent集中收口；
C长期中文发布者只在以后明确发布授权时启动/复用，不现在发布。
按AGENTS和编排文档创建fork_turns="none"干净子Agent，不复制主Agent全量对话。
给每个Agent自包含提示词：实际仓库/分支/HEAD、WP/US、精确文件、目标/非目标、
安全/契约边界、最小验证、迭代上限、停止条件和提交权限。
同包连续follow-up复用A，复审失败继续同一个B，不重开整套流程。
共享区任何时刻只有一个写入者；测试写红测前确认A结束，B结束才审核/提交。

已有能力只回归：候选局部加载/防重、draft_id+base_revision/CAS、即时字幕组、
规则1.5秒防抖、保存修改flush、原子save-confirm/部分成功/幂等/未知恢复、
悬浮Toast timer、未保存不调用safe-info；不重新立项重做。
禁止新增后端/API/OpenAPI/generated字段、数据库/worker/移动/下载能力、单项重搜、
实时进度、未保存持久化；不重排AnimeDraftEditor或做Stage44/45。
草案只用服务端能力/版本/允许patch，不回传完整Request当权威，不猜revision。
关键错误/结果/恢复留原业务区域，不能移成Toast。
RSS URL/magnet/Cookie/凭据/原始响应/绝对路径/能力/完整Request/未知字段不公开。
CONFLICT候选保持禁选，NEEDS_CONFIRMATION保持显式确认，唯一候选不自动选。

普通story只跑列明受影响Vitest/typecheck/lint；浏览器前build。
UI用项目dev-browser skill在真实Chromium验证三档桌面视口、200%缩放、长标题、
键盘/焦点、reduced-motion、空/失败/无资源/部分成功与敏感canary。
外部系统route mock、真实envelope、held route控制在途，不在handler sleep。
隔离运行数据，未知用户数据先核对，不能删除/覆盖；临时服务由启动者收尾。
只选受影响契约用例；Stage43收尾按PRD运行一次完整后端/前端/Chromium门禁。
失败先最小失败用例，无变化不重复全量；skip/Agent自述不算通过。

Ralph每条实际AC与验证满足才passes=true，并记录实际progress命令/结果、文件、风险。
本次已授权本地逐story提交：精确暂存本条代码/测试/prd/progress，
格式feat: [Story ID] - [Story Title]；不git add .，不吞他人文件。
审核状态单独记录；发现阻断继续收口，不用passes/COMPLETE替代审核。
文档准备已提交，开始时核对实际log，不能重新假报或重复提交同一整理。

每包报告实际协作/模型模式，以及开发/测试/审核/修复四类提示词一句话摘要。
全部Stage43完成后给已审核HEAD、实际验证、工作区状态和Stage44编写交接，再停止。
未获发布授权不push/PR/merge；不要自动启动下一Stage。
若遇到新增决策/契约/环境缺口，先完成不依赖的授权工作，再报告精确阻断。
```
