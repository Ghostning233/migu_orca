# 响应 DTO 校验只在测试期生效

[Issue #172 的调查](../api/response-dto-runtime-audit-172.md) 证实：`api_contract.py` 的
`ok_result` 从未把 success DTO 接回运行时（全仓库零调用者），docstring 宣称的「出现意外字段就大声
失败」并不成立；用真实响应逐端点 `model_validate` 的实测同时暴露两处真实漂移——
`POST /api/v1/batches/parse` 的 `preference_hits` 在偏好回退时是 `null`，四个管理写多出内部字段
`outcome`。[Issue #204](https://github.com/Ghostning233/migu_orca/issues/204) 采纳「选项 3：仅测试期
校验」：把那次调查的一次性审计钩子产品化为 `tests/api_contract` 的契约夹具、修掉两处漂移，并让
`ok_result` 不再声称运行时白名单。本决策固化这条边界。

## 决策

1. **响应白名单的执法点是测试，不是运行时。** 每个 `/api/v1` 端点的 success DTO 由
   `openapi_gen._ENDPOINTS[...]["success"]` 声明；`tests/api_contract/conftest.py` 的 autouse 夹具
   钩住 `Flask.process_response`，对**真实 route/serializer 产出**的成功信封（`ok is True`）逐端点
   `model_validate`。`tests/api_contract/test_zz_response_dto_audit.py` 在整套 `tests/api_contract`
   跑完后 fail closed：声明了 success DTO 的端点必须全部被观测到且全部通过；未观测、未登记
   （JSON 成功信封却查不到 success DTO）或校验失败都让用例变红。夹具只作用于本包，不改变任何运行时
   行为，也不把校验结果写进响应或日志。
2. **`ok_result` 只负责信封，不负责校验。** 它不再接受 `dto` 参数，也不再
   `model_validate`；仓库内不再保留「声称运行时校验」的死接口。
3. **漂移按契约的真实来源修，不按运行时的当前字节改。**
   - `BatchParseItemDTO.preference_hits` 改为 `list[dict[str, Any]] | None = None`，与
     `serializers._serialize_preference_application` 的既有语义（偏好不可用时
     `applied_preferences` 与 `preference_hits` 同时为 `None`）以及前端既有的
     `item.preference_hits ?? []` 一致；
   - `routes_tracking._management_result()` 不再返回 `outcome`：`management_status` /
     `safe_message` / `needs_manual` 已表达同一语义，生成类型与前端从未消费它。
4. **宽松 DTO 保持宽松。** `_SnapshotBase`（`extra="allow"`）的声明字段只参与类型检查——它们本就
   允许引擎快照增加安全字段；测试期校验不得把它当作「白名单防泄漏」，也不得为它收紧 `extra`。
5. **生成产物跟随契约。** `docs/api/openapi.json` 与 `frontend/src/api/generated/api.ts` 照常由
   `uv run migu-orca-openapi` / `npm run api:generate` 重新生成，不手工编辑。

## 为什么不接回运行时（选项 1）

调查已实证：把 `ok_result(result, dto)` 接回运行时，上述两处漂移不会表现为可识别的服务端契约错误，
而是被 `extensions/flask_api/api.py:handle_exception` 归类为 **HTTP 400 `data_validation_errors`**
——把一次已经完成的服务端操作说成客户端输入错误，客户端可能据此改参数或重试。测试期校验用**同一份
证据面**（真实响应 + 同一批夹具）在 CI 里变红，不改变任何响应字节、状态码或错误契约，因此可以先拿到
收益，把风险留给接回运行时的那张票。

## 日后要接回运行时需要的前置

1. 漂移清零（本票已做），并且测试期审计在接线前保持全绿，作为接线安全网；
2. 改掉把管理写路径短路成 3 键 dict 的测试替身
   （`src/apps/migu_orca_web/tracking_management_routes_test.py`），让替身也走
   `_management_result()` 的完整序列化，否则运行时校验会让该用例因缺
   `safe_message`/`tracking` 而假红并掩盖真实失败；
3. 把「契约违规」分类为服务端错误（5xx + 独立 `error_type`），与输入校验的 400 分开，
   不再复用 `data_validation_errors`；
4. 明确严格/宽松两套制度：只有 `extra="forbid"` 的严格 DTO 才承担 fail-closed 防泄漏职责，
   `_SnapshotBase` 无论哪一阶段都只能是「测试期 + 生成类型」的作用。

## 后果

- 两处漂移在 CI 可见：偏好回退分支（`preference_hits == null`）与四个管理写的真实成功路径都有显式
  用例，不再只是「生成类型与运行时不一致」的隐患；
- 覆盖面受夹具可达路径限制：损坏 JSON、迁移告警、遗留回退等未被夹具触发的分支不会暴露其漂移；
  另外三类响应本来就不在覆盖内——SSE 帧（`Accept: text/event-stream` 的表示）与错误信封
  （`ok:false`）不是 success envelope，`success=None` 的二进制 poster 端点则以显式 `responses`
  声明、不走 JSON envelope。这些盲区正是选项 1 相对测试期校验的固有优势，也是接回前必须补齐的证据；
- 运行时零行为变化（除两处契约修正：删除 `outcome`、`preference_hits` 可空），不引入新的失败模式。
