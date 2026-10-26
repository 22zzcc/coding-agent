# -*- coding: utf-8 -*-
"""
agent 包 —— 本地 Coding Agent（Claude Code 式）

一个「纯粹」的本地 coding agent，重点实现：
    loop        —— ReAct 主循环（解析/分发/回填/终止）+ 快照断点
    tools       —— read/write/edit/glob/grep/bash/task 七个工具
    permissions —— 三档权限 + 危险命令黑名单 + 路径越界 + 审计（被拒写轨迹不进上下文）
    context     —— 轨迹感知上下文管理（四指标）+ 三级压缩
    snapshot    —— 快照 + 写入锁（失败恢复、断点续跑）
    router      —— 三级路由（规则→向量→LLM）+ 子 agent 隔离（最多 2 个）
    trajectory  —— 轨迹评测（定位工具误选/编辑失效/上下文丢失三类失败）
"""
