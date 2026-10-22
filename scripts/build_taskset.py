#!/usr/bin/env python3
"""把 taskset/selection.json 的人工标注与验证集原始数据合并，生成实验任务集。

输出 taskset/experiment_tasks.json（含 query / answer / steps，可直接用于实验与评分）。

用法:
    python scripts/build_taskset.py
    python scripts/build_taskset.py --input /tmp/valid.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "valid.jsonl"
SELECTION = ROOT / "taskset" / "selection.json"
OUT = ROOT / "taskset" / "experiment_tasks.json"


def answer_type(a: object) -> str:
    s = str(a).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return "number"
    if s.startswith("http"):
        return "url"
    if len(s) <= 8:
        return "short"
    return "text"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DATA)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"找不到 {args.input}，请先运行: python scripts/fetch_dataset.py")
        return 1

    raw = {}
    for line in args.input.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            raw[r["task_id"]] = r

    sel = json.loads(SELECTION.read_text(encoding="utf-8"))
    tasks, missing = [], []
    for item in sel["tasks"]:
        tid = item["task_id"]
        if tid not in raw:
            missing.append(tid)
            continue
        r = raw[tid]
        tasks.append(
            {
                "task_id": tid,
                "level": str(r.get("level")),
                "category": item["category"],
                "media": item["media"],
                "stability": item["stability"],
                "expected_error": item["expected_error"],
                "query": r.get("query", "").strip(),
                "answer": str(r.get("answer", "")).strip(),
                "answer_type": answer_type(r.get("answer")),
                "steps": str(r.get("steps", "")).strip(),
                "file_name": r.get("file_name") or "",
                "requires_file": bool(r.get("file_name")),
            }
        )

    if missing:
        print(f"! 有 {len(missing)} 个 task_id 未在数据中找到：{missing}")

    doc = {
        "version": sel.get("version", "0.2"),
        "source": "CCF BDCI 2025 京东多智能体挑战赛 验证集（经 MetaJD@MIT 获取）",
        "total": len(tasks),
        "by_level": {lv: sum(1 for t in tasks if t["level"] == lv) for lv in sorted({t["level"] for t in tasks})},
        "by_category": {
            c: sum(1 for t in tasks if t["category"] == c) for c in sorted({t["category"] for t in tasks})
        },
        "tasks": tasks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已生成 {OUT.relative_to(ROOT)}：{len(tasks)} 条")
    print(f"  按难度: {doc['by_level']}")
    print(f"  按类别: {doc['by_category']}")
    for t in tasks:
        print(f"  [L{t['level']}|{t['category']:14s}] {t['query'][:56]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
