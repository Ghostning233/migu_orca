# MiGuOrca Stage 39 PRD：部署连接配置与设置发布收尾

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Stage / 工作包 | 39；新增后端前置支撑 + 扩展 F-G |
| Backlog | BL-025 后端新增支撑、BL-026 设置与发布收尾 |
| 状态 | US-318～US-340 已实现；US-338～US-340 完成候选验收记录，等待独立审核；未发布 |
| 决策日期 | 2026-09-13 |
| 核对基线 | 本地 HEAD `c294ee4`；本地 `origin/main=c9a35d9`，两者文件树一致；未刷新远端或验证最新 CI |
| 当前工作分支 | `docs/agent-workflow-guidance`，工作区初始干净；不在此分支启动 Ralph |
| 目标开发分支 | `ralph/stage39-deployment-settings`，仅指定名称，尚未创建 |
| Ralph stories | US-318～US-340，23 条；US-318～US-337 已完成，US-338～US-340 候选验收中 |
| 待启动 JSON | [Stage 39 计划](../scripts/ralph/plans/stage39-deployment-settings/prd.json) |
| 前置 | Stage 28～38 已交付的草案、tracking、AB adapter、generated API 与设计系统 |
| 验收基线 | [交互规格](design/frontend-ux-interaction-spec.md)、[设计 Token](design/frontend-ux-design-tokens-v1.md)、[Stage 38 记录](MiGuOrca_stage38_tracking_management_PRD.md) |

本轮仅编写文档与待启动计划，不切分支、不更新活动 Ralph 状态、不执行实现、测试、Git 提交或发布。
`scripts/ralph/prd.json` / `progress.txt` 仍保留 Stage 38，启动前须按[计划加载说明](../scripts/ralph/plans/README.md)核对并归档。
PRD 准备就绪不代表任意批次或团队已获启动授权。

## 2. 产品决策与评审结论

用户在 F-G 评审后的本次讨论明确确认：

1. 项目是本地部署的订阅编排工作台；AB 地址、账号与凭据应保存在部署端，跨页面、浏览器刷新与服务重启保留。
2. 第一阶段只持久化 Auto Bangumi。qBittorrent 配置及其独立连接测试不服务当前目标，删除相关前后端代码，不接管下载业务。
3. MiKan 搜索由 MiGuOrca 封装。普通用户只输入番名、人工选择真实合集，不配置 MiKan endpoint、timeout、Cookie 或账号。
4. 不保留无用兼容实现；已有正式替代的旧端点、独占 DTO 与执行编排在核对引用后删除。历史数据不因代码退役被删除。
5. 不再使用全局连接输入弹窗。设置统一管理 AB 连接，顶部状态入口进入设置；追番页仅做明确的业务动作。
6. 外部同步/提交/管理仍须显式触发；配置保存、测试、导航或页面初始化都不是外部写授权。

因此此前的“凭据离页销毁”“全部秘密不得在任何服务端位置持久化”“所有旧端点必须保留”
不再是本阶段产品目标。例外仅限专用 AB 配置；其余敏感输出、业务存储、幂等/恢复与媒体保留规则不变。
已完成 Stage 的历史验收不重写；旧规格有冲突时以本 PRD 的新目标为准，但当前代码仍是旧实现。

### 2.1 只读核对发现

- qB 唯一对外业务调用是 `routes_connections.py` 的连接测试，`pyproject.toml` 单独打包 qB engine；主订阅流程没有生产依赖。
- `default_mikan_config()` 已提供真实搜索默认值；正式前端不提交搜索 endpoint，但 Web schema 仍接受 `mikan_config`，Request create 还默认 static-fixture。
- 旧单番 `submit-ab` 和旧批量队列仍存在直接提交编排及事后 tracking 投影；不能以历史文档宣称它们已经统一经过 operation。
- `QueueView/queueWorkbench` 已退出默认运行时，旧 batch_id 定位桥仍调用 queue API。
- 设置保存开关已无正式添加流程消费者；设置与追番仍持有临时敏感输入。
- 当前 operation 与外部映射没有部署连接归属 ref；单纯持久化秘密而不补绑定会扩大跨 AB 实例误写风险。
- 现有历史 migration 仍读取旧 queue 文件，因此必要的只读解析器不是“无用代码”，不得为了清空目录破坏数据可读性。
- 原始配置、真实端点、秘密、运行数据均未读取；本轮仅核对代码、契约与记录，没有运行任何门禁。

评审结论：本次产品疑问已经得到用户决策，可编写开发 PRD。实现必须先交付并独立审核新增后端支撑，
不能把此项当作纯前端收尾。不存在现成的部署凭据保存能力，也不把已完成 Stage 38 的测试数量当作本阶段通过证据。

## 3. 目标与非目标

目标是“一次配置 AB → 输入番名 → 选择真实合集 → 审核并保存确认 → 逐条显式提交/管理”。
未配置或 AB 不在线仍可完成搜索、本地方案编辑、保存与纯本地复核。

不在范围内：qB 下载/文件查询/任务接管、MiKan 用户配置、真实 LLM provider、新版 Token 写能力、移动端、
数据库/多 worker/后台轮询、服务端批量现场恢复、更新集数猜测、系统密钥环/通用加密系统、
多用户权限、公网直接部署、发布安装包。保留精确 AB 3.1.18 password 管理能力边界。

CLI 的显式参数、离线 fixture 与仍被使用的 adapter 是另一信任边界，不因 Web 退役而删除。
本阶段不把 CLI 改成无需配置的真实搜索默认入口，不扩展其秘密持久化。
备份业务方案不应顺带复制秘密；部署配置单独备份时明确按秘密文件保护，不能宣称它天然加密。

## 4. 冻结设计

### D39-01：一个部署、一个 AB 配置

- AB 配置属于整个服务部署，不属于 storage profile、Request 或浏览器。profile 改变不复制或切换 AB 凭据。
- `MIGU_ORCA_WEB_CONFIG_ROOT` 只由服务端指定，默认 `.migu_orca/config`。专用文件 `autobangumi.json` 不放在任何业务 profile 下。
- 沿用现有 JSON repository 技术，但新增专用读写入口与秘密模型；不建立通用 system-config engine。
- 配置文件存储的是受限权限的秘密，不提供加密承诺。POSIX 目录 0700、文件与临时文件 0600。
  非 POSIX/不支持权限保证的部署不能默默保存，需安全失败并记录支持限制；Windows 凭据设施不在本阶段。
- 路径/链接由部署方指定且必须验证；拒绝配置/父路径中的不受信符号链接、权限扩大与不安全读取。
  写入用权限受限的同目录临时文件原子替换；错误中不回显任何路径、原始内容或秘密。
- 删除配置会移除秘密，只保留不含秘密的 revision tombstone。不清除业务文件、媒体或外部订阅。

### D39-02：配置版本与更换语义

- `configuration_revision` 是部署配置的单调整数，初始未配置为 0；成功保存/删除各递增一次。
  `connection_ref` 是每次成功保存重新生成的随机 UUID opaque 标识，不从 endpoint/username/password/Token 派生。
- 任意保存都视为新的不可变配置版本，包括同地址换密码。成功保存重置探测状态，并使旧 ref 的能力摘要和外部管理映射失效。
  用户需重新探测、必要时确认只读同步；不会自动重新创建订阅。
- PUT 是完整替换：必须完整输入新地址和秘密；不存在“空密码沿用”或从服务端回读秘密。
- 配置 CAS 防多页面覆盖；服务端当前进程的外部请求取得 ref/revision 快照和 lease。
  在途请求期间配置修改立即冲突，所有结束路径释放 lease；不长时间阻塞、不靠浏览器按钮充当锁。
- 未决操作不阻止用户在请求结束后清除或更换配置，但原操作 ref 与恢复锁不得被改写；原秘密不额外保留在 operation。
  原 ref 不再可解析时只允许本地证据或人工恢复，禁止拿新连接当作原连接进行核验/重放。

### D39-03：唯一允许的秘密持久化例外

| 位置 | 允许内容 |
| --- | --- |
| 专用部署配置与其受控原子写临时文件 | AB 服务根、认证方式、账号、密码或 Token |
| 设置的受控编辑表单、单次配置 PUT body | 用户本次输入；不回读已保存秘密 |
| 服务端 adapter 的请求快照 | 本次调用所需配置，生命周期限于请求 |
| 普通公开 DTO / 浏览器内存 store | 安全摘要、opaque ref/revision、capability |
| Request/history/tracking/operation/queue/migration、普通业务备份 | 非敏感模型；operation/mapping 仅允许随机连接 ref |
| URL/history、浏览器持久存储、通知/日志、其余 DOM/属性、截图/trace、Git | 不允许秘密、地址、账号、原始响应或秘密摘要 |

`connection_ref` 是绑定引用，不是认证令牌，不可用作绕过既有确认/服务端校验的能力密钥。
保存的秘密不返回给前端“自动填表”，不由 Pinia/IndexedDB/localStorage 保存。
表单保存失败可保留本次输入修正；保存成功、取消、切模式、离页销毁浏览器输入，不删除部署端配置。
“测试已保存配置”请求不带秘密，所以测试失败只更新安全摘要，不删除配置。

### D39-04：本地保存凭据后的 HTTP 边界

本地部署不意味着任意浏览器网页或任意 Host 可以借保存凭据触发写。
新配置入口与全部使用保存 AB 配置的变更/外部调用 POST 必须检查：

1. JSON content type；简单跨站表单不得进入配置写或外部调用。
2. 受信 Host 默认 loopback/localhost；其他域名由部署方服务端明确配置，不从请求头自动信任。
3. 有 Origin 时严格同源；开发 Vite 的可信源由服务端显式提供，不反射来路、不开放 CORS。
   无 Origin 的脚本客户端仍受 Host/部署访问限制，不把 Origin 检查伪装成身份认证。
4. 代理可信主机/源从部署配置指定，不盲信 `X-Forwarded-*`。
5. GET 配置只返回安全摘要并使用 no-store，不做探测；服务默认只监听本机。
   LAN/远程访问仍必须由部署方提供认证及传输保护，不新增多用户系统。
6. HTTP(S) AB 根地址由服务端权威验证；不接受浏览器业务请求夹带地址、原始秘密或任意服务根。
   不打印配置 body、请求快照或 adapter 异常原文。

### D39-05：操作与映射归属

- 新 operation schema v3、外部映射 schema v2 增加唯一私有非敏感字段 `connection_ref`；
  当前旧 schema 保持可读。配置引用不能由客户端在恢复或同步时改写到旧 operation。
- submit/retry 与四类管理写的指纹绑定原 ref、tracking revision、action/scope/patch 等既有字段。
  相同 key 改 ref/revision 均冲突；终态只返回已有安全结果，进行中/未知不得再次发外部写。
- 管理目标映射必须属于实际请求配置 ref；异实例同 ID 不构成目标证明。
- 旧映射缺 ref 或因配置更换失效时，只有用户确认的只读同步及既有严格、去歧义匹配证据可重新核验。
  单凭同标题/同外部编号不许重新绑定，不增加前端猜测规则。
- 同步不能重绑未知操作或把另一个 AB 实例中的对象缺失判为已删除；无法证明时保留本地记录与安全只读原因。
- 旧未绑定 operation 不猜测归属。AUTO 只读本地证据，VERIFY_EXTERNAL 必须严格匹配原 ref，
  人工恢复保持独立核对、二次确认、默认取消与 audit。未知结果不等于确定失败。

### D39-06：设置与全局状态

- 设置唯一负责连接保存、替换、测试与清除；没有外部提交按钮，没有凭据浮窗。
- 顶部显示“未配置 / 已配置 / 连接可用 / 需检查”，点击进入设置，遵守现有离开保护。
- 连接可用表示当前配置最近一次用户触发探测通过，不承诺持续在线；重启后保留配置但验证状态降为已配置。
- 初始加载只读取本地配置摘要、tracking/Request，绝不自动探测、同步或外部写。
- 追番可显式探测已保存连接，再按 capability/action/scope 交集提供操作；未配置不禁用本地复核。
- 全局徽标从当前 profile 的 generated tracking list 统计 `PENDING_SUBMIT + SUBMIT_FAILED`，只做展示计数；
  零隐藏，未知/读取失败不伪造零。更换 profile 清除旧计数，列表/写响应按代际收敛。
- 不回显地址、账号或秘密；高级区只显示安全版本、capability、固定诊断，不加日志 raw 响应 API。

### D39-07：MiKan 封装

正式 Web 入口默认真实 MiKan，source 与搜索配置是实现细节，不再进入 Web 请求 schema。
候选响应仍提供公开合集证据并由用户最终选择；删 source/mikan_config 不改变人工选择这一事实边界。
离线/API/浏览器测试通过 fixture 或 fake transport 注入，绝不默认连接实站。
主文案用“搜索番剧/选择合集”，无需解释搜索服务配置；可选合集直连保留在默认折叠高级救援入口。
有界端点预算、页面忙锁和网络/HTTP/解析/内部错误分类不改变，不在本阶段做并发性能改造。

## 5. API 目标契约

本节是待实现目标，不是当前 `openapi.json` 的能力宣告；对应 story 必须联动 schema/DTO/serializer/OpenAPI/generated/inventory/URL map 与真实契约测试。

### 5.1 配置管理

公共摘要严格白名单：

```text
configured: bool
configuration_revision: int >= 0
connection_ref: UUID | null
auth_mode: "password" | "api_token" | null
credential_present: bool
connection_status: "UNCONFIGURED" | "CONFIGURED" | "VERIFIED" | "ERROR"
checked_at: RFC3339 | null
capabilities: 既有严格公开 capability DTO | null
```

无配置时 ref/auth_mode/checked_at/capabilities 为 null、credential_present=false；
新保存或服务重启时 CONFIGURED、checked_at/capabilities=null。
失败的安全 capability 响应可以保留在 ERROR 中；字段之间的组合由严格 DTO/serializer 测试约束。

| Endpoint / operationId | 请求 | 副作用 |
| --- | --- | --- |
| GET `/api/v1/settings/autobangumi` / getAutoBangumiConnection | 无秘密、无 storage profile | 仅本地读 |
| PUT 同路径 / saveAutoBangumiConnection | confirm=true、expected_configuration_revision、严格 configuration 联合 | 完整替换配置，仅本地 |
| DELETE 同路径 / deleteAutoBangumiConnection | confirm=true、expected_configuration_revision | 清秘密并更新 tombstone，仅本地 |

configuration 的 password 分支仅为 auth_mode/base_url/username/password；
api_token 分支仅为 auth_mode/base_url/token。非空秘密、字段长度、HTTP(S) 根严格校验；
默认禁用 legacy fallback，不把 fallback_enabled 作为用户配置或静默放开 Token 写。
400 表示输入/确认错误，409 表示配置 CAS/在途冲突，服务端 IO 错误为安全 5xx；全部纳入正式错误注册与固定中文。

### 5.2 使用配置的 AB 请求

| 既有 operation | 目标变化 |
| --- | --- |
| probeSavedAutoBangumiCapabilities（新增） | POST /api/v1/settings/autobangumi/probe，connection_ref + configuration_revision；用户显式只读 |
| syncTrackingItems | 相同引用，confirm=true 不变 |
| submitTrackingItem / retryTrackingItem | 相同引用，confirm/revision/key/profile 不变 |
| modifyTrackingItem / setTrackingItemEnabled / refreshTrackingRss / deleteExternalTrackingItem | 相同引用，scope/严格 patch/confirm/revision/key 不变 |
| recoverTrackingItem: VERIFY_EXTERNAL | 相同引用，必须匹配原 operation ref，仅只读 |
| recoverTrackingItem: AUTO / 人工；revalidateTrackingItem | 不接收连接引用或秘密，纯本地 |

引用缺失、配置损坏、ref/revision 过期、operation 未绑定/异 ref、映射未核验分别返回固定安全错误；
不打印 endpoint、账号、输入值，不以客户端 capability 替代同次服务端探测。
外部写始终使用原追番动作的明确确认与一次意图 key，配置确认不能替代它。

### 5.3 退役与保留

| 目标 | 处理 / 替代 |
| --- | --- |
| qB test endpoint、qB engine、设置区与专属契约 | 删除；项目不直接集成 qB |
| 旧 AB test-connection | 删除 Web 端点；保存配置后的能力探测替代，仍有效的 engine helper 保留 |
| 旧 autobangumi/capabilities 临时凭据入口 | US-330 切换追番页后删除；保存连接探测是唯一正式探测入口 |
| Request submit-ab | 删除；正式 tracking submit 替代 |
| Request preview-save | 删除；save-confirm 替代 |
| Web Request create save_request 直接保存选项 | 删除；只签发服务端草案，持久化仅由 save-confirm 负责 |
| batch accept/submit/retry/recover | 删除；batch save-confirm + 单条 tracking 替代 |
| batch queue GET、QueueView、queueWorkbench、trackingCompat | 删除旧执行与桥接 |
| `/app/queue` / 旧 entry 路由 | 只保留小型安全重定向，不保留业务组件/调用；旧 batch_id 不定位、不写 |
| Request accept/cancel/modify/delete、preview-modify | 保留，仍有本地恢复/编辑职责 |
| 历史 queue 数据与 migration reader | 数据不删；只保留确有调用的最小只读模型/解析器 |
| CLI 参数、现用 AB/MiKan/RSS adapter | 保留，不能因 Web 退役删有效共享实现 |

API 删除统一为真实路由不注册的 404，不保留无调用的 410/stub。
同期移除 generated operation、inventory、schema/DTO 与独占测试；增加 URL map/404 与正式替代旅程回归。
这是明确的本地项目接口变更，可能破坏旧脚本；用户文档记录迁移方式，不宣称兼容。
历史 Stage 文档/归档及运行数据保留，不清分支、缓存、旧方案或媒体。

## 6. Ralph 执行与停止条件

- 一次迭代只做一条最高 priority、依赖满足的 story；全部初始 passes=false、notes=""。
- 下表是建议审查批次，不是启动授权。每次启动显式最多 3 次迭代；最后一批最多 2 次。
- US-326 后必须独立审核后端前置工作包，未通过不得进入前端；可以更早停止，不能以批次未凑满为理由扩大工作。
- US-318～US-326 为独立后端提交组，先增加配置 API/保存连接探测与严格绑定 service，不提前破坏
  现有前端依赖的 generated 请求字段。US-327 起消费已审核语义与配置 API；US-328/329/330 各自
  在同一 story 原子切换对应 HTTP schema/OpenAPI/generated/调用者，不留长期兼容请求联合或 stub。
  每轮 typecheck 均需通过，不能把后续前端修复当作本轮验收。中间状态不能发布或部署为完成品；
  旧浏览器请求仍含秘密这一事实必须在 US-330 完整迁移后才解除。
- 同一共享工作区一个写入者；本次未启用子 Agent。实现模型、提交权限、批次须启动时明确，
  不从历史团队/发布任务自动继承授权。
- 无 meaningful change 不重跑同一全量；失败先最小用例。达上限即停，重复修复无进展报告。
- 新语义缺口、秘密泄漏、映射归属无法证明、必要消费者未覆盖：停止对应 story 并交回评审，不能猜测接口或伪造通过。
- 最后交付 Gate 5 候选包，不自动 push/建 PR/合并/删分支，不因文案 COMPLETE 宣告已发布。

| 批次 | stories | 审查重点 |
| --- | --- | --- |
| 1 | US-318～US-320 | 私有配置 IO、HTTP 管理与新绑定模型 |
| 2 | US-321～US-323 | 快照/能力、可靠提交、同步归属 |
| 3 | US-324～US-326 | 管理、恢复、后端独立验收并强制停止 |
| 4 | US-327～US-329 | 设置、追番提交与管理 |
| 5 | US-330～US-332 | 同步恢复、顶部与设置偏好 |
| 6 | US-333～US-335 | qB、旧单番、旧批量 API 删除 |
| 7 | US-336～US-338 | 旧队列删除、MiKan 封装、跨页定向验收 |
| 8 | US-339～US-340 | 文档与完整 Gate 5 候选交付 |

## 7. 用户故事与验收条件

下面与待启动 JSON 同源，priority 即顺序；每条只承担其边界内实现，不顺带推进下一条。
“Tests pass”须对应实际定向证据；UI 附 dev-browser 的真实 Chromium 验证要求。
### US-318：建立隔离的部署端 AB 配置 repository

作为本地部署用户，我希望 AB 配置在服务重启后保留，而不混入番剧业务文件。

- 新增仅服务端可指定的 MIGU_ORCA_WEB_CONFIG_ROOT，默认 .migu_orca/config；autobangumi.json 与所有 Web storage profile 独立，浏览器不能指定或覆盖配置根
- 严格 password/API Token 配置联合；秘密模型隐藏 repr；HTTP(S) 服务根规范化支持裸 host:port，拒绝路径、用户信息、查询、片段与歧义输入，不保存未经校验的地址
- 每次成功保存生成全新 opaque connection_ref，configuration_revision 单调递增；删除以不含秘密的 tombstone 保留 revision，重建不能产生 ABA
- 目录 0700、配置与临时文件 0600，限制权限失败、符号链接、损坏内容和 IO 故障 fail closed；原子替换失败保留上次成功值，错误不回显值、内容或路径
- 仅专用配置文件允许保存 base_url、账号、密码或 Token；Request、history、tracking、operation、队列、迁移、普通备份与公开 serializer 不得含这些字段值
- 新增 repository 测试覆盖重建实例读取、save/delete/CAS、权限、符号链接、损坏文件、写失败、revision 和 canary 隔离；Tests pass
- Typecheck passes

### US-319：实现 AB 配置管理 API 与本地写入口防护

作为用户，我希望显式保存、更换和清除 AB 配置，并且不能从 API 读取秘密。

- GET/PUT/DELETE /api/v1/settings/autobangumi，operationId 为 getAutoBangumiConnection/saveAutoBangumiConnection/deleteAutoBangumiConnection；PUT 和 DELETE 要求 confirm=true 与 expected_configuration_revision
- GET 及写响应仅返回第 5 节安全摘要，不含 base_url、username、password、token、原始配置或路径；GET 无配置与配置损坏均不触发外部访问，损坏返回固定安全错误
- PUT 必须提交完整新配置，禁止空秘密表示沿用、回读旧秘密、合并其他 profile 或自动迁移浏览器输入；保存不自动探测、同步或提交；DELETE 只清除 AB 配置
- 为配置修改建立服务端 CAS 与当前进程外部请求 lease；在途外部请求时修改立即 409 connection_in_use，不长时间阻塞，不仅靠前端 disabled
- 相关变更请求只接受 application/json；有 Origin 时严格核对部署方受信同源，不反射任意 Origin、不开 CORS；缺失 Origin 的非浏览器客户端仍受受信 Host 约束
- Flask 受信 Host 默认仅 localhost/loopback，额外部署 Host 仅由服务端配置；恶意 Host/Origin 与简单跨站表单在使用保存的凭据或产生配置副作用之前被拒绝
- 同步 schema/DTO/serializer/OpenAPI/generated/inventory、真实 Flask 契约和恶意 Origin/Host 测试；API drift check and Tests pass
- Typecheck passes

### US-320：为 operation 与外部映射增加非敏感连接绑定

作为维护者，我需要持久的连接绑定，防止服务重启或更换配置后误操作另一 AB 实例。

- TrackingOperation 使用向后可读的 schema v3，仅新增 connection_ref；external_mapping 使用向后可读的 schema v2，仅新增 connection_ref；旧入口切换前未绑定路径按 legacy 分支可读，最终新保存连接入口必须有 ref，未知字段/schema 严格拒绝
- 绑定只保存随机 opaque ref，不保存地址、账号、秘密或秘密摘要；新 operation 的幂等绑定包含原 connection_ref、expected_revision 和既有 action/scope/patch fingerprint
- 可读取旧 operation v1/v2 与旧映射 v1；旧缺失 ref 标记为未绑定，不将当前连接猜成原连接，不自动改写、终结或清除旧未知操作
- 新映射必须有合法 ref；缺失、过期或与当前 ref 不符的映射不得执行外部管理；公共详情只显示安全的需重新核验原因，不暴露私有映射
- repository round-trip、版本兼容、同键不同 ref、未知字段和 canary 测试覆盖真实读写；Tests pass
- Typecheck passes

### US-321：接入部署配置能力探测与请求快照

作为用户，我希望测试已保存的 AB 连接，并在跨页后复用配置而不重复输入凭据。

- 新增 POST /api/v1/settings/autobangumi/probe（probeSavedAutoBangumiCapabilities），请求 connection_ref + configuration_revision；服务端解析当前保存配置，取得 immutable snapshot 与 lease，结束/失败释放；既有临时凭据探测暂不改类型，US-330 删除
- 探测仍为显式只读 POST；响应复用既有严格 capability DTO，安全摘要显示 UNCONFIGURED/CONFIGURED/VERIFIED/ERROR，已保存不等于连接成功
- 探测结果仅绑定本次 ref/revision；旧探测响应不能更新新配置的状态；配置保存或删除使 capability 缓存失效，重启后只显示 CONFIGURED，不持久化 raw probe
- HTTP 200 下 FAILED/PARTIAL/UNKNOWN 不误报 VERIFIED；API Token 只按已验证 capability 提供能力，管理写仍仅 password + 精确 3.1.18
- 共享快照解析器拒绝缺配置、过期 ref/revision、损坏配置和同时夹带 ab_config；业务服务中的临时配置不离开受控 adapter
- 同步 OpenAPI/generated 与相关探测/租约/代际/能力降级契约测试；API drift check and Tests pass
- Typecheck passes

### US-322：迁移可靠提交与重试到保存的 AB 连接

作为用户，我希望刷新后仍能提交，而不破坏原有确认、幂等与未知结果保护。

- 先新增仅服务端消费配置引用的 submit/retry 服务入口与严格输入模型，不提前改变现有 operation 请求形状；US-328 同轮切换 HTTP schema/generated/全部调用者并删除业务请求 ab_config，保留 confirm/revision/key/profile
- 进入外部边界前原子校验当前配置绑定并取得 lease，operation 在 PREPARED/IN_PROGRESS 前持久化原 ref；写前复核、外部调用、写后回查与落盘顺序不变
- 同 key 的重放必须先验证原 ref/revision/action 绑定；成功终态可安全返回既有结果，未知/进行中不得因配置更换产生新调用或新 key
- 成功提交落盘的外部映射绑定实际使用的 ref；本地 NEEDS_RECONFIRM 与存储失败不伪造外部成功，不把尚未外部调用的错误记成未知
- 重启、更换配置、同 ref 请求重放、同键不同 ref、明确失败和未知结果测试真实进入统一 service；未知和重放场景外部调用计数不增加
- 冻结新引用输入模型/安全结果与 service handoff；既有 HTTP/generated 请求保持可编译直到 US-328 原子切换；定向 service/模型测试和当前 API drift check pass，Tests pass
- Typecheck passes

### US-323：迁移同步并验证外部映射归属

作为用户，我希望显式同步当前 AB，且更换连接后旧外部编号不会成为新服务的写目标。

- 新增保存连接的同步 service 入口与严格引用模型，保留 confirm=true；现有 syncTrackingItems HTTP/generated 输入在 US-330 切换，初始 list/detail 与 GET 配置不触发外部访问
- 同步以本次连接快照执行，产生的新映射绑定实际 ref；旧配置的响应不能覆盖新 ref 数据，失败/PARTIAL/UNKNOWN 保留既有本地列表
- 旧缺失 ref 或已失效映射仅在用户确认的只读同步及既有严格匹配/去歧义证据成立后核验；单凭相同外部 ID、标题或旧状态不得重新绑定
- 未决 operation 的源 ref、绑定与恢复锁不得被同步改写；跨实例找不到对象不直接把旧项判为外部删除，不自动创建替代订阅
- 不新增猜测匹配规则；无法证明归属时保留本地项、提供安全只读原因，当前外部对象可按 EXTERNAL_ONLY 展示
- 双 AB 实例同 ID、歧义匹配、旧未绑定映射、未知操作、旧响应与部分成功回归通过；API drift check and Tests pass
- Typecheck passes

### US-324：迁移外部管理到严格连接绑定

作为用户，我希望修改、启停、刷新和删除只作用于核验过的当前 AB 对象。

- 为四类管理增加保存连接 service 入口和严格 ref/revision 输入模型；US-329 同轮切换 modify/set-enabled/refresh/delete HTTP schema/generated/调用者，保留 patch/scope/confirm/tracking revision/key
- 管理动作依次验证配置 ref、映射 ref、服务端 action/scope 和同次 capability；映射旧/缺失/异实例一律在外部写前拒绝
- operation 与管理幂等 fingerprint 绑定实际 ref；写前读取、写后回查、部分结果和未知保护不变，配置修改不得绕过管理意图锁
- 删除始终单条且 adapter 固定 file=false；所有成功/失败/未知结果保留本地方案、tracking、审计、任务与媒体
- 不同 AB 实例复用外部 ID 和相同 key、scope、patch 不得发写请求；覆盖四类管理及未知/能力降级/租约冲突
- 冻结管理输入模型/绑定 service 与当前 API drift；不提前移除现有 generated ab_config 字段导致前端失败，US-329 原子切换；定向 service/契约准备测试和 Tests pass
- Typecheck passes

### US-325：迁移未知结果恢复并保护历史未绑定意图

作为用户，我希望更新或清除配置后，仍能安全处理以前结果未知的操作。

- 增加保存连接的 VERIFY_EXTERNAL service 入口与严格引用模型；AUTO/MARK_SUCCEEDED/MARK_FAILED 不解析 AB 配置；recoverTrackingItem HTTP/generated 联合于 US-330 切换，外部核验仅只读原 operation
- VERIFY_EXTERNAL 要求 operation 原 ref 与当前 ref 严格一致；配置更换、清除、旧 operation 缺失 ref 均安全拒绝外部核验，不暗换连接、不产生外部写
- 保留旧未知/未绑定记录与审计；AUTO 只使用本地持久证据，无法确定时进入既有人工恢复流程，不自动将失败或成功标为终态
- 人工恢复保留独立核对、二次确认和默认取消；不接收外部 ID、URL、自由备注或秘密；明确终态之前 submit/retry/management 均保持服务端锁
- 模拟服务重启及删配置后重建，原未知意图不能重放；相同 ref 只读核验、人工明确失败后新确认新 key 等回归通过
- 冻结严格恢复引用模型、旧未绑定策略和 service handoff；现有 HTTP/generated 输入直到 US-330 原子切换才移除 ab_config；定向 recovery/模型测试和 API drift check pass，Tests pass
- Typecheck passes

### US-326：完成新增后端支撑的独立验收与前端交接

作为维护者，我需要先核实后端连接契约，再让 F-G 页面开始接入。

- 逐条核对 US-318～US-325 的实际代码、schema、操作绑定、IO 权限、Origin/Host 和 targeted 测试证据，不以 passes 标记代替审核
- 新增配置专属测试 fixture 与 Flask app 配置根隔离，所有受影响 API/浏览器 fixture 必须指向临时配置根，不读取开发者默认配置
- 运行受影响 repository/service/API contract 测试、Ruff、OpenAPI drift 与 generated typecheck，不在此 story 重跑全部后端/前端/Chromium门禁
- 交付新配置 API、保存连接探测和业务 service 入口/严格引用模型 handoff，语义先审核；旧业务 operation HTTP/generated 仍保持可编译，前端切片同轮修改请求契约与调用者；仅配置文件可含秘密
- 本工作包后强制停止独立审核，未通过不得进入 US-327；中间分支不能部署为完成品，不 push/PR/merge
- Targeted backend handoff checks and Tests pass
- Typecheck passes

### US-327：将设置页 AB 区域改为保存与测试连接

作为本地用户，我希望在设置中配置一次 AB，此后刷新和离页不用重新输入。

- Settings AB 区域仅使用 generated get/save/deleteAutoBangumiConnection 与新增 probeSavedAutoBangumiCapabilities，提供保存/测试/更换/清除配置；同轮移除 submitAb、request_id 提交上下文与旧提交按钮，不等待端点退役
- 默认 password，API Token 按真实能力只读降级；保存与探测分开，输入服务地址支持既有裸局域网地址规范化，不填写内部 Request/storage/API 术语
- 秘密永不回显；已保存只展示 credential_present 和安全摘要，修改需完整重填；成功保存、取消、切认证、离页清除浏览器输入，不删除部署端配置
- 保存失败保留本次受控表单输入供修正，仅给固定安全错误；测试已保存配置失败不删除配置；409 先重读摘要要求重新确认，不静默覆盖
- GET 不含 endpoint/账号/秘密，表单必要输入不复制到属性、结果、通知、URL/history/storage/console；删除必须确认且不影响本地方案或媒体
- Vitest 与真实 Chromium 覆盖保存、测试成功/失败、刷新/跨页保留、取消、删除、CAS、裸地址与 canary；Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-328：迁移追番页提交与重试输入

作为用户，我希望追番页使用已保存连接，同时继续逐条显式确认提交。

- 同轮切换 submit/retry HTTP schema/OpenAPI/generated 及 TrackingView/纯 body builder/测试，使用 ref/revision 删除这两类请求 ab_config；写意图不持有密码、Token、地址或 writeConfigSnapshot，未切换的旧探测输入在 US-330 统一移除
- 未配置/未探测/能力 UNKNOWN 时安全降级，提供去设置或显式探测入口；页面加载、回到追番页、配置保存和探测都不得自动提交
- 保留写 intent 原 key、tracking revision、connection_ref 与 configuration_revision；同一传输意图不得用重读后的 ref/revision 改写绑定
- 连接变化清除旧 capability 与可执行确认上下文；结果未知仍只读回查/恢复；确认取消零写，409 重读并要求重新确认
- 配置查询/列表/详情代际分别处理，旧摘要不得覆盖新 ref；写结果面板不因改 key 重挂载而丢失
- 定向 submit/retry Vitest 与 Chromium 覆盖跨页/刷新后提交、新旧配置、未知与重复点击；Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-329：迁移追番页外部管理输入

作为用户，我希望外部管理使用保存的连接且不能操作旧实例的映射。

- 同轮切换四类管理 HTTP schema/OpenAPI/generated、TrackingView 与 intents/body/tests，仅发送 ref/revision，不持有 managementConfigSnapshot；dispatch 与 body 门控一致
- 管理按钮仍来自 available_actions + target_scopes + capability 交集；旧映射或新配置未核验时只读降级
- 新配置摘要到达时取消旧未执行确认上下文；未决 management 意图保留源 ref 与锁，不能使用新配置重试
- 逐条影响确认、最新 tracking revision、同一 key、单飞、写后回查、未知保护和 file=false 文案不变
- 定向四类管理 Vitest/Chromium 覆盖同 ID 异实例、配置变化、能力降级、取消零写、未知恢复与 canary；Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-330：迁移追番页同步、探测与恢复并移除凭据弹窗

作为用户，我希望连接配置留在设置中，追番页只负责同步、恢复和业务动作。

- 同轮切换 sync/recover HTTP schema/OpenAPI/generated/全部调用者：probe 使用新增 probeSavedAutoBangumiCapabilities，sync/VERIFY_EXTERNAL 发送 ref/revision；AUTO/人工/revalidate 不要求连接
- 删除 POST /api/v1/autobangumi/capabilities 的临时凭据入口与 generated operation、CredentialSessionDialog、TrackingView 所有 ab_config/秘密状态及无调用测试；不保留全局凭据弹窗或双轨兼容层
- 同步仍须用户确认、单飞、旧列表保留和写后详情回查；不因全局 chip、导航、刷新或恢复结果而自动同步
- 原 operation 未绑定或 ref 不符时只提供可行的本地/人工恢复；未知不能变成明确失败、不能解除源锁
- 定向 Vitest 与 Chromium 覆盖配置跨页、纯本地复核、同 ref 外部核验、删配置与旧未绑定恢复、失败降级和敏感值；Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-331：实现安全全局连接提示与待处理徽标

作为用户，我希望知道连接是否配置好，并能找到需要处理的追番项。

- App 顶部状态采用未配置/已配置/连接可用/需检查，只消费 generated 安全摘要；连接可用只表示本次配置最近探测通过，不保证持续在线
- 点击状态入口通过 routeLocation 到设置，不打开凭据弹窗；品牌返回添加页并遵守已有离开保护，导航与焦点语义保持可达
- 加载摘要不探测外部；安全摘要只可在非持久内存 store 缓存，更换/删除/重启使旧验证失效，旧响应不得回写新配置
- 追番徽标仅从当前 profile 的 generated listTrackingItems.items.status 计数 PENDING_SUBMIT + SUBMIT_FAILED，不使用不存在的 summary 字段或旧 queue；零隐藏，失败/未知不伪造零
- profile 改变清除旧计数并重读，保存确认/写/恢复后由服务端摘要收敛；不以徽标构建客户端状态机
- Vitest/Chromium 覆盖四状态、服务重启、跨页/profile、零计数、查询失败、离开保护、键盘与 200%；Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-332：简化设置偏好并迁移无效保存开关

作为用户，我希望设置只包含实际生效的默认规则和存储偏好。

- 移除默认保存订阅方案控件、saveRequest 类型/摘要和无消费者键写入；读到旧 miguOrca.web.saveRequest 只删除该明确旧键，不清空其他 localStorage
- 相对 storage profile 保留；默认规则保存范围不变，既有方案不静默改写，恢复默认仍确认且失败回到上次服务端成功值
- 设置按 AB 连接、默认字幕/过滤、存储与目录、高级诊断分组；高级技术字段默认折叠，安全版本/capability 使用中文说明
- 设置消费的 API 类型从 generated 提取，移除重复手写 UserPreferences DTO，但保留 DEFAULT_PREFERENCES 和纯转换函数
- 不显示绝对路径、外部 ID、原始配置/响应/日志，也不新增后台日志查询接口；不把设置变成业务提交页
- 定向设置/偏好/存储 Vitest 与 Chromium 覆盖旧键迁移、恢复默认、表单失败和敏感输入；Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-333：删除 qBittorrent 连接测试全链路

作为维护者，我希望项目不承担与当前目标无关的 qBittorrent 配置和集成。

- 删除 Settings qB 区域与专属状态/输入/调用，删除 POST /api/v1/qbittorrent/test-connection、qB 专属 schema/DTO/serializer/error mapping/endpoint 注册
- 确认不存在生产调用者后删除 src/qbittorrent_engine 及其专属测试/exports/pyproject wheel 注册，不保留空 engine、兼容 stub 或未来下载占位
- 同步 OpenAPI/generated/inventory、包装构建清单和相关测试；qB 功能测试删除对应已退役功能，增加真实 Flask 404 与默认 bundle 无 qB 接入断言
- 主添加/追番/设置不访问 qB、不接收 qB 配置；不删除用户运行数据，也不删除 AB 负责下载这一产品边界说明
- 定向设置 Vitest/Chromium、受影响契约与引用检查证明不存在 qB 生产依赖；API drift check and Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-334：移除旧单番提交与重复保存 Web API

作为维护者，我希望单番只保留一个正式保存确认与一个可靠外部提交入口。

- 确认 US-327 已移除 Settings submitAb/request_id 提交上下文与旧跳转，再删除 POST /api/v1/requests/<request_id>/submit-ab 与 POST /api/v1/requests/preview-save
- 删除 POST /api/v1/autobangumi/test-connection，由已保存配置能力探测替代；删除这些端点独占的 Web schema/DTO/serializer/helper/测试，不保留410/stub
- 同轮删除 Web Request create 的 save_request 选项及直接保存分支，更新 candidateSearch/batchWorkbench/generated/测试为只签发服务端草案；保留 CLI 显式保存 helper，不保留另一条 Web preview-save→accept 主流程
- 复用现有 save-confirm 与 tracking submit；保留仍被 CLI 使用的 apply_ab_submit_action/AB adapter，保留本地 accept/cancel/modify/delete 与 preview-modify
- 更新路由 settings query 白名单使旧 request_id 安全清理，不产生写；现有方案编辑、SafeInfo、复制再用与 tracking 深链继续可用
- OpenAPI/generated/inventory 与真实 Flask URL map 同步；已退役端点 404，单番保存确认和提交只经过正式服务
- 定向单番/设置/方案/API contract Vitest 与 Chromium 验证无旧写请求且取消零写；API drift check and Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-335：删除旧批量接受与队列外部写 API

作为维护者，我希望批量审核只负责保存确认，外部写统一逐条经 tracking。

- 删除 POST /api/v1/batches/<batch_id>/accept、submit、retry、recover 四类旧端点与端点独占的 schema/response DTO/route 编排
- 批量 parse、逐项服务端 draft、save-confirm 及其部分成功/1～36边界保留；不新增批量外部提交或服务端批量现场
- 没有 CLI/有效生产调用者的旧 batch_accept/batch_submit 写编排删除；不得仅因名称类似删除仍用于保存确认或纯规则的共享函数
- 删除旧 Web 到 CLI submit 与 queue 外部写反射路径；用户结果未知记录仍由 tracking 恢复，不清理任何历史数据文件
- 契约清单/generated 与 URL map 不再含这些动作；真实 Flask 404 与正式批量保存部分成功回归通过
- 受影响契约/批量 Vitest 与 Chromium 定向测试通过，证明默认运行时不调用旧批量写；API drift check and Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-336：删除旧队列运行时与兼容投影写入

作为维护者，我希望退出默认运行时的旧队列不继续占用生产代码和维护成本。

- 删除 GET /api/v1/batches/<batch_id>/queue、QueueView/queueWorkbench、trackingCompat 旧 batch_id 定位桥，以及仅供旧队列的接线与测试
- 追番页不再接受 batch_id query；/app/queue 保留小型安全重定向到 /app/tracking 并清理旧 query，不调用旧 API或暗选条目
- 删除 tracking_queue_compat 与 submission/recovery 中 queue 写投影钩子；确认保存确认、tracking 状态与未知恢复仍以统一服务为权威
- 删除无调用的 queue 写 repository/controller；历史 migration 所需读取模型/纯解析器最小化保留，明确只读，不为了零引用破坏已有数据可读性
- 无运行数据删除、无媒体删除；旧 queue/history 文件继续可迁移，不批量改写历史操作
- 默认 bundle/引用/URL map 不含旧队列执行逻辑；历史迁移/API/Vitest/Chromium 定向回归通过；API drift check and Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-337：封装 MiKan Web 搜索并收敛用户语言

作为普通番剧用户，我希望输入番名就能搜索，不必了解或配置 MiKan 服务。

- Web candidate search/batch parse/Request create 删除 mikan_config 公共字段和 RequestMikanConfigPayload，仅使用服务端 default_mikan_config；旧字段严格拒绝，不静默覆盖
- Web Request create 删除用户 source 选择，正式默认真实 MiKan；离线 fixture 通过测试 fixture/transport 注入，不能令生产用户被默认假数据搜索
- 前端与 generated 请求不发送 source 或 MiKan endpoint/timeout；主入口文案为搜索番剧/选择合集，候选仍人工选择真实合集
- 保留默认折叠的可选合集直连救援入口，但不把它作为配置要求；不持久化 MiKan 账号、Cookie、地址或搜索词
- 保留 CLI 显式源与配置这一独立高级信任边界，保持离线示例可用；不为 Web 封装删除仍被 engine/RSS/CLI 使用的 MikanConfig/transport
- 沿用端点级有界等待预算、忙锁、FOUND/EMPTY/FAILED 和中文错误分类；mock transport 隔离实站，覆盖无配置搜索、直连、批量与失败
- 同步前端相关调用/文案/Vitest/Chromium 与 Web schema/OpenAPI/generated；API drift check and Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-338：完成跨页配置、安全与桌面旅程验收

作为用户，我希望配置一次后跨页使用，并且秘密只存在于部署端配置和必要输入中。

- 真实 Chromium 经真实 Flask 配置 API 保存 fake AB 配置，再跨设置/添加/方案/追番及浏览器刷新；至少一条旅程不 mock 配置 API，AB 只通过 fake transport
- 实际重建 app/repository 或重启测试服务，验证保存配置仍可使用，配置状态重置为已配置；新 fake AB 连接不重用旧 operation key/ref，不连接真实服务
- 独立 canary 覆盖地址、账号、密码、Token；仅专用测试配置文件和受控输入允许出现，公开响应、业务 JSON、DOM其余区域/属性、URL/history/storage/console/截图/trace 均干净
- 恶意 Origin/Host、表单请求、配置CAS、保存失败、清除、更换配置、同 ID异实例、原未知恢复与旧未绑定记录均有真实后端负例
- 覆盖单番和批量 1/12/36、部分成功、返回修改、同步/提交/恢复/四类管理、未配置仍可搜索；无旧端点请求，无自动外部写
- 验证1280x720/1440x900/1920x1080与200%缩放、键盘/焦点、aria-live、非纯颜色状态、reduced-motion；Tests pass
- Verify in browser using dev-browser skill
- Typecheck passes

### US-339：同步用户文档、模块边界与退役记录

作为维护者，我需要区分新目标、真实交付与旧阶段历史，避免开发文档再要求保留旧实现。

- 按实际完成事实同步 README、docs索引/main PRD/future stages/backlog、架构、M10/M13/M14、根/模块AGENTS及前端交互/实施/后端支撑文档
- 明确 AB 专用部署配置的唯一秘密持久化例外、文件权限/备份敏感性、容器持久卷、清除配置、无加密保证、单进程与无认证部署限制
- 记录旧端点/字段退役及外部调用迁移方式；保留旧Stage PRD/归档作为历史，不改历史 passes 或抹掉历史测试证据
- 更新 dev-browser/前端handoff 的旧队列与canary规则：配置 API 不全用 route mock，运行数据与测试配置根双隔离，已退役功能不再作为门禁
- Ralph progress仅记录实际命令/结果与剩余风险，文档链接/路径/冲突检查通过；不伪造发布时间、CI、截图或线程链接
- Documentation checks and affected handoff tests pass
- Typecheck passes

### US-340：完成完整门禁、归档与 Gate 5 候选交付

作为维护者，我需要在完整验收后判断本轮前端重构能否作为候选发布包。

- 逐条映射US-318～US-339的代码/提交/证据，尤其检查秘密持久化例外、跨配置未知保护、被删除功能与保留的历史读取器
- 完整执行api:check/typecheck/lint/Vitest/build、Python compileall/Ruff/OpenAPI drift、非浏览器pytest、真实Chromium各一轮；不重复组合含浏览器的完整pytest
- 全部通过且没有skip冒充后才标本story通过；失败先最小用例，记录真实计数，删除退役专属测试导致计数变化必须能逐项解释
- 按第8节Gate5矩阵完成正常/失败/部分成功/未知/配置重启与跨页/多视口/200%/敏感信息验收，不将mock实现或自述当作独立审核
- 归档prd/progress和阶段完成记录一致，不提交dist、trace、截图、配置、秘密、storage artifact；下一步停下交用户审核
- 本story不授权git提交、push、PR、merge、安装包或删分支；未获发布授权不宣称已发布
- Verify in browser using dev-browser skill
- Typecheck passes

## 8. 验收矩阵与验证计划

| 维度 | 必须证明的结果 | 主要 stories |
| --- | --- | --- |
| 配置生命周期 | 保存、重建实例/服务、浏览器刷新与跨页保留；清除只清秘密 | 318/319/327/338 |
| IO 与公开边界 | 权限/链接/原子写失败、损坏数据安全失败；唯一专用配置可含 canary | 318/319/326/338 |
| 本地 HTTP 防护 | Host/Origin/JSON 负例在配置或 AB 副作用前失败 | 319/326/338 |
| 操作绑定 | 同 key 不同 ref、在途修改、重启后未知意图均零重复写 | 320/322/324/325/338 |
| 映射归属 | 双 AB 相同 ID、旧未绑定或换配置不能成为管理目标 | 320/323/324/338 |
| 能力与探测 | 已配置不等于在线；200 FAILED/PARTIAL/UNKNOWN 与 Token 只读降级 | 321/327/330/331 |
| 主旅程 | 单番、批量1/12/36、人工合集、部分成功、纯本地复核与返回修改 | 328～332/337/338 |
| 外部动作 | 显式 sync/submit/retry/recover/四管理动作，取消零写，file=false | 322～325/328～330/338 |
| 退役 | 旧 API 404、bundle/引用无旧执行，必要历史解析仍可读 | 333～336 |
| 桌面/a11y | 三档桌面视口、200%、键盘/焦点、读屏、缩减动画 | 327～338 |
| 发布就绪 | 证据/代码/提交/归档一致；没有真实秘密或生成/运行 artifact | 339/340 |

### 8.1 普通 story 最小验证

根据实际改动选用，不机械执行所有命令：

- repository/model：专属 pytest + 受影响 Ruff，schema 迁移需真实 round-trip。
- HTTP/service：目标 pytest 与真实 Flask 契约、OpenAPI check、generated check/typecheck。
- 前端逻辑：受影响 Vitest + typecheck/lint；UI 加 build 后的真实 Chromium 定向。
- 删除 story：引用/URL map/404、受影响契约及正式替代旅程，不能只删除测试令全量变绿。
- 文档 story：链接/路径、冲突、diff；不单为文档执行 pytest 或浏览器。

新专属测试建议落点：

```text
src/storage_engine/controllers/deployment_connection_repository_test.py
src/tracking_engine/models/operation_test.py
src/tracking_engine/models/tracking_test.py
src/apps/migu_orca_web/deployment_connection_service_test.py
tests/api_contract/test_deployment_connection_contract.py
tests/api_contract/test_retired_endpoints.py
tests/browser/test_app_deployment_connection.py
```

已有受影响测试必须同步：tracking_{submission,sync,management,recovery,migration}_service_test.py、
tests/api_contract/、SettingsView/TrackingView/candidateSearch/batchWorkbench/路由 Vitest、
tests/browser/test_app_{settings,tracking,workbench,batch_workbench,feature_parity,shell,responsive_a11y}.py。
路径为落点建议，不代表文件已经存在；实现中核对实际文件名。不得在命令中直接执行占位路径。

浏览器按项目 dev-browser skill；测试配置根和业务数据根都隔离。
至少一条保存→跨页→业务请求经过真实 Flask 配置读取，真实外部系统全部 fake transport；
仅 route mock 配置摘要不能证明部署持久化。
观察 loading 用 held route；异步焦点用 Playwright 轮询；禁止秘密截图/trace。

### 8.2 US-340 完整门禁

```bash
# 仓库根
uv run python -m compileall -q src tests
uv run ruff check src tests
uv run migu-orca-openapi --check
uv run pytest -q -m "not browser"
# frontend/
npm run api:check
npm run typecheck
npm run lint
npm run test:unit -- --run
npm run build
# 仓库根，最新构建与隔离配置/数据根后
uv run pytest tests/browser/ -q
git diff --check
```

compileall 不替代 Ruff。CI 按新提交独立验证；本地记录不伪造 CI 成功。
本阶段删除退役测试并新增真实配置旅程，测试数允许改变，但须逐类解释，不沿用 Stage 38 数字作证。

## 9. 激活、文档维护与交付

当前活动 Stage 38 prd 与既有归档 JSON 一致，但 progress 快照不完全一致（后续安全/局域网/MiKan 修复追加），
不能覆盖旧归档或依赖 ralph.sh 跨分支自动归档猜阶段。
只在得到启动授权、目标分支和当时实时基线确认后，使用唯一新归档目录保存活动 JSON/progress，
再加载本计划并初始化 progress。

正式开发前还需确认：本批 stories、最多迭代数、实现模型、单写入者、是否允许本地 story 提交。
用户本次只授权规划与文档，不自动授权发布。
完成时交付：

1. 实际验收后的阶段记录与退役迁移说明；
2. generated API、代码、测试与每条 passes 的可核对映射；
3. 跨页/重启持久化与无重复写证据、剩余部署限制；
4. 归档与干净 artifact 状态；
5. 停下交用户决定是否发布，不预分配下一 Stage。

## 10. 本轮评审与文档验证记录

本轮只做静态证据核对与文档/JSON计划检查，未运行 pytest、Vitest、Chromium、构建或外部服务探测。
本节不计为任何 story 的实现验收；所有 stories 保持未通过。

文档检查结果：`git diff --check` 通过；Node 只读校验确认标准 Ralph 字段、23 条连续 story/priority、
全部 passes=false/notes 为空、13 条 UI 的 dev-browser 验收、每条末尾 Typecheck、Markdown/JSON
逐条验收一致、74 个本地链接存在、无冲突标记，活动 Stage 38 prd/progress 原文保持不变。
最终文档补充后再次检查 story/验收一致性与空白；没有执行任何实现门禁，不能据此标 story 通过。
