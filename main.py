#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py —— 本地 Coding Agent 入口
==================================

用法（在项目根目录）：

    python main.py run "修复 add 函数" --mock            # 离线跑通 ReAct 全链路
    python main.py run "新增 subtract 函数" --mock
    python main.py run "修复 add" --mock --level read    # 演示权限审计（edit 被拒进轨迹）
    python main.py run "子 agent 处理" --mock            # 演示子 agent
    python main.py eval --mock                           # 三类失败定位演示
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def build(args):
    from agent.llm import OllamaLLM, MockLLM
    from agent.permissions import Permissions
    from agent.snapshot import SnapshotManager
    from agent.trajectory import Trajectory
    from agent.tools import Ctx, build_registry, describe_tools
    from agent.router import Router
    from agent.loop import Loop

    root = Path(args.root).resolve()
    llm = MockLLM() if args.mock else OllamaLLM()
    perms = Permissions(level=args.level, workspace_root=root)
    snap = SnapshotManager(root)
    traj = Trajectory()
    registry = build_registry()
    ctx = Ctx(root=root, permissions=perms, trajectory=traj, snapshot=snap)

    system = "你是终端编程 Agent。通过工具修改代码完成任务。\n可用工具：\n" \
        + describe_tools(registry)
    router = Router(llm, registry, ctx, system_prompt=system)
    ctx.router = router
    loop = Loop(llm, registry, ctx, checkpoint_path=str(root / ".." / "data" / "checkpoint.json"))
    return loop, traj, router


def _print_result(loop, traj, router):
    print("=" * 70)
    print("轨迹：")
    for i, s in enumerate(traj.steps, 1):
        print(f"  {i}. [{s['tool']}] {'✓' if s['ok'] else '✗'}  {s['thought'] or s['result'][:50]}")
    if traj.diffs:
        print("变更(diff)：")
        for d in traj.diffs:
            print(f"  {d['path']}: {d['old'][:30]!r} -> {d['new'][:30]!r}")
    print("权限审计：")
    print("  " + traj.audit())
    print(f"路由统计：规则 {router.rule_hits} / 向量 {router.vector_hits} / LLM {router.llm_hits}")


def cmd_run(args):
    loop, traj, router = build(args)
    print(f"[Coding Agent] 工作区={Path(args.root).resolve()}  权限档={args.level}")
    final, traj = loop.run(args.request)
    print(f"最终回答：\n{final or '(未完成)'}\n")
    _print_result(loop, traj, router)


def cmd_eval(args):
    from agent.trajectory import classify_failure
    tasks = ["修复 add 函数", "新增 subtract 函数", "跑一个不存在的命令"]
    for t in tasks:
        loop, traj, router = build(args)
        _, traj = loop.run(t)
        ok = bool(traj.final) and all(s["ok"] for s in traj.steps)
        fail = "" if ok else classify_failure(traj, loop.cm.rebuild_count > 0)
        print(f"  {'✅' if ok else '❌'} {t}  {fail or '（成功）'}")


def main():
    parser = argparse.ArgumentParser(description="本地 Coding Agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="执行任务")
    p.add_argument("request")
    p.add_argument("--root", default="demo_repo")
    p.add_argument("--level", default="write", choices=["read", "write", "execute"])
    p.add_argument("--mock", action="store_true")
    p.set_defaults(func=cmd_run)

    p2 = sub.add_parser("eval", help="三类失败定位")
    p2.add_argument("--root", default="demo_repo")
    p2.add_argument("--level", default="write", choices=["read", "write", "execute"])
    p2.add_argument("--mock", action="store_true")
    p2.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
