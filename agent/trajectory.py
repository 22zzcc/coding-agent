# -*- coding: utf-8 -*-
"""
agent/trajectory.py —— 轨迹记录与评测（三类失败定位 + 权限审计）
==================================================================

轨迹 = Agent 的「黑匣子」：记录 prompt / 工具调用 / diff / 被拒操作。
评测时把失败定位到三类根因：工具误选、编辑失效、上下文丢失。
「权限审计」：被权限拒绝的操作写进轨迹（不进上下文），据此能审计
「agent 试图做什么、被拦了什么」。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Trajectory:
    task: str = ""
    steps: list[dict] = field(default_factory=list)        # {thought,tool,args,result,ok}
    diffs: list[dict] = field(default_factory=list)        # {path,old,new}
    rejections: list[dict] = field(default_factory=list)   # 权限审计：被拒操作
    final: str = ""

    def record_step(self, thought, tool, args, result, ok) -> None:
        self.steps.append({"thought": thought, "tool": tool, "args": args,
                           "result": result[:400], "ok": ok})

    def record_diff(self, path, old, new) -> None:
        self.diffs.append({"path": path, "old": old, "new": new})

    def record_rejection(self, tool, args, reason) -> None:
        """权限审计：被拒的操作只进轨迹（不进上下文）。"""
        self.rejections.append({"tool": tool, "args": args, "reason": reason})

    def audit(self) -> str:
        """审计报告：agent 试图做了什么、被拦了什么。"""
        if not self.rejections:
            return "（无被拒操作）"
        return "\n".join(f"- 试图 {r['tool']}({r['args']}) → 被拒：{r['reason']}"
                         for r in self.rejections)

    def to_dict(self) -> dict:
        return {"task": self.task, "steps": self.steps, "diffs": self.diffs,
                "rejections": self.rejections, "final": self.final,
                "n_steps": len(self.steps)}


def classify_failure(traj: Trajectory, hit_rebuild: bool = False) -> str:
    """把「没成功」定位到三类根因之一：工具误选 / 编辑失效 / 上下文丢失。"""
    for s in traj.steps:
        if not s["ok"]:
            if s["tool"] == "edit" and ("匹配" in s["result"] or "命中" in s["result"]):
                return "编辑失效"
            if s["tool"] == "bash" and "权限" in s["result"]:
                return "权限拦截"
            return "工具误选"
    if hit_rebuild or not traj.final:
        return "上下文丢失"
    return "其他"
