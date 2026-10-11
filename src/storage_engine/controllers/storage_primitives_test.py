from __future__ import annotations

from pathlib import Path

import pytest

from storage_engine.controllers.storage_primitives import (
    KeyedLocks,
    is_relative_to,
    write_text_atomic,
)


def test_is_relative_to_answers_membership_only(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert is_relative_to(root / "a.json", root) is True
    assert is_relative_to(root / "nested" / "a.json", root) is True
    # 原语是词法判定（与旧 `_is_relative_to` 一致）：`..` 由调用方的 resolve 先收敛。
    assert is_relative_to(root / ".." / "escape.json", root) is True
    assert is_relative_to((root / ".." / "escape.json").resolve(), root) is False
    assert is_relative_to(tmp_path / "root2" / "a.json", root) is False
    assert is_relative_to(root, root) is True


def test_write_text_atomic_replaces_content_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "record.json"
    target.write_text("old", encoding="utf-8")

    write_text_atomic(target, '{"new": true}\n')

    assert target.read_text(encoding="utf-8") == '{"new": true}\n'
    assert [path.name for path in tmp_path.iterdir()] == ["record.json"]


def test_write_text_atomic_surfaces_oserror_without_leaving_temp(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        write_text_atomic(tmp_path / "missing-dir" / "record.json", "{}\n")
    assert list(tmp_path.iterdir()) == []


def test_keyed_locks_are_stable_per_key_and_per_pool() -> None:
    locks = KeyedLocks()
    assert locks.for_key("tracking-a") is locks.for_key("tracking-a")
    assert locks.for_key("tracking-a") is not locks.for_key("tracking-b")
    # 每个 repository 一份锁池：不同池的同名 key 互不影响（沿用旧粒度）。
    assert KeyedLocks().for_key("tracking-a") is not locks.for_key("tracking-a")
    with locks.for_key("tracking-a"), locks.for_key("tracking-a"):
        pass
