# Coding Agent · 本地 Claude Code 式终端编程 Agent

> 一个「纯粹」的本地 coding agent，重点实现主循环、tools 层、上下文管理、轨迹评测
> 与权限审计，区别于求职向的其它项目。

## 架构

```
用户任务
  │
  ▼
┌─ loop.py  ReAct 主循环（解析→分发→回填→终止）+ 快照断点 ─────────────┐
│   每步存快照，失败可回滚、断点续跑                                    │
└───────────────┬────────────────────────────────────────────────────┘
                │ 工具调用（统一签名，唯一文件通道）
┌───────────────▼────────────────────────────────────────────────────┐
│ tools.py  read / write / edit / glob / grep / bash / task（7 个）     │
│   permissions.py  三档权限 + 危险命令黑名单 + 路径越界                 │
│   snapshot.py     写入锁 + 文件快照（失败恢复）                       │
│   router.py       三级路由（规则→向量→LLM）+ 子 agent 隔离（最多 2 个）│
└───────────────┬────────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────────┐
│ context.py     轨迹感知上下文：四指标 + 三级压缩                      │
│ trajectory.py  轨迹评测：三类失败定位 + 权限审计                      │
└────────────────────────────────────────────────────────────────────┘
```

## 快速开始

核心零硬依赖（LLM 走标准库 urllib）。

```bash
cd coding-agent

python main.py run "修复 add 函数" --mock            # 离线跑通 ReAct 全链路
python main.py run "新增 subtract 函数" --mock
python main.py run "修复 add" --mock --level read    # 权限审计：edit 被拒写进轨迹
python main.py run "子 agent 处理" --mock            # 子 agent 隔离上下文
python main.py eval --mock                           # 三类失败定位
```

## 设计要点（对照需求）

| 需求 | 落地 |
| :--- | :--- |
| 主循环与 tools 层 | `loop.py`（ReAct 四步）+ `tools.py`（7 工具统一签名） |
| 上下文管理与轨迹评测 | `context.py` + `trajectory.py` |
| 权限：被拒写轨迹不进上下文 | `loop.py`：被拒操作只进 `traj.rejections`、不进上下文；`traj.audit()` 审计 agent 试图做什么 |
| 最多两个子 agent | `router.py:max_subagents=2`，隔离上下文，只回传结论 |
| 轨迹感知上下文处理 | `context.py`：相关性/重要性/后续任务必要性/信息冗余度 四指标打分取舍 |
| 按 token 三级压缩 | 结果截断 → 历史摘要 → 会话重建 |
| 快照与写入锁 | `snapshot.py`：写入前快照 + 加锁，失败回滚、断点续跑 |
| 三档权限 + 黑名单 + 越界 | `permissions.py` |
| 三级路由 | `router.py`：规则→向量→LLM |
| 三类失败定位 | `trajectory.py:classify_failure`：工具误选/编辑失效/上下文丢失 |

## 参考

- opencode：https://github.com/sst/opencode
- Aider：https://github.com/Aider-AI/aider
