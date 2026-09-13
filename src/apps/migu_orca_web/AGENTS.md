# Web API Agent 规范

遵循根 [AGENTS.md](../../../AGENTS.md)；本文件只补充 Web 适配层约束。

## 分层与契约同步

- `schemas.py` 校验输入，`api_contract.py` 定义公开 DTO，`serializers.py` 和
  `tracking_serializers.py` 构造安全输出；`services.py`/`tracking_*_service.py` 编排用例。
  `routes_*.py` 只做入口适配，不复制规则、状态机、幂等或 revision 逻辑。
- Blueprint 定义在 `blueprints.py`；`views.py` 导入路由模块完成注册，
  包的 blueprints 由 `apps/registry.py` 收集。新增 route 不忘注册/清单。
- API envelope 统一；HTTP 错误分类复用 `extensions/flask_api/api.py:_error_http_status`，
  不在各 route 自建分类表；新增 envelope error_type 同步 `_ENDPOINTS` errors。
- 契约改动联动检查 schema/DTO、serializer、`openapi_gen.py`、endpoint inventory、
  OpenAPI、生成 TypeScript 类型、DTO/golden/runtime-consistency 测试；不得只改前端类型。
- DTO 白名单与 serializer 默认拒绝都要保留；部分兼容 DTO 允许额外安全字段，
  不误以为所有嵌套对象均严格，也不能把宽松 DTO 当作放出上游原始对象的许可。

## 存储与可靠性

- 所有 Web storage 使用 `services._storage_dir`；空值必须返回服务端根，而不是 None。
  绝对路径/穿越/符号链接逃逸拒绝，错误只含固定字段/原因，不回显路径。
- DraftStore 是进程级权威；修改走 CAS，保存走 reserve → persist → commit/release。
  写盘失败释放预留、保留草案；进行中/过期/重放不绕过校验；不接收完整客户端 Request。
- save-confirm 复用 `save_confirm_service.py` 的持久化幂等协调器；同键不同绑定拒绝，
  已保存确认失败按 saved Request 恢复，不重新生成第二份。批量逐条部分成功，不回滚成功项。
- 批量输入先按共享 splitter 检查 1～36 条，再做解析/外部访问；错误不回显原始输入。
- 已确认 Request → tracking 复用 `tracking_handoff.py`：ensure 不覆盖既有记录；
  tracking 写失败不回滚已确认方案，不伪造状态，后续访问可补偿。
- TrackingRecord/TrackingOperation 的 CAS/持久化由 repository 处理，外部写前持久化意图，
  写后回查并落安全结果；未知结果进入恢复，不能误记成直接可重试失败。
- 旧 submit/batch queue 复用统一 tracking submission/recovery，queue 只是兼容投影；
  已落盘成功不被旧投影降级。这是既有契约要求，不代表旧路径已全部满足；Stage 39 已授权目标
  为核对后退役旧 Web 写/队列端点，不修补并保留无用兼容路径；历史读取仍需可用。
- revalidate/AUTO 恢复纯本地；VERIFY_EXTERNAL 才携带临时 AB 配置做能力校验的只读恢复。
  管理写仅在精确 3.1.18 password 能力开放，read-before-write/confirm/key/revision 必须保留。
- 删除媒体参数在 adapter 固定 file=false，不能通过客户端输入覆盖；
  关联 RSS 操作只处理已映射单条集合，不扩大到全局对象。
- Stage 39 新增 AB 专用部署配置 repository，与业务 storage/profile 隔离，唯一允许保存 AB
  地址/账号/秘密；不从客户端选择配置根、不回显秘密、不把 snapshot 送入普通 repository。
  目标接口使用配置引用、operation/映射归属、CAS/lease 与同源/受信 Host 校验；当前尚未实现，
  具体边界见 [Stage 39 PRD](../../../docs/MiGuOrca_stage39_deployment_settings_PRD.md)。

## 展示与服务边界

- 列表/详情/全部信息复用安全 serializer/safe-info；自由文本二次脱敏，不 str(dict/list)。
  只放公开标题/安全计数/相对 profile/安全状态，不回传外部 ID、凭据、原始响应或完整 RSS URL。
  poster 仅允许同源 opaque 代理路径；“已更新集数”固定待开发。
- 候选查询复用共享名称查询计划，HTTP 200+FAILED 与 EMPTY 区分；
  返回安全 machine type/category，外部失败原因不降为一个无信息的通用文案。
- SPA fallback 仅 `/app/*`，不吞 API、poster、healthz/readiness；当前入口重定向到 add/settings。
  构建资产使用 immutable 内容哈希缓存，shell 用 no-cache，不提交 dist/sourcemap。
- healthz 不做 IO；readiness 只检查本地存储，不把能 ping 或本地就绪当作外部 HTTP 连接成功。

## 验证与参考

- Python 用 uv；指定受影响 pytest 用例 + Ruff。契约变更执行
  `uv run migu-orca-openapi`、`uv run migu-orca-openapi --check`，在 frontend 生成/检查客户端。
  完整门禁与发布权限按根规范和当前 PRD，不每次运行全量。
- monkeypatch 指向符号实际调用的模块，不是原定义处；明确测试是否真的进入目标边界。
  fixture 清理 DraftStore/context，用临时 Web root，不能创建/读取用户默认存储当测试数据。
- API/浏览器测试默认 fake transport/route mock 外部系统，不隐式写真实 AB 或 qB。
  需要真实诊断时先分 HTTP/上游/浏览器时限，日志只留状态、耗时和安全计数。

需要具体 seam/协议历史时按关键词查[旧 Web 实现参考](../../../docs/history/web_AGENTS_legacy_2026-09-13.md)
并核对当前代码/API；它不是新任务的实现范围或权限来源。
