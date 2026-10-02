"""#155：截图证据与构建新鲜度工具（测试期专用）。

用途
----
浏览器视觉/几何门禁产出的截图只有在能证明「它来自当前前端源码构建出的产物，且页面
真的加载了那份产物」时才算有效证据。本模块提供三件事：

1. ``build``：运行前端生产构建，并把「源码指纹 + 产物摘要 + Git 状态」写进
   ``frontend/.evidence/build-evidence.json``（构建戳）；
2. ``verify``：校验当前 ``frontend/dist`` 与构建戳、当前源码三者一致。任一不匹配
   （陈旧产物、被改写的 dist、源码在构建后变化）都抛 ``EvidenceError``，不允许作为
   最新验收证据；
3. ``capture_evidence`` / ``write_manifest``（库函数，无独立 CLI）：把一次真实 Chromium 截图整理成安全证据清单——Git HEAD/脏状态、限定
   前端源码与构建输入的指纹、产物摘要、页面实际加载资源摘要、Chromium 版本、viewport/
   缩放、fixture 标识、场景与操作步骤、截图摘要。

安全边界
--------
- 指纹只覆盖 ``frontend/src`` 与构建配置/锁文件，不读 ``dist``、``node_modules``、
  运行 storage、部署配置或凭据；
- 清单里不出现本地绝对路径、秘密、完整服务/RSS URL：截图只记文件名与摘要，页面资源只
  记同源路径（``/app/...``，去掉 scheme/host/query）；
- 清单会被 ``assert_manifest_safe`` 扫描一次，禁止绝对路径与 ``http(s)://``。

命令行
------
    uv run python -m tests.browser.evidence build     # 构建并写构建戳
    uv run python -m tests.browser.evidence verify    # 校验 dist 是否可作最新证据
    uv run python -m tests.browser.evidence preview   # 用同一份 dist 启动人工预览

复现指南见 ``docs/development/visual-evidence.md``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
EVIDENCE_DIR = FRONTEND_DIR / ".evidence"
STAMP_NAME = "build-evidence.json"
SCHEMA_VERSION = 1

# 指纹覆盖的构建输入：前端源码 + 构建配置 + 锁文件。刻意不包含 README/文档，
# 也不递归读取 dist/node_modules 或任何运行数据。
_FINGERPRINT_TOP_LEVEL = (
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "vitest.config.ts",
    "tsconfig.json",
    "eslint.config.js",
)
_FINGERPRINT_TREES = ("src",)

_FORBIDDEN_MANIFEST_KEYS = frozenset(
    {"password", "passwd", "token", "secret", "credential", "credentials", "cookie", "authorization", "api_key", "apikey"}
)
_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])(?:[A-Za-z]:[\\/]|/(?:home|Users|tmp|var|etc|root|opt|srv|mnt|media)/)")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_ASSET_CONTENT_TYPES = ("javascript", "ecmascript", "css", "html")


class EvidenceError(RuntimeError):
    """构建/产物/清单不能作为最新验收证据。"""


# ---------------------------------------------------------------------------
# 指纹与摘要
# ---------------------------------------------------------------------------


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _display_path(path: Path, root: Path) -> str:
    """仓库内给相对路径，仓库外只给名字——错误信息里也不泄漏本地绝对路径。"""
    try:
        return _relative(path, root)
    except ValueError:
        return path.name


def _is_test_source(relative: str) -> bool:
    """测试文件不参与 Vite 构建；编辑它们不该让截图证据失效。"""
    name = relative.rsplit("/", 1)[-1]
    return ".test." in name or ".spec." in name or f"/{relative}".startswith("/src/test/")


def fingerprint_paths(frontend_dir: Path = FRONTEND_DIR) -> list[Path]:
    """返回指纹覆盖的文件（排序、去重），全部位于 ``frontend_dir`` 内。"""
    paths: list[Path] = []
    for name in _FINGERPRINT_TOP_LEVEL:
        candidate = frontend_dir / name
        if candidate.is_file():
            paths.append(candidate)
    for tree in _FINGERPRINT_TREES:
        root = frontend_dir / tree
        if root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    unique: dict[str, Path] = {}
    for path in paths:
        relative = _relative(path, frontend_dir)
        if _is_test_source(relative):
            continue
        unique[relative] = path
    return [unique[key] for key in sorted(unique)]


def source_fingerprint(frontend_dir: Path = FRONTEND_DIR) -> dict[str, Any]:
    """前端源码/构建输入的内容指纹；只含仓库相对路径与摘要。"""
    entries: list[tuple[str, str]] = []
    for path in fingerprint_paths(frontend_dir):
        entries.append((_relative(path, frontend_dir), file_digest(path)))
    digest = hashlib.sha256()
    for relative, item_digest in entries:
        digest.update(f"{relative}\0{item_digest}\n".encode())
    return {
        "algorithm": "sha256",
        "roots": list(_FINGERPRINT_TREES),
        "files": [name for name, _ in entries],
        "file_count": len(entries),
        "digest": digest.hexdigest(),
    }


def artifact_manifest(dist_dir: Path = DIST_DIR) -> dict[str, Any]:
    """构建产物的内容清单（相对 ``dist`` 的路径 → sha256），构建戳自身不计入。"""
    files: dict[str, str] = {}
    if dist_dir.is_dir():
        for path in sorted(dist_dir.rglob("*")):
            if not path.is_file() or path.name == STAMP_NAME:
                continue
            files[_relative(path, dist_dir)] = file_digest(path)
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(f"{name}\0{files[name]}\n".encode())
    return {"file_count": len(files), "files": files, "digest": digest.hexdigest()}


def git_state() -> dict[str, Any]:
    """Git HEAD、分支与脏状态（忽略被 gitignore 的产物目录）。"""
    def _run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise EvidenceError(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
        return result.stdout

    status = [line for line in _run("status", "--porcelain").splitlines() if line.strip()]
    return {
        "head": _run("rev-parse", "HEAD").strip(),
        "branch": _run("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "dirty": bool(status),
        "changed_paths": len(status),
    }


def _tool_version(command: Sequence[str], cwd: Path) -> str:
    try:
        result = subprocess.run(list(command), cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:  # pragma: no cover - 缺少工具时只记录 unknown
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamp_path(frontend_dir: Path = FRONTEND_DIR) -> Path:
    """构建戳始终写在 ``frontend/.evidence/``，不进入被 Flask 静态托管的 dist。"""
    if frontend_dir == FRONTEND_DIR:
        return EVIDENCE_DIR / STAMP_NAME
    return frontend_dir / ".evidence" / STAMP_NAME


def load_stamp(frontend_dir: Path = FRONTEND_DIR) -> dict[str, Any] | None:
    path = stamp_path(frontend_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:  # pragma: no cover - 人为破坏时给出可读错误
        raise EvidenceError(f"构建戳不是合法 JSON：{error}") from error


def write_stamp(stamp: dict[str, Any], frontend_dir: Path = FRONTEND_DIR) -> Path:
    path = stamp_path(frontend_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stamp, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_frontend(*, frontend_dir: Path = FRONTEND_DIR, dist_dir: Path = DIST_DIR) -> dict[str, Any]:
    """运行 ``npm run build`` 并写入构建戳（含源码指纹与产物摘要）。"""
    if not (frontend_dir / "node_modules").is_dir():
        raise EvidenceError("frontend/node_modules 缺失；先运行 `npm ci`。")
    result = subprocess.run(
        ["npm", "run", "build"], cwd=frontend_dir, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-20:])
        raise EvidenceError(f"前端构建失败（exit {result.returncode}）：\n{tail}")
    artifacts = artifact_manifest(dist_dir)
    if not (dist_dir / "index.html").is_file() or artifacts["file_count"] == 0:
        raise EvidenceError("构建结束但 dist 为空；拒绝写入构建戳。")
    stamp = {
        "schema_version": SCHEMA_VERSION,
        "built_at": _now(),
        "git": git_state(),
        "source_fingerprint": source_fingerprint(frontend_dir),
        "artifact": {"digest": artifacts["digest"], "file_count": artifacts["file_count"]},
        "toolchain": {
            "node": _tool_version(["node", "--version"], frontend_dir),
            "npm": _tool_version(["npm", "--version"], frontend_dir),
        },
    }
    write_stamp(stamp, frontend_dir)
    return stamp


def verify_build(*, frontend_dir: Path = FRONTEND_DIR, dist_dir: Path = DIST_DIR) -> dict[str, Any]:
    """校验 dist 与构建戳、当前源码三者一致；不一致则拒绝作为最新证据。"""
    reasons: list[str] = []
    if not (dist_dir / "index.html").is_file():
        reasons.append(f"缺少构建产物：{_display_path(dist_dir, REPO_ROOT)}/index.html 不存在")
    stamp = load_stamp(frontend_dir)
    if stamp is None:
        reasons.append(
            "缺少构建戳 frontend/.evidence/build-evidence.json；先运行 "
            "`uv run python -m tests.browser.evidence build`"
        )
    if reasons:
        raise EvidenceError("；".join(reasons))
    assert stamp is not None
    if stamp.get("schema_version") != SCHEMA_VERSION:
        reasons.append(f"构建戳版本 {stamp.get('schema_version')} 与工具 {SCHEMA_VERSION} 不一致")
    current_fingerprint = source_fingerprint(frontend_dir)
    if stamp.get("source_fingerprint", {}).get("digest") != current_fingerprint["digest"]:
        reasons.append("前端源码/构建输入在构建之后发生了变化，构建戳已过期")
    current_artifact = artifact_manifest(dist_dir)
    if stamp.get("artifact", {}).get("digest") != current_artifact["digest"]:
        reasons.append("dist 产物与构建戳不一致（被改写、缺失或由另一次构建产生）")
    if reasons:
        raise EvidenceError("；".join(reasons))
    return stamp


def require_fresh_build() -> dict[str, Any]:
    """``require_dist`` 的实现：dist 必须是当前源码的最新一次证据构建产物。"""
    try:
        return verify_build()
    except EvidenceError as error:
        raise RuntimeError(
            f"frontend/dist 不能作为最新验收证据：{error}。"
            "先运行 `uv run python -m tests.browser.evidence build` 再截图。"
        ) from error


# ---------------------------------------------------------------------------
# 页面实际加载资源
# ---------------------------------------------------------------------------


def _same_origin_path(url: str, base_url: str) -> str | None:
    """把同源 URL 压缩成路径；跨源、带 query 的值一律不记录。"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    base = urlparse(base_url)
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        return None
    return parsed.path or "/"


def is_asset_path(path: str) -> bool:
    return path.startswith("/app/assets/")


@dataclass
class LoadedResourceRecorder:
    """记录页面实际加载的同源 ``/app`` 资源路径与响应体摘要。"""

    base_url: str
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def attach(self, page: Any) -> None:
        page.on("response", self._on_response)

    def _on_response(self, response: Any) -> None:
        try:
            path = _same_origin_path(response.url, self.base_url)
        except Exception:  # pragma: no cover - Playwright 已关闭时忽略
            return
        if path is None or not path.startswith("/app/"):
            return
        content_type = (response.headers or {}).get("content-type", "")
        if not any(token in content_type for token in _ASSET_CONTENT_TYPES):
            return
        if response.status != 200:
            self.resources[path] = {"path": path, "status": response.status, "sha256": None, "content_type": content_type}
            return
        try:
            body = response.body()
        except Exception:  # pragma: no cover - 响应体不可读时不阻塞主断言
            return
        self.resources[path] = {
            "path": path,
            "status": response.status,
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": content_type,
        }

    def records(self) -> list[dict[str, Any]]:
        return [self.resources[path] for path in sorted(self.resources)]


def verify_loaded_resources(
    resources: Iterable[dict[str, Any]], *, dist_dir: Path = DIST_DIR
) -> None:
    """证明页面实际加载的 ``/app/assets/*`` 与 ``/app`` 外壳字节与 dist 产物逐一致。"""
    checked = 0
    for resource in resources:
        path = str(resource.get("path", ""))
        if resource.get("status") != 200:
            raise EvidenceError(f"页面加载的资源状态不是 200：{path} → {resource.get('status')}")
        content_type = str(resource.get("content_type", ""))
        if is_asset_path(path):
            target = dist_dir / path.removeprefix("/app/")
        elif path.startswith("/app/") and "html" in content_type:
            # SPA 外壳：/app/ 与 /app/<client-route> 都返回同一份 index.html。
            target = dist_dir / "index.html"
        else:
            continue
        if not target.is_file():
            raise EvidenceError(f"页面加载了 dist 中不存在的资源：{path}")
        if resource.get("sha256") != file_digest(target):
            raise EvidenceError(f"页面加载的资源与 dist 产物不一致：{path}")
        checked += 1
    if checked == 0:
        raise EvidenceError("页面没有加载任何 /app 资源，无法证明截图来自本次构建")


# ---------------------------------------------------------------------------
# 证据清单
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureDescriptor:
    """固定安全数据的 fixture；mock 只替换安全数据/海报。"""

    fixture_id: str
    description: str
    mock_routes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioDescriptor:
    """一次截图场景：标识、标题与可复现的操作步骤。"""

    scenario_id: str
    title: str
    steps: tuple[str, ...]


def _screenshot_digest(screenshot: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(screenshot) as image:
        size = image.size
    return {
        "file_name": screenshot.name,
        "sha256": file_digest(screenshot),
        "width": size[0],
        "height": size[1],
    }


def capture_evidence(
    page: Any,
    screenshot: Path,
    *,
    base_url: str,
    scenario: ScenarioDescriptor,
    fixture: FixtureDescriptor,
    resources: Iterable[dict[str, Any]],
    route: str = "/app/add",
    dist_dir: Path = DIST_DIR,
) -> dict[str, Any]:
    """组装一次真实 Chromium 截图的证据清单并校验其内部一致性。"""
    stamp = verify_build(dist_dir=dist_dir)
    records = list(resources)
    verify_loaded_resources(records, dist_dir=dist_dir)
    browser = page.context.browser
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": _now(),
        "git": stamp["git"],
        "build": {
            "built_at": stamp["built_at"],
            "artifact_digest": stamp["artifact"]["digest"],
            "artifact_file_count": stamp["artifact"]["file_count"],
            "source_fingerprint": stamp["source_fingerprint"],
            "toolchain": stamp["toolchain"],
        },
        "runtime": {
            "chromium_version": browser.version if browser is not None else "unknown",
            "viewport": page.viewport_size,
            "device_scale_factor": page.evaluate("() => window.devicePixelRatio"),
            "css_zoom": page.evaluate("() => getComputedStyle(document.documentElement).zoom || '1'"),
            "reduced_motion": page.evaluate(
                "() => window.matchMedia('(prefers-reduced-motion: reduce)').matches"
            ),
        },
        "fixture": {
            "id": fixture.fixture_id,
            "description": fixture.description,
            "mock_routes": list(fixture.mock_routes),
        },
        "scenario": {"id": scenario.scenario_id, "title": scenario.title, "steps": list(scenario.steps)},
        "page": {"route": route, "loaded_resources": records},
        "screenshot": _screenshot_digest(screenshot),
    }
    assert_manifest_safe(manifest)
    return manifest


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_manifest(manifest: dict[str, Any], directory: Path, stem: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.evidence.json"
    path.write_text(canonical_json(manifest), encoding="utf-8")
    return path


def manifest_safety_errors(payload: Any) -> list[str]:
    """扫描清单里的绝对路径、URL 与可疑秘密键；返回问题列表（空表示安全）。"""
    problems: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered in _FORBIDDEN_MANIFEST_KEYS:
                    problems.append(f"清单出现可疑秘密字段：{path}.{key}")
                walk(item, f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        if isinstance(value, str):
            if _ABSOLUTE_PATH_RE.search(value):
                problems.append(f"清单出现本地绝对路径：{path}")
            if _URL_RE.search(value):
                problems.append(f"清单出现完整 URL：{path}")

    walk(payload, "$")
    return problems


def assert_manifest_safe(payload: Any) -> None:
    problems = manifest_safety_errors(payload)
    if problems:
        raise EvidenceError("；".join(problems))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_build(_args: argparse.Namespace) -> int:
    stamp = build_frontend()
    print(
        "构建戳已写入 frontend/.evidence/build-evidence.json："
        f"HEAD={stamp['git']['head'][:12]} dirty={stamp['git']['dirty']} "
        f"artifact={stamp['artifact']['digest'][:12]} sources={stamp['source_fingerprint']['file_count']} 个文件"
    )
    return 0


def _cmd_verify(_args: argparse.Namespace) -> int:
    try:
        stamp = verify_build()
    except EvidenceError as error:
        print(f"不通过：{error}", file=sys.stderr)
        return 1
    print(
        "通过：dist 与构建戳一致；"
        f"HEAD={stamp['git']['head'][:12]} dirty={stamp['git']['dirty']} "
        f"artifact={stamp['artifact']['digest'][:12]}"
    )
    return 0


def _cmd_preview(args: argparse.Namespace) -> int:
    """用同一份已校验 dist + 固定安全 fixture 启动**隔离**的人工交互预览。

    预览进程不读写真实验运行数据与部署配置（临时 config/storage），``/api/v1`` 只应答
    与截图同源的固定 fixture，其余接口在本地 fail closed，不连接真实 MiKan／Auto Bangumi／
    qBittorrent，也不产生任何保存/提交/删除写。
    """
    try:
        stamp = verify_build()
    except EvidenceError as error:
        print(f"不通过：{error}", file=sys.stderr)
        return 1
    from tests.browser.preview_fixtures import PREVIEW_BATCH_ID, create_preview_app

    app, temp_root = create_preview_app()
    print("人工预览（隔离临时目录 + 固定安全 fixture）：")
    print(f"  单番首屏 / 批量首屏：http://{args.host}:{args.port}/app/add")
    print(f"  固定批量草案现场：http://{args.host}:{args.port}/app/workbench?batch_id={PREVIEW_BATCH_ID}")
    print(
        "  构建产物："
        f"{stamp['artifact']['digest'][:12]}（HEAD={stamp['git']['head'][:12]} dirty={stamp['git']['dirty']}，已校验与当前源码一致）"
    )
    print(f"  隔离目录（临时，可随时删除）：{temp_root}")
    print("  说明：AB 未配置、追番列表为空；批量/候选/海报为固定安全 fixture；")
    print("        未覆盖的 /api/v1 接口在本地 fail closed，不产生外部调用。")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="#155 截图证据与构建新鲜度工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="运行前端生产构建并写入构建戳")
    sub.add_parser("verify", help="校验 dist 是否可作为最新验收证据")
    preview = sub.add_parser("preview", help="用同一份 dist 启动人工交互预览")
    preview.add_argument("--host", default="127.0.0.1")
    preview.add_argument("--port", type=int, default=5000)
    args = parser.parse_args(argv)
    if os.environ.get("MIGU_ORCA_EVIDENCE_DEBUG"):
        print(json.dumps({"frontend": str(FRONTEND_DIR)}, ensure_ascii=False))
    return {"build": _cmd_build, "verify": _cmd_verify, "preview": _cmd_preview}[args.command](args)


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
