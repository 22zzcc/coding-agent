# -*- coding: utf-8 -*-
"""
agent/loop.py —— ReAct 主循环（解析→分发→回填→终止）+ 快照断点
================================================================

每轮四步：解析（JSON 动作）→ 分发执行（工具）→ 结果回填（上下文）→ 终止判定。
关键设计：
    - 权限被拒的操作：写进轨迹、**不进上下文**（审计用，不污染上下文）；
    - 每步执行后存快照，失败/崩溃可从快照恢复、断点续跑。
"""
from __future__ import annotations

import json
import re

from .context import ContextManager
from .tools import Ctx, describe_tools, run_tool
from .trajectory import Trajectory

_SYSTEM = """你是终端编程 Agent。通过调用工具修改工作区代码完成任务。

可用工具：
{tools}

每轮只输出一个 JSON，二选一：
1. 调用工具：{{"thought": "思考", "tool": "工具名", "args": {{...}}}}
2. 完成任务：{{"thought": "思考", "final": "最终回答"}}

规则：动手前先 read；edit 的 old_string 必须与文件完全一致；任务完成输出 final。
"""


def _parse(raw: str) -> dict | None:
    try:
        return json.loads(raw) if isinstance(json.loads(raw), dict) else None
    except Exception:
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e > s:
            try:
                return json.loads(raw[s:e + 1])
            except Exception:
                return None
    return None


class Loop:
    def __init__(self, llm, registry: dict, ctx: Ctx,
                 context_manager: ContextManager | None = None,
                 max_steps: int = 10, checkpoint_path: str = "data/checkpoint.json"):
        self.llm = llm
        self.registry = registry
        self.ctx = ctx
        self.max_steps = max_steps
        self.checkpoint_path = checkpoint_path
        self.cm = context_manager or ContextManager(
            _SYSTEM.format(tools=describe_tools(registry)))

    def run(self, task: str, traj: Trajectory | None = None) -> tuple[str, Trajectory]:
        # 默认用 ctx.trajectory（工具层也写它），保证权限审计/轨迹一致；
        # 子 agent 可传独立 traj，避免污染主轨迹。
        if traj is None:
            traj = self.ctx.trajectory
        traj.task, traj.steps, traj.diffs, traj.rejections, traj.final = \
            task, [], [], [], ""
        self.cm.set_task(task)
        self.cm.add("user", f"任务：{task}")

        for _ in range(self.max_steps):
            self.cm.fit()
            messages = [{"role": "system", "content": self.cm.system_prompt}] + self.cm.to_list()
            raw = self.llm.complete(messages)
            obj = _parse(raw)

            if obj is None:
                self.cm.add("assistant", raw)
                self.cm.add("user", "上一轮不是合法 JSON，请只输出一个 JSON。")
                traj.record_step("", "(解析失败)", {}, "非法 JSON", False)
                continue

            thought = obj.get("thought", "")
            if "final" in obj:
                traj.final = obj["final"]
                traj.record_step(thought, "(final)", {}, obj["final"], True)
                self._checkpoint(traj)
                return obj["final"], traj

            tool, args = obj.get("tool", ""), obj.get("args", {}) or {}
            before_rej = len(traj.rejections)
            result, ok = run_tool(self.registry, tool, args, self.ctx)
            traj.record_step(thought, tool, args, result, ok)

            # 结果回填：权限被拒的操作不进上下文（只进轨迹，审计用）
            if len(traj.rejections) > before_rej or "权限" in result:
                self.cm.add("assistant", raw)
                self.cm.add("user", f"（{tool} 被权限拒绝，已记录审计，不再尝试）")
            else:
                self.cm.add("assistant", raw)
                self.cm.add("user", f"工具 {tool} 返回：\n{result}")

            self._checkpoint(traj)     # 每步快照，失败可断点续跑

        traj.final = ""
        return "", traj

    def _checkpoint(self, traj: Trajectory) -> None:
        try:
            self.ctx.snapshot.save_state(self.checkpoint_path, {
                "task": traj.task, "steps": len(traj.steps),
                "messages": self.cm.to_list(), "final": traj.final})
        except Exception:
            pass

    def resume(self) -> Trajectory | None:
        """断点续跑：从快照恢复会话。"""
        state = self.ctx.snapshot.load_state(self.checkpoint_path)
        if not state:
            return None
        self.cm.messages = state.get("messages", [])
        traj = Trajectory(task=state.get("task", ""))
        traj.final = state.get("final", "")
        return traj
