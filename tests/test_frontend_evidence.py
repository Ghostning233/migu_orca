"""#155：构建新鲜度与证据清单的最小可失败证明（不需要浏览器）。

这些用例固定「陈旧/被改写产物会被拒绝」「源码变化使构建戳失效」「清单不含绝对路径/
URL/秘密」以及「页面实际加载资源必须与 dist 逐字节一致」这几条工具契约。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.browser import evidence


def _fake_frontend(root: Path) -> Path:
    frontend = root / "frontend"
    (frontend / "src" / "features").mkdir(parents=True)
    (frontend / "src" / "main.ts").write_text("export const value = 1\n", encoding="utf-8")
    (frontend / "src" / "features" / "view.vue").write_text("<template><p>a</p></template>\n", encoding="utf-8")
    (frontend / "index.html").write_text("<div id='app'></div>\n", encoding="utf-8")
    (frontend / "package.json").write_text('{"name":"fake"}\n', encoding="utf-8")
    (frontend / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    # 这些文件必须落在指纹范围之外：
    (frontend / "node_modules").mkdir()
    (frontend / "node_modules" / "dep.js").write_text("dep\n", encoding="utf-8")
    (frontend / "dist").mkdir()
    (frontend / "dist" / "index.html").write_text("<div id='app'></div>\n", encoding="utf-8")
    (frontend / "README.md").write_text("docs only\n", encoding="utf-8")
    return frontend


def _fake_dist(frontend: Path) -> Path:
    dist = frontend / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<div id='app'></div>\n", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log('app')\n", encoding="utf-8")
    return dist


def _stamp_for(frontend: Path, dist: Path) -> dict[str, object]:
    return {
        "schema_version": evidence.SCHEMA_VERSION,
        "built_at": "2026-10-02T00:00:00Z",
        "git": {"head": "0" * 40, "branch": "feat/fake", "dirty": True, "changed_paths": 3},
        "source_fingerprint": evidence.source_fingerprint(frontend),
        "artifact": {
            "digest": evidence.artifact_manifest(dist)["digest"],
            "file_count": evidence.artifact_manifest(dist)["file_count"],
        },
        "toolchain": {"node": "v22.0.0", "npm": "10.0.0"},
    }


def test_fingerprint_scope_excludes_build_output_and_docs(tmp_path: Path) -> None:
    frontend = _fake_frontend(tmp_path)
    _fake_dist(frontend)
    (frontend / "src" / "features" / "view.test.ts").write_text("test\n", encoding="utf-8")
    names = {path.relative_to(frontend).as_posix() for path in evidence.fingerprint_paths(frontend)}
    assert "src/main.ts" in names
    assert "index.html" in names
    assert "package-lock.json" in names
    assert not any(name.startswith("dist/") for name in names)
    assert not any(name.startswith("node_modules/") for name in names)
    assert "README.md" not in names
    # 测试文件不参与构建，也不进入指纹。
    assert "src/features/view.test.ts" not in names


def test_missing_stamp_is_rejected(tmp_path: Path) -> None:
    frontend = _fake_frontend(tmp_path)
    dist = _fake_dist(frontend)
    with pytest.raises(evidence.EvidenceError, match="缺少构建戳"):
        evidence.verify_build(frontend_dir=frontend, dist_dir=dist)


def test_fresh_dirty_build_is_accepted_and_identifiable(tmp_path: Path) -> None:
    frontend = _fake_frontend(tmp_path)
    dist = _fake_dist(frontend)
    stamp = _stamp_for(frontend, dist)
    evidence.write_stamp(stamp, frontend)
    verified = evidence.verify_build(frontend_dir=frontend, dist_dir=dist)
    assert verified["git"]["dirty"] is True
    assert verified["git"]["branch"] == "feat/fake"


def test_modified_artifact_is_rejected(tmp_path: Path) -> None:
    frontend = _fake_frontend(tmp_path)
    dist = _fake_dist(frontend)
    evidence.write_stamp(_stamp_for(frontend, dist), frontend)
    (dist / "assets" / "index-abc.js").write_text("console.log('tampered')\n", encoding="utf-8")
    with pytest.raises(evidence.EvidenceError, match="dist 产物与构建戳不一致"):
        evidence.verify_build(frontend_dir=frontend, dist_dir=dist)


def test_source_change_since_build_is_rejected(tmp_path: Path) -> None:
    frontend = _fake_frontend(tmp_path)
    dist = _fake_dist(frontend)
    evidence.write_stamp(_stamp_for(frontend, dist), frontend)
    (frontend / "src" / "main.ts").write_text("export const value = 2\n", encoding="utf-8")
    with pytest.raises(evidence.EvidenceError, match="构建戳已过期"):
        evidence.verify_build(frontend_dir=frontend, dist_dir=dist)


def test_removed_artifact_file_is_rejected(tmp_path: Path) -> None:
    frontend = _fake_frontend(tmp_path)
    dist = _fake_dist(frontend)
    evidence.write_stamp(_stamp_for(frontend, dist), frontend)
    (dist / "assets" / "index-abc.js").unlink()
    with pytest.raises(evidence.EvidenceError, match="dist 产物与构建戳不一致"):
        evidence.verify_build(frontend_dir=frontend, dist_dir=dist)


def test_loaded_assets_must_match_dist_bytes(tmp_path: Path) -> None:
    frontend = _fake_frontend(tmp_path)
    dist = _fake_dist(frontend)
    digest = evidence.file_digest(dist / "assets" / "index-abc.js")
    evidence.verify_loaded_resources(
        [{"path": "/app/assets/index-abc.js", "status": 200, "sha256": digest}], dist_dir=dist
    )
    with pytest.raises(evidence.EvidenceError, match="与 dist 产物不一致"):
        evidence.verify_loaded_resources(
            [{"path": "/app/assets/index-abc.js", "status": 200, "sha256": "f" * 64}], dist_dir=dist
        )
    with pytest.raises(evidence.EvidenceError, match="dist 中不存在"):
        evidence.verify_loaded_resources(
            [{"path": "/app/assets/index-missing.js", "status": 200, "sha256": "f" * 64}], dist_dir=dist
        )
    with pytest.raises(evidence.EvidenceError, match="没有加载任何"):
        evidence.verify_loaded_resources([], dist_dir=dist)


def test_manifest_safety_scan_flags_paths_urls_and_secrets() -> None:
    safe = {
        "fixture": {"id": "batch-draft", "mock_routes": ["/api/v1/batch/parse"]},
        "page": {"route": "/app/add"},
        "screenshot": {"file_name": "shot.png", "sha256": "0" * 64},
    }
    assert evidence.manifest_safety_errors(safe) == []

    assert evidence.manifest_safety_errors({"path": "/home/someone/migu_orca/x.png"})
    assert evidence.manifest_safety_errors({"path": "/tmp/pytest-of-root/x.png"})
    assert evidence.manifest_safety_errors({"url": "https://mikan.example/Home/Bangumi/1"})
    assert evidence.manifest_safety_errors({"password": "hunter2"})
    assert evidence.manifest_safety_errors({"nested": [{"token": "abc"}]})
