# MiGuOrca Stage 24 PRD：AutoBangumi 真实认证与订阅兼容闭环

## 1. 文档信息

| 字段 | 内容 |
| --- | --- |
| Stage | 24 |
| 状态 | 已完成（2026-08-25） |
| 日期 | 2026-08-24 |
| Ralph 分支 | `agent/stage24-autobangumi-compatibility` |
| 主要模块 | M10、M12、M13、M14、Web API、浏览器测试 |
| 实机基线 | AutoBangumi 3.1.18；服务根地址由用户 request-scoped 提供 |

## 2. 背景与问题

Stage 20 已建立单个/批量 Request 的 AutoBangumi 提交队列、重试、恢复和脱敏结果契约，但真实 HTTP adapter 是未经目标版本验证的抽象骨架。2026-08-24 对局域网 AutoBangumi 实例进行只读检查后确认：

1. 实例版本为 3.1.18，`POST /api/v1/auth/login` 接收表单用户名/密码，返回访问 token；后续接口使用 `token` Cookie，而不是 `Authorization: Bearer`。
2. 当前 MiGuOrca 强制用户提供 token，并把 endpoint 当作完整创建 URL，无法让普通用户直接填写服务根地址和账号密码。
3. 3.1.18 创建订阅使用 `POST /api/v1/rss/subscribe`，body 是 `{data: Bangumi, rss: RSSItem}`；当前自定义 `{title, rss_url, save_path, filter_rule}` payload 不兼容。
4. 3.1.18 成功响应使用 `status/msg_en/msg_zh`；当前 client 强制要求订阅 ID，会把有效响应误判为失败。
5. 新版 AutoBangumi 已存在 API Token/Bearer 模式，因此不能用旧版 Cookie 登录实现替换全部兼容能力。

Stage 24 的目标是让已经跑通的 Request 创建/接受/队列流程能够真实、安全地连接 AutoBangumi，而不是扩展为 AutoBangumi 管理器。

## 3. 目标

1. 设置页默认提供“账号密码”认证，同时保留“API Token”兼容模式。
2. 用户只填写 AutoBangumi 服务根地址；客户端按适配器版本拼接已知 API 路径。
3. 支持 AutoBangumi 3.1.18 登录、只读连接测试和 `/api/v1/rss/subscribe` 订阅提交。
4. 保留未来/新版 Bearer token adapter，不把两种认证字段混用。
5. 单个提交、批量顺序提交、失败重试和人工恢复继续复用同一 M10 client/payload/result seam。
6. 用户名、密码、token、登录 Cookie 和完整服务地址严格保持 request-scoped，不持久化、不回显、不进入日志或测试产物。

## 4. 非目标

1. 不自动探测或暴力尝试未知 AutoBangumi 私有接口。
2. 不管理 AutoBangumi 用户、API token、配置、RSS 列表或已有番剧。
3. 不在自动化测试中对用户实机创建、修改或删除订阅。
4. 不直接创建 qBittorrent 下载任务，不绕过 AutoBangumi。
5. 不实现正式番名/季度解析、部署向导或流式封面代理；分别由 backlog BL-018、BL-014 与 `docs/optional_features.md` OF-001 管理。新版 Bearer 写兼容登记为条件触发的 BL-022；这些事项不预绑定 Stage 编号。

## 5. 产品决策

### 5.1 认证模式

`auth_mode` 使用显式枚举：

- `password`：默认。需要 `base_url`、`username`、`password`；先登录，再使用仅存于当前 client/session 的 Cookie。
- `api_token`：兼容模式。需要 `base_url`、`token`；使用 `Authorization: Bearer <token>`。

表单切换认证方式时，只显示并提交当前模式所需字段；切换和成功操作后清理另一模式的敏感输入。后端拒绝混合、缺失或未知字段，不回显字段值。

### 5.2 地址语义

UI 字段命名为“服务地址”，接受形如 `http://host:port` 的根地址。规范化仅允许 `http/https`，拒绝 URL userinfo、query、fragment；尾部 `/` 可安全移除。已知路径由 adapter 内部拼接，不能让用户填写任意写接口。

局域网/私网地址是合法部署目标，不能套用 MiKan 封面代理的公网 SSRF 限制；但凭据绝不能被发送到初始 origin 之外，禁止跨 origin 重定向。

### 5.3 版本与能力

连接测试先调用已知健康/状态接口并取得公开版本；适配器按显式 `adapter` 或可靠能力判断选择契约。Stage 24 至少保证：

- `legacy_3_1`：账号密码 + token Cookie + `/api/v1/rss/subscribe`。
- `bearer_api`：API token + Bearer Header；只有在 fixture/官方契约证明具体提交路径和 body 后才能标记“可提交”。若只验证认证而未证明写契约，连接测试必须返回“可连接但暂不支持提交”，不能套用旧 payload。

不得根据一次 401 自动把密码/token 发送给另一 origin 或无限尝试认证方式。

### 5.4 3.1.18 订阅映射

Request 到 `{data, rss}` 的映射集中在 M10 纯函数并有 fixture 测试。至少覆盖：

- `official_title`、`title_raw`、`season`、字幕组、分辨率/来源/字幕等公开可用信息；缺失的可选字段使用 AutoBangumi 合法默认值，不伪造事实。
- `rss_link` 来自当前用户确认的 RSS；`save_path` 来自 Request 目标目录；`filter` 从现有包含/排除规则按 3.1.18 能表达的范围转换。
- `rss` 描述所选订阅源，URL 必须与用户确认的 RSS 一致。

若现有 Request 规则无法无损表达为 3.1.18 的字符串过滤器，提交前返回明确、脱敏、可修改的兼容性错误，不能静默丢弃排除规则或正则语义。

### 5.5 成功与幂等边界

3.1.18 响应 `status == true` 即表示 AutoBangumi 接受请求；订阅 ID 为可选字段，不再作为通用成功前提。结果保存继续使用 MiGuOrca 的稳定 `ab_submit_result`，没有外部 ID 时允许 `ab_subscription_id = null`。

Stage 20 的 `SUBMITTING`、`SUCCEEDED`、`RESULT_PERSIST_FAILED` 和人工恢复边界保持不变；不因新 adapter 自动重试不确定写结果。

## 6. 连接测试

新增 request-scoped AutoBangumi 连接测试 API，与 qBittorrent 测试体验一致：

1. 校验并构造认证配置。
2. 登录或使用 API token。
3. 只调用状态/版本等只读接口。
4. 返回脱敏摘要：`reachable`、公开 `version`、`auth_mode` 中文标签、`adapter`、`submit_supported`。
5. 不返回 token、Cookie、用户名、密码、完整地址、原始响应或完整失败 URL。

真实局域网烟雾测试只能验证登录、状态和只读列表；自动化与 Ralph 不得调用真实订阅写接口。真正提交由用户在 Web UI 对已接受 Request 显式确认。

## 7. Web UI

Settings 的 AutoBangumi 分区在没有 `request_id` 时也显示“测试连接”；存在已接受 Request 时额外显示“提交订阅方案”。字段：

1. 服务地址。
2. 认证方式，默认“账号密码”，可切换“API Token”。
3. 账号密码模式：用户名、密码。
4. API Token 模式：token。
5. 测试连接按钮、脱敏结果区。
6. 提交按钮及显式确认。

连接成功或提交成功后清空全部敏感字段；失败时可保留当前输入便于修正，但不得复制到通知、DOM data attribute、URL、localStorage/sessionStorage、history 或 trace。

批量提交前队列复用相同认证组件/配置契约，不保留旧的 endpoint/token 专用表单。

## 8. 安全与错误契约

1. 密码、token、Cookie、Authorization header、用户名、完整服务地址、原始响应体和完整失败 URL不得进入 API response、错误 details、日志、Request、AB result、队列、浏览器 storage、URL、截图或 trace。
2. HTTP client 禁止把认证 header/Cookie 跟随到不同 origin；重定向默认拒绝或严格限制同 origin。
3. 登录失败统一为认证失败；连接、超时、协议不兼容、规则不可表达分别使用稳定错误类型，详情只含类别和安全状态码。
4. 测试 fixture 使用虚构地址和凭据；不得把用户提供的局域网地址或账号密码写入仓库。
5. 登录 token/Cookie 只保存在一次请求内的 client/session，操作完成即释放。

## 9. Ralph User Stories

### US-173：重构 AutoBangumi 配置与适配器契约

建立 `password` 默认模式与 `api_token` 模式的判别配置，规范化服务根地址，拒绝混合字段、URL userinfo/query/fragment 和未知模式。保持 CLI/Web/批量入口可共享且敏感值 request-scoped。

### US-174：实现 3.1.18 登录会话与只读能力探测

实现表单登录、token Cookie 会话、同 origin/无危险重定向限制，以及状态/版本只读探测。用 transport fixture 覆盖登录成功、401、超时、非法响应和凭据不泄露。

### US-175：实现 3.1.18 订阅 payload 与响应适配

把已接受 Request 映射到 `/api/v1/rss/subscribe` 的 `{data, rss}`，显式处理不可表达筛选规则，并以 `status` 判断成功、允许无订阅 ID。不得调用真实实例写接口。

### US-176：保留新版 API Token/Bearer 兼容模式

实现与 legacy adapter 隔离的 Bearer 认证策略和能力状态。只有有明确契约覆盖的 adapter 才允许提交；未知版本/写契约返回“连接成功但暂不支持提交”。

### US-177：增加 AutoBangumi 只读连接测试 API

提供单一/批量 UI 可复用的 request-scoped 测试入口，返回版本、认证模式、adapter 和是否支持提交的脱敏摘要；补齐 API、安全和失败分类测试。

### US-178：重构 Settings 与批量认证界面

默认显示账号密码认证，支持切换 API Token；服务地址使用用户术语。测试连接不需要 Request，提交仍要求已接受 Request和显式确认；用真实 Chromium 验证字段切换、清理、可访问性与敏感数据边界。

### US-179：接通单个与批量真实提交编排

让单个 submit、批量 submit/retry 统一使用新 adapter，保留 Stage 20 队列幂等和恢复语义。通过 fake 3.1.18 transport 完整验证登录 → submit，并证明单项失败不阻塞批量后续项。

### US-180：Stage 24 文档、安全回归与实机只读验收（已完成）

同步项目文档，运行完整测试与真实 Chromium；提供不含真实凭据的手动验收说明。允许对显式提供的实例执行只读连接烟雾测试，但禁止自动创建订阅。

## 10. 验收基线

1. `uv run python -m compileall -q src tests` 通过。
2. `uv run pytest -q` 通过。
3. `node --check src/apps/migu_orca_web/static/app.js` 通过。
4. `uv run pytest tests/browser/ -q` 在真实 Chromium 运行且不整体 skipped。
5. fixture 端到端覆盖账号密码登录、Cookie 认证、3.1.18 payload/响应、Bearer 能力边界、单个提交、批量提交和连接测试。
6. 自动化不访问真实 AutoBangumi 写接口；实机只读烟雾不输出或持久化凭据。
7. README、主 PRD、Future Stages、backlog、Stage 24 PRD 和 M10/M12/M13/M14 文档一致。

Stage 24 完成标志（已达成）：用户在 Settings 填写服务地址和默认账号密码即可先验证 AutoBangumi 连接，再对已接受 Request 显式提交；3.1.18 使用经过验证的 Cookie 与 RSS subscribe 契约，新版 token 模式具有明确能力边界；单个/批量队列保持幂等与脱敏，且任何凭据都不落盘。

## 11. 手动只读验收

仅当操作者显式提供自己的实例和凭据时，可在 `/settings#auto-bangumi` 选择认证模式并点击“测试连接”。确认摘要只显示连通性、公开版本、认证方式、adapter 和提交能力；不要记录、截图或复制服务地址、账号、密码、token、Cookie、Authorization 或原始响应。

本阶段的 Ralph 与自动化只运行 fixture/Chromium 回归，不使用真实实例，也不会调用订阅写接口。真实订阅只能由用户在已接受 Request 上通过页面确认后自行执行。
