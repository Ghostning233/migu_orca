# MiGuOrca Stage 31 PRD：Auto Bangumi 可靠写管理

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | Stage 31 PRD：Auto Bangumi 可靠写管理 |
| 文档类型 | 执行 PRD / 前端体验重构 B-C2 |
| 当前状态 | 已规划，待开发（US-237～US-246） |
| 创建日期 | 2026-09-09 |
| Backlog | BL-025（B-C2） |
| 优先级 | P0 |
| 前置条件 | Stage 30 已完成并合入 `main`；3.1.18 只读 adapter、capability、ExternalMapping v1 与 tracking sync 已冻结 |
| 开发分支 | `ralph/stage31-ab-write-management` |
| Ralph stories | US-237～US-246 |

## 2. 背景与阶段边界

Stage 30 已能安全读取 Auto Bangumi 3.1.18、对账本地与外部追番并执行只读核验，但正式“追番
管理”仍不能修改、启停、刷新或删除外部对象。Stage 31 承接 B-C2，只补齐可靠外部写能力；它
不开发页面，也不承担最终 B-D 契约清理。

Auto Bangumi 3.1.18 存在以 GET/DELETE 表达状态变更的历史接口，番剧删除和停用还暴露 `file`
参数。MiGuOrca 不能把这些上游细节直接交给浏览器，所有写动作必须经过本地 tracking ID、显式
确认、能力探测、幂等操作、revision CAS、写后只读核验和结果未知恢复。

## 3. 固定事实源与上游路由

以 Auto Bangumi 官方仓库 `3.1.18` tag 为唯一写契约事实源：

- 番剧修改：`PATCH /api/v1/bangumi/update/{bangumi_id}`，body 为 `BangumiUpdate`。
- 番剧启用：`GET /api/v1/bangumi/enable/{bangumi_id}`。
- 番剧停用：`DELETE /api/v1/bangumi/disable/{bangumi_id}?file=false`。
- 番剧删除：`DELETE /api/v1/bangumi/delete/{bangumi_id}?file=false`。
- RSS 修改：`PATCH /api/v1/rss/update/{rss_id}`，body 为 `RSSUpdate`。
- RSS 启用：`POST /api/v1/rss/enable/many`，body 只传本条 tracking 已映射的 RSS ID 列表。
- RSS 停用：`PATCH /api/v1/rss/disable/{rss_id}`。
- RSS 删除：`DELETE /api/v1/rss/delete/{rss_id}`。
- RSS 刷新：`GET /api/v1/rss/refresh/{rss_id}`。

事实源：

- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/api/bangumi.py>
- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/api/rss.py>
- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/models/bangumi.py>
- <https://github.com/EstrellaXD/Auto_Bangumi/blob/3.1.18/backend/src/module/models/rss.py>

所有自动化测试使用 recording fake transport，不得访问用户真实实例。adapter 只允许上述精确
method/path；不得提供接收任意 URL、method、query 或上游 body 的通用代理。

## 4. 目标

1. 把 3.1.18 已核实的番剧/RSS 写能力从 `UNKNOWN` 提升为 `SUPPORTED`，其他版本继续 fail closed。
2. 以本地 `tracking_id` 定位外部对象，浏览器永远不提交或接收 Auto Bangumi 原始 ID。
3. 提供 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、`REFRESH_RSS` 四类可靠操作。
4. 每次外部写入前持久化幂等绑定和进行中边界，禁止重放导致二次调用。
5. 2xx 响应后执行只读回查；只有已验证的外部状态才能更新本地安全投影。
6. 对 timeout、连接中断、5xx、响应无法识别和写后回查失败保守进入结果未知，不允许盲重试。
7. 扩展 `VERIFY_EXTERNAL`，按当前管理操作的目标指纹核验成功、失败或仍需人工处理。
8. 删除外部对象时永久强制 `file=false`，并保留本地 Request、TrackingRecord、审计、下载任务和媒体。
9. 为后续 B-D 和 F-F“追番管理”冻结 strict API/DTO、错误码和安全动作摘要。

## 5. 非目标

1. 不实现任何正式 Web 页面、导航、弹窗或视觉组件。
2. 不支持 Auto Bangumi 3.1.18 以外版本或 API Token 模式的管理写操作。
3. 不实现批量外部删除、批量 tracking 管理 API 或后台定时同步。
4. 不允许浏览器传 Auto Bangumi ID、RSS URL、原始 filter 表达式、save_path、poster URL 或 `file`。
5. 不提供修改 RSS URL；RSS URL 只可在 request-scoped 上游快照中原样保留。
6. 不直接操作 qBittorrent，不删除种子、下载任务、媒体文件或本地目录。
7. 不删除本地 Request、TrackingRecord、operation、审计和兼容 queue 投影。
8. 不把凭据、endpoint、Cookie、原始请求/响应、完整 URL、标题正文、路径或 traceback 写入 operation。
9. 不实现 BL-020“已更新集数”。
10. 不删除 Stage 29/30 的旧入口；兼容删除属于 Stage 32 B-D。

## 6. 核心决策

| 编号 | 决策 | 说明 |
| --- | --- | --- |
| D31-01 | 只支持精确 3.1.18 password adapter | 版本、认证或能力未知时拒绝写入，不猜测兼容。 |
| D31-02 | 四类 operation kind | 固定为 `MODIFY`、`SET_ENABLED`、`DELETE_EXTERNAL`、`REFRESH_RSS`，不得复用 `SUBMIT` 假装管理操作。 |
| D31-03 | 目标只有 `SUBSCRIPTION` 与 `ASSOCIATED_RSS` | API 用本地 tracking ID 和固定 scope；不暴露外部 ID。RSS scope 只覆盖操作开始时该 tracking mapping 内的 ID 集合。 |
| D31-04 | 先读再写 | 每次写入先重新读取 capability 与目标，校验 mapping 仍唯一；未知、缺失或歧义时不调用写接口。 |
| D31-05 | 修改只接受业务白名单 | 番剧 patch 只允许 title/season/subtitle_group/filter_rule/offset/expected_folder_name；RSS patch 只允许 name/aggregate/parser。adapter 从最新上游对象补齐 3.1.18 所需 body。 |
| D31-06 | RSS URL 永远不由浏览器修改 | RSSUpdate 需要完整字段时，只能从当前请求内已验证快照原样保留 URL。 |
| D31-07 | `file=false` 为不可绕过常量 | 番剧 disable/delete 的 query 由 adapter 固定生成；schema 明确拒绝 `file` 及未知字段。 |
| D31-08 | 幂等绑定先于外部写 | operation `PREPARED → IN_PROGRESS` 成功持久化后才能调用一次外部接口。 |
| D31-09 | 写响应不等于最终成功 | 明确失败进入 FAILED；2xx 后必须只读回查并匹配目标投影，才能 SUCCEEDED。 |
| D31-10 | 未知结果禁止新写重试 | 网络/5xx/未知响应/回查失败进入 OUTCOME_UNKNOWN 或 RECOVERY_REQUIRED，只能 `VERIFY_EXTERNAL` 或人工恢复。 |
| D31-11 | 操作意图只保存摘要 | operation 保存 target scope、先前状态和预期外部投影摘要，不保存 patch、标题、URL、ID 或凭据。 |
| D31-12 | 部分 RSS 结果保守处理 | ASSOCIATED_RSS 多对象逐条执行；只要任一对象未知或写后无法完整回查，整体不得宣告成功。 |
| D31-13 | 删除仅改变外部投影 | 番剧删除成功转 `EXTERNAL_DELETED`；RSS 删除只更新 mapping，不删除本地权威对象。 |
| D31-14 | refresh 的未知结果不可推断 | 刷新成功响应可终态化；超时无法由静态快照证明是否执行，进入人工恢复而非重复刷新。 |

## 7. 管理操作模型

### 7.1 TrackingOperation v2

Stage 31 将 operation schema 升级为 v2，同时兼容读取 Stage 29/30 的 v1 SUBMIT 记录。保留现有
确定性 operation ID 和状态机，增加严格可选字段：

```text
target_scope: SUBSCRIPTION | ASSOCIATED_RSS | null
previous_tracking_status: 已知 TrackingStatus | null
expected_external_fingerprint: sha256 digest | null
```

- `SUBMIT` v1/v2 语义不变；管理 operation 必须写上述三项中的适用字段。
- 现有 `request_fingerprint` 对管理操作保存规范化动作输入的 SHA-256 绑定摘要；不保存输入正文。
- 同一 idempotency key 只有在 tracking_id、operation kind、expected_revision、scope 和全部摘要一致时重放。
- v1 读取不得原地改写；发生合法后续写时才按显式迁移规则输出 v2。
- operation 仍不得保存外部 ID、patch、标题、路径、URL、凭据或原始错误。

### 7.2 操作结果分类

```text
PREPARED -> IN_PROGRESS -> SUCCEEDED
                        -> FAILED
                        -> OUTCOME_UNKNOWN
                        -> RECOVERY_REQUIRED
```

- 认证、配置、capability、校验和明确 4xx/406 是确定失败；若外部尚未调用，record 不进入未知状态。
- timeout、连接中断、5xx、非 JSON/未知 shape 是 `OUTCOME_UNKNOWN`。
- 外部结果已确认但本地 CAS/结果持久化失败是 `RECOVERY_REQUIRED`。
- 相同 key 的终态重放只返回持久化安全结果，不再次访问外部。
- 不同 key 在当前 operation 未解决时返回 409，不能绕过恢复保护。

### 7.3 安全目标摘要

外部预期指纹只能由规范化安全投影计算：

- MODIFY：允许字段的规范化目标值摘要。
- SET_ENABLED：scope + 目标布尔值摘要。
- DELETE_EXTERNAL：scope + “目标应不存在”的摘要。
- REFRESH_RSS：无可观测持久目标，只保存 scope；未知结果直接要求人工处理。

摘要用于 `VERIFY_EXTERNAL` 比较，不得被 API 当作外部 ID 或调试数据返回。

## 8. 写流程

所有动作遵循同一顺序：

1. 校验 `confirm=true`、opaque idempotency key、expected revision 和 strict payload。
2. 加载 TrackingRecord；拒绝无 mapping、不允许当前状态或尚未解决的 operation。
3. 使用 request-scoped `ab_config` 探测 3.1.18 capability，并读取目标最新快照。
4. 由 mapping 在服务端解析 SUBSCRIPTION 或 ASSOCIATED_RSS；0 个、歧义或漂移均在写前失败。
5. 计算规范化动作摘要和预期外部指纹，绑定 PREPARED operation。
6. CAS 设置 `current_operation_id`，再把 operation CAS 为 IN_PROGRESS。
7. 通过 action-specific adapter 最多调用一次外部写接口。
8. 对可验证动作执行只读回查；分类外部结果。
9. 先持久化安全 operation 结果，再用一次 TrackingRecord CAS 更新 mapping/status/audit/revision。
10. 返回统一安全结果；任何未知结果都不给出“可重试写入”。

并发相同 key 最多一次外部写；并发不同 key 只有一个能通过 record CAS。进程重启后根据持久化
operation 恢复，不通过“时间过去了”推断成功或失败。

## 9. 动作语义

### 9.1 MODIFY

`POST /api/v1/tracking/items/{tracking_id}/modify`

`scope=SUBSCRIPTION` patch 允许 title、season、subtitle_group、filter_rule、offset、
expected_folder_name；`scope=ASSOCIATED_RSS` patch 只允许 name、aggregate、parser。空 patch、混用
scope 字段、绝对/穿越路径和未知字段均 400。原始 filter、RSS URL 与完整上游 body 不由浏览器提供。

### 9.2 SET_ENABLED

`POST /api/v1/tracking/items/{tracking_id}/set-enabled`

请求含 scope 与严格布尔 enabled。SUBSCRIPTION 停用固定 `file=false`；ASSOCIATED_RSS 对操作启动
时映射的 RSS 集合执行，空集合在写前失败。番剧停用目标状态为 DISABLED，重新启用为 ACTIVE。

### 9.3 DELETE_EXTERNAL

`POST /api/v1/tracking/items/{tracking_id}/delete-external`

仅允许单条 tracking。schema 不存在 file 字段，SUBSCRIPTION adapter 永远生成 `file=false`。
ASSOCIATED_RSS 只逐条删除该 mapping 中的 RSS，不调用 many delete。本地数据和媒体始终保留。

### 9.4 REFRESH_RSS

`POST /api/v1/tracking/items/{tracking_id}/refresh`

只对 ASSOCIATED_RSS 生效，只调用单 RSS `/refresh/{rss_id}`，禁止 `/refresh/all`。任一超时或未知
响应都进入结果未知且不自动再次刷新。

## 10. VERIFY_EXTERNAL 扩展

- MODIFY：重新读取并比较预期安全投影摘要；一致为成功。
- SET_ENABLED：读取对应 scope 的 enabled/deleted 状态；全部一致为成功。
- DELETE_EXTERNAL：只有完整验证列表确认目标全部不存在才成功。
- REFRESH_RSS：没有稳定可观察结果；未知写保持 RECOVERY_REQUIRED，允许人工标记但不自动重试。
- 读失败、版本未知、映射漂移、多对象部分匹配均保持 RECOVERY_REQUIRED。

核验必须终态化原 operation，不能创建第二个管理 operation。Stage 29 SUBMIT 与 Stage 30 普通只读
核验行为保持兼容。

## 11. API 请求与响应

四个 endpoint 共用严格字段：confirm=true、idempotency_key、expected_revision、request-scoped
ab_config，并按动作增加 scope、enabled 或 patch。统一结果只返回：

```text
tracking: TrackingItemDTO
operation: safe TrackingOperation summary
action: MODIFY | SET_ENABLED | DELETE_EXTERNAL | REFRESH_RSS
management_status: SUCCEEDED | FAILED | VERIFYING_EXTERNAL | RECOVERY_REQUIRED
needs_manual: bool
safe_message: 固定中文
```

不得返回 external/RSS ID、URL、patch、expected fingerprint、上游 method/path/body、凭据或原始错误。
外部写可能发生后的未知结果使用 HTTP 200 + 明确状态；校验、revision、状态、capability 和幂等冲突
使用稳定 400/404/409。

## 12. 错误与审计

| error_type | HTTP | 场景 |
| --- | --- | --- |
| `tracking_management_confirmation_required` | 400 | confirm 缺失或不是 true |
| `tracking_management_target_missing` | 409 | mapping 无目标或关联 RSS 为空 |
| `tracking_management_state_conflict` | 409 | 当前状态或未解决 operation 禁止新写 |
| `tracking_management_capability_unknown` | 409 | 版本/动作能力未验证 |
| `tracking_management_patch_invalid` | 400 | 空 patch、scope 混用或危险字段 |
| `tracking_management_outcome_unknown` | 业务结果 | 外部结果无法确定，禁止新写重试 |

新增审计至少覆盖管理开始、成功、明确失败、结果未知、恢复成功/失败，只保存 kind、scope、固定
reason/safe_message、operation ID 和 revision。

## 13. 模块边界

```text
src/ab_engine/controllers/ab_management_client.py     # action-specific 3.1.18 写 adapter
src/ab_engine/controllers/management_outcome.py       # 纯结果分类/目标摘要
src/tracking_engine/models/operation.py                # v2 与四类 operation kind
src/tracking_engine/controllers/manage_external.py    # 纯状态/动作决策
src/apps/migu_orca_web/tracking_management_service.py # credential + storage + adapter 编排
src/apps/migu_orca_web/routes_tracking.py
src/apps/migu_orca_web/schemas.py
src/apps/migu_orca_web/api_contract.py
src/apps/migu_orca_web/tracking_serializers.py
src/apps/migu_orca_web/openapi_gen.py
```

route 只解析 strict schema；adapter 不 import web/storage；纯 controller 不访问网络；service 是唯一
能同时接触临时凭据、repository 和 adapter 的层。前端不得手写新 DTO。

## 14. Ralph User Stories

### US-237：冻结管理 operation v2 与纯动作契约

扩展 operation kind、v2 可选绑定字段、v1 兼容读取、动作输入/目标投影摘要与纯结果分类。覆盖
确定性 ID、同键同绑定重放、跨 kind/scope/摘要冲突、schema 迁移和敏感值拒绝。

### US-238：实现 3.1.18 番剧写 adapter 与 capability

为 MODIFY/SET_ENABLED/DELETE_EXTERNAL 实现精确 method/path、一次会话、固定 `file=false` 和有界
响应解析；补 recording transport。只有 password + 3.1.18 对应 capability 为 SUPPORTED。

### US-239：实现 3.1.18 RSS 写 adapter 与 capability

实现 RSS update、单集合 enable、逐条 disable/delete/refresh；禁止全局 refresh、many delete 和任意
代理路径。测试 method/path/body、部分失败分类、临时 URL 保留与响应脱敏。

### US-240：实现服务端目标解析与安全 patch 构造

用 mapping 解析 SUBSCRIPTION/ASSOCIATED_RSS，构造规范化白名单 patch 和动作摘要；完整上游 body
只由当前快照补齐。覆盖空/歧义/漂移、scope 混用、URL/file/路径注入拒绝。

### US-241：建立可靠管理操作协调器

实现 confirm/revision/capability/read-before-write、PREPARED/IN_PROGRESS、record CAS、同键重放和
不同键并发保护的通用骨架。用注入 adapter 的离线测试证明每个 operation 最多一次写调用。

### US-242：接入 MODIFY 与 SET_ENABLED

实现番剧/RSS 修改和启停，2xx 后只读回查，更新安全 mapping/status/audit；覆盖成功、明确失败、
timeout、回查失败、部分 RSS、重放和本地持久化失败。

### US-243：接入 DELETE_EXTERNAL 与 REFRESH_RSS

实现单 tracking 外部删除和关联 RSS 单项刷新；番剧 disable/delete 永远 `file=false`，不提供全局
刷新或批量删除。覆盖本地对象保留、媒体零调用、部分删除、未知刷新与审计。

### US-244：扩展 VERIFY_EXTERNAL 管理操作恢复

按 operation kind/scope/预期摘要回查并终态化原 operation；refresh 未知保持人工恢复。保持 SUBMIT
与 Stage 30 普通核验兼容，覆盖进程重启、映射漂移、缺失、歧义和能力降级。

### US-245：提供管理 API 与安全 DTO

新增四个 POST endpoint、strict payload/result DTO、available action 摘要、HTTP/error 映射和递归
泄漏测试；同步 endpoint inventory、OpenAPI JSON、生成 TypeScript client 与 operation fixture。

### US-246：完成 Stage 31 回归、文档与归档

用 recording fake 演练四类动作的成功/失败/未知/恢复/重放/并发与删除媒体保护；执行最终完整门禁，
同步 README/架构/模块 PRD/backlog/future stages，冻结 Stage 32 B-D handoff 并归档 prd/progress。

## 15. 验收策略与成本边界

1. US-237～US-245 每轮只运行受影响的定向测试、Ruff/compileall 与必要 OpenAPI/前端生成检查。
2. 只有 US-246 运行一次完整非浏览器、前端和 Chromium 门禁；不得每个 story 重复全套回归。
3. 所有外部测试必须使用 recording fake，断言写调用次数、顺序、method/path/body 与 `file=false`。
4. fault injection 覆盖 operation bind/CAS、record CAS、timeout、connection、5xx、未知响应和回查失败。
5. 每个 story 单独提交并更新 Ralph 状态；未完成验收不得把 passes 改为 true。
6. Stage 31 预计 10 次 story 迭代；超过 12 次仍未完成时停止循环，报告剩余 story 与阻塞，不进行
   无界探索或反复全仓测试。

最终门禁：

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

## 16. Stage 32 B-D Handoff

Stage 31 完成后，Stage 32 只负责最终契约收尾：兼容/迁移演练、旧端点处置、所有操作 DTO 与前端
生成类型冻结、跨版本 capability 降级、安全泄漏矩阵、真实页面所需 handoff 和发布回退方案。
Stage 32 不再补写新的外部管理动作，也不开发 F-F 页面。

## 17. 完成标准

1. US-237～US-246 全部通过、独立提交并归档。
2. 四类管理动作只有在 3.1.18 capability VERIFIED/SUPPORTED 时执行。
3. 相同幂等键最多一次外部写，未知结果不能通过新 key 盲重试。
4. 每个可验证写操作完成写后只读回查，安全投影和 operation/record 状态一致。
5. 任何番剧停用/删除调用都固定 `file=false`，代码和 recording test 双重证明。
6. 本地 Request、TrackingRecord、审计、下载任务和媒体在所有删除路径中保留。
7. API/storage/log/test fixture 不含凭据、URL、外部 ID、patch、原始响应和绝对路径。
8. OpenAPI、endpoint inventory、生成客户端与代码无漂移。
9. 正式追番管理页面仍未实现；Stage 32 handoff 清楚且无隐含新增动作。
