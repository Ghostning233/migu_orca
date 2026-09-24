# 设置数值基线（Issue 117 起）

## 0. 状态与用途

| 项目 | 内容 |
| --- | --- |
| 状态 | **已建立（2026-09-24，#117）**；本文件是「设置」一级页面的数值布局基线 |
| 依据 | GitHub Issue #117（父规格 #107）；冻结 Token V1；壳层基线见[壳层数值基线](frontend-ux-shell-geometry-baseline.md) |
| 范围 | 三分组顺序、组内分段、数据档案语义与连接卡；移动端不在范围 |
| 位图角色 | 设计 PNG 仅作人工对照（图 18 的「存储设置／番剧文件的存储位置」是生成器旧文案，已被图 17 修订取代） |

## 1. 分组顺序与分段

| 顺序 | 分组标题 | 内容 |
| --- | --- | --- |
| 1 | 默认偏好 | 分段：字幕组 → 过滤规则 → 命名方式；每段一个 `h3.settings-group-title`（`--font-size-lg` / `--font-weight-semibold`，上边距 `--space-4`）；搜索词修正作为独立选项留在动作之前 |
| 2 | MiGuOrca 本地数据 | 当前浏览器选用的业务数据 profile；`#settings-storage-dir` + 保存／清除 |
| 3 | Auto Bangumi 连接 | 安全状态、只读测试与编辑；秘密不回显 |

页面容器沿用壳层档位内边距与 `--space-5` 分组间距（`.settings-view { gap: 1.25rem }`）。
没有明确用途的独立「高级诊断」区已移除；连接能力说明保留在连接卡内。

## 2. 数据档案语义

- 文案固定说明：这里的数据档案是**当前浏览器选用的 MiGuOrca 业务数据 profile**（方案、追番记录等），**不是下载媒体的位置**。
- 选择只写入当前浏览器 `localStorage`；服务端仍按相对 profile 校验，绝对路径／穿越／符号链接逃逸回退到服务器默认数据档案。
- 切换或清除选择只改变当前浏览器选用项：提示「切换数据档案不会移动原有数据；可切回原档案查看」，清除后提示「原有数据不会被移动」。
- 不提供服务端统一默认档案、档案迁移功能或 Auto Bangumi `downloader.path` 编辑。

## 3. 连接卡

已保存配置（`configured` / `credential_present` / `connection_ref`）与最近探测结果（`connection_status` / `capabilities`）分开呈现；
连接摘要只回传安全字段，`connection_ref`、凭据与内部代码不进入 DOM、URL/history、storage 或日志。

## 4. 验证命令

```bash
cd frontend && npm run typecheck && npm run lint && npm run test:unit -- --run
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_settings_groups.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/browser/test_app_settings.py -q
```
