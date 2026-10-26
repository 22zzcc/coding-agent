# -*- coding: utf-8 -*-
"""
agent/tools.py —— 七个核心工具（read/write/edit/glob/grep/bash/task）
======================================================================

统一签名 (ctx, **args) -> (结果, 是否成功)。工具是 agent 碰文件系统的唯一通道：
每次操作都过权限 + 快照（写入锁），异常不抛出、转成错误文本。
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .permissions import Permissions, PermissionError_
from .snapshot import SnapshotManager
from .trajectory import Trajectory


@dataclass
class Ctx:
    """工具上下文：把权限/轨迹/快照/路由传给每个工具。"""
    root: Path
    permissions: Permissions
    trajectory: Trajectory
    snapshot: SnapshotManager
    router: object | None = None


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------
def _read(ctx: Ctx, path: str, start: int | None = None, end: int | None = None):
    p = ctx.permissions.resolve_path(path)
    if not p.exists():
        return f"错误：文件不存在 {path}", False
    lines = p.read_text(encoding="utf-8").splitlines()
    start, end = max(1, start or 1), min(len(lines), end or len(lines))
    return "\n".join(f"{i:>4} | {lines[i-1]}" for i in range(start, end + 1)) or "(空)", True


def _write(ctx: Ctx, path: str, content: str):
    if not ctx.permissions.tool_allowed("write"):
        ctx.trajectory.record_rejection("write", {"path": path}, "权限档不足")
        return "错误：当前权限档不允许写入", False
    p = ctx.permissions.resolve_path(path)
    ctx.snapshot.acquire(path)          # 写入锁
    ctx.snapshot.snapshot_file(path)    # 快照（失败可回滚）
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {path}（{len(content)} 字符）", True
    finally:
        ctx.snapshot.release(path)


def _edit(ctx: Ctx, path: str, old_string: str, new_string: str):
    if not ctx.permissions.tool_allowed("edit"):
        ctx.trajectory.record_rejection("edit", {"path": path}, "权限档不足")
        return "错误：当前权限档不允许编辑", False
    p = ctx.permissions.resolve_path(path)
    if not p.exists():
        return f"错误：文件不存在 {path}", False
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return f"错误：未匹配到目标文本（请先 read 看当前内容）", False   # 编辑失效
    if count > 1:
        return f"错误：目标文本命中 {count} 处，请提供更长唯一上下文", False
    ctx.snapshot.acquire(path)
    ctx.snapshot.snapshot_file(path)
    try:
        p.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
        ctx.trajectory.record_diff(path, old_string, new_string)
        return f"已修改 {path}（1 处替换）", True
    finally:
        ctx.snapshot.release(path)


def _glob(ctx: Ctx, pattern: str):
    return "\n".join(sorted(str(p.relative_to(ctx.root))
                            for p in ctx.root.glob(pattern) if p.is_file())) or "未匹配", True


def _grep(ctx: Ctx, pattern: str, path: str = "."):
    base = ctx.permissions.resolve_path(path)
    files = base.rglob("*") if base.is_dir() else [base]
    hits = []
    rx = re.compile(pattern)
    for f in files:
        if not f.is_file():
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(ctx.root)}:{i}: {line}")
        except UnicodeDecodeError:
            continue
    return "\n".join(hits[:100]) or f"未匹配：{pattern}", True


def _bash(ctx: Ctx, command: str):
    if not ctx.permissions.tool_allowed("bash"):
        ctx.trajectory.record_rejection("bash", {"command": command}, "需 execute 权限档")
        return "错误：执行命令需 execute 权限档", False
    try:
        ctx.permissions.check_command(command)
    except PermissionError_ as e:
        ctx.trajectory.record_rejection("bash", {"command": command}, str(e))
        return f"权限拦截：{e}", False
    try:
        proc = subprocess.run(command, shell=True, cwd=str(ctx.root),
                              capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "错误：命令超时（30s）", False
    return (proc.stdout + proc.stderr).strip()[:4000] or "(无输出)", proc.returncode == 0


def _task(ctx: Ctx, prompt: str):
    if ctx.router is None:
        return "错误：子 agent 路由未初始化", False
    result, ok = ctx.router.run_subagent(prompt)
    return result, ok


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
@dataclass
class Tool:
    name: str
    description: str
    params: dict
    func: object


def build_registry() -> dict[str, Tool]:
    return {
        "read": Tool("read", "读取文件（带行号）", {"path": "路径"}, _read),
        "write": Tool("write", "整文件写入", {"path": "路径", "content": "内容"}, _write),
        "edit": Tool("edit", "精确替换（old_string 唯一命中）",
                     {"path": "路径", "old_string": "原文", "new_string": "替换文"}, _edit),
        "glob": Tool("glob", "按模式列文件", {"pattern": "glob"}, _glob),
        "grep": Tool("grep", "正则搜内容", {"pattern": "正则", "path": "目录"}, _grep),
        "bash": Tool("bash", "执行 shell（需 execute）", {"command": "命令"}, _bash),
        "task": Tool("task", "派生子 agent（隔离上下文，最多 2 个）", {"prompt": "子任务"}, _task),
    }


def describe_tools(registry: dict[str, Tool]) -> str:
    return "\n".join(f"- {t.name}({', '.join(t.params)}): {t.description}"
                     for t in registry.values())


def run_tool(registry: dict[str, Tool], name: str, args: dict, ctx: Ctx):
    tool = registry.get(name)
    if tool is None:
        return f"错误：未知工具 {name}", False
    try:
        return tool.func(ctx, **args)
    except PermissionError_ as e:
        ctx.trajectory.record_rejection(name, args, str(e))
        return f"权限拦截：{e}", False
    except Exception as e:
        return f"工具异常：{type(e).__name__}: {e}", False
