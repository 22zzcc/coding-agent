# -*- coding: utf-8 -*-
"""
agent/router.py —— 三级路由（规则→向量→LLM）+ 子 agent 隔离（最多 2 个）
========================================================================

三级路由：便宜的层级先上，不自信才升级——
    规则（正则/关键词，最快）→ 向量（embedding 相似，中等）→ LLM（最贵，兜底）。

子 agent：Task 工具触发，派生全新隔离上下文，只回传截断结论；最多 2 个。
"""
from __future__ import annotations

import json
import math
import re

from .context import ContextManager

RULES = {"修复": [r"修复", r"\bfix\b", r"错误"], "新增": [r"新增", r"添加", r"\badd\b"],
         "测试": [r"测试", r"\btest\b"]}


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)) + 1e-9)


class Router:
    def __init__(self, llm, registry, ctx, system_prompt: str,
                 max_subagents: int = 2, embed_fn=None):
        self.llm = llm
        self.registry = registry
        self.ctx = ctx
        self.system_prompt = system_prompt
        self.max_subagents = max_subagents
        self.embed_fn = embed_fn
        self.subagent_count = 0
        self.rule_hits = self.vector_hits = self.llm_hits = 0

    # ---- 三级路由 ----
    def route(self, text: str) -> tuple[str, str]:
        for cat, pats in RULES.items():
            for p in pats:
                if re.search(p, text, flags=re.I):
                    self.rule_hits += 1
                    return cat, "rule"
        if self.embed_fn is not None:
            try:
                qv = self.embed_fn([text])[0]
                best, best_sim = None, 0.0
                for cat, exs in {"修复": ["修复 bug"], "新增": ["新增功能"]}.items():
                    sim = max(_cosine(qv, ev) for ev in self.embed_fn(exs))
                    if sim > best_sim:
                        best, best_sim = cat, sim
                if best and best_sim > 0.5:
                    self.vector_hits += 1
                    return best, "vector"
            except Exception:
                pass
        self.llm_hits += 1
        return self._llm_route(text), "llm"

    def _llm_route(self, text: str) -> str:
        try:
            prompt = ("归类到 修复/新增/测试 之一，只输出类别：\n" + text)
            raw = self.llm.complete([{"role": "user", "content": prompt}])
            return next((c for c in RULES if c in raw), "修复")
        except Exception:
            return "修复"

    @property
    def llm_ratio(self) -> float:
        total = self.rule_hits + self.vector_hits + self.llm_hits
        return self.llm_hits / total if total else 0.0

    # ---- 子 agent（隔离上下文，最多 2 个）----
    def run_subagent(self, prompt: str):
        if self.subagent_count >= self.max_subagents:
            return f"错误：子 agent 已达上限（{self.max_subagents} 个）", False
        from .loop import Loop  # 惰性导入，避免循环依赖
        from .trajectory import Trajectory
        self.subagent_count += 1
        cm = ContextManager(self.system_prompt)          # 全新隔离上下文
        sub_traj = Trajectory()                          # 独立轨迹（不污染主轨迹）
        child_ctx = Ctx_clone(self.ctx, router=None)
        child_ctx.trajectory = sub_traj                  # 子 agent 不再递归派生子 agent
        loop = Loop(self.llm, self.registry, child_ctx, context_manager=cm, max_steps=4)
        final, _ = loop.run(prompt, traj=sub_traj)
        # 子 agent 的权限拒绝合并回主轨迹（审计完整），但步骤不回传
        self.ctx.trajectory.rejections.extend(sub_traj.rejections)
        return final[:1000] or "（子 agent 未产出）", bool(final)


def Ctx_clone(ctx, router=None):
    """克隆一个工具上下文（共享权限/轨迹/快照，但不递归派生子 agent）。"""
    return ctx.__class__(root=ctx.root, permissions=ctx.permissions,
                         trajectory=ctx.trajectory, snapshot=ctx.snapshot,
                         router=router)
