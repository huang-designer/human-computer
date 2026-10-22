#!/usr/bin/env python3
"""由商品库 + 任务约束求解标准答案，生成实验任务集。

为什么由脚本求解而不是手工写金标：
  手工写金标容易与商品参数不一致；一旦金标错了，整个实验的数据就废了。
  这里用 catalog.json 的 **actual** 值（而非商品页标称值）逐条判定，
  并要求每个任务恰好有 1 个解，否则直接报错退出。

同时输出「陷阱有效性」检查：哪些机型在只用标称值时会错误地通过约束——
这些就是系统容易踩、用户应该发现的错误。

用法:
    python scripts/build_taskset.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "taskset" / "catalog.json"
TASKS = ROOT / "taskset" / "decision_tasks.json"
OUT = ROOT / "taskset" / "experiment_tasks.json"

NONE_LABEL = "无合适机型"


def passes(spec: dict[str, Any], c: dict[str, Any]) -> bool:
    """spec 为 actual（或 listed）视图，c 为约束。"""
    if c.get("budget_max") is not None and spec["price"] > c["budget_max"]:
        return False
    if c.get("min_ram_gb") is not None and spec["ram_gb"] < c["min_ram_gb"]:
        return False
    if c.get("max_weight_kg") is not None and spec["weight_kg"] > c["max_weight_kg"]:
        return False
    if c.get("min_storage_gb") is not None and spec["storage_gb"] < c["min_storage_gb"]:
        return False
    if c.get("require_discrete_gpu") and spec["gpu_class"] != "discrete":
        return False
    if c.get("require_official") and "自营" not in spec["after_sales"]:
        return False
    if c.get("min_pos_rate") is not None and spec["pos_rate"] < c["min_pos_rate"]:
        return False
    return True


def view(product: dict[str, Any], which: str) -> dict[str, Any]:
    """把 listed / actual 合并成一版完整视图（actual 只覆盖被修正的字段）。"""
    merged = dict(product["listed"])
    if which == "actual":
        merged.update(product["actual"])
    return merged


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["products"]
    tasks_def = json.loads(TASKS.read_text(encoding="utf-8"))

    tasks: list[dict[str, Any]] = []
    errors: list[str] = []

    for t in tasks_def["tasks"]:
        c = t["constraints"]
        gold = [p for p in catalog if passes(view(p, "actual"), c)]
        bait = [p for p in catalog if passes(view(p, "listed"), c) and not passes(view(p, "actual"), c)]

        if len(gold) > 1:
            errors.append(f"{t['id']}: 有 {len(gold)} 个解 {[p['id'] for p in gold]}，约束不够紧")
            continue
        if not gold and t["id"] != "T08":
            errors.append(f"{t['id']}: 无解，需要放宽约束")
            continue

        answer = gold[0]["id"] if gold else "NONE"
        label = gold[0]["name"] if gold else NONE_LABEL

        tasks.append(
            {
                "task_id": t["id"],
                "title": t["title"],
                "query": f"{t['usage']}\n\n预算上限 {c.get('budget_max', '不限')} 元。",
                "usage": t["usage"],
                "constraints": c,
                "constraint_text": render_constraints(c),
                "answer": answer,
                "answer_label": label,
                "answer_reason": explain(gold[0], c) if gold else "没有任何机型能同时满足全部约束",
                "trap_bait": [p["id"] for p in bait],
                "note": t.get("note", ""),
            }
        )

    if errors:
        print("任务集不自洽：")
        for e in errors:
            print("  ✗", e)
        return 1

    doc = {
        "version": "1.0",
        "persona": tasks_def["participant_persona"],
        "catalog": "taskset/catalog.json（教学用模拟商品库，非真实在售商品）",
        "total": len(tasks),
        "no_solution_tasks": [t["task_id"] for t in tasks if t["answer"] == "NONE"],
        "tasks": tasks,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已生成 {OUT.relative_to(ROOT)}：{len(tasks)} 个任务\n")
    for t in tasks:
        bait = f"  陷阱诱饵: {t['trap_bait']}" if t["trap_bait"] else ""
        print(f"  {t['task_id']} {t['title']:8s} → {t['answer']:8s} ({t['answer_label']}){bait}")
    print(f"\n无解任务: {doc['no_solution_tasks']}")
    return 0


def render_constraints(c: dict[str, Any]) -> str:
    parts = []
    if c.get("budget_max") is not None:
        parts.append(f"预算 ≤ {c['budget_max']} 元")
    if c.get("require_discrete_gpu"):
        parts.append("必须独立显卡")
    if c.get("min_ram_gb") is not None:
        parts.append(f"内存 ≥ {c['min_ram_gb']}GB")
    if c.get("min_storage_gb") is not None:
        parts.append(f"存储 ≥ {c['min_storage_gb']}GB")
    if c.get("max_weight_kg") is not None:
        parts.append(f"重量 ≤ {c['max_weight_kg']}kg")
    if c.get("require_official"):
        parts.append("必须自营售后")
    if c.get("min_pos_rate") is not None:
        parts.append(f"好评率 ≥ {c['min_pos_rate']:.0%}")
    return " · ".join(parts)


def explain(p: dict[str, Any], c: dict[str, Any]) -> str:
    a = view(p, "actual")
    bits = [f"实际售价 {a['price']} 元"]
    if c.get("require_discrete_gpu"):
        bits.append(f"{a['gpu']}")
    bits.append(f"{a['ram_gb']}GB 内存 / {a['storage_gb']}GB")
    bits.append(f"{a['weight_kg']}kg")
    bits.append(f"好评率 {a['pos_rate']:.0%}")
    bits.append(a["after_sales"])
    return "；".join(bits)


if __name__ == "__main__":
    raise SystemExit(main())
