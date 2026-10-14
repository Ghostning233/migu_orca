# 请求契约的单一来源是 schemas.py + 已评审细化白名单

[Issue #171](../api/openapi-request-body-equivalence-171.md) 之前，`docs/api/openapi.json` 的 requestBody 是
`schemas.py` 的手写副本，两份副本已经漂移（`local_plan`、`submission_mode`、retry 的
`connection_ref` 等）。#171 让「能执行的」当源、「被生成的」当产物；[Issue #203] 补上同一方向上的
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
     新增或覆盖属性名。`properties` 只允许出现在条件子树里作 `const`/`enum` 分支判别，
     不得重述属性类型；
   - 能下沉到模型同一 schema 内表达的规则优先下沉，细化只处理跨字段/分支语义。
5. **不在 `_ENDPOINTS` 重写结构。** 维护约束：加字段先改 `schemas.py`；加端点先确认 URL rule
   与路径参数；跨字段规则先核实运行时 validator，再作为已评审 `merge` 细化加入并补对照用例。
   `if`/`then`/`else` 是纯文档投影，不改变任何运行时行为，也不得为它放宽或改写运行时校验。

## 后果

- 生成客户端可以从契约构造全部 29 个 requestBody 端点的 URL（#171 发现的 12 个缺失端点补齐）。
- `delete-plan`/`recover`/`resubmit` 的「何时必需、何时禁止」在文档中可直接读出，并由
  `tests/api_contract/test_openapi_conditional_required.py` 与真实 route 的 400/404 对照冻结。
- 已知不精确处（**不修**，只登记）：JSON Schema 的 `required` 只看键是否存在，运行时校验器比较
  值是否为 `None`。因此显式 `null` 与「未提供」不等价 —— `recover` 的
  `connection_ref: null`/`configuration_revision: null`、`resubmit` 的 `connection_ref: null`、
  `delete-plan` 的 `configuration_revision: null` 等少数分支会出现「文档判定」与运行时相反的
  结果。要逐字等价就必须在细化里重述属性类型，正是本决策禁止的第二结构源；这些分支改为由测试
  逐一冻结（含方向），而不是被静默掩盖。
- `delete-plan` 故意没有 `else`：模型在 `delete_external=false` 时仍接受
  `connection_ref`/`configuration_revision`，补一个「其它分支禁止携带」的 `else` 会与运行时
  validator 冲突。
