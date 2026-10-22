"""实验用归一化会话结构（Session）。

所有前端只消费这一种结构，与底层是 OxyGent 真实运行还是离线预生成无关。
OxyGent 的原始 trace 由 src/adapters/trace_to_session.py 转换而来。

Session
├── session_id: str
├── task: {task_id, level, query, answer, steps}
├── condition: "A" | "B" | "C"
├── final_answer: str            # 系统最终输出的答案
├── correct: bool | None         # 与 task.answer 比对结果（仅研究者可见）
├── agents: [Agent]              # 参与本次协作的 Agent 名册
├── steps: [Step]                # 执行时间线（C 条件展示）
├── disagreements: [Disagreement]# 意见分歧（C 条件展示）
└── error_markers: [ErrorMarker] # 已知错误位置（仅研究者可见，用于评分）

Agent
├── id: str                      # 与 Step.agent_id 对应
├── name: str                    # 展示名，如「检索 Agent」
├── role: str                    # 职责说明
├── status: "ok" | "error" | "skipped"
├── elapsed_ms: int
└── summary: str                 # 该 Agent 的结论摘要

Step
├── i: int                       # 时间线序号，从 1 开始
├── agent_id: str
├── kind: "plan" | "think" | "tool" | "answer"
├── title: str                   # 一行摘要
├── detail: str                  # 展开后的完整说明
├── tool: str | None             # 工具名（kind == "tool" 时）
├── evidence: [Evidence]         # 可展开的证据来源
└── confidence: float | None     # 0–1，Agent 自评置信度

Evidence
├── label: str                   # 如「京东商详页」
├── source: str                  # URL 或文件名
└── snippet: str                 # 摘录

Disagreement
├── topic: str                   # 争议点
├── options: [{agent_id, claim, evidence: str}]
└── resolution: {chosen_agent, reason}

ErrorMarker
├── step_i: int                  # 错误发生在第几步（0 表示最终答案本身错误）
├── agent_id: str
├── type: "wrong_fact" | "wrong_calc" | "wrong_source" | "format" | "tool_failure"
└── detail: str
"""

from __future__ import annotations

import re
from typing import Any

CONDITIONS = ("A", "B", "C")

#: 条件语义 —— 前端据此决定展示哪些区块
CONDITION_SPEC: dict[str, dict[str, Any]] = {
    "A": {
        "label": "单 Agent",
        "short": "单个",
        "description": "一个 Agent 直接完成检索、比较和推荐，用户只看到最终建议。",
        "show": ["answer"],
        "human_in_loop": False,
    },
    "B": {
        "label": "多个 Agent",
        "short": "多个",
        "description": "多个 Agent 在后台分工协作，用户只看到最终建议，不参与过程。",
        "show": ["answer"],
        "human_in_loop": False,
    },
    "C": {
        "label": "多个 Agent + 人",
        "short": "多个 + 人",
        "description": "多个 Agent 协作，并在关键节点把决定权交给人：确认行动、裁决分歧、追加约束；人也可以随时推翻建议。",
        "show": ["answer", "agents", "interactions", "disagreements", "steps"],
        "human_in_loop": True,
    },
}

#: 人机协作点的类型（仅 C 条件出现）
INTERACTION_TYPES = ("confirm", "arbitrate", "augment")

#: 无解任务的答案标记
NO_SOLUTION = "NONE"
_NONE_PATTERN = re.compile(r"(none|无合适|无符合|没有合适|都不满足|都不符合)", re.IGNORECASE)

_ANSWER_NORMALIZE = re.compile(r"[\s\"'`，。；：、]+")


def normalize_answer(a: object) -> str:
    """赛题采用「准精确匹配」，此处做保守规范化：去空白/引号/常见中文标点。"""
    return _ANSWER_NORMALIZE.sub("", str(a or "")).lower()


def is_correct(final: object, gold: object) -> bool:
    """判定用户/系统的选择是否正确。

    gold 为商品 id（如 "PS-T15"）时精确比对；gold 为 NO_SOLUTION 时，
    只要用户表达了「没有合适机型」即算正确。
    """
    if str(gold).strip().upper() == NO_SOLUTION:
        return bool(_NONE_PATTERN.search(str(final or "")))
    return normalize_answer(final) == normalize_answer(gold)


def validate(session: dict[str, Any]) -> list[str]:
    """返回问题列表，空列表表示通过。"""
    errs: list[str] = []
    for key in ("session_id", "task", "condition", "final_answer", "agents", "steps"):
        if key not in session:
            errs.append(f"缺少字段 {key}")
    if session.get("condition") not in CONDITIONS:
        errs.append(f"condition 必须是 {CONDITIONS} 之一")
    for k in ("task_id", "query", "answer"):
        if k not in session.get("task", {}):
            errs.append(f"task 缺少字段 {k}")
    agent_ids = {a.get("id") for a in session.get("agents", [])}
    for s in session.get("steps", []):
        if s.get("agent_id") not in agent_ids:
            errs.append(f"step {s.get('i')} 引用了未知 agent_id {s.get('agent_id')!r}")
    for d in session.get("disagreements", []):
        for o in d.get("options", []):
            if o.get("agent_id") not in agent_ids:
                errs.append(f"分歧选项引用了未知 agent_id {o.get('agent_id')!r}")
    for it in session.get("interactions", []):
        if it.get("type") not in INTERACTION_TYPES:
            errs.append(f"interaction {it.get('id')} 的 type 必须是 {INTERACTION_TYPES}")
        if not it.get("options"):
            errs.append(f"interaction {it.get('id')} 没有选项")
        for o in it.get("options", []):
            aid = o.get("agent_id")
            if aid and aid not in agent_ids:
                errs.append(f"interaction {it.get('id')} 引用了未知 agent_id {aid!r}")
    if session.get("condition") != "C" and session.get("interactions"):
        errs.append("只有 C 条件（多个 Agent + 人）可以有 interaction")
    return errs
