# -*- coding: utf-8 -*-
"""
agent/permissions.py —— 三档权限 + 危险命令黑名单 + 路径越界 + 审计
====================================================================

三档权限：read < write < execute。危险命令黑名单 + 路径越界检测。
关键设计（权限审计）：被拒操作**写进轨迹、不进上下文**，据此能审计
「agent 试图越界什么」——安全审计的依据，也是「误杀率」的数据来源。
"""
from __future__ import annotations

import re
from pathlib import Path

TOOL_LEVEL = {"read": "read", "glob": "read", "grep": "read",
              "write": "write", "edit": "write",
              "bash": "execute", "task": "read"}
_LEVEL_RANK = {"read": 0, "write": 1, "execute": 2}

DANGEROUS_PATTERNS = [
    r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b", r"\bsudo\b", r"\bmkfs\b",
    r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", r">\s*/dev/(sd|nvme|disk)",
    r"\bchmod\s+777\b", r"\bshutdown\b", r"\breboot\b", r"\b:\(\)\s*\{",
]


class PermissionError_(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Permissions:
    def __init__(self, level: str = "write", workspace_root: str | Path = "."):
        self.level = level
        self.root = Path(workspace_root).resolve()

    def tool_allowed(self, tool: str) -> bool:
        need = TOOL_LEVEL.get(tool, "execute")   # 未知工具按最高要求
        return _LEVEL_RANK[need] <= _LEVEL_RANK[self.level]

    def check_command(self, command: str) -> None:
        for pat in DANGEROUS_PATTERNS:
            if re.search(pat, command, flags=re.I):
                raise PermissionError_(f"命令命中危险黑名单：{command!r}")

    def resolve_path(self, path: str | Path) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        resolved = p.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise PermissionError_(f"路径越界被拦截：{path!r}")
        return resolved
