# MiGuOrca 架构与目录约定

## 1. 目标

项目采用模块化单体结构。架构首先服务于当前可验证行为，只有在职责具有独立变化
原因时才拆分模块，不要求 PRD 模块与 Python 包一一对应。

## 2. 分层

```text
CLI / 后续 UI
       ↓
apps：用例编排
       ↓
engines：业务能力
       ↓
shared / 外部适配
```

- `apps` 接收输入、调用 engine、转换输出，不实现具体规则。
- `*_engine` 封装一组高内聚业务能力。
- `shared` 只存放跨 engine 契约、错误、配置和日志等基础能力。
- 外部系统接入后放在对应 engine 的适配目录，不让领域规则直接依赖网络客户端。

## 3. 当前目录

```text
src/
  apps/
    migu_orca_entry/
      controllers/

  catalog_engine/
    controllers/
    models/

  rss_engine/
    controllers/
    models/

  subscription_engine/
    controllers/
    models/

  request_engine/
    controllers/
    models/

  ab_engine/
    controllers/

  shared/
    config.py
    errors.py
    logging.py
    models.py
```

职责映射：

| 代码模块 | PRD 职责 | 当前责任 |
| --- | --- | --- |
| `apps/migu_orca_entry` | M00 | CLI、流程编排、统一结果、显式 AB 提交入口 |
| `catalog_engine` | M02、M03 | 静态候选读取、标题匹配 |
| `rss_engine` | M04、M06 | RSS 解析、正则筛选 |
| `subscription_engine` | M05、M07 | 字幕组选择、文件夹名 |
| `request_engine` | M01、M09 | Request 契约、快照组装、确认、取消、受限修改 |
| `ab_engine` | M10 | AB 提交结果契约、payload 映射、fake client、fallback JSON、AB config 读取 |
| `shared/config.py` | M08、M14 的最小子集 | 用户 JSON 与默认路径 |
| `shared/logging.py` | M12 的最小子集 | 标准库日志初始化 |

M11、M13 仍未实现，不提前创建空实现目录。真实 Auto Bangumi HTTP adapter 属于 Stage 4，应在 `ab_engine` 的现有 client 协议边界内演进，不反向污染 Request 生成和确认逻辑。

## 4. 拆分规则

满足下列任一条件时，可以新增或拆分 engine：

1. 出现独立外部系统适配边界；
2. 规则有独立发布或替换需求；
3. 模块已经形成明显的数据和行为内聚；
4. 当前合并导致循环依赖或无法独立测试。

不得仅因 PRD 有独立编号就创建 engine。

## 5. 依赖规则

1. `apps` 可以依赖所有 Stage 1 engine 和 `shared`。
2. engine 可以依赖 `shared`。
3. engine 之间优先通过 `shared.models` 中的契约传值。
4. engine 不得反向依赖 `apps`。
5. `shared` 不得依赖任何 engine。
6. 不在多个 engine 中复制同名数据模型。

## 6. Controller 与 Model

- Controller 是 engine 的公开业务入口。
- Model 是 engine 私有模型；跨 engine 模型放在 `shared.models`。
- Stage 1 不预建 `services`、`clients`、`repositories` 等空目录。
- 当真实 API、认证或存储出现后，再根据实际调用边界增加这些目录。

## 7. 测试

当前延续既有约定：测试文件与被测文件放在同一目录，使用 `*_test.py`。

测试分为：

- 纯规则单元测试；
- fixture 解析测试；
- 入口端到端测试。

所有测试使用：

```bash
uv run pytest
```

## 8. 配置与运行数据

- 仓库内默认 fixture：`config/system/`、`fixtures/rss/`。
- 仓库内用户示例配置：`config/user/`。
- 日志目录仅在显式启用文件日志时使用。
- 运行时生成的日志不提交 Git。

## 9. 后续演进

真实 MiKan 接入优先作为 `catalog_engine` 的新适配器；Auto Bangumi 已形成独立 `ab_engine` 和稳定提交契约，下一步应只替换真实 HTTP client adapter 注入点；持久化状态机在 M11 阶段设计，不反向扩大 Request 快照的职责。
