# Issue #172 调查报告：响应 DTO 白名单能否在运行时生效

- 关联 Issue：[#172 调查：响应 DTO 白名单能否在运行时生效（ok_result 的处置）](https://github.com/Ghostning233/migu_orca/issues/172)
- 调查对象：`src/apps/migu_orca_web/api_contract.py` 的 `ok_result(result, dto)`（definition at `api_contract.py:1289`）
- 性质：**只读调查**。本报告不改源码、契约、测试或生成产物；仓库内唯一新增物就是本文档。
- 参照状态：`c54655d`（#169 + #184 合并后，含新增 `POST /…/resubmit`）上的 `/api/v1` 现状。

## 1. 结论摘要

1. `ok_result(result, dto)` 全仓库**零调用者**（`grep -rn ok_result src tests tools` 只命中定义），
   响应 DTO 白名单目前只在测试里生效；其 docstring 宣称的「出现意外字段就大声失败」在运行时并不成立。
2. 用现有夹具实测 **37/37** 个声明了 success DTO 的 JSON 端点（含专门补测的
   `cancel` 与 `tracking/sync` 成功路径）：**32 个端点全绿**，5 个端点出现 FAIL——
   其中 `POST /api/v1/batches/parse` 是 1 处真实漂移，4 个管理写端点在套件里的失败来自测试替身
   （真实路径另证 1 处 `outcome` 漂移）（§4、§5）。#184 新增的 `resubmit` 端点 12 次运行全绿。
3. 两处真实漂移：
   - `POST /api/v1/batches/parse`：`items[*].preference_hits` 运行时按设计是 `null`，
     但 `BatchParseItemDTO.preference_hits` 声明为不可空 `list`；
   - 四个管理写端点：真实响应带 `outcome`，但 `TrackingManagementResultDTO`（`extra="forbid"`）没有该字段。
4. 若把 `ok_result(result, dto)` 直接接回运行时，上述漂移不会表现为「可识别的服务端契约错误」，
   而是被 `extensions/flask_api/api.py:handle_exception` 归类成
   **HTTP 400 `data_validation_errors`**——把服务端漂移说成客户端输入错误（§5.4 有实证）。
5. **单一建议：选项 3「改为仅测试期校验」**（§6）。理由：它用同一套夹具把漂移固定在 CI，
   不改变任何运行时行为，也不会把一次成功的业务操作变成客户端眼里的 400；
   选项 1（接回运行时）只有在先修掉两处漂移、并把「契约违规」分类为服务端错误之后才是安全的升级路径。

## 2. 背景

`ok_result(result, dto)` 的意图是让响应 DTO 白名单在运行时生效：

```python
def ok_result(result: Any, dto: type[BaseModel] | None = None) -> Any:
    """Return a validated ``{ok: true, result}`` envelope.

    When ``dto`` is given the result is validated against it first, so a
    whitelisted result shape that gains an unexpected field fails loudly.
    """
```

但路由都直接返回 dict（`PostView.response()` → `ok_response(...)`），**没有一处传入 `dto`**：

```console
$ grep -rn "ok_result" src tests tools --include=*.py
src/apps/migu_orca_web/api_contract.py:1289:def ok_result(result: Any, dto: type[BaseModel] | None = None) -> Any:
```

于是「响应白名单」目前的价值只体现在两处：`docs/api/openapi.json` 生成的
TypeScript 类型，以及 `tests/api_contract/test_dto_contracts.py` 之类的静态断言。
真实响应是否仍然符合 DTO，没有任何检查。

## 3. 方法（可复现）

**不在测试里逐端点重造响应**，而是在**现有夹具产生的真实响应**上做校验：一个 pytest 插件钩住
`Flask.process_response`，对每个 `/api/v1` 的成功 envelope（`ok: true`）取出 `result`，
用 `_ENDPOINTS[key]["success"]` 声明的 DTO 调 `model_validate`——即补上
`ok_result(result, dto)` 今天没有做的那一步。全文见附录 A（约 80 行，可直接放进 `/tmp` 运行）。

```console
# 1) 非浏览器全量套件 + 审计钩子（35 个端点被观测）
mkdir -p ~/.cache/mo172 && cp <附录 A 的插件源码> ~/.cache/mo172/dto_audit.py
DTO_AUDIT_OUT=~/.cache/mo172/audit_full.json \
  PYTHONPATH=src:$HOME/.cache/mo172 uv run pytest -q -m "not browser" -p dto_audit

# 2) 补测套件未覆盖的两个成功路径（cancel / tracking-sync）+ 真实管理写路径
#    （临时测试文件，复用 tests/api_contract 的夹具与本地 AB 3.1.18 stand-in，运行后删除）
DTO_AUDIT_OUT=~/.cache/mo172/audit_gap.json \
  PYTHONPATH=src:$HOME/.cache/mo172 uv run pytest -q -p dto_audit \
  tests/api_contract/test_zz_dto_audit_gap172.py
```

- 全部外部系统都是 fake/localhost：MiKan 走静态夹具与既有 monkeypatch，
  Auto Bangumi 走 `tests/api_contract/test_tracking_confirmation_local_ab.py` 的
  `LocalAb318`（127.0.0.1 本地 stand-in）。没有隐式访问真实 MiKan / Auto Bangumi。
- 审计钩子只读响应，不改变任何断言；钩子自身 0 次报错。
- 覆盖：`_ENDPOINTS` 里 38 个 `/api/v1` operation 中，37 个声明了 success DTO（全部被观测），
  1 个是二进制 poster 端点（`success=None`，不是 JSON envelope，不适用）。

## 4. 逐端点结果

结论列里的「FAIL」分两类：**真实漂移**（§5.1/§5.2）与**测试替身假失败**（§5.3），后者不是端点缺陷。
管理写端点在套件里只被测试替身观测到（4 次 FAIL），真实路径由 §3 的补测单独验证（1 次
`Extra inputs are not permitted: outcome`）。

| 端点 | 声明的 success DTO | 结论 |
| --- | --- | --- |
| `DELETE /api/v1/settings/autobangumi` | `AutoBangumiConnectionSummaryDTO` | pass（2 次） |
| `GET /api/v1/corrections` | `CorrectionsResultDTO` | pass（3 次） |
| `GET /api/v1/preferences` | `PreferenceResultDTO` | pass（4 次） |
| `GET /api/v1/requests` | `RequestListResultDTO` | pass（6 次） |
| `GET /api/v1/requests/<path:request_id>` | `RequestDetailResultDTO` | pass（7 次） |
| `GET /api/v1/requests/<path:request_id>/safe-info` | `RequestSafeInfoResultDTO` | pass（5 次） |
| `GET /api/v1/settings/autobangumi` | `AutoBangumiConnectionSummaryDTO` | pass（32 次） |
| `GET /api/v1/tracking/items` | `TrackingItemListResultDTO` | pass（30 次） |
| `GET /api/v1/tracking/items/<path:tracking_id>` | `TrackingDetailResultDTO` | pass（4 次） |
| `POST /api/v1/batches/<batch_id>/save-confirm` | `BatchSaveConfirmResultDTO` | pass（24 次） |
| `POST /api/v1/batches/parse` | `BatchParseResultDTO` | **FAIL**（1/37 次：`items.0.preference_hits`, `items.1.preference_hits` 见 §4） |
| `POST /api/v1/corrections` | `CorrectionsResultDTO` | pass（6 次） |
| `POST /api/v1/mikan/candidates` | `MikanCandidateResultDTO` | pass（16 次） |
| `POST /api/v1/preferences` | `PreferenceResultDTO` | pass（5 次） |
| `POST /api/v1/requests` | `RequestCreateResultDTO` | pass（111 次） |
| `POST /api/v1/requests/<path:request_id>/accept` | `RequestActionResultDTO` | pass（2 次） |
| `POST /api/v1/requests/<path:request_id>/cancel` | `RequestActionResultDTO` | pass（1 次） |
| `POST /api/v1/requests/<path:request_id>/delete` | `RequestDeleteResultDTO` | pass（2 次） |
| `POST /api/v1/requests/<path:request_id>/modify` | `RequestActionResultDTO` | pass（2 次） |
| `POST /api/v1/requests/preview-modify` | `RequestPreviewModifyResultDTO` | pass（10 次） |
| `POST /api/v1/requests/save-confirm` | `RequestSaveConfirmResultDTO` | pass（12 次） |
| `POST /api/v1/settings/autobangumi/probe` | `AutoBangumiCapabilitiesDTO` | pass（6 次） |
| `POST /api/v1/settings/autobangumi/test` | `AutoBangumiConnectionTestResultDTO` | pass（1 次） |
| `POST /api/v1/tracking/batch-submit` | `TrackingBatchSubmitResultDTO` | pass（15 次） |
| `POST /api/v1/tracking/items/<path:tracking_id>/check` | `TrackingCheckResultDTO` | pass（3 次） |
| `POST /api/v1/tracking/items/<path:tracking_id>/delete-external` | `TrackingManagementResultDTO` | **FAIL**（1/1 次：`safe_message`, `tracking` 见 §4） |
| `POST /api/v1/tracking/items/<path:tracking_id>/delete-plan` | `TrackingPlanDeleteResultDTO` | pass（9 次） |
| `POST /api/v1/tracking/items/<path:tracking_id>/modify` | `TrackingManagementResultDTO` | **FAIL**（1/1 次：`safe_message`, `tracking` 见 §4） |
| `POST /api/v1/tracking/items/<path:tracking_id>/recover` | `TrackingRecoverResultDTO` | pass（4 次） |
| `POST /api/v1/tracking/items/<path:tracking_id>/refresh` | `TrackingManagementResultDTO` | **FAIL**（1/1 次：`safe_message`, `tracking` 见 §4） |
| `POST /api/v1/tracking/items/<path:tracking_id>/resubmit` | `TrackingResubmitResultDTO` | pass（12 次） |
| `POST /api/v1/tracking/items/<path:tracking_id>/retry` | `TrackingSubmitResultDTO` | pass（1 次） |
| `POST /api/v1/tracking/items/<path:tracking_id>/revalidate` | `TrackingRevalidateResultDTO` | pass（4 次） |
| `POST /api/v1/tracking/items/<path:tracking_id>/set-enabled` | `TrackingManagementResultDTO` | **FAIL**（1/1 次：`safe_message`, `tracking` 见 §4） |
| `POST /api/v1/tracking/items/<path:tracking_id>/submit` | `TrackingSubmitResultDTO` | pass（45 次） |
| `POST /api/v1/tracking/sync` | `TrackingSyncResultDTO` | pass（1 次） |
| `PUT /api/v1/settings/autobangumi` | `AutoBangumiConnectionSummaryDTO` | pass（11 次） |
| `GET /api/v1/mikan/posters/<key>` | —（二进制，未声明 DTO） | 不适用（非 JSON envelope） |

## 5. 失败归类

### 5.1 真实漂移 A：`POST /api/v1/batches/parse` 的 `preference_hits`（类型不符）

- 声明：`api_contract.py:571` `BatchParseItemDTO.preference_hits: list[dict[str, Any]] = []`（不可空）。
- 运行：`serializers.py:247-266` `_serialize_preference_application()` 明确写着
  「the first two are ``None`` when preferences were unavailable」，即 `applied_preferences` 与
  `preference_hits` 在偏好不可用时就是 `None`。
- 实测：37 次成功响应里 **1 次**命中该分支（偏好读取失败回退默认流程）：
  `items[0].preference_hits == null`，校验报 `Input should be a valid list`。
- 归类：**DTO 写错了**（不是运行时错）。相邻字段 `applied_preferences: dict | None = None` 已经是
  可空写法，`preference_hits` 应同为 `list[dict[str, Any]] | None = None`。
- 前端影响：`frontend/src/api/generated/api.ts` 把该字段生成成不可空数组（类型撒谎），
  而 `frontend/src/features/workbench/batchWorkbench.ts:260` 已经写着
  `const hits = item.preference_hits ?? []`——防御性代码说明消费方早就假定它可为空。
- 判定：**该收紧 DTO 到与 serializer 一致**（修 DTO，不是放宽运行时）。

### 5.2 真实漂移 B：四个管理写端点的 `outcome`（额外字段）

- 声明：`api_contract.py:1201 TrackingManagementResultDTO(_StrictBase)`（`extra="forbid"`）声明
  `action / management_status / needs_manual / safe_message / operation_id / tracking / operation`，
  **没有 `outcome`**。
- 运行：`routes_tracking.py:339` `_management_result()` 对四个管理写（`modify`/`set-enabled`/
  `delete-external`/`refresh`）都返回 `"outcome": result.get("outcome")`。
- 实测（真实路径，先用本地 AB stand-in 完成 submit 再 `set-enabled`）：

  ```console
  $ python -c "..."   # 见 §3 命令 2
  POST .../set-enabled -> 200
  {'loc': ['outcome'], 'type': 'extra_forbidden', 'msg': 'Extra inputs are not permitted'}
  ```

  （同一 `_management_result()` 服务四个端点；`modify`/`refresh`/`delete-external` 在同一次补测里
  因状态被 `set-enabled` 改变而返回 409，未产生成功响应。）
- 归类：**契约与运行时不一致**。`management_status` 已经是安全状态词表，`outcome` 更像内部值；
  两个修法方向都成立（删运行时的 `outcome`，或评审后把它加进 DTO），需要产品/契约决定，
  不是本调查报告能单方面收紧的安全边界。
- 前端影响：生成的 TS 类型没有 `outcome`，前端没有消费它（`trackingProjection.ts:530` 读的是
  **check** 端点的 `outcome`，那是 `TrackingCheckResultDTO` 自己的字段），所以修哪一边都不会破坏现有前端。

### 5.3 非缺陷：四个管理端点在套件里的失败来自测试替身

`src/apps/migu_orca_web/tracking_management_routes_test.py:29-61` 把 `_run_management_route`
替换成返回 3 个键的假实现：

```python
def fake_run(payload, selected_action, **kwargs):
    return {"management_status": "SUCCEEDED", "needs_manual": False, "action": selected_action}

monkeypatch.setattr(routes_tracking, "_run_management_route", fake_run)
```

于是审计看到的 `result` 缺 `safe_message`/`tracking`，报 `Field required`。真实 serializer 会补齐它们
（`routes_tracking.py:_management_result()`）。**这不是端点缺陷**，但它是一个重要的前置事实：
一旦接回运行时校验，这个测试替身必须先改，否则该用例会因 400 而变红。

### 5.4 接回运行时后，漂移的真实表现是 400（把服务端问题说成客户端错误）

`APIBaseView.dispatch_request`（`extensions/flask_api/api.py:334-341`）会捕获视图内异常并交给
`handle_exception`，后者把 pydantic `ValidationError` 归类为 **400 `data_validation_errors`**。
用 §5.1/§5.2 的真实响应实测：

```console
$ PYTHONPATH=src uv run python - <<'PY'
import json
from pydantic import ValidationError
from apps.base import create_app
from apps.migu_orca_web.api_contract import BatchParseResultDTO, TrackingManagementResultDTO
from extensions.flask_api.api import handle_exception
app = create_app("testing")
with app.app_context():
    for name, dto, payload in (
        ("TrackingManagementResultDTO", TrackingManagementResultDTO, <§5.2 的真实响应>),
        ("BatchParseResultDTO", BatchParseResultDTO,
         {"batch_id": "b1", "raw_input": "x", "items": [{"item_id": "i1", "preference_hits": None}]}),
    ):
        try:
            dto.model_validate(payload)
        except ValidationError as exc:
            r = handle_exception("X", exc)
            print(name, "->", r.status_code, json.dumps(r.get_json(), ensure_ascii=False))
PY
TrackingManagementResultDTO -> 400
  {"error_data": {"errors": [{"field": "outcome", "message": "Extra inputs are not permitted"}]},
   "error_type": "data_validation_errors", "ok": false}
BatchParseResultDTO -> 400
  {"error_data": {"errors": [{"field": "items.0.preference_hits", "message": "Input should be a valid list"}]},
   "error_type": "data_validation_errors", "ok": false}
```

也就是说：**一次已经成功完成的外部/本地操作，会以「你的请求参数不合法」返回给客户端**，
客户端可能据此重试或改参数。这是选项 1 必须先解决的前置问题——契约违规应分类为服务端错误
（例如 5xx + 独立 error_type），而不是复用输入校验的 400。

### 5.5 「必须保持宽松」的兼容字段：`_SnapshotBase`

`api_contract.py:110-122` 的 `_SnapshotBase` 明确 `extra="allow"`，注释写着
「engine snapshot dicts may legitimately gain fields over time … the views return the engine
dicts as-is」。当前有 **16 个**这样的宽松 DTO（如 `RequestSnapshotDTO`、`BatchParseItemDTO`、
`AbResultRecordDTO`、`ConfirmableConfigDTO`、`MatchedBangumiDTO` 等），另有 **73 个**严格 DTO。
含义：

- 对宽松 DTO，**运行时校验不可能承担「白名单防泄漏」职责**：意外字段被允许，只有声明字段的
  类型/必填仍会被检查（`preference_hits` 正是这种类型漂移，不是泄漏）。
- 因此「接回运行时」的安全收益只落在 `extra="forbid"` 的严格 DTO 上：那里的意外字段更可能是
  序列化器越界（含敏感字段），此时把响应替换成失败确实比把字段发出去好。
- 反过来说，16 个宽松 DTO 无论选哪个选项都只能是「测试期 + 生成类型」的作用，这点要在选项里说清。

## 6. 三个选项的代价与建议

### 选项 1：接回运行时（全量或分阶段）

做法：让每个端点在返回前调用 `ok_result(result, dto)`（或在校验层统一注入注册表 DTO）。

- 主要收益：严格 DTO 下的**意外字段/类型漂移 fail closed**，不会把序列化器越界（潜在敏感字段）
  静默发给客户端；契约与运行时的漂移立刻可见。
- 代价（本次审计已证实的前置）：
  1. 先修 §5.1、§5.2 两处漂移，并决定 `outcome` 归契约还是归 serializer；
  2. 先改 `tracking_management_routes_test.py` 的测试替身（§5.3），否则用例变红；
  3. 先改失败分类（§5.4），否则成功操作会以 400 输入错误呈现；
  4. 覆盖盲区的风险仍在：套件没走到的分支（损坏 JSON、迁移告警、遗留回退等）一旦 DTO 与运行时
     不一致，就会在用户现场变成失败。选择「全量」时这个面最大；「分阶段」可先对最敏感的严格白名单
     端点（`getRequestSafeInfo`、`getTrackingItemDetail`、`listTrackingItems`、四个管理写）启用，
     再推广到其余 DTO；嵌套的宽松快照 DTO（§5.5）无论哪一阶段都只能是测试期 + 生成类型，
     代价是两套校验制度并存、需要在注册表里显式标注严格度。
- 验证面：全量非浏览器 + 浏览器套件；新增「每个成功响应都通过其 DTO」的运行时断言会与业务断言重复，
  建议只保留测试期版本（见选项 3）。

### 选项 2：保持现状 + 删除死入口

做法：删掉 `ok_result` 的 `dto` 参数（或整个函数），承认响应白名单只在测试期生效。

- 收益：零运行时风险，代码不再有「声称校验、实际不校验」的误导性接口，维护成本最低。
- 代价：本次发现的两处漂移继续不可见——`preference_hits` 与 `outcome` 会一直是
  「生成类型与运行时不一致」的隐患；未来新增的序列化器越界也没有任何运行时或 CI 拦截。
- 结论：比选项 3 差，因为它把「已知不可见」留成了默认状态。

### 选项 3：改为仅测试期校验（本次建议）

做法：保留 DTO 与生成类型；删除/收窄 `ok_result` 的运行时入口（不再假装运行时白名单），
把 §3 的审计钩子产品化为 `tests/api_contract` 的正式夹具——用现有夹具跑真实响应并逐端点
`model_validate`；先修 §5.1、§5.2，或把它们登记为显式已知例外并在报告中跟踪。

- 收益：
  - 与「接回运行时」**同一份证据面**（同样是真实响应 + 同一批夹具），但零生产风险；
  - 漂移在 CI 变红，而不是在用户现场变成 400/500；
  - 不改变任何端点行为、错误契约或响应字节，符合本仓库「行为零变化」的迁移口径。
- 代价：
  - 只覆盖夹具可达的路径；需要在测试里维护「response 审计」这一层（约 80 行 + 一处 hook）；
  - 对真正没被测试走到的分支，这个保证弱于运行时校验。
- 升级路径：若后续希望恢复「严格白名单 fail closed」，按选项 1 的三项前置改造后，
  可从严格 DTO 分阶段接回；届时测试期审计正好是「接线前必须先绿」的安全网。

### 单一建议

**选选项 3「改为仅测试期校验」**，并把 §5.1/§5.2 作为紧随其后的两张修复票
（`BatchParseItemDTO.preference_hits` 收窄为可空；`TrackingManagementResultDTO.outcome`
二选一）。理由浓缩：运行时校验的失败模式（把成功的服务端操作报成客户端 400）在本次审计里已被实证，
而它带来的安全收益只覆盖严格 DTO；在 drift 尚未清零、失败分类尚未修正之前，
测试期校验能以同等证据强度先拿到收益，且不改任何运行时行为。

## 7. 覆盖限制

- 只审计**成功 envelope**（`ok: true`）与现有夹具可达的路径；错误 envelope 由
  `tests/api_contract/test_golden_contracts.py` 等既有用例覆盖，不在本票范围。
- 损坏 JSON、历史迁移告警、遗留回退等分支若未被夹具触发，本次不会暴露其漂移。
- 端点的多次运行取并集：任一运行失败即记为 FAIL，并给出出错字段路径。
- `cancel` 与 `tracking/sync` 的成功路径由 §3 的补测夹具覆盖（非浏览器套件不覆盖）；
  4 个管理写端点的真实成功路径由本地 AB stand-in 覆盖（`set-enabled`；另外 3 个共享同一 serializer）。
- #184 合并后（`c54655d`）重跑过同一套审计：新增 `resubmit` 端点 12 次运行全绿，
  两处漂移与四个管理端点测试替身的结论不变。

## 附录 A：审计插件源码（一次性，未入库）

```python
"""Issue #172 audit plugin (throwaway, not part of the repo).

Hooks ``Flask.process_response`` for every ``/api/v1`` JSON success envelope
produced by the existing test fixtures, and validates ``result`` against the
DTO declared in ``_ENDPOINTS[key]["success"]`` — i.e. it simulates the
``ok_result(result, dto)`` call that no route performs today.

Usage:
    PYTHONPATH=src:~/.cache/mo172 DTO_AUDIT_OUT=~/.cache/mo172/audit.json \
        uv run pytest -q -m "not browser" -p dto_audit
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import flask
from pydantic import BaseModel, ValidationError

from apps.migu_orca_web.openapi_gen import _ENDPOINTS

RECORDS: dict[str, dict] = {}
CRASHES: list[str] = []
_original = flask.Flask.process_response


def _patched(self, response):  # type: ignore[no-untyped-def]
    try:
        rule = flask.request.url_rule
        if rule is not None and rule.rule.startswith("/api/v1/"):
            key = f"{flask.request.method} {rule.rule}"
            entry = _ENDPOINTS.get(key)
            dto = entry.get("success") if entry else None
            if isinstance(dto, type) and issubclass(dto, BaseModel):
                payload = response.get_json(silent=True)
                if isinstance(payload, dict) and payload.get("ok") is True:
                    record = RECORDS.setdefault(
                        key, {"dto": dto.__name__, "runs": 0, "failures": [], "sample": None}
                    )
                    record["runs"] += 1
                    try:
                        dto.model_validate(payload.get("result"))
                        record["sample"] = payload.get("result")
                    except ValidationError as exc:
                        record["failures"].append(
                            {
                                "errors": [
                                    {"loc": list(item["loc"]), "type": item["type"], "msg": item["msg"]}
                                    for item in exc.errors()
                                ],
                                "result": payload.get("result"),
                            }
                        )
    except Exception as exc:  # never break the suite
        CRASHES.append(repr(exc))
    return _original(self, response)


flask.Flask.process_response = _patched


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    out = Path(os.environ.get("DTO_AUDIT_OUT", str(Path.home() / ".cache/mo172/audit.json")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"records": RECORDS, "crashes": CRASHES}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n[#172 audit] {len(RECORDS)} endpoints observed, {len(CRASHES)} hook errors -> {out}")

```

配套的补测夹具（同样一次性，运行后删除；`cancel` / `tracking-sync` / 真实管理写）：

```python
from tests.api_contract.conftest import saved_request
from tests.api_contract.test_tracking_confirmation_local_ab import LocalAb318, _seed

def test_audit_cancel_success(tmp_path, client):
    saved_request(tmp_path, request_id="request-1")
    r = client.post("/api/v1/requests/request-1/cancel",
                    json={"storage_dir": "storage", "cancel_reason": "审计"})
    assert r.status_code == 200, r.get_json()

def test_audit_sync_success(tmp_path, client):
    ab = LocalAb318()
    try:
        body, _ = _seed(tmp_path, ab)
        r = client.post("/api/v1/tracking/sync", json={
            "confirm": True, "storage_dir": body["storage_dir"],
            "connection_ref": body["connection_ref"],
            "configuration_revision": body["configuration_revision"]})
        assert r.status_code == 200, r.get_json()
    finally:
        ab.close()

def test_audit_management_real_path(tmp_path, client):
    ab = LocalAb318()
    try:
        body, record = _seed(tmp_path, ab)
        client.post(f"/api/v1/tracking/items/{record.tracking_id}/submit", json=body)
        # 之后用同一 connection_ref/revision + 最新 record.revision POST
        # .../set-enabled（其余三个管理写共享同一 _management_result serializer）
    finally:
        ab.close()
```
