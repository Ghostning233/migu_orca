# MiGuOrca 架构与目录约定

## 1. 当前形态

项目采用本地优先的模块化单体结构。Flask 同时提供服务端页面与 JSON API，CLI 和 Web API 复用业务 engine 与存储适配器。当前不包含独立前端构建链、数据库、后台 worker 或多用户认证系统。

```text
CLI                     Flask/Jinja + 原生 JavaScript
 │                                  │
 └──────────── apps / Web API ──────┘
                    │
        batch / request / source 编排
                    │
   engines + shared contracts + external adapters
                    │
     本地 JSON storage / MiKan / AutoBangumi / qB
```

## 2. 分层职责

- `apps`：接收 CLI 或 HTTP 输入，编排用例并转换输出，不复制 engine 内的业务规则。
- `extensions/flask_api`：统一 JSON envelope、Pydantic 请求校验和异常脱敏。
- `*_engine`：封装业务能力、外部系统适配器和对应模型。
- `shared`：跨 engine 契约、错误、配置、日志、标题季数等基础能力。
- `tests/browser`：使用 Playwright 在真实 Chromium 验证 Web 用户旅程，默认以 fixture 和 route fake 隔离外部系统。

## 3. 当前目录与职责

| 目录 | 主要责任 |
| --- | --- |
| `apps/migu_orca_entry` | CLI、Request 生成总编排、显式 AutoBangumi 提交入口 |
| `apps/migu_orca_web` | Flask 页面、JSON API、Web 请求/响应适配与静态前端资源 |
| `extensions/flask_api` | API envelope、校验、异常转换和错误脱敏 |
| `batch_engine` | 批量输入、标题解析、查询计划、偏好应用、接受与提交队列 |
| `catalog_engine` | 静态 fixture catalog 与标题匹配 |
| `mikan_engine` | 真实 MiKan 搜索/详情/RSS 读取、候选缓存和安全封面缓存 |
| `rss_engine` | RSS 解析与种子筛选 |
| `subscription_engine` | 字幕组选择与文件夹命名 |
| `request_engine` | Request 契约、确认、取消、受限修改和摘要 |
| `ab_engine` | AutoBangumi 配置、认证 adapter、payload 与提交结果 |
| `qbittorrent_engine` | qBittorrent 配置和显式只读连接测试 |
| `storage_engine` | Request、history、AB result、queue、preference、correction 的本地 JSON 存储 |
| `shared` | 跨模块模型、错误、安全日志、标题季数与候选季数证据 |

## 4. 依赖规则

1. `apps` 可以依赖 engine、`shared` 和 Web extension。
2. `shared` 不得依赖 `apps` 或具体 engine。
3. engine 不得反向依赖 `apps`。
4. engine 之间只在已有明确用例关系时直接依赖；跨模块稳定数据优先放入 `shared` 契约。
5. 外部 HTTP、认证与存储细节留在对应 adapter/repository，不进入纯规则函数。
6. 不在多个 engine 中复制标题季数、Request 状态或提交状态模型。

当前存在的跨 engine 依赖包括 Request 使用订阅命名、RSS 使用 MiKan transport 数据、批量接受/提交使用 Request 与 AutoBangumi 能力、storage queue repository 使用批量队列模型。这些是现有用例关系，不代表可以任意增加双向依赖。

## 5. Web 边界现状

Web 页面已经通过 `/api/v1/*` JSON API 完成主要业务操作，但工程上仍未前后端分离：

- `/index` 与 `/settings` 由 Jinja 模板渲染。
- 两个页面共用 `static/app.js` 和 `static/style.css`。
- API 请求模型、序列化辅助和路由主要集中在 `apps/migu_orca_web/views.py`。
- `docs/api/` 尚无正式 OpenAPI 契约。

因此后续前端工程化应先固化 API 契约和服务端安全边界，再渐进替换页面；不得在没有兼容层的情况下同时重写 API 与全部用户旅程。

## 6. 状态与持久化

- 默认运行数据位于 `.migu_orca/storage`，不应提交 Git。
- Request、history、AB result、queue、preference 和 correction 分目录保存为 JSON。
- 候选缓存、候选选择 context 等短期状态当前位于单进程内存，不能假定天然支持多 worker。
- AutoBangumi 与 qBittorrent 凭据保持 request-scoped，不进入持久化、URL、浏览器 storage、日志或测试产物。

## 7. 测试与质量门禁

测试包括纯规则单元测试、fixture 解析、API/入口测试和 Playwright 浏览器测试。统一命令为：

```bash
uv run python -m compileall -q src tests
uv run pytest -q
uv run pytest tests/browser/ -q
node --check src/apps/migu_orca_web/static/app.js
```

浏览器不可用时允许明确记录 skip 原因，但不得把整体 skip 当作 UI Stage 的完成证据。

## 8. 拆分原则

满足以下条件之一时再拆分模块：

1. 出现独立外部系统适配边界。
2. 规则具有独立变化、替换或测试需求。
3. 当前文件已经同时承担 schema、路由、编排和序列化等多种职责。
4. 现有依赖导致循环、并发状态不安全或无法独立验证。

拆分应保持行为兼容和安全边界，不仅为了目录数量或 PRD 编号创建空层次。
