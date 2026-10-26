# -*- coding: utf-8 -*-
"""
agent/llm.py —— 本地模型接口（Ollama + 确定性 Mock）
====================================================
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen3:4b"


class OllamaLLM:
    def __init__(self, model: str = MODEL, url: str = OLLAMA_URL):
        self.model, self.url = model, url

    def complete(self, messages: list[dict], temperature: float = 0.1) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "format": "json", "options": {"temperature": temperature}}
        req = urllib.request.Request(self.url + "/api/chat",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = json.loads(r.read().decode())
        except urllib.error.URLError as e:
            raise RuntimeError(f"无法连接 Ollama：{e}") from e
        return (body.get("message") or {}).get("content", "").strip()


class MockLLM:
    """确定性 Mock：按任务关键词走一条「读→改→完成」的脚本，离线可跑通全链路。"""

    def __init__(self):
        self.script: list[dict] | None = None
        self.i = 0

    def _plan(self, task: str) -> list[dict]:
        t = task.replace("任务：", "")
        if "sub" in t.lower() or "子" in t:
            return [{"thought": "派生子 agent 处理子任务", "tool": "task",
                     "args": {"prompt": "修复 add 函数"}},
                    {"final": "子 agent 已完成，主任务收尾"}]
        if "新增" in t or "subtract" in t or "multiply" in t:
            return [{"thought": "先读文件末尾", "tool": "read",
                     "args": {"path": "src/math_utils.py"}},
                    {"thought": "追加函数", "tool": "edit",
                     "args": {"path": "src/math_utils.py", "old_string": "    return a * b",
                              "new_string": "    return a * b\n\n\ndef subtract(a, b):\n    \"\"\"两数相减。\"\"\"\n    return a - b"}},
                    {"final": "已新增 subtract 函数"}]
        return [{"thought": "先读目标文件", "tool": "read", "args": {"path": "src/math_utils.py"}},
                {"thought": "修复 add", "tool": "edit",
                 "args": {"path": "src/math_utils.py", "old_string": "return a - b",
                          "new_string": "return a + b"}},
                {"final": "已修复 add 函数"}]

    def complete(self, messages: list[dict], temperature: float = 0.1) -> str:
        if self.script is None:
            task = next((m["content"] for m in messages if m.get("role") == "user"), "")
            self.script = self._plan(task)
            self.i = 0
        if self.i < len(self.script):
            step = self.script[self.i]
            self.i += 1
            return json.dumps(step, ensure_ascii=False)
        return json.dumps({"final": "（结束）"})
