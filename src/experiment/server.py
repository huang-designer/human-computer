#!/usr/bin/env python3
"""实验服务端：托管三条件界面、提供 fixture、记录全部行为日志。

零依赖（只用标准库），保证在任何机器上都能起：

    python3 -m src.experiment.server --port 8000
    # 打开 http://localhost:8000/?pid=P01&task=demo-ok&cond=C

接口
    GET  /api/tasks                     任务清单（taskset + 是否有 fixture）
    GET  /api/session?task_id=&condition=  归一化 Session
    POST /api/log                       行为事件（追加 JSONL）
    POST /api/response                  最终作答 + 主观量表
    GET  /api/export                    导出全部日志（研究者用）

日志落在 data/logs/（已 gitignore）。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.schema import CONDITIONS, CONDITION_SPEC, is_correct, validate

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
FIXTURES = ROOT / "fixtures"
TASKSET = ROOT / "taskset" / "experiment_tasks.json"
CATALOG = ROOT / "taskset" / "catalog.json"
LOGS = ROOT / "data" / "logs"


def load_tasks() -> list[dict]:
    if not TASKSET.exists():
        return []
    return json.loads(TASKSET.read_text(encoding="utf-8"))["tasks"]


def find_session(task_id: str, condition: str) -> dict | None:
    """先找 fixtures/<task_id>/<cond>.json，再找 fixtures/sample.json 里的 demo 条目。"""
    direct = FIXTURES / task_id / f"{condition}.json"
    if direct.exists():
        return json.loads(direct.read_text(encoding="utf-8"))
    bundle = FIXTURES / "sample.json"
    if bundle.exists():
        data = json.loads(bundle.read_text(encoding="utf-8"))
        return data.get("tasks", {}).get(task_id, {}).get("conditions", {}).get(condition)
    return None


def demo_tasks() -> list[dict]:
    bundle = FIXTURES / "sample.json"
    if not bundle.exists():
        return []
    data = json.loads(bundle.read_text(encoding="utf-8"))
    return [
        {
            "task_id": tid,
            "level": "decision",
            "title": f"示例 · {'系统答对' if 'ERR' not in tid else '系统答错'}",
            "query": v.get("query", ""),
            "constraint_text": v.get("constraints", ""),
            "demo": True,
        }
        for tid, v in data.get("tasks", {}).items()
    ]


def append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "HCIExperiment/0.2"

    # ---------- helpers ----------
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: object, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt: str, *args) -> None:  # 静音默认访问日志
        pass

    def _static(self, rel: str) -> None:
        target = (WEB / rel).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.is_file():
            self._json({"error": "not found", "path": rel}, 404)
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # ---------- routes ----------
    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            self._static("index.html")
            return
        if u.path == "/api/health":
            self._json({"ok": True, "ts": time.time(), "conditions": CONDITIONS})
            return
        if u.path == "/api/catalog":
            data = json.loads(CATALOG.read_text(encoding="utf-8"))
            # 只下发商品页可见的信息（listed），actual 值属于评分依据，不能给被试看
            items = [
                {"id": p["id"], "name": p["name"], "tag": p.get("tag", ""), **p["listed"], "issues": p.get("issues", [])}
                for p in data["products"]
            ]
            self._json({"products": items, "note": data.get("note", "")})
            return
        if u.path == "/api/tasks":
            seen = {t["task_id"] for t in demo_tasks()}
            tasks = demo_tasks() + [t for t in load_tasks() if t["task_id"] not in seen]
            for t in tasks:
                t.setdefault("level", "decision")
                t["has_fixture"] = all((FIXTURES / t["task_id"] / f"{c}.json").exists() for c in CONDITIONS) or bool(
                    t.get("demo")
                )
            self._json({"tasks": tasks, "condition_spec": CONDITION_SPEC})
            return
        if u.path == "/api/session":
            tid = (q.get("task_id") or [""])[0]
            cond = (q.get("condition") or ["C"])[0]
            if cond not in CONDITIONS:
                self._json({"error": f"condition 必须是 {CONDITIONS}"}, 400)
                return
            s = find_session(tid, cond)
            if not s:
                self._json({"error": "尚无该任务在该条件下的运行结果（fixture 未生成）", "task_id": tid, "condition": cond}, 404)
                return
            problems = validate(s)
            if problems:
                self._json({"error": "fixture 结构非法", "problems": problems}, 500)
                return
            self._json(s)
            return
        if u.path == "/api/export":
            out = {}
            for name in ("events", "responses"):
                p = LOGS / f"{name}.jsonl"
                out[name] = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
            self._json(out)
            return

        self._static(u.path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        body = self._read_body()

        if u.path == "/api/log":
            append_jsonl(LOGS / "events.jsonl", {"ts": time.time(), **body})
            self._json({"ok": True})
            return

        if u.path == "/api/response":
            tid = body.get("task_id", "")
            task = next((t for t in load_tasks() if t["task_id"] == tid), None)
            gold = task["answer"] if task else body.get("gold", "")
            user_answer = body.get("user_answer", "")
            append_jsonl(
                LOGS / "responses.jsonl",
                {
                    "ts": time.time(),
                    **body,
                    "correct": is_correct(user_answer, gold),
                    "ai_correct": is_correct(body.get("ai_answer", ""), gold),
                    "user_matched_ai": is_correct(user_answer, body.get("ai_answer", "")),
                },
            )
            self._json({"ok": True, "correct": is_correct(user_answer, gold)})
            return

        self._json({"error": "not found"}, 404)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"实验服务已启动: http://{args.host}:{args.port}/")
    print(f"  demo : /?pid=P01&task=demo-ok&cond=C")
    print(f"  日志 : {LOGS.relative_to(ROOT)}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
