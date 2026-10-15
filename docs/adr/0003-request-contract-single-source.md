# 请求契约的单一来源是 schemas.py + 已评审细化白名单

[Issue #171](../api/openapi-request-body-equivalence-171.md) 之前，`docs/api/openapi.json` 的 requestBody 是
`schemas.py` 的手写副本，两份副本已经漂移（`local_plan`、`submission_mode`、retry 的
`connection_ref` 等）。#171 让「能执行的」当源、「被生成的」当产物；
[Issue #203](https://github.com/Ghostning233/migu_orca/issues/203) 补上同一方向上的
路径参数与条件必需约束。本决策固化这条边界，防止第二结构源以「文档更好看」为名回流。

## 决策

1. **结构只有两个来源，派生方向单向。** `schemas.py` 的 pydantic 模型（路由真正执行的校验器）
   提供字段名、类型、`required`、`enum`、`default`、`additionalProperties`；Flask `url_map`
   的 URL rule 提供路径参数。`openapi_gen.py` 的 `_REFINEMENT_ALLOWLIST` 是唯一允许的例外。
   生成产物（`docs/api/openapi.json`、`frontend/src/api/generated/api.ts`）永远由
   `uv run migu-orca-openapi` / `npm run api:generate` 重新生成，不手工编辑。
2. **路径参数从 URL rule 派生。** registry 的 `in: path` 条目只允许 `name`/`in`/`description`
   ——即只允许**文档覆盖层**；`required` 与 `schema` 由生成器从 URL rule 补齐。声明的 path
   参数集合必须等于 URL rule 的 `{param}` 集合：多余或改名由生成器直接抛错，缺失由 URL rule
   兜底，三种方向都有一致性测试。query 参数声明不在本决策范围内。
3. **覆盖层只许文档键。** 请求体 overlay 只接受 `description`/`example`/`x-request-scoped`/
   `x-legacy` 一类文档键（`properties`/`items` 作为容器仅用于定位字段）。出现 `type`/
   `required`/`enum` 等结构键时合并 fail closed（`_merge_overlay` 抛错）。
4. **细化白名单的评审规则。** 只有 pydantic 无法投影、且由运行时真的执行的规则才能登记：
   - 规则必须对应一个 `model_validator`/服务端业务校验，并有真实 route 的 400 对照用例；
   - 键登记在 `_REFINEMENT_ALLOWLIST`（`<endpoint>|<path>`、`|merge:<path>`、
     `|required+=<name>`）；未登记的细化让 `_build_openapi()` 抛错，宁可生成失败也不产出第二源；
   - `merge` 式细化只允许**追加** `allOf`/`anyOf`/`oneOf`/`not`/`if`/`then`/`else`；不允许
     新增或覆盖属性名。条件（`if`/`then`/`else`）子树同样只接受约束键，`properties` 只允许
     作 `const`/`enum` 分支判别且字段名必须已存在于模型，任意位置的 `required` 也只能引用
     已存在的属性名，不得重述属性类型；
   - 能下沉到模型同一 schema 内表达的规则优先下沉，细化只处理跨字段/分支语义。
5. **不在 `_ENDPOINTS` 重写结构。** 维护约束：加字段先改 `schemas.py`；加端点先确认 URL rule
   与路径参数；跨字段规则先核实运行时 validator，再作为已评审 `merge` 细化加入并补对照用例。
   `if`/`then`/`else` 是纯文档投影，不改变任何运行时行为，也不得为它放宽或改写运行时校验。

## 后果

- 生成客户端可以从契约构造全部 29 个 requestBody 端点的 URL（#171 发现的 12 个缺失端点补齐）。
- `delete-plan`/`recover`/`resubmit` 的「何时必需、何时禁止」在文档中可直接读出，并由
  `tests/api_contract/test_openapi_conditional_required.py` 与真实 route 的 400/404 对照冻结。
- 已知不精确处（**不修**，只登记）：JSON Schema 的 `required` 只看键是否存在，运行时校验器比较
  值是否为 `None`。因此显式 `null` 与「未提供」不等价，少数分支会出现「文档判定」与运行时相反
  的结果。要逐字等价就必须在细化里重述属性类型，正是本决策禁止的第二结构源；
  `tests/api_contract/test_openapi_conditional_required.py` 为每个端点族冻结一个**代表性方向**，
  其余已知形状列在下方「已知残留」，不被静默掩盖。
- `delete-plan` 故意没有 `else`：模型在 `delete_external=false` 时仍接受
  `connection_ref`/`configuration_revision`，补一个「其它分支禁止携带」的 `else` 会与运行时
  validator 冲突。

## 已知残留（后续票候选）

1. **未逐一冻结的 null 形状。** 除测试已冻结的代表性方向外，以下形状同样由「`required` 只看键
   存在」造成，行为已实测但未写成用例：`delete-plan` 且 `delete_external=true` 时
   `connection_ref=null`、以及二者同为 `null`；`recover` 且 `action=VERIFY_EXTERNAL` 时
   `configuration_revision=null`、以及二者同为 `null`；`resubmit` 且 `confirm=true` 时二者同为
   `null`；`recover` 且 `action=AUTO` 时二者同为 `null`。前五者运行时 400、文档判定「满足」，
   最后一者运行时 404、文档判定「禁止」。补齐这些用例属独立票，本决策只要求它们被登记而非
   被当作已覆盖。
2. **`recover` 的 `MARK_* → confirm=true` 未在契约表达。** 运行时要求
   `action` 为 `MARK_SUCCEEDED`/`MARK_FAILED` 时 `confirm` 必须为 `true`（无 `confirm` 实测
   400 `data_validation_errors`）。该规则实际有两个强制点，且都在签约模型之外：
   - **handoff 模型（回答 HTTP 400 的那一处）**：`SavedTrackingRecoveryInput._manual_confirmation`
     （`schemas.py:623` 起）在 `confirm is not True` 时抛 `confirm must be true`。路由
     `routes_tracking.py:349` 会把已通过 `TrackingRecoverPayload` 的载荷重新
     `SavedTrackingRecoveryInput.model_validate(...)`，所以真实请求在这里被拦下。
   - **service 层防御**：`tracking_recovery_service.py:392-398` 的
     `manual and confirm is not True` 抛 `Stage1Error("tracking_confirmation_required", …)`
     （第 394 行是 error_type），覆盖直接调用 service 的路径；
     `tracking_saved_recovery_service.run_saved_tracking_recovery` 只是入口并委派给它。
   **分层原因**：签约 requestBody 的来源模型是 `TrackingRecoverPayload`（#171 单一来源原则），
   上述两处都属于 handoff/service 层；为它们在 `_ENDPOINTS`/细化里重述结构会重新制造第二源，
   因此本票只登记不改。若产品要求客户端可见该约束，应作为独立票先确认来源模型边界再评审加入。
