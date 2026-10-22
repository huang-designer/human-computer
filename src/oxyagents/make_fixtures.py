"""生成实验用的 fixture（Session JSON）。

为什么要离线预生成，而不是实验时实时跑：
1. **内容一致性** —— B 与 C 条件必须喂给用户完全相同的答案与轨迹，否则差异无法归因于界面；
2. **可复现** —— 实验中途某个任务出错时，实时重跑会得到不同结果，数据即失效；
3. **解耦** —— 前端和 Agent 工程可以并行推进，前端口可以先吃 demo fixture 开工。

⚠️ 这不等同于 Wizard-of-Oz：输出确实由真实多智能体系统产生，只是提前跑并冻结。
报告里应如实写明。

用法:
    python -m src.oxyagents.make_fixtures --limit 3            # 先跑 3 个任务验证
    python -m src.oxyagents.make_fixtures --task-id 4cc2e0f7-... --conditions ABC
    python -m src.oxyagents.make_fixtures --dry-run            # 只打印将要执行的任务

依赖：pip install oxygent python-dotenv，并配置 .env 中的 DEFAULT_LLM_*
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from src.schema import is_correct

ROOT = Path(__file__).resolve().parents[2]
TASKSET = ROOT / "taskset" / "experiment_tasks.json"
FIXTURES = ROOT / "fixtures"


def _load_tasks() -> list[dict[str, Any]]:
    return json.loads(TASKSET.read_text(encoding="utf-8"))["tasks"]


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
    from src.oxyagents.roles import MASTER

    t0 = time.monotonic()
    prompt = f"{task['query']}\n\n只输出最终答案，不要解释。"
    answer = await mas.call(callee=MASTER, arguments={"query": prompt})
    ms = int((time.monotonic() - t0) * 1000)
    return {
        "final_answer": str(answer).strip(),
        "agents": [
            {
                "id": "single_agent",
                "name": "单 Agent",
                "role": "独立完成检索、推理与作答",
                "status": "ok",
                "elapsed_ms": ms,
                "summary": str(answer).strip()[:280],
            }
        ],
        "steps": [_step(1, "single_agent", "answer", "直接作答", str(answer), elapsed_ms=ms)],
        "disagreements": [],
    }


async def run_multi(mas: Any, task: dict[str, Any]) -> dict[str, Any]:
    """B/C 条件：多 Agent 分工 + 校验质疑 + 主控汇总。

    步骤与 OxyGent 自己的 trace 同构，但由本流程显式记录——
    这样「分歧」这一语义能落到具体字段上（OxyGent 的 trace 里没有这个概念）。
    """
    from src.oxyagents.roles import EXPERTS, MASTER

    steps: list[dict[str, Any]] = []
    agents: dict[str, dict[str, Any]] = {}
    claims: dict[str, str] = {}
    i = 0

    for name in EXPERTS:
        i += 1
        t0 = time.monotonic()
        try:
            out = await mas.call(callee=name, arguments={"query": task["query"]})
            out = str(out).strip()
            status = "ok"
        except Exception as exc:  # noqa: BLE001 —— 单角色失败不应中断整条链路
            out, status = f"[失败] {type(exc).__name__}: {exc}", "error"
        ms = int((time.monotonic() - t0) * 1000)
        claims[name] = out
        agents[name] = {
            "id": name,
            "name": name.replace("_agent", " Agent"),
            "role": "",
            "status": status,
            "elapsed_ms": ms,
            "summary": out[:280],
        }
        steps.append(
            _step(
                i,
                name,
                "think",
                f"{name.replace('_agent', ' Agent')}：{out.splitlines()[0][:70] if out else '（无输出）'}",
                out,
                evidence=[],
                elapsed_ms=ms,
            )
        )

    # 校验者看到前面所有结论，可能提出反对意见
    i += 1
    t0 = time.monotonic()
    draft = json.dumps(claims, ensure_ascii=False)
    verify = await mas.call(
        callee="verify_agent",
        arguments={
            "query": (
                f"原始问题：{task['query']}\n\n各专家结论：{draft}\n\n"
                "请指出：1) 是否存在错误或互相矛盾；2) 最不确定的一步；3) 你认为的答案。"
            )
        },
    )
    verify = str(verify).strip()
    ms = int((time.monotonic() - t0) * 1000)
    agents["verify_agent"]["elapsed_ms"] = ms
    steps.append(_step(i, "verify_agent", "think", f"校验 Agent：{verify.splitlines()[0][:70] if verify else '（无输出）'}", verify, elapsed_ms=ms))

    # 主控汇总
    i += 1
    t0 = time.monotonic()
    final = await mas.call(
        callee=MASTER,
        arguments={
            "query": (
                f"{task['query']}\n\n专家结论：{draft}\n\n校验意见：{verify}\n\n"
                "综合以上，严格按题目格式要求只输出最终答案。"
            )
        },
    )
    final = str(final).strip()
    ms = int((time.monotonic() - t0) * 1000)
    agents[MASTER] = {
        "id": MASTER,
        "name": "主控 Agent",
        "role": "汇总各方结论、处理分歧、输出最终答案",
        "status": "ok",
        "elapsed_ms": ms,
        "summary": final[:280],
    }
    steps.append(_step(i, MASTER, "answer", "主控：汇总并输出答案", final, elapsed_ms=ms))

    disagreements = detect_disagreements(task, claims, verify, final)
    return {"final_answer": final, "agents": list(agents.values()), "steps": steps, "disagreements": disagreements}


def detect_disagreements(
    task: dict[str, Any], claims: dict[str, str], verify: str, final: str
) -> list[dict[str, Any]]:
    """粗略识别分歧：专家结论彼此不同、或校验者与主控结论不同。

    注意：这是启发式。正式的「分歧」标注建议人工复核一遍再进 fixture，
    因为实验里要展示给被试，标注错误会直接污染数据。
    """
    from src.schema import normalize_answer

    out: list[dict[str, Any]] = []
    distinct: dict[str, list[str]] = {}
    for name, claim in claims.items():
        distinct.setdefault(normalize_answer(claim)[:80], []).append(name)
    if len(distinct) > 1:
        out.append(
            {
                "topic": "专家结论不一致",
                "options": [
                    {"agent_id": n, "claim": c[:300], "evidence": ""} for n, c in claims.items() if n != "verify_agent"
                ],
                "resolution": {"chosen_agent": "master_agent", "reason": "主控按题目约束择一输出"},
            }
        )
    if verify and normalize_answer(verify) != normalize_answer(final) and "无法确定" not in verify:
        out.append(
            {
                "topic": "校验者与主控结论不一致",
                "options": [
                    {"agent_id": "verify_agent", "claim": verify[:300], "evidence": ""},
                    {"agent_id": "master_agent", "claim": final[:300], "evidence": ""},
                ],
                "resolution": {"chosen_agent": "master_agent", "reason": "主控保留最终裁决权"},
            }
        )
    return out


def build_session(task: dict[str, Any], condition: str, run: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": f"{task['task_id']}::{condition}",
        "trace_id": "",
        "task": {
            "task_id": task["task_id"],
            "level": task["level"],
            "query": task["query"],
            "answer": task["answer"],
            "steps": task.get("steps", ""),
        },
        "condition": condition,
        "final_answer": run["final_answer"],
        "correct": is_correct(run["final_answer"], task["answer"]),
        "agents": run["agents"],
        "steps": run["steps"],
        "disagreements": run["disagreements"],
        "error_markers": [],
    }


async def main_async(args: argparse.Namespace) -> int:
    tasks = _load_tasks()
    if args.task_id:
        tasks = [t for t in tasks if t["task_id"].startswith(args.task_id)]
    tasks = tasks[: args.limit]

    if args.dry_run:
        print(f"将处理 {len(tasks)} 个任务，条件 {args.conditions}:")
        for t in tasks:
            print(f"  L{t['level']} {t['task_id'][:8]} {t['query'][:60]}")
        print("\n(dry-run，未调用模型)")
        return 0

    if not os.getenv("DEFAULT_LLM_API_KEY"):
        print("缺少 DEFAULT_LLM_API_KEY。请在 .env 或环境变量中配置，或先跑 --dry-run。")
        return 1

    from oxygent import MAS

    from src.oxyagents.roles import build_oxy_space

    space = build_oxy_space(enable_web=args.enable_web)
    async with MAS(oxy_space=space) as mas:
        for t in tasks:
            d = FIXTURES / t["task_id"]
            d.mkdir(parents=True, exist_ok=True)
            print(f"[{t['task_id'][:8]}] L{t['level']} {t['query'][:48]}")

            single = await run_single(mas, t)
            multi = await run_multi(mas, t)

            (d / "_run.json").write_text(
                json.dumps({"single": single, "multi": multi}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            for cond in args.conditions:
                run = single if cond == "A" else multi
                s = build_session(t, cond, run)
                (d / f"{cond}.json").write_text(
                    json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            print(
                f"   A 单Agent={single['final_answer'][:30]!r} 多Agent={multi['final_answer'][:30]!r} "
                f"gold={t['answer'][:30]!r}"
            )
    print(f"\n完成。fixture 在 {FIXTURES}/<task_id>/*.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个任务（0 = 全部）")
    ap.add_argument("--task-id", default="", help="按前缀筛选 task_id")
    ap.add_argument("--conditions", default="ABC")
    ap.add_argument("--enable-web", action="store_true", help="挂载联网检索工具")
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
