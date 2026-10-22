#!/usr/bin/env python3
"""生成演示用 fixture（fixtures/sample.json）。

⚠️ 内容为**人工构造**，用于在无 API key 时跑通界面，不得作为实验数据分析。
真实 fixture 由 `python -m src.oxyagents.make_fixtures` 生成到 fixtures/<task_id>/。

两个演示任务都对应真实任务集 T01 的约束（预算 7000、独显、≤2.2kg、16GB、好评≥0.85）：
  DEMO-OK   系统推荐 磐石 T15 —— 正确
  DEMO-ERR  系统推荐 云舟 A16 —— 错误（采信商品页标称的 16GB，实际仅 8GB）

B 与 C 的底层数据完全一致，只有 condition 字段不同 —— 这是实验唯一要操纵的自变量。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "sample.json"
TASKSET = ROOT / "taskset" / "experiment_tasks.json"

CONSTRAINTS = {
    "budget_max": 7000,
    "require_discrete_gpu": True,
    "max_weight_kg": 2.2,
    "min_ram_gb": 16,
    "min_pos_rate": 0.85,
}
QUERY = (
    "写代码 + 偶尔训练小模型，需要独显；每天背着上课，不能太重。\n\n"
    "预算上限 7000 元。"
)
CONSTRAINT_TEXT = "预算 ≤ 7000 元 · 必须独立显卡 · 内存 ≥ 16GB · 重量 ≤ 2.2kg · 好评率 ≥ 85%"


def agents(ok: bool):
    if ok:
        return [
            {"id": "retrieval_agent", "name": "检索 Agent", "role": "抓取候选机型的价格、参数与评价",
             "status": "ok", "elapsed_ms": 8400, "summary": "筛出 3 款进入候选：云舟 A16、磐石 T15、云舟 A14。"},
            {"id": "performance_agent", "name": "性能 Agent", "role": "判断性能是否满足使用需求",
             "status": "ok", "elapsed_ms": 5200, "summary": "磐石 T15（RTX 3050）满足独显要求，可跑小模型训练。"},
            {"id": "cost_agent", "name": "成本 Agent", "role": "核对预算与性价比",
             "status": "ok", "elapsed_ms": 4100, "summary": "磐石 T15 实际售价 5999 元，在预算内；页面 5299 为过期活动价。"},
            {"id": "risk_agent", "name": "风险 Agent", "role": "收集差评集中点与潜在风险",
             "status": "ok", "elapsed_ms": 3900, "summary": "磐石 T15 售后为第三方、屏幕色域偏低；云舟 A16 内存实为 8GB。"},
            {"id": "master_agent", "name": "主控 Agent", "role": "汇总各方结论并输出建议",
             "status": "ok", "elapsed_ms": 2600, "summary": "推荐 磐石 T15。"},
        ]
    return [
        {"id": "retrieval_agent", "name": "检索 Agent", "role": "抓取候选机型的价格、参数与评价",
         "status": "ok", "elapsed_ms": 8100, "summary": "筛出 3 款进入候选：云舟 A16、磐石 T15、云舟 A14。"},
        {"id": "performance_agent", "name": "性能 Agent", "role": "判断性能是否满足使用需求",
         "status": "ok", "elapsed_ms": 5000, "summary": "云舟 A16：RTX 4050 + 16GB 内存，6999 元，三项都满足。"},
        {"id": "cost_agent", "name": "成本 Agent", "role": "核对预算与性价比",
         "status": "ok", "elapsed_ms": 3600, "summary": "云舟 A16 售价 6999 元，逼近但未超预算。"},
        {"id": "risk_agent", "name": "风险 Agent", "role": "收集差评集中点与潜在风险",
         "status": "ok", "elapsed_ms": 4200, "summary": "云舟 A16 有差评提到内存与参数页不符，建议核实。"},
        {"id": "master_agent", "name": "主控 Agent", "role": "汇总各方结论并输出建议",
         "status": "ok", "elapsed_ms": 2300, "summary": "推荐 云舟 A16。"},
    ]


def steps(ok: bool):
    common = [
        {"i": 1, "agent_id": "retrieval_agent", "kind": "tool", "title": "调用工具 `search_products`",
         "detail": "按预算与独显筛选，返回 3 款候选。", "tool": "search_products",
         "evidence": [{"label": "候选列表", "source": "search_products",
                       "snippet": "YZ-A16 / PS-T15 / YZ-A14"}], "confidence": None, "elapsed_ms": 8400},
        {"i": 2, "agent_id": "performance_agent", "kind": "think",
         "title": "性能 Agent：对比显卡与内存",
         "detail": "磐石 T15 为 RTX 3050 4G；云舟 A16 为 RTX 4050 6G，显卡更强。",
         "tool": None, "evidence": [], "confidence": 0.72, "elapsed_ms": 5000},
        {"i": 3, "agent_id": "cost_agent", "kind": "think", "title": "成本 Agent：核对实际售价",
         "detail": "磐石 T15 商品页显示 5299 元，但客服确认当前活动价为 5999 元。",
         "tool": None,
         "evidence": [{"label": "价格快照", "source": "商品页 / 客服记录",
                       "snippet": "标价 5299（上月活动）→ 现价 5999"}],
         "confidence": 0.8, "elapsed_ms": 3600},
        {"i": 4, "agent_id": "risk_agent", "kind": "think", "title": "风险 Agent：查差评与售后",
         "detail": "云舟 A16 有已购用户反馈内存仅 8GB，与商品页标称 16GB 不一致。",
         "tool": None,
         "evidence": [{"label": "已购评价", "source": "商品评价区",
                       "snippet": "「参数页写 16G，任务管理器显示 8G，客服说以实物为准」"}],
         "confidence": 0.66, "elapsed_ms": 4200},
    ]
    if ok:
        last = [
            {"i": 5, "agent_id": "master_agent", "kind": "answer", "title": "主控：汇总并给出建议",
             "detail": "推荐 磐石 T15（PS-T15）。实际售价 5999 元，在预算内；独显满足需求；"
                       "16GB 内存与 512GB 存储达标。需注意售后为第三方、屏幕色域偏低。",
             "tool": None, "evidence": [], "confidence": None, "elapsed_ms": 2600},
        ]
    else:
        last = [
            {"i": 5, "agent_id": "master_agent", "kind": "answer", "title": "主控：汇总并给出建议",
             "detail": "推荐 云舟 A16（YZ-A16）。6999 元，RTX 4050 独显，16GB 内存，2.15kg。",
             "tool": None, "evidence": [], "confidence": None, "elapsed_ms": 2300},
        ]
    return common + last


def disagreements(ok: bool):
    if ok:
        return [{
            "topic": "性能与预算的取舍",
            "options": [
                {"agent_id": "performance_agent", "claim": "云舟 A16 显卡更强（RTX 4050），更适合跑模型。", "evidence": "显卡参数对比"},
                {"agent_id": "cost_agent", "claim": "磐石 T15 便宜 1000 元且满足独显要求，性价比更高。", "evidence": "实际售价 5999 元"},
            ],
            "resolution": {"chosen_agent": "master_agent", "reason": "预算必须满足，且云舟 A16 内存实际不足 16GB，故采纳成本 Agent 的方向并改为推荐磐石 T15。"},
        }]
    return [{
        "topic": "云舟 A16 的内存到底是多少",
        "options": [
            {"agent_id": "performance_agent", "claim": "商品页标称 16GB，满足约束，推荐云舟 A16。", "evidence": "商品页参数表"},
            {"agent_id": "risk_agent", "claim": "已购评价显示实际 8GB，不满足 16GB 硬约束，应排除。", "evidence": "商品评价区"},
        ],
        "resolution": {"chosen_agent": "master_agent", "reason": "主控采信了商品页标称值，未采纳风险 Agent 的核实建议。"},
    }]


ERROR_MARKERS = [
    {"step_i": 2, "agent_id": "performance_agent", "type": "wrong_fact",
     "detail": "采信商品页标称的 16GB 内存，实际为 8GB，导致推荐违反硬约束"},
    {"step_i": 5, "agent_id": "master_agent", "type": "wrong_fact",
     "detail": "最终建议基于错误的内存参数"},
]


def session(task_id: str, cond: str, *, ok: bool) -> dict:
    final = "PS-T15" if ok else "YZ-A16"
    price = 5999 if ok else 6999
    return {
        "session_id": f"{task_id}::{cond}",
        "trace_id": "",
        "task": {
            "task_id": task_id,
            "level": "decision",
            "query": QUERY,
            "constraints": CONSTRAINTS,
            "constraint_text": CONSTRAINT_TEXT,
            "answer": "PS-T15",
            "answer_label": "磐石 T15",
            "steps": "云舟 A16 因实际内存 8GB 被排除；磐石 T15 满足全部约束",
        },
        "condition": cond,
        "final_answer": final,
        "recommendation": {
            "id": final,
            "name": "磐石 T15" if ok else "云舟 A16",
            "price": price,
            "reason": (
                "实际售价 5999 元，在预算内；RTX 3050 独显满足需求；16GB 内存 / 512GB 存储达标。"
                if ok else
                "6999 元，RTX 4050 独显，16GB 内存，2.15kg。"
            ),
        },
        "correct": ok,
        "agents": agents(ok),
        "steps": steps(ok),
        "disagreements": disagreements(ok),
        "error_markers": [] if ok else ERROR_MARKERS,
    }


def main() -> int:
    taskset = json.loads(TASKSET.read_text(encoding="utf-8"))
    t01 = next(t for t in taskset["tasks"] if t["task_id"] == "T01")

    tasks = {}
    for tid, ok in (("DEMO-OK", True), ("DEMO-ERR", False)):
        tasks[tid] = {
            "level": "decision",
            "query": QUERY,
            "constraints": CONSTRAINT_TEXT,
            "origin_task": "T01",
            "conditions": {c: session(tid, c, ok=ok) for c in ("A", "B", "C")},
        }

    doc = {
        "note": "人工构造的演示数据，仅用于跑通界面，不得作为实验数据。"
                "约束取自真实任务集 T01；真实 fixture 由 src.oxyagents.make_fixtures 生成。",
        "tasks": tasks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写出 {OUT.relative_to(ROOT)}：2 个演示任务 × 3 条件（对应真实任务 {t01['task_id']} 的约束）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
