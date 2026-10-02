# 截图证据与构建新鲜度（#155）

浏览器视觉/几何用例在真实 Chromium 里截图，截图只有在能证明「来自当前源码构建出的
产物，且页面真的加载了那份产物」时才算有效证据。本文是该取证的复现指南；工具实现在
[`tests/browser/evidence.py`](../../tests/browser/evidence.py)，浏览器入口断言在
[`tests/browser/test_app_visual_evidence.py`](../../tests/browser/test_app_visual_evidence.py)。

## 1. 构建（截图前的硬前置）

```bash
uv run python -m tests.browser.evidence build
```

它运行 `npm run build`，并把构建戳写入 `frontend/.evidence/build-evidence.json`：
Git HEAD/分支/脏状态、限定前端源码与构建输入的 sha256 指纹（`frontend/src` +
`index.html`、`package.json`、`package-lock.json`、Vite/Vitest/TS/ESLint 配置）、
dist 产物摘要与文件数、Node/npm 版本。

- 指纹不读取 `dist`、`node_modules`、运行 storage、部署配置、凭据或上游响应；
- 构建戳放在 `frontend/.evidence/`（已 gitignore，也不经 Flask 静态托管），因此
  `@app/build-evidence.json` 之类的产物不会出现在页面里；
- dirty 工作区允许取证，但构建戳会记下 `git.dirty` 与改动文件数，可识别源码版本。

## 2. 校验（浏览器用例自动执行）

```bash
uv run python -m tests.browser.evidence verify
```

`tests/browser/visual_support.py` 的 `require_dist()` 在每次浏览器截图前调用同一校验：

- 缺少 `dist/index.html` 或缺少构建戳 → 拒绝；
- 源码/构建输入在构建后变化 → 拒绝（构建戳过期）；
- `dist` 被改写、缺失或由另一次构建产生 → 拒绝。

因此浏览器套件前必须跑第 1 步；仅检查 `index.html` 是否存在或依赖 mtime 不再被接受。

## 3. 人工交互预览（同一份 dist）

```bash
uv run python -m tests.browser.evidence preview
```

先用同一构建戳校验 dist，再以 Flask 启动 `http://127.0.0.1:5000/app/add`。预览与截图
使用同一份产物，不需要真实 MiKan/Auto Bangumi/qBittorrent 凭据，也不做任何外部写。

## 4. 截图随附证据清单

任何一轮审核截图都必须随附清单。标准做法（见 `test_app_visual_evidence.py`）：

1. 在导航前把 `LoadedResourceRecorder(live_server_url)` 挂到 page 上；
2. 用固定 fixture（只 mock 安全数据/海报）走到目标状态；
3. `capture_canvas(page, screenshot)` 截图；
4. `capture_evidence(page, screenshot, base_url=…, scenario=…, fixture=…, resources=recorder.records())`
   组装清单并校验「页面实际加载的 `/app/assets/*` 与 dist 逐字节一致」；
5. `write_manifest(manifest, directory, stem)` 与截图同目录写出 `<stem>.evidence.json`。

清单字段：schema 版本、取证时间、Git HEAD/分支/脏状态、构建时间与产物摘要、源码指纹
（摘要 + 覆盖文件数）、Node/npm 与 Chromium 版本、viewport/`devicePixelRatio`/
reduced-motion、fixture 标识与 mock 路由、场景标识/标题/操作步骤、页面路由与实际加载
资源（同源路径 + 响应体 sha256）、截图文件名与 sha256/尺寸。

安全约束（`assert_manifest_safe` 会扫描）：不出现本地绝对路径、完整 `http(s)://` URL
或密码/令牌/凭据一类字段。截图只记文件名，不记 `tmp_path`。

## 5. 边界

- PNG 由真实 `/app/add` 与共享实际组件生成；mock 只替换安全数据/海报，不为截图增造
  按钮或改变业务 DOM/布局；
- 稳定截图 CSS（隐藏光标/插入符、关闭动画与过渡）只服务于取景，默认动效与
  reduced-motion 另行验收；关闭动画不能代替动效验收；
- 截图不证明点击行为：交互（如标题搜索关闭按钮）必须在真实 Chromium 中逐次真实点击；
- 新候选图连续三次稳定并逐张人工批准后才能成为金样；本工具不批准、不替换任何金样。
