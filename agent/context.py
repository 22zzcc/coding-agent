# -*- coding: utf-8 -*-
"""
agent/context.py —— 轨迹感知上下文管理（四指标 + 三级压缩）
============================================================

「轨迹感知」：压缩上下文时不只看「谁最旧」，而是用四个指标给每条历史打分，
保留「最该留」的：

    - 轨迹相关性   ：与当前任务/当前动作的语义相关度（相关越高越留）；
    - 重要性       ：是否被后续步骤引用（diff、被读过的关键文件 = 重要）；
    - 后续任务必要性：是否后续任务还需要的「状态」（快照、已完成变更）；
    - 信息冗余度   ：与其它条目的重复程度（冗余 = 可安全丢弃）。

keep_score = 相关性 + 重要性 + 必要性 - 冗余度。
超预算时优先丢 keep_score 最低的条目，而不是粗暴丢最旧。
仍不够才降级到三级压缩：结果截断 → 历史摘要 → 会话重建。
"""
from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _tokens(text: str) -> set[str]:
    return set(_CJK.findall(text.lower())) | set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def estimate_tokens(text: str) -> int:
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk) // 4


class ContextManager:
    """轨迹感知的上下文：四指标打分 + 三级压缩。"""

    def __init__(self, system_prompt: str, max_tokens: int = 8000,
                 keep_recent: int = 4):
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent
        self.messages: list[dict] = []        # {role, content, meta}
        self.current_task: str = ""
        self.rebuild_count = 0

    def set_task(self, task: str) -> None:
        self.current_task = task

    def add(self, role: str, content: str, meta: dict | None = None) -> None:
        self.messages.append({"role": role, "content": content,
                              "meta": meta or {}})

    def total_tokens(self) -> int:
        return estimate_tokens(self.system_prompt) + \
            sum(estimate_tokens(m["content"]) for m in self.messages)

    # ---- 四指标 ----
    def _keep_score(self, item: dict) -> float:
        relevance = _jaccard(item["content"], self.current_task)      # 轨迹相关性
        importance = item["meta"].get("importance", 0.0)              # 重要性
        necessity = item["meta"].get("necessity", 0.0)                # 后续任务必要性
        # 信息冗余度：与其它条目最大相似度
        redundancy = max((_jaccard(item["content"], o["content"])
                          for o in self.messages if o is not item), default=0.0)
        return relevance + importance + necessity - redundancy

    def fit(self) -> None:
        """按四指标取舍；不够则三级压缩。"""
        # 三级压缩 L1：截断超长结果
        for m in self.messages:
            if len(m["content"]) > 2000:
                m["content"] = m["content"][:1000] + f"\n…（省略 {len(m['content'])-2000}）…\n" \
                    + m["content"][-1000:]
        if self.total_tokens() <= self.max_tokens:
            return

        # 轨迹感知取舍：丢 keep_score 最低的（留最近 keep_recent 条兜底）
        while self.total_tokens() > self.max_tokens and len(self.messages) > self.keep_recent:
            worst = min(range(len(self.messages)),
                        key=lambda i: self._keep_score(self.messages[i]))
            self.messages.pop(worst)

        # L2 历史摘要 / L3 会话重建（兜底）
        if self.total_tokens() > self.max_tokens:
            blob = "\n".join(m["content"][:200] for m in self.messages[:-self.keep_recent])
            self.messages = ([{"role": "user", "content": "（历史摘要）" + blob[:800],
                               "meta": {}}] + self.messages[-self.keep_recent:])
        if self.total_tokens() > self.max_tokens:
            self.rebuild_count += 1
            self.messages = self.messages[-self.keep_recent:]

    def to_list(self) -> list[dict]:
        return self.messages
