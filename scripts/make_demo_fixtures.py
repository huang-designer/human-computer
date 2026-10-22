#!/usr/bin/env python3
"""生成演示用 fixture（fixtures/sample.json）。

⚠️ 这里的内容是**人工构造**的，用于让前端先在无 API key 的情况下可跑通。
它不是真实 Agent 的运行结果，报告中不得作为实验数据分析。
真实 fixture 由 `python -m src.oxyagents.make_fixtures` 生成到 fixtures/<task_id>/。

设计要点：B 与 C 的底层数据**完全相同**，只有 condition 字段不同——
这正是实验要操纵的唯一自变量，演示数据也必须守住这一点。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "sample.json"

GOLD_QUERY = (
    "你雇人工作7天，手上仅有一根金条并且需每日支付1/7根金条作为报酬。"
    "问最少将金条切成多少段，使得每天能支付当日工资？仅输出数字"
)
GOLD_ANSWER = "3"


def agents():
    return [
        {"id": "search_agent", "name": "检索 Agent", "role": "定位问题类型与可用资料",
         "status": "ok", "elapsed_ms": 2100, "summary": "这是自包含的逻辑题，无需外部检索。"},
        {"id": "code_agent", "name": "计算 Agent", "role": "枚举切割方案并验证支付序列",
         "status": "ok", "elapsed_ms": 4300, "summary": "切成 1/7、2/7、4/7 三段即可用找零覆盖 1–7 天。"},
        {"id": "verify_agent", "name": "校验 Agent", "role": "检查约束与格式",
         "status": "ok", "elapsed_ms": 2600, "summary": "答案满足『仅输出数字』的格式要求。"},
        {"id": "master_agent", "name": "主控 Agent", "role": "汇总并输出最终答案",
         "status": "ok", "elapsed_ms": 1800, "summary": "输出 3。"},
    ]


def steps(final_note: str):
    return [
        {"i": 1, "agent_id": "search_agent", "kind": "plan", "title": "判断题型：自包含逻辑题",
         "detail": "题目不含外部实体，不需要联网，属于可穷举验证的组合问题。",
         "tool": None, "evidence": [], "confidence": 0.9, "elapsed_ms": 2100},
        {"i": 2, "agent_id": "code_agent", "kind": "tool", "title": "调用工具 `run_python_code`",
         "detail": "枚举 7 天的所有支付/找零序列，求最小段数。",
         "tool": "run_python_code",
         "evidence": [{"label": "工具返回", "source": "run_python_code",
                       "snippet": "cuts=3 -> [0.142857, 0.285714, 0.571429]\npayable 1..7 = True"}],
         "confidence": None, "elapsed_ms": 4300},
        {"i": 3, "agent_id": "code_agent", "kind": "think", "title": "计算 Agent：三段分别为 1/7、2/7、4/7",
         "detail": "第 2 天收到 2/7 找零 1/7，第 4 天收到 4/7 找零 3/7，其余天数同理可覆盖。",
         "tool": None, "evidence": [], "confidence": 0.95, "elapsed_ms": None},
        {"i": 4, "agent_id": "verify_agent", "kind": "think", "title": f"校验 Agent：{final_note}",
         "detail": "检查了格式约束与每日可行支付序列，未发现跳步。",
         "tool": None, "evidence": [], "confidence": 0.8, "elapsed_ms": 2600},
        {"i": 5, "agent_id": "master_agent", "kind": "answer", "title": "主控：汇总并输出答案",
         "detail": "3", "tool": None, "evidence": [], "confidence": None, "elapsed_ms": 1800},
    ]


def session(task_id: str, cond: str, *, final: str, disagreements: list, error_markers: list, note: str) -> dict:
    return {
        "session_id": f"{task_id}::{cond}",
        "trace_id": "",
        "task": {"task_id": task_id, "level": "1", "query": GOLD_QUERY, "answer": GOLD_ANSWER,
                 "steps": "切成 1/7、2/7、4/7 三段"},
        "condition": cond,
        "final_answer": final,
        "correct": final == GOLD_ANSWER,
        "agents": agents(),
        "steps": steps(note),
        "disagreements": disagreements,
        "error_markers": error_markers,
    }


def main() -> int:
    # 正常案例：系统答对，存在一次轻微分歧但已解决
    ok_dis = [{
        "topic": "最少段数",
        "options": [
            {"agent_id": "search_agent", "claim": "直觉上 7 天需要 7 段。", "evidence": ""},
            {"agent_id": "code_agent", "claim": "三段足够，因为可以用找零。", "evidence": "run_python_code 枚举结果"},
        ],
        "resolution": {"chosen_agent": "master_agent", "reason": "计算 Agent 的结论经穷举验证，检索 Agent 未做计算。"},
    }]

    # 错误案例：系统漏掉「找零」规则，忽略 48h 类约束，给出 7
    err_dis = [{
        "topic": "最少段数",
        "options": [
            {"agent_id": "code_agent", "claim": "7 段，每天一段最稳妥。", "evidence": "未使用找零，直接按天数切分"},
            {"agent_id": "verify_agent", "claim": "应为 3 段：1/7、2/7、4/7，可用找零覆盖 1–7 天。",
             "evidence": "支付序列可构造，符合题目的『最少』要求"},
        ],
        "resolution": {"chosen_agent": "master_agent", "reason": "主控优先采纳了计算 Agent，未处理校验者的反对意见。"},
    }]
    err_markers = [{"step_i": 2, "agent_id": "code_agent", "type": "wrong_calc",
                    "detail": "未考虑找零机制，得到 7；正确答案为 3"}]

    tasks = {
        "demo-ok": {
            "level": "1", "query": GOLD_QUERY,
            "conditions": {
                "A": session("demo-ok", "A", final="3", disagreements=[], error_markers=[], note="答案满足格式要求"),
                "B": session("demo-ok", "B", final="3", disagreements=ok_dis, error_markers=[], note="答案满足格式要求"),
                "C": session("demo-ok", "C", final="3", disagreements=ok_dis, error_markers=[], note="答案满足格式要求"),
            },
        },
        "demo-err": {
            "level": "1", "query": GOLD_QUERY,
            "conditions": {
                "A": session("demo-err", "A", final="7", disagreements=[], error_markers=err_markers, note="答案满足格式要求"),
                "B": session("demo-err", "B", final="7", disagreements=err_dis, error_markers=err_markers, note="格式合规"),
                "C": session("demo-err", "C", final="7", disagreements=err_dis, error_markers=err_markers, note="格式合规"),
            },
        },
    }

    doc = {
        "note": "人工构造的演示数据，仅用于跑通界面，不得作为实验数据。真实数据由 src.oxyagents.make_fixtures 生成。",
        "tasks": tasks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写出 {OUT.relative_to(ROOT)}（{len(tasks)} 个演示任务 × 3 条件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
