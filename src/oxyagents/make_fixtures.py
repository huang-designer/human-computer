"""生成实验用 fixture（Session JSON）——购买决策场景。

一次运行产出三个条件：
  A 由单 Agent 独立完成；B / C 复用同一次多 Agent 结果（B 与 C 数据必须完全一致）。

⚠️ 关于「离线预生成」：这是保证 B 与 C 内容一致的唯一可靠方式（实时跑会有随机性，
实验中途重跑还会让已收集的数据失效）。输出确实由真实多智能体系统产生，只是提前跑并冻结，
报告中应如实写明。

用法:
    python -m src.oxyagents.make_fixtures --dry-run
    python -m src.oxyagents.make_fixtures --task-id T01 --conditions ABC
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from src.oxyagents.roles import EXPERTS, LABELS, MASTER, describe_agents
from src.schema import NO_SOLUTION, is_correct

ROOT = Path(__file__).resolve().parents[2]
TASKSET = ROOT / "taskset" / "experiment_tasks.json"
CATALOG = ROOT / "taskset" / "catalog.json"
FIXTURES = ROOT / "fixtures"


def load_tasks() -> list[dict[str, Any]]:
    return json.loads(TASKSET.read_text(encoding="utf-8"))["tasks"]


def catalog_brief() -> str:
    """给 Agent 看的商品清单（只给商品页可见信息，actual 值留给评分）。"""
    products = json.loads(CATALOG.read_text(encoding="utf-8"))["products"]
    lines = []
    for p in products:
        L = p["listed"]
        lines.append(
            f"- {p['id']} {p['name']}：{L['price']}元，{L['cpu']}，{L['gpu']}，"
            f"{L['ram_gb']}GB 内存，{L['storage_gb']}GB，{L['weight_kg']}kg，"
            f"好评率 {L['pos_rate']:.0%}，{L['after_sales']}；已知问题：{('、'.join(p.get('issues', [])) or '无')}"
        )
    return "\n".join(lines)


def task_prompt(task: dict[str, Any]) -> str:
    return (
        f"用户需求：{task['usage']}\n"
        f"硬约束：{task['constraint_text']}\n\n"
        f"候选机型：\n{catalog_brief()}\n\n"
        "请给出唯一推荐的机型 ID（无满足项时输出 NONE）。"
    )


def _step(i: int, agent_id: str, kind: str, title: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "i": i,
        "agent_id": agent_id,
        "kind": kind,
        "title": title,
        "detail": detail,
        "tool": extra.get("tool"),
        "evidence": extra.get("evidence", []),
        "confidence": extra.get("confidence"),
        "elapsed_ms": extra.get("elapsed_ms", 0),
    }


async def run_single(mas: Any, task: dict[str, Any]) -> dict[str, Any]:
    """A 条件：一个 Agent 直接做完。"""
    t0 = time.monotonic()
    out = await mas.call(
        callee=MASTER,
        arguments={"query": task_prompt(task) + "\n\n只输出机型 ID 和一句话理由。"},
    )
    ms = int((time.monotonic() - t0) * 1000)
    out = str(out).strip()
    return {
        "final_answer": extract_id(out),
        "recommendation": {"id": extract_id(out), "name": "", "price": None, "reason": out[:300]},
        "agents": [
            {
                "id": "single_agent",
                "name": "单 Agent",
                "role": "独立完成检索、比较与推荐",
                "status": "ok",
                "elapsed_ms": ms,
                "summary": out[:280],
            }
        ],
        "steps": [_step(1, "single_agent", "answer", "直接给出建议", out, elapsed_ms=ms)],
        "disagreements": [],
    }


async def run_multi(mas: Any, task: dict[str, Any]) -> dict[str, Any]:
    """B/C 条件：四个专家分工 + 主控汇总。"""
    steps: list[dict[str, Any]] = []
    agents: dict[str, dict[str, Any]] = {a["id"]: {**a, "status": "ok", "elapsed_ms": 0, "summary": ""} for a in describe_agents()}
    claims: dict[str, str] = {}
    i = 0

    for name in EXPERTS:
        i += 1
        t0 = time.monotonic()
        try:
            out = str(await mas.call(callee=name, arguments={"query": task_prompt(task)})).strip()
            status = "ok"
        except Exception as exc:  # noqa: BLE001 —— 单个角色失败不应中断整条链路
            out, status = f"[失败] {type(exc).__name__}: {exc}", "error"
        ms = int((time.monotonic() - t0) * 1000)
        claims[name] = out
        agents[name].update({"status": status, "elapsed_ms": ms, "summary": out[:280]})
        steps.append(
            _step(i, name, "think", f"{LABELS[name]}：{out.splitlines()[0][:70] if out else '（无输出）'}", out, elapsed_ms=ms)
        )

    i += 1
    t0 = time.monotonic()
    final = str(
        await mas.call(
            callee=MASTER,
            arguments={
                "query": task_prompt(task)
                + "\n\n各专家结论：\n"
                + json.dumps(claims, ensure_ascii=False)
                + "\n\n综合以上，给出最终建议的机型 ID 与 2 句话理由；若无人满足全部约束，输出 NONE。"
            }
        )
    ).strip()
    ms = int((time.monotonic() - t0) * 1000)
    agents[MASTER].update({"elapsed_ms": ms, "summary": final[:280]})
    steps.append(_step(i, MASTER, "answer", "主控：汇总并给出建议", final, elapsed_ms=ms))

    pid = extract_id(final)
    return {
        "final_answer": pid,
        "recommendation": {"id": pid, "name": "", "price": None, "reason": final[:300]},
        "agents": list(agents.values()),
        "steps": steps,
        "disagreements": detect_disagreements(task, claims, final),
    }


def extract_id(text: str) -> str:
    """从自由文本里抽机型 ID；抽不到就返回原文（后续会被判为错误，属正常现象）。"""
    products = json.loads(CATALOG.read_text(encoding="utf-8"))["products"]
    if "NONE" in text.upper() or "没有机型" in text or "无合适" in text:
        return NO_SOLUTION
    for p in products:
        if p["id"] in text:
            return p["id"]
    return text[:40]


def detect_disagreements(task: dict[str, Any], claims: dict[str, str], final: str) -> list[dict[str, Any]]:
    """识别专家之间的分歧。

    启发式：不同专家抽出的机型 ID 不一致即为分歧。正式实验前建议人工复核一遍，
    因为这段内容会展示给被试，标注错误会直接污染数据。
    """
    ids = {name: extract_id(text) for name, text in claims.items()}
    distinct = {v for v in ids.values() if v}
    if len(distinct) <= 1:
        return []
    return [
        {
            "topic": "推荐机型不一致",
            "options": [
                {"agent_id": name, "claim": claims[name][:300], "evidence": ""}
                for name in ids
            ],
            "resolution": {
                "chosen_agent": MASTER,
                "reason": f"主控最终采纳 {final[:60]}",
            },
        }
    ]


def build_session(task: dict[str, Any], condition: str, run: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": f"{task['task_id']}::{condition}",
        "trace_id": "",
        "task": {
            "task_id": task["task_id"],
            "level": "decision",
            "title": task.get("title", ""),
            "query": task["query"],
            "constraints": task.get("constraints", {}),
            "constraint_text": task.get("constraint_text", ""),
            "answer": task["answer"],
            "answer_label": task.get("answer_label", ""),
            "steps": task.get("answer_reason", ""),
        },
        "condition": condition,
        "final_answer": run["final_answer"],
        "recommendation": run.get("recommendation", {}),
        "correct": is_correct(run["final_answer"], task["answer"]),
        "agents": run["agents"],
        "steps": run["steps"],
        "disagreements": run.get("disagreements", []),
        "error_markers": [],  # 由人工在挑错阶段补充
    }


async def main_async(args: argparse.Namespace) -> int:
    tasks = load_tasks()
    if args.task_id:
        tasks = [t for t in tasks if t["task_id"].startswith(args.task_id)]
    tasks = tasks[: args.limit]

    if args.dry_run:
        print(f"将处理 {len(tasks)} 个任务，条件 {args.conditions}:")
        for t in tasks:
            print(f"  {t['task_id']} {t['title']} → 金标 {t['answer']}")
        print("\n(dry-run，未调用模型)")
        return 0

    if not os.getenv("DEFAULT_LLM_API_KEY"):
        print("缺少 DEFAULT_LLM_API_KEY。请在 .env 中配置，或先跑 --dry-run。")
        return 1

    from oxygent import MAS

    from src.oxyagents.roles import build_oxy_space

    space = build_oxy_space(enable_web=args.enable_web)
    async with MAS(oxy_space=space) as mas:
        for t in tasks:
            d = FIXTURES / t["task_id"]
            d.mkdir(parents=True, exist_ok=True)
            print(f"[{t['task_id']}] {t['title']}")
            single = await run_single(mas, t)
            multi = await run_multi(mas, t)
            (d / "_run.json").write_text(
                json.dumps({"single": single, "multi": multi}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            for cond in args.conditions:
                run = single if cond == "A" else multi
                (d / f"{cond}.json").write_text(
                    json.dumps(build_session(t, cond, run), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            print(f"   A={single['final_answer']}  多Agent={multi['final_answer']}  金标={t['answer']}")
    print(f"\n完成。fixture 在 {FIXTURES}/<task_id>/*.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--task-id", default="")
    ap.add_argument("--conditions", default="ABC")
    ap.add_argument("--enable-web", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.limit <= 0:
        args.limit = 10**6

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
