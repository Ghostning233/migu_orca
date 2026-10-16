# 浏览器测试环境（Playwright + Chromium）

本文是浏览器测试环境的唯一现行说明。历史上那套"无 sudo 解包系统库"的回退已删除，理由见文末
[已移除](#已移除及原因)。

## 一句话

Chromium 的**系统库是操作系统依赖**：用发行版包管理器装一次，放在平台库目录里，全机所有项目、
所有 Playwright 版本共享。仓库不自建解包目录，也不注入 `LD_LIBRARY_PATH`。

## 一次性安装

```bash
# 1) 浏览器二进制（Playwright 管理，持久且跨项目共享）
uv run playwright install chromium
#    → 落在 ~/.cache/ms-playwright（Playwright 的全局默认路径，重启不丢）
#    → 需要换共享位置时才设 PLAYWRIGHT_BROWSERS_PATH

# 2) 系统库（需要 sudo，装一次即可）
sudo apt-get install -y libnspr4 libnss3

# 等价的全量声明集（CI 用的就是这条）
sudo uv run playwright install-deps chromium
```

`libnspr4` 与 `libnss3` 在 Ubuntu/Debian 上提供 `libnspr4.so`、`libnss3.so`、
`libnssutil3.so`、`libsmime3.so`。Chromium 其余的 dlopen 依赖（`libgbm`、`libatk-1.0`、
`libcups`、`libasound`、`libpango-1.0`、`libxkbcommon`、`libdrm`、`libxcomposite`、
`libxdamage`、`libxfixes`、`libxrandr`、`libdbus-1`、`libatspi`、`libcairo` …）在标准桌面上
已由系统提供，所以真实的缺口通常只有这两个包。

缺什么用 `ldd` 判定，不要靠猜或照抄一份固定的包清单：

```bash
ldd "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | grep "not found"
```

若某台机器确实无法安装系统库，那是该机器的环境例外，不属于本仓库要维护的能力；请自行用包管理器
或本地解包处理，并自己保证库文件在重启后仍然存在。

## 怎么跑

```bash
uv run pytest tests/browser/test_xxx.py::TestYyy::test_zzz -q   # 定向用例
uv run pytest tests/browser/ -q                                 # 全量门禁，通常 Stage 收尾跑一轮
```

截图／几何类用例还有**构建新鲜度**门禁，需要先产出证据构建：

```bash
uv run python -m tests.browser.evidence build     # 生产构建 + 写构建戳
uv run python -m tests.browser.evidence verify     # 只校验 dist 是否可作为最新证据
```

细节见 [视觉与截图证据](visual-evidence.md)。SPA 用例需要最新的 `frontend/dist`。

## 不可用时会发生什么

`tests/browser/conftest.py` 在收集阶段探测一次可用性：在 `~/.cache/ms-playwright` 下找
`chromium_headless_shell-*/…/chrome-headless-shell` 或 `chromium-*/chrome-linux64/chrome`，
再跑一次 `--version`；返回 0 才算可用。缺共享库时 `--version` 会报
`error while loading shared libraries: libnspr4.so`，正是这条路径把它变成明确的结论：

- **本地**：浏览器用例被标记 `skip` 并打印提示——不会静默当成通过；
- **CI**（`MIGU_ORCA_CI=1`）：同样条件下**硬失败**，因为 skip 不算通过。

## CI

`.github/workflows/ci.yml` 的 browser job 执行 `uv run playwright install --with-deps chromium`。
那是在 root 环境里装系统依赖，与本地"用包管理器装系统库"是同一条路子，只是本地需要你自己输一次密码。

## 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| `error while loading shared libraries: libnspr4.so` | 系统库缺失：按上文安装；用 `ldd … \| grep "not found"` 定位具体缺哪个 |
| 浏览器用例全被 skip | 同上；确认本地未设 `MIGU_ORCA_CI`（设了就是硬失败而不是 skip） |
| 找不到 Chromium 二进制 | `uv run playwright install chromium` |
| 截图用例报构建戳缺失/过期 | `uv run python -m tests.browser.evidence build` 重跑 |

不要往 `/tmp` 解包系统库：`/tmp` 会被 `systemd-tmpfiles` 的 `D /tmp` 条目**在每次开机时清空**，
重启后环境即失效，只能再手工恢复一次。

## 已移除（及原因）

| 移除项 | 原因 |
| --- | --- |
| `script/setup-browser-deps.sh` | 无 sudo 时把 17 个 `.deb` 解到 `/tmp/chromium-libs`；重启即失，且固定包列表与真实缺口无关（本机实际只缺 2 个包） |
| `bin/chromium-wrapper.sh` | 全仓库无任何引用；且硬编码浏览器 build 号（`chromium_headless_shell-1234`），Playwright 升级即失效 |
| `tests/browser/conftest.py` 的 `LD_LIBRARY_PATH` 注入 | 系统库按操作系统依赖安装后不再需要；探测逻辑保留（它才是"不可用就明确 skip／CI 硬失败"的依据） |
| `.gitignore` 的 `.agents/.chromium-libs/`、`.chromium-deps/` | 上述方案的产物目录约定，随方案一并移除 |
