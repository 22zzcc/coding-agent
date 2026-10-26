# -*- coding: utf-8 -*-
"""
agent/snapshot.py —— 快照 + 写入锁（失败恢复、断点续跑）
========================================================

- 快照：写入前记录文件原内容 + 会话状态，失败可回滚、可断点续跑；
- 写入锁：edit/write 前对目标文件加锁，防止并发冲突。
"""
from __future__ import annotations

import json
from pathlib import Path


class SnapshotManager:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._originals: dict[str, str] = {}   # 文件原内容（回滚用）
        self._locks: set[str] = set()          # 写入锁

    # ---- 写入锁 ----
    def acquire(self, path: str) -> None:
        """对文件加写入锁；已加锁则抛错（防止并发写冲突）。"""
        p = str(Path(path).resolve())
        if p in self._locks:
            raise RuntimeError(f"写入锁冲突：{path} 正被其它操作占用")
        self._locks.add(p)

    def release(self, path: str) -> None:
        self._locks.discard(str(Path(path).resolve()))

    # ---- 快照（写入前记录原内容）----
    def snapshot_file(self, path: str) -> None:
        p = Path(path).resolve()
        if p.exists() and str(p) not in self._originals:
            self._originals[str(p)] = p.read_text(encoding="utf-8")

    def restore_file(self, path: str) -> None:
        """失败恢复：把文件回滚到写入前的内容。"""
        key = str(Path(path).resolve())
        if key in self._originals:
            Path(key).write_text(self._originals[key], encoding="utf-8")

    # ---- 会话状态快照（断点续跑）----
    def save_state(self, path: str, state: dict) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def load_state(self, path: str) -> dict | None:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None
