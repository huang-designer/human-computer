"""把 OxyGent 的原始 trace 转换成实验用 Session 结构。

OxyGent 会在 ES（或本地 JSON）里持久化两张表：

  app_trace: {trace_id: {request_id, trace_id, input, callee, output, create_time, ...}}
  app_node:  {node_id:  {node_id, node_type(agent|llm|tool), caller, callee,
                          father_node_id, call_stack, input, output,
                          create_time, update_time, state, extra}}

node 之间的父子关系由 father_node_id 给出，caller/callee 构成调用边，
create_time / update_time 给出耗时。本模块把调用树压平成时间线。

示例（离线转换某个 trace）:
    python -m src.adapters.trace_to_session \
        --cache /tmp/og/cache_dir/local_es_data \
        --trace-id hqKLrQDktZMBfxyg \
        --taskset taskset/experiment_tasks.json \
        --task-id 4cc2e0f7-f998-4617-b77d-ab6b762e8724 \
        --condition C \
        --out fixtures/4cc2e0f7-f998-4617-b77d-ab6b762e8724/C.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.schema import is_correct

#: Agent 展示名。新增角色时在这里登记，前端按此渲染。
AGENT_LABELS: dict[str, tuple[str, str]] = {
    "master_agent": ("主控 Agent", "拆分任务、汇总各 Agent 结论、输出最终答案"),
    "search_agent": ("检索 Agent", "定位信息源，抓取候选页面与文档"),
    "reader_agent": ("阅读 Agent", "从附件（PDF/视频/图片/表格）中抽取事实"),
    "file_agent": ("文件 Agent", "读取并解析附件"),
    "code_agent": ("计算 Agent", "执行代码完成计算与数据核对"),
    "verify_agent": ("校验 Agent", "检查答案是否满足题目格式与约束，指出可疑步骤"),
    "planner_agent": ("规划 Agent", "把任务拆成可执行步骤"),
}


#: OxyState: 1=CREATED 2=RUNNING 3=COMPLETED 4=FAILED 5=PAUSED 6=SKIPPED 7=CANCELED
_STATE_MAP = {"3": "ok", "4": "error", "5": "error", "6": "skipped", "7": "skipped"}


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    # OxyGent 写的是纳秒精度（如 .783518000），strptime 只接受 6 位
    txt = str(s)
    if "." in txt:
        head, frac = txt.split(".", 1)
        txt = f"{head}.{frac[:6]}"
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def _ms_between(a: str | None, b: str | None) -> int:
    d1, d2 = _dt(a), _dt(b)
    if not d1 or not d2:
        return 0
    return max(0, int((d2 - d1).total_seconds() * 1000))


def _json_or_raw(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


def _label(callee: str) -> tuple[str, str]:
    if callee in AGENT_LABELS:
        return AGENT_LABELS[callee]
    pretty = callee.replace("_", " ").strip().title()
    return (f"{pretty} Agent", f"由 `{callee}` 执行")


def load_cache(cache_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    traces = json.loads((cache_dir / "app_trace.json").read_text(encoding="utf-8"))
    nodes = json.loads((cache_dir / "app_node.json").read_text(encoding="utf-8"))
    return traces, nodes


def nodes_of_trace(nodes: dict[str, Any], trace_id: str) -> list[dict[str, Any]]:
    return sorted(
        (n for n in nodes.values() if n.get("trace_id") == trace_id),
        key=lambda n: (_dt(n.get("create_time")) or datetime.min, n.get("node_id", "")),
    )


def build_session(
    trace: dict[str, Any],
    node_list: list[dict[str, Any]],
    task: dict[str, Any],
    condition: str,
) -> dict[str, Any]:
    trace_id = trace.get("trace_id", "")

    # ---- Agent 名册：出现在 callee 上的 agent 类节点 ----
    agents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in node_list:
        if n.get("node_type") != "agent":
            continue
        aid = n.get("callee", "")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        name, role = _label(aid)
        agents.append(
            {
                "id": aid,
                "name": name,
                "role": role,
                "status": _STATE_MAP.get(str(n.get("state")), "ok"),
                "elapsed_ms": _ms_between(n.get("create_time"), n.get("update_time")),
                "summary": str(n.get("output") or "")[:280],
            }
        )

    # ---- 时间线：保留 agent 与 tool 节点，丢弃 llm 节点的噪声 ----
    steps: list[dict[str, Any]] = []
    i = 0
    for n in node_list:
        ntype = n.get("node_type")
        if ntype not in ("agent", "tool"):
            continue
        i += 1
        caller, callee = n.get("caller", ""), n.get("callee", "")
        if ntype == "tool":
            steps.append(
                {
                    "i": i,
                    "agent_id": caller,
                    "kind": "tool",
                    "title": f"调用工具 `{callee}`",
                    "detail": _short(n.get("input")),
                    "tool": callee,
                    "evidence": [{"label": "工具返回", "source": callee, "snippet": _short(n.get("output"), 600)}],
                    "confidence": None,
                    "elapsed_ms": _ms_between(n.get("create_time"), n.get("update_time")),
                }
            )
        else:
            is_master = caller == "user"
            out = _short(n.get("output"), 1200)
            first = out.split("\n", 1)[0][:80]
            steps.append(
                {
                    "i": i,
                    "agent_id": callee,
                    "kind": "answer" if is_master else "think",
                    "title": ("主控：汇总并输出答案" if is_master else f"{_label(callee)[0]}：{first}"),
                    "detail": out,
                    "tool": None,
                    "evidence": [],
                    "confidence": None,
                    "elapsed_ms": _ms_between(n.get("create_time"), n.get("update_time")),
                }
            )

    final = trace.get("output") or (steps[-1]["detail"] if steps else "")
    return {
        "session_id": f"{task['task_id']}::{condition}::{trace_id}",
        "trace_id": trace_id,
        "task": task,
        "condition": condition,
        "final_answer": str(final).strip(),
        "correct": is_correct(final, task.get("answer")),
        "agents": agents,
        "steps": steps,
        # OxyGent 不记录"分歧"这一语义，需在生成阶段由 orchestrator 显式写入，
        # 或用 --disagreements 传入人工标注文件。
        "disagreements": [],
        "error_markers": [],
    }


def _short(v: Any, limit: int = 240) -> str:
    s = _json_or_raw(v)
    s = json.dumps(s, ensure_ascii=False) if isinstance(s, (dict, list)) else str(s or "")
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True, help="含 app_trace.json / app_node.json 的目录")
    ap.add_argument("--trace-id", required=True)
    ap.add_argument("--taskset", type=Path, default=Path("taskset/experiment_tasks.json"))
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--condition", choices=["A", "B", "C"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    traces, nodes = load_cache(args.cache)
    if args.trace_id not in traces:
        print(f"找不到 trace {args.trace_id}，可选: {list(traces)[:10]}")
        return 1
    pool = {t["task_id"]: t for t in json.loads(args.taskset.read_text(encoding="utf-8"))["tasks"]}
    if args.task_id not in pool:
        print(f"taskset 中找不到 {args.task_id}")
        return 1

    session = build_session(traces[args.trace_id], nodes_of_trace(nodes, args.trace_id), pool[args.task_id], args.condition)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写出 {args.out}：{len(session['agents'])} 个 Agent / {len(session['steps'])} 步 / correct={session['correct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
