# Issue #171 等价性报告：requestBody 从 `schemas.py` 派生

- 关联 Issue：[#171 OpenAPI 请求体从 schemas.py 派生并保留手写描述](https://github.com/Ghostning233/migu_orca/issues/171)
- 参照产物：`docs/api/openapi.json` @ `c54655d`（#169 + #184 合并后、#171 之前）
- 迁移范围：`_ENDPOINTS` 中全部 **29** 个带 JSON requestBody 的端点（29/29，无遗漏、无静默跳过）
- 并入 `origin/main` 时新增的 `POST /…/resubmit`（#184）也仍是手写 requestBody：CI 上的生成期守卫
  直接把它拦下（22 个用例红），本次一并迁移到派生管道（模型 `TrackingResubmitPayload` 已存在）。
- 结论：
  - 手写中文 `description` / `example` / `x-request-scoped` / `x-legacy` **零丢失**（文档差异仅由字段本身变化引起，见 §3）；
  - **49** 处结构差异、**5** 处示例差异，全部在 §3 逐类解释，无未解释差异；
  - 无法由 pydantic 投影的结构约束收敛为 **7** 条已评审细化（§4），并由生成器与契约测试双重 fail closed。

## 1. 变更前的双源问题

同一个请求接口此前有两个手写源，且没有任何测试比对二者：

| 来源 | 角色 |
| --- | --- |
| `src/apps/migu_orca_web/schemas.py` | 运行时真正的校验器（路由 `model_validate`） |
| `src/apps/migu_orca_web/openapi_gen.py` 的 `_ENDPOINTS[*]["requestBody"]` | 无人比对的文档副本，进 `docs/api/openapi.json` 与生成客户端 |

两份副本已经漂移：`local_plan`、`submission_mode`、retry 的 `connection_ref`/`configuration_revision`
等等（见 §6）。本票让「能执行的」当源（`schemas.py`），「被生成的」当产物。

## 2. 派生管道

`_ENDPOINTS[*]["requestBody"]` 现在是一个 `_RequestBodySpec`（工厂 `_rb()`），只允许携带两类信息：

1. **文档覆盖层 `overlay`**：中文 `description`/`example` 与 `x-request-scoped`/`x-legacy` 安全标记。
   合并前先生成模型结构，合并只写文档键，不产生结构。
2. **已评审结构细化 `replace` / `required_extra`**：pydantic 无法投影的约束（见 §4），
   逐条登记在 `_REFINEMENT_ALLOWLIST`。

生成顺序（`_request_body_schema`）：

```
schemas.py 模型
  → model_json_schema() + _dereference()（复用既有管道）
  → _normalize_derived()：结构归一化（§5）
  → 剔除 URL 路径参数（视图会把 path args 合并进 body，它们不是 body 字段）
  → 应用已评审细化（replace / required_extra）
  → 合并文档覆盖层
  → _request_body()：附 summary 作为 body 级 description，并按 schema 生成示例
```

`_build_openapi()` 对每个端点调用 `_assert_reviewed_refinements(key, spec)`：出现未登记的结构细化
直接抛错，生成器不会静默产出第二源。

## 3. 差异分类（49 结构 + 5 示例）

| 类别 | 行数 / 端点数 | 差异 | 判定 |
| --- | --- | --- | --- |
| **A** 收紧额外字段 | 11 / 10 | `additionalProperties: <absent> → false` | 模型是 `extra="forbid"`，运行时确实拒绝未知字段；旧文档漏写。**该收紧** |
| **B** `const` 补 `type` | 8 / 7 | `properties.confirm.type: <absent> → "boolean"` | 旧文档只写 `const: true`；派生同时给出 `type`。语义不变，更完整 |
| **C** `enum` 改 `const` | 8 / 4 | `confirm.enum: [true] → <absent>` + `confirm.const: <absent> → true` | 旧文档 4 个端点用 `enum`、其余用 `const`，不一致；`json_schema_extra` 统一为 `const`。语义等价 |
| **D** 可空性变准确 | 15 / 7 | 见下表 | 模型是 `T | None`；旧文档写成不可空。**该保持模型口径** |
| **E** 补文档化已存在的字段 | 2 / 2 | `POST /requests` 的 `storage_dir`；batch-submit 的 `submission_mode` | 运行时接受但旧文档未列出 |
| **F** 补「必需但未定义」字段 | 2 / 1 | retry 的 `connection_ref` / `configuration_revision`（旧文档在 `required` 里列出、`properties` 里没有） | 修正无效契约 |
| **G** 条件必需回落为可选 | 1 / 1 | delete-plan 的 `required` 去掉 `connection_ref`/`configuration_revision` | 见 §6.3：条件约束 JSON Schema 未表达 |
| **H** 删除运行时拒绝的字段 | 1 / 1 | modify 的 `local_plan` | 见 §6.1，**既有缺陷** |
| **I** 默认值显式化 | 1 / 1 | recover `confirm.default: <absent> → false` | 模型默认值，补全 |
| **DOC** 示例变化 | 5 / 4 | 见 §3.2 | 由 A–I 派生，示例仍为虚构脱敏值 |

### 3.1 D 类明细（可空性）

```text
POST /api/v1/batches/{batch_id}/save-confirm      properties.item_ids.type              "array"   → ["array", "null"]
POST /api/v1/requests                             properties.candidate_context.type     "string"  → ["string", "null"]
POST /api/v1/requests                             properties.mikan_bangumi.type         "string"  → ["string", "null"]
POST /api/v1/requests                             properties.season_confirmation.type   "integer" → ["integer", "null"]
POST /api/v1/requests/{request_id}/cancel         properties.cancel_reason.type         "string"  → ["string", "null"]
POST /api/v1/settings/autobangumi[/test]          config.oneOf[*].properties.{username,password,token}.type   "string" → ["string", "null"]
POST /api/v1/tracking/items/{tracking_id}/delete-plan  properties.connection_ref.type   "string"  → ["string", "null"]
POST /api/v1/tracking/items/{tracking_id}/delete-plan  properties.configuration_revision.type "integer" → ["integer", "null"]
POST /api/v1/tracking/items/{tracking_id}/resubmit        properties.previous_operation_id.type "string"  → ["string", "null"]
POST /api/v1/tracking/items/{tracking_id}/resubmit        properties.connection_ref.type         "string"  → ["string", "null"]
```

`AutoBangumiConfigPayload` 的 `username`/`password`/`token` 在模型里是 `str | None`；`model_validator`
在所选 `auth_mode` 分支上要求非空。派生保留 nullable，由 `oneOf` 分支的 `required` 表达「必须出现」，
「不得为 null」由校验器保证——这是 JSON Schema 无法无损投影的部分（§4）。

### 3.2 DOC 类明细（示例）

```text
POST /api/v1/tracking/batch-submit              example.submission_mode        <absent> → "CONTINUE_TRACKING"   （E 类新字段）
POST /api/v1/tracking/items/{tracking_id}/delete-plan  example.connection_ref   "示例"   → null                  （F/G 类不再必需）
POST /api/v1/tracking/items/{tracking_id}/recover      example.configuration_revision  null → 1                    （可空联合取非空分支）
POST /api/v1/tracking/items/{tracking_id}/retry        example.connection_ref / configuration_revision  <absent> → "示例" / 1
```

示例仍全部为虚构/脱敏值：凭据字段与 `storage_dir` 不参与示例，`example.invalid` 仍为文档保留域。

## 4. 已评审的结构细化（pydantic 无法投影）

`_REFINEMENT_ALLOWLIST`（生成器 fail closed + 契约测试冻结）：

| 端点 | 细化 | 为什么不能派生 |
| --- | --- | --- |
| `PUT /api/v1/settings/autobangumi` / `POST …/test` | `properties.config` | `AutoBangumiConfigPayload.model_validator` 的 `password`/`api_token` 判别联合；分支属性仍取自模型字段 |
| `POST /api/v1/tracking/items/<tracking_id>/modify` | 根节点 | `TrackingModifyPayload` 把 `target_scope` 绑定到 patch 家族的跨字段校验；`allOf`/`anyOf` 由 `model.model_fields` 组装 |
| `POST /api/v1/requests/preview-modify` | `properties.patch` | 模型刻意用 `dict[str, Any]`（服务端抛中文 `invalid_modify_patch_field`），发布形状由服务规则决定 |
| `POST /api/v1/preferences` / `POST /api/v1/corrections` | `properties.preferences` / `properties.correction` + `required+=` | 模型刻意用 `Any`（同上）；路由在 `None` 时抛业务 `validation_error`，因此文档必须标记 required |

`_any_of_patch_node()` 只从 `model.model_fields` 取字段名与约束，patch 的 `allOf`/`anyOf` 编码中不含手写字段表。

## 5. 归一化规则

派生结构统一应用以下规则（结构归一化，不做「生成后字符串处理」）：

1. 丢弃 pydantic 元数据 `title`；丢弃模型 docstring 派生的 `description`
   （**文档一律来自覆盖层**，避免开发者注释意外进入公开契约）；
2. 丢弃 `default: null`（`null` 联合分支已表达）；
3. 丢弃 `additionalProperties: true`（JSON Schema 默认值）；
4. `T | None` 联合渲染为 `type: [T, "null"]`（保持旧文档风格）；
5. `properties` 映射按**映射**遍历：字段名 `title`/`description` 不会被误当元数据丢弃
   （迁移中曾因此丢掉 `title: string`，已由等价性报告发现并修复）。

## 6. 迁移暴露的既有缺陷（本票不改，另票处理）

### 6.1 modify 端点在运行时拒绝 `local_plan`（用户可见缺陷）

`TrackingModifyPayload` 是 `extra="forbid"` 且没有 `local_plan` 字段，而前端
`useTrackingWriteSession.ts` 仍会发送它，旧 OpenAPI 也把它写进契约：

```console
$ PYTHONPATH=src uv run python - <<'PY'
from apps.base import create_app
c = create_app("testing").test_client()
print(c.post("/api/v1/tracking/items/trk-1/modify", json={
  "target_scope": "SUBSCRIPTION", "expected_revision": 1, "idempotency_key": "k-1",
  "confirm": True, "connection_ref": "11111111-1111-4111-1111-111111111111",
  "configuration_revision": 1, "patch": {"expected_folder_name": "x"},
  "local_plan": {"expected_folder_name": "x"}}).get_json())
PY
# 400 {'error_type': 'data_validation_errors', 'error_data': {'errors': [{'field': 'local_plan',
#     'message': 'Extra inputs are not permitted'}]}}
```

浏览器用例 `tests/browser/test_app_tracking_workbench.py::TestPlanApply` 用 `page.route` 拦截
`**/api/v1/**`，只断言请求体里带 `local_plan`，因此真实服务端的 400 不被覆盖。
#171 只能让文档说真话（派生后 `local_plan` 从契约移除）；**修复运行时要另开票据**。

> **状态更新（本报告快照 `c54655d` 之后）**：该运行时缺陷已由 **#202** 修复——
> `TrackingModifyPayload` 重新接受 `local_plan`，契约只在 modify 的 SUBSCRIPTION 分支
> 暴露该字段（`ASSOCIATED_RSS` 携带它仍 400），并新增后端 HTTP 契约用例覆盖落盘提升、
> 结果待确认不提升与绑定独立。上面这段仍是对当时快照的原有描述，保留以便追溯。

### 6.2 11 个端点在 OpenAPI 里没有声明 URL 路径参数

`check` / `delete-plan` / `recover` / `retry` / `revalidate` / `submit` / `batch save-confirm`
及 5 个 `requests/{request_id}/*` 端点只声明了 requestBody，没有 `in: path` 参数。生成的客户端因此
无法从契约构造路径。属既有缺口，本票不改（避免顺带改动契约其他部分）。

### 6.3 条件必需约束未在文档中表达

`delete-plan` 的 `connection_ref`/`configuration_revision` 只在 `delete_external=true` 时必需，
`recover` 只在 `VERIFY_EXTERNAL` 时必需且其它动作不得携带，`auto bangumi` 凭据按 `auth_mode` 分支必需。
JSON Schema 可用 `if/then` 表达一部分，但 pydantic 无法派生；本票选择「模型口径 + 报告说明」，
不新增未评审的手写结构。若后续要求精确的客户端约束，应作为独立细化逐条加入 `_REFINEMENT_ALLOWLIST`。

### 6.4 retry 契约曾「必需但未定义」

旧 `retryTrackingItem` 的 requestBody 把 `connection_ref`/`configuration_revision` 列入 `required`
却没有定义其 `properties`（`openapi-typescript` 生成 `unknown`）。派生后二者恢复为
`format: uuid` / `minimum: 0` 的正确定义（F 类）。

## 7. 复现命令

```console
# 参照产物（#169 + #184 合并后、#171 之前）
git show c54655d:docs/api/openapi.json > /tmp/openapi-before-171.json

# 当前产物
uv run migu-orca-openapi

# 逐端点逐字段差异报告
uv run python tools/openapi_request_body_equivalence.py \
    /tmp/openapi-before-171.json docs/api/openapi.json

# 两道门禁
uv run migu-orca-openapi --check
cd frontend && npm run api:check
```

## 附录 A：逐端点逐字段差异（工具输出）

reference: `/tmp/openapi-before-171.json`
current:   `docs/api/openapi.json`

- endpoints with a request body: 29 (reference) / 29 (current)
- only in reference: none
- only in current:   none

### DELETE /api/v1/settings/autobangumi

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `properties.confirm.type`: `<absent>` -> `"boolean"`

### POST /api/v1/batches/parse

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `additionalProperties`: `<absent>` -> `false`

### POST /api/v1/batches/{batch_id}/save-confirm

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `properties.item_ids.type`: `"array"` -> `["array", "null"]`

### POST /api/v1/corrections

No differences.

### POST /api/v1/mikan/candidates

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `additionalProperties`: `<absent>` -> `false`

### POST /api/v1/preferences

No differences.

### POST /api/v1/requests

5 structural / 0 documentation / 0 metadata difference(s).

#### structure (5)

- `additionalProperties`: `<absent>` -> `false`
- `properties.candidate_context.type`: `"string"` -> `["string", "null"]`
- `properties.mikan_bangumi.type`: `"string"` -> `["string", "null"]`
- `properties.season_confirmation.type`: `"integer"` -> `["integer", "null"]`
- `properties.storage_dir`: `<absent>` -> `{"type": ["string", "null"]}`

### POST /api/v1/requests/preview-modify

No differences.

### POST /api/v1/requests/save-confirm

No differences.

### POST /api/v1/requests/{request_id}/accept

No differences.

### POST /api/v1/requests/{request_id}/cancel

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `properties.cancel_reason.type`: `"string"` -> `["string", "null"]`

### POST /api/v1/requests/{request_id}/delete

No differences.

### POST /api/v1/requests/{request_id}/modify

No differences.

### POST /api/v1/settings/autobangumi/probe

No differences.

### POST /api/v1/settings/autobangumi/test

3 structural / 0 documentation / 0 metadata difference(s).

#### structure (3)

- `properties.config.oneOf[0].properties.password.type`: `"string"` -> `["string", "null"]`
- `properties.config.oneOf[0].properties.username.type`: `"string"` -> `["string", "null"]`
- `properties.config.oneOf[1].properties.token.type`: `"string"` -> `["string", "null"]`

### POST /api/v1/tracking/batch-submit

5 structural / 1 documentation / 0 metadata difference(s).

#### structure (5)

- `additionalProperties`: `<absent>` -> `false`
- `properties.confirm.const`: `<absent>` -> `true`
- `properties.confirm.enum`: `[true]` -> `<absent>`
- `properties.items.items.additionalProperties`: `<absent>` -> `false`
- `properties.submission_mode`: `<absent>` -> `{"default": "CONTINUE_TRACKING", "enum": ["CONTINUE_TRACKING", "DOWNLOAD_EXISTING"], "type": "string"}`

#### documentation (1)

- `example.submission_mode`: `<absent>` -> `"CONTINUE_TRACKING"`

### POST /api/v1/tracking/items/{tracking_id}/check

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `additionalProperties`: `<absent>` -> `false`

### POST /api/v1/tracking/items/{tracking_id}/delete-external

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `properties.confirm.type`: `<absent>` -> `"boolean"`

### POST /api/v1/tracking/items/{tracking_id}/delete-plan

5 structural / 1 documentation / 0 metadata difference(s).

#### structure (5)

- `properties.configuration_revision.type`: `"integer"` -> `["integer", "null"]`
- `properties.confirm.const`: `<absent>` -> `true`
- `properties.confirm.enum`: `[true]` -> `<absent>`
- `properties.connection_ref.type`: `"string"` -> `["string", "null"]`
- `required`: `["confirm", "idempotency_key", "connection_ref", "configuration_revision"]` -> `["confirm", "idempotency_key"]`

#### documentation (1)

- `example.connection_ref`: `"示例"` -> `null`

### POST /api/v1/tracking/items/{tracking_id}/modify

3 structural / 0 documentation / 0 metadata difference(s).

#### structure (3)

- `oneOf[0].properties.confirm.type`: `<absent>` -> `"boolean"`
- `oneOf[0].properties.local_plan`: `{"type": ["object", "null"], "additionalProperties": false, "description": "issue #91：外部修改确认成功后同时提升的本地方案字段（身份字段不可编辑）。与 …` -> `<absent>`
- `oneOf[1].properties.confirm.type`: `<absent>` -> `"boolean"`

### POST /api/v1/tracking/items/{tracking_id}/recover

2 structural / 1 documentation / 0 metadata difference(s).

#### structure (2)

- `additionalProperties`: `<absent>` -> `false`
- `properties.confirm.default`: `<absent>` -> `false`

#### documentation (1)

- `example.configuration_revision`: `null` -> `1`

### POST /api/v1/tracking/items/{tracking_id}/refresh

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `properties.confirm.type`: `<absent>` -> `"boolean"`

### POST /api/v1/tracking/items/{tracking_id}/resubmit

3 structural / 0 documentation / 0 metadata difference(s).

#### structure (3)

- `additionalProperties`: `<absent>` -> `false`
- `properties.connection_ref.type`: `"string"` -> `["string", "null"]`
- `properties.previous_operation_id.type`: `"string"` -> `["string", "null"]`

### POST /api/v1/tracking/items/{tracking_id}/retry

5 structural / 2 documentation / 0 metadata difference(s).

#### structure (5)

- `additionalProperties`: `<absent>` -> `false`
- `properties.configuration_revision`: `<absent>` -> `{"minimum": 0, "type": "integer"}`
- `properties.confirm.const`: `<absent>` -> `true`
- `properties.confirm.enum`: `[true]` -> `<absent>`
- `properties.connection_ref`: `<absent>` -> `{"format": "uuid", "type": "string"}`

#### documentation (2)

- `example.configuration_revision`: `<absent>` -> `1`
- `example.connection_ref`: `<absent>` -> `"示例"`

### POST /api/v1/tracking/items/{tracking_id}/revalidate

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `additionalProperties`: `<absent>` -> `false`

### POST /api/v1/tracking/items/{tracking_id}/set-enabled

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `properties.confirm.type`: `<absent>` -> `"boolean"`

### POST /api/v1/tracking/items/{tracking_id}/submit

3 structural / 0 documentation / 0 metadata difference(s).

#### structure (3)

- `additionalProperties`: `<absent>` -> `false`
- `properties.confirm.const`: `<absent>` -> `true`
- `properties.confirm.enum`: `[true]` -> `<absent>`

### POST /api/v1/tracking/sync

1 structural / 0 documentation / 0 metadata difference(s).

#### structure (1)

- `properties.confirm.type`: `<absent>` -> `"boolean"`

### PUT /api/v1/settings/autobangumi

4 structural / 0 documentation / 0 metadata difference(s).

#### structure (4)

- `properties.config.oneOf[0].properties.password.type`: `"string"` -> `["string", "null"]`
- `properties.config.oneOf[0].properties.username.type`: `"string"` -> `["string", "null"]`
- `properties.config.oneOf[1].properties.token.type`: `"string"` -> `["string", "null"]`
- `properties.confirm.type`: `<absent>` -> `"boolean"`

### Summary

- structural differences: 49
- documentation differences: 5
