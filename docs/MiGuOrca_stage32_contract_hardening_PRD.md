# MiGuOrca Stage 32 PRD：后端契约固化、兼容迁移与前端交接

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage | 32 |
| 工作包 | B-D：后端契约收尾 |
| Backlog | BL-025 |
| 状态 | 已完成并归档（2026-09-10） |
| 目标分支 | `ralph/stage32-contract-hardening` |
| Ralph stories | US-247～US-256 |
| 前置 | Stage 28 B-A、Stage 29 B-B、Stage 30 B-C1、Stage 31 B-C2 已完成 |
| 并行关系 | 可与前端 Stage 33 F-A 并行；Stage 32 不修改其页面、路由或设计系统 |

## 2. 背景与阶段判断

Stage 31 已于 2026-09-10 合入远端 `main`，B-C2 的四类可靠写操作、operation v2、写后回查和
结果未知恢复已经交付。B-A～B-C2 的业务能力因此齐备，但正式追番管理前端仍缺少一个可直接消费
的最终后端交接基线：当前新旧端点并存，持久化数据跨越多个 schema 世代，公开枚举与动作语义尚未
形成单一矩阵，安全回归也分散在各 Stage 测试中。

Stage 32 可以立即开始，且不需要新增产品决策。它只完成 B-D：把已经存在的能力组织为可机器检查、
可迁移、可回退、可供后续 F-B～F-F 消费的稳定契约。任何新 Auto Bangumi 写动作、正式页面或旧
端点删除都属于范围扩张。

实时基线：

- 远端 `main` 为 Stage 31 合并提交 `df35e6f`，Stage 31 实现头为 `8e52f04`。
- Stage 31 的 US-237～US-246 全部完成并已归档。
- 前端 Stage 33 使用 US-257～US-265，已在独立 clone 开始开发；US-247～US-256 仍完整留给本阶段。
- 当前前端仍实际使用部分旧 preview、batch queue 与单番 submit 端点，尚未经历一个完整发布周期，
  因此 Stage 32 不具备删除它们的条件。

## 3. 目标

1. 建立全部 B-A～B-C2 端点的生命周期与替代关系清单，并由自动化阻止 OpenAPI、endpoint
   inventory 和实现漂移。
2. 冻结 tracking、capability、operation、handoff、错误和 `available_actions` 的严格公开语义。
3. 让 OpenAPI 与生成 TypeScript client 成为后续前端唯一 DTO 事实源，不残留关键 `Any`、手写
   interface 或不稳定 operationId。
4. 证明旧入口与新 tracking 入口共享同一权威状态，不会因混用、重放或重启重复创建外部订阅，
   也不会降级已确认成功。
5. 用脱敏 fixture 演练历史 Request、queue、AB result、TrackingRecord、ExternalMapping、operation
   v1/v2 和 migration manifest 的升级、部分失败、重试与未知 schema 拒绝。
6. 冻结认证模式、Auto Bangumi 版本、capability、tracking 状态、mapping 和未解决 operation 组合
   下的允许/拒绝矩阵。
7. 建立覆盖 API、storage、日志、OpenAPI、生成代码和浏览器可见面的统一敏感信息泄漏矩阵。
8. 给出无需删除业务数据的发布、升级与回退方案，并用离线 fixture 验证关键故障窗口。
9. 形成 F-B～F-F 可直接使用的版本化前端 handoff，明确页面动作、确认、revision、幂等和恢复顺序。

## 4. 非目标

1. 不新增 Auto Bangumi 管理动作；仍只有 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、
   `REFRESH_RSS`。
2. 不支持 3.1.18 以外版本或 API Token 模式的管理写操作，不猜测新版接口。
3. 不删除、改名或改变现有旧端点的请求/响应语义；旧端点删除必须等待真实发布周期和独立 PRD。
4. 不开发 F-B～F-G 页面，不修改 Stage 33 壳层，不制作 mock-only 追番管理页。
5. 不实现批量外部管理、后台同步 worker、数据库、多用户认证、移动端或部署向导。
6. 不实现 BL-020“已更新集数”；继续返回 `updated_episode=null` 与
   `updated_episode_status=NOT_IMPLEMENTED`。
7. 不把兼容收尾变成 tracking、storage、Web 分层或 generated client 的全量重写。
8. 不连接用户真实 MiKan、Auto Bangumi 或 qBittorrent，不对真实实例执行读写验收。
9. 不删除本地 Request、TrackingRecord、operation、审计、queue、下载任务、目录或媒体文件。

## 5. 冻结决策

### D32-01：端点生命周期只有三类

Stage 32 建立机器可检查的生命周期清单，状态固定为：

- `PRIMARY`：后续前端默认消费的组合保存、tracking、capability 与安全详情契约。
- `RECOVERY`：仍承担明确恢复职责的入口，例如保存成功但确认失败后的 Request accept；不是待删冗余。
- `COMPATIBILITY`：当前前端或历史客户端仍在使用的旧编排入口，继续可用但不再增加新业务能力。

每项必须记录 method、OpenAPI path、状态、替代端点或保留原因。清单必须覆盖
`endpoint_inventory.md` 中全部相关端点；不得把“尚未发现调用方”等同于允许删除。

### D32-02：本阶段不删除旧端点

`preview-save`、旧单番 `submit-ab`、batch `accept|queue|submit|retry|recover` 至少保持当前契约。
它们继续调用与新入口相同的 draft/tracking/submission/recovery 服务。只有满足以下全部条件后，
才能另立 PRD 讨论删除：

1. 生产发布记录证明至少经过一个完整兼容周期；
2. 前端、浏览器套件、文档与外部调用方清单不再依赖；
3. 有迁移说明、遥测或等价使用证据、版本策略和回退方案；
4. 删除范围经用户再次确认。

Stage 32 可以标明生命周期和替代关系，但不返回新的不兼容响应、不静默 301/404/410，也不借
OpenAPI 收尾隐藏仍可用端点。

### D32-03：tracking 是外部提交流程的唯一权威状态

旧 queue 和 AB result 仍是兼容投影或迁移证据。新旧入口混用时必须收敛到同一确定性
`tracking_id` 和 operation；已持久化 `ACTIVE`、`DISABLED`、`EXTERNAL_DELETED` 或成功 operation
不能被陈旧 queue、重复迁移、旧响应或回退演练降级。可能已送达外部的结果仍必须先恢复，任何
兼容入口都不能绕过未知结果保护。

### D32-04：公开 DTO、枚举与错误只能兼容扩展

冻结以下前端可见集合及其语义：

- TrackingStatus、status group、CapabilityState、probe status；
- operation kind/state、management status、target scope、recovery action；
- `available_actions[].code/style/requires_confirmation`；
- save-confirm handoff、tracking list/detail、capability、sync、revalidate、submit/retry/recover、
  四类 management result；
- 已公开的 400/401/404/409/500/502/503/504 错误分类与“结果未知返回业务态而非伪失败”的规则。

同一 `/api/v1` 内只能增加有默认值或可空、不会破坏旧客户端的字段。删除字段、收窄旧合法输入、
重命名枚举或改变 HTTP/业务态边界需要新的 API 版本或独立迁移 PRD。

### D32-05：`available_actions` 表示本地可执行性，不伪造远端能力

tracking GET 不接收凭据，因此 `available_actions` 只能表达基于本地 status、mapping 和未解决
operation 的候选动作；它不能声称当前凭据或远端版本已经支持。真正外部动作仍在同一次 POST 内用
request-scoped `ab_config` 重新探测 capability，并以服务端校验为最终权威。

前端 handoff 必须明确每个 action code 对应的 endpoint、scope、确认级别、capability key、成功态、
未知结果和恢复动作。若现有 DTO 不足以无歧义表达该边界，只允许做向后兼容的严格字段补充并同步
OpenAPI/生成客户端；不得要求前端读取 Python 常量或自行猜测状态机。

### D32-06：持久化版本不为“收尾”而无意义升级

TrackingRecord v1、ExternalMapping v1、migration manifest v1 和 TrackingOperation v1/v2 保持当前
兼容读取规则。v1 operation 只有发生合法后续写时才按既有规则输出 v2；单纯读取、启动或演练不得
原地重写。未知未来 schema 必须 fail closed，保留原文件且返回固定安全错误，不能删除、降级解析或
当成空数据重新创建。

所有迁移纯本地、可重入、逐条隔离且不访问外部系统。PARTIAL 可以在修复输入后重试，COMPLETE
不得反复全量扫描。

### D32-07：安全矩阵覆盖所有可观察面

至少把以下值注入脱敏 fixture：password、token、Cookie、Authorization、endpoint、完整 RSS/MiKan
URL、magnet、外部 ID、原始上游响应、patch 正文、本地绝对路径和 traceback。断言它们不进入：

- API 成功/失败 envelope、DTO、header 和 URL；
- TrackingRecord、operation、migration manifest、queue 与其他持久化 JSON；
- 应用日志、异常字符串和审计；
- OpenAPI example/description、生成 TypeScript client 与测试快照；
- DOM、browser storage、截图和 trace。

公开标题等业务显示字段仍需经过现有安全 serializer；测试不能通过只扫描字段名而漏掉嵌套值或
异常路径。

### D32-08：回退只回应用，不回滚或清理业务数据

发布回退流程固定为：停止新外部写 → 保存 storage 副本 → 切回上一应用版本 → 保留所有未知/新版
文件 → 必要时以前向版本重新启动并恢复。不得通过删除 operation、manifest、tracking 或 queue 来
让旧版本“正常”。对已经 `IN_PROGRESS`、`OUTCOME_UNKNOWN` 或 `RECOVERY_REQUIRED` 的操作，回退
后也不能自动重放；人工处理必须保留证据。

### D32-09：前后端并行只通过生成契约交接

Stage 32 只修改后端主 clone。最终生成的 OpenAPI、TypeScript client 和 handoff 文档由后续前端
分支同步；不得直接修改正在开发的 Stage 33 clone。F-F 正式追番管理必须等待 Stage 32 合入并重新
核对生成契约，F-A/F-B 不得假设新增业务 API。

## 6. 契约收尾范围

### 6.1 PRIMARY 契约

- draft 创建/修改、单番与批量 `save-confirm`；批量仍强制 1～36 部且逐条部分成功。
- Request `safe-info` 与保存后必要恢复入口。
- capability probe、tracking list/detail/sync。
- tracking revalidate/submit/retry/recover。
- tracking modify/set-enabled/delete-external/refresh。

保存并确认成功只进入追番管理的待提交状态；外部提交仍需用户再次显式确认。真实 MiKan 合集选择
继续是保存前提，MiGuOrca 不绕过 Auto Bangumi 创建 qBittorrent 下载。

### 6.2 COMPATIBILITY 契约

旧 preview、单番提交和 batch queue 编排端点保持可调用、保持 strict schema 和安全响应。兼容性
测试必须覆盖：

1. 先旧后新、先新后旧和同键重放；
2. 单番与批量对同一 Request 的收敛；
3. 外部调用前持久化失败、调用后本地写失败和响应丢失；
4. 成功投影不降级、未知结果不盲重试；
5. 兼容 queue 更新失败不覆盖 tracking 权威结果。

### 6.3 前端 handoff

handoff 至少包含：

- 页面用例 → endpoint/operationId → 生成请求/响应类型；
- 状态/动作/确认/幂等/revision/capability/恢复矩阵；
- 列表刷新、409 revision 冲突、HTTP 失败、业务结果未知和人工恢复流程；
- 哪些值只允许在组件局部内存与单次 POST body 中出现；
- F-B/F-C/F-D/F-E 可消费的 draft/save-confirm/safe-info/tracking 子集；
- F-F 必须等待本阶段合入后才能消费的 sync/management 子集；
- `updated_episode` 占位语义与不得推断集数的约束；
- 旧端点的兼容期状态，禁止新页面继续依赖它们。

## 7. User Stories

### US-247：冻结端点生命周期与 B-D 基线

建立 B-A～B-C2 端点、调用方、生命周期、替代关系和数据权威矩阵；提供机器可检查的清单并校验
实现路由、endpoint inventory 与 OpenAPI 全覆盖。明确没有端点在 Stage 32 删除。

### US-248：冻结公开 DTO、枚举、动作与错误语义

逐项审计 tracking/capability/operation/handoff DTO 和 HTTP/业务错误边界，消除关键公开结构中的
无类型逃逸或歧义默认值；固定 `available_actions` 的本地可执行语义及每类动作的远端 capability
前提。只允许兼容扩展。

### US-249：固化 OpenAPI 与生成 TypeScript 契约

同步确定性 OpenAPI、稳定 operationId、endpoint inventory 与生成 client；增加编译级消费 fixture，
证明 F-B～F-F 所需请求/响应、nullable 字段、枚举和错误均可只依赖 generated types 表达，且 drift
check 能拦截手写或过期契约。

### US-250：完成旧入口与 tracking 权威状态兼容演练

用脱敏 fixture 覆盖旧 preview/accept/submit/batch queue 与新 save-confirm/tracking 入口的混合顺序、
重放、重启、并发和投影写失败。证明同一 Request/幂等意图不重复创建，旧投影不降级权威终态。

### US-251：完成持久化 schema 与历史迁移演练

演练历史 Request、queue、AB result、TrackingRecord v1、ExternalMapping v1、operation v1/v2 和 manifest
的首次迁移、PARTIAL 修复重试、COMPLETE 重启、损坏单条及未知未来 schema。读取不得隐式改写，
失败不得访问外部、删除原文件或泄漏内容。

### US-252：冻结 capability 降级与服务端动作矩阵

用表驱动测试覆盖 password/API Token、精确 3.1.18/其他或未知版本、探测成功/部分/失败、tracking
状态、mapping、scope 和未解决 operation 的组合。客户端隐藏不是安全边界；每个写 endpoint 必须
独立 fail closed，并保持 `file=false`、read-before-write 与未知结果恢复。

### US-253：建立端到端敏感信息泄漏矩阵

把 D32-07 的敏感 canary 注入成功、校验失败、认证失败、timeout、5xx、非 JSON、持久化失败、迁移
损坏和写后回查失败路径；递归检查 API/storage/log/OpenAPI/generated client，并对现有页面进行最小
真实 Chromium 可见面检查。测试资产本身只使用明显虚构值且不得保存真实凭据。

### US-254：完成发布回退与故障窗口演练

建立版本升级/回退 runbook，并用离线临时 storage 演练调用前失败、外部可能已执行、operation 已
终态但 record 未更新、queue 投影失败、迁移中断和再次前向启动。证明回退不清理业务数据、不盲目
重试外部写且可由现有 recover/VERIFY_EXTERNAL 收敛。

### US-255：交付版本化前端契约 handoff

形成 F-B～F-F 页面用例、generated type、endpoint、状态、动作、确认、revision、幂等、capability、
错误与恢复矩阵；加入最小 TypeScript 消费测试，禁止手写 DTO。明确 F-F 等待 Stage 32 合入，Stage
33 的 QueueView 兼容挂载不等于正式追番管理完成。

### US-256：完成最终门禁、文档同步与归档

运行一次完整后端、OpenAPI、前端生成契约及真实 Chromium 门禁；失败后只复跑最小失败用例。
同步 README、主 PRD、架构、M01/M09/M10/M11/M12/M13、backlog、future stages、工作目标和候选
支撑 PRD，记录兼容/迁移/安全/回退证据，归档 Ralph 状态并冻结后续前端 handoff。

## 8. 验收矩阵

| 风险 | 必须证明 |
| --- | --- |
| 契约漂移 | route、lifecycle 清单、endpoint inventory、OpenAPI、generated TS 一致 |
| DTO 漂移 | 关键响应 strict；枚举、nullable、默认值和 error shape 有 golden/编译测试 |
| 旧入口分叉 | 新旧路径落到同一 tracking/operation，成功不降级、未知不重放 |
| 历史迁移 | 首次、PARTIAL、COMPLETE、损坏、未知 schema 均纯本地且可重入 |
| 能力误判 | 非 password、非 3.1.18、探测失败和 scope 不匹配均服务端拒绝写入 |
| 删除风险 | 所有番剧停用/删除保持 `file=false`，本地数据和媒体零删除 |
| 敏感泄漏 | D32-07 每类 canary 对全部可观察面递归检查 |
| 发布回退 | 故障窗口保留证据和数据，不用清理状态换取重试 |
| 前端可消费 | 仅 generated types 即可表达 F-B～F-F 所需流程，无手写 DTO |

## 9. 迭代与成本控制

1. Ralph 每轮只完成一个最高优先级未通过 story，并产生一个独立、可回退提交。
2. US-247～US-255 只运行受影响的定向测试、Ruff/compileall 和必要 OpenAPI/TypeScript 检查。
3. 只有 US-256 运行一次完整非浏览器、前端和 Chromium 门禁；失败后先跑最小失败用例，代码无
   变化时禁止重复全量。
4. 迁移、兼容和安全测试使用临时目录与 recording fake，不连接真实外部服务。
5. 每个 story 优先扩展已有测试模块；不为矩阵复制整套巨型 fixture，不扫描无关历史归档。
6. 预计 10 个实现迭代，最多允许 2 个修复迭代；超过 12 轮仍未完成时停止并报告剩余 story 与阻塞。
7. 若发现需要新增管理动作、删除旧端点、改变 API 版本或修改正式前端页面，立即停止并请求用户确认。

## 10. 最终门禁

```bash
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run migu-orca-openapi --check
uv run pytest -q -m "not browser"
cd frontend
npm run api:check
npm run typecheck
npm run lint
npm run test:run
npm run build
cd ..
uv run pytest tests/browser/ -q
git diff --check
```

不得使用真实 Auto Bangumi、MiKan 或 qBittorrent 作为门禁。若环境无法运行 Chromium，Stage 32
不能仅凭静态测试宣告完成，必须记录阻塞并在可用环境补跑。

本次最终门禁实际结果：非浏览器测试 1,630 passed、前端 unit tests 265 passed、真实 Chromium 测试
134 passed；compileall、Ruff、OpenAPI drift、typecheck、lint、build 与 diff check 均通过。

## 11. 完成定义

1. US-247～US-256 全部 `passes=true`，每个 story 有独立提交和验证记录。
2. 生命周期清单覆盖所有目标端点，旧端点无删除且兼容策略可由自动化检查。
3. tracking/capability/operation/handoff/错误契约与 generated client 无漂移、无关键无类型逃逸。
4. 新旧入口、历史迁移、版本降级、故障窗口与回退演练均证明不会重复外部写或降级成功状态。
5. 精确 3.1.18 password 之外的管理写继续 fail closed；所有删除路径保持 `file=false` 和本地保留。
6. API、storage、日志、OpenAPI、生成代码、DOM、截图和 trace 通过统一泄漏矩阵。
7. F-B～F-F handoff 明确、版本化且只依赖 OpenAPI/generated types；F-F 可以在本阶段合入后另行规划。
8. 正式追番管理页面、BL-020、旧端点删除和任何新增外部动作仍未被实现或暗示完成。

## 12. 后续 handoff

Stage 32 完成并合入后，后端 B-A～B-D 才算整体闭环。前端可以继续按实际合并状态评审 F-B“共享
审核核心”，之后推进 F-C 单番、F-D 批量和 F-E 追番方案；F-F“正式追番管理”必须以本阶段最终
handoff 和生成契约为基线单独编写 PRD。Stage 32 不预先分配后续 Stage 编号，也不把 F-F 工作
塞入本分支。
