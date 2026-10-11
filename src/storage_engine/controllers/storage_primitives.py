"""本地 JSON 存储的共享原语（#170）。

只回答三件事：**是否在根内**、**怎么写才不会读到半个文件**、**同一 key 如何串行**。

「越界算哪种错误、`failed_step` 是什么、用户看到哪句中文」属于各 repository 的错误
契约，继续留在它们自己手里（各处 `error_type` 不同且被契约测试与前端断言钉住）。

分层：本模块属于 `storage_engine`（本地 JSON 存储细节），不放进 `shared`。
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from threading import RLock


def is_relative_to(path: Path, parent: Path) -> bool:
    """纯布尔：``path`` 是否位于 ``parent`` 之内。

    只回答「是否越界」；越界时抛哪种错误、带什么 `failed_step` 由调用方决定。
    """
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def write_text_atomic(path: Path, payload: str) -> None:
    """同目录 ``<name>.tmp`` + ``os.replace`` 原子写。

    崩溃或中断时目标文件要么是旧内容要么是新内容，读者不会看到半个文件；写入或替换
    失败向上抛 ``OSError``，由调用方翻译成自己的 ``storage_error``（文案与 `failed_step`
    不变）。临时文件在 finally 里清除，与既有实现一致。
    """
    temp_path = path.with_name(path.name + ".tmp")
    try:
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()


class KeyedLocks:
    """进程内 per-key 可重入锁池。

    每个 repository 持有自己的一份实例，键空间互不干扰（沿用旧实现的粒度）：同一条目
    的并发 ensure/CAS 写被串行化，不同条目互不阻塞。锁随进程存活；id 空间小（一条记录
    一把锁），不做回收。
    """

    def __init__(self) -> None:
        self._guard = RLock()
        self._locks: dict[str, RLock] = {}

    def for_key(self, key: str) -> RLock:
        """返回 ``key`` 对应的锁（首次访问时创建）。"""
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = RLock()
                self._locks[key] = lock
            return lock
