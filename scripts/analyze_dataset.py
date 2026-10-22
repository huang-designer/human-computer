#!/usr/bin/env python3
"""分析验证集结构，为实验任务集选型提供依据。

输出 data/dataset_report.md，并在终端打印摘要。

用法:
    python scripts/analyze_dataset.py
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VALID = DATA / "valid.jsonl"
REPORT = DATA / "dataset_report.md"


def answer_type(a: object) -> str:
    s = str(a).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return "number"
    if s.startswith("http"):
        return "url"
    if len(s) <= 8:
        return "short"
    return "text"


def parse_file_name(fn: object) -> list[str]:
    """file_name 字段是不规范的字符串，形如 "['knoa2.mp4']" 或 "['辣妹子辣,mp3']"。"""
    if not fn:
        return []
    s = str(fn)
    names = re.findall(r"\[?'?([^\[\]',]+(?:[.,][^\[\]',]+)*)'?\]?", s)
    return [n.strip() for n in names if n.strip()]


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else "(目录)"


def main() -> int:
    rows = [json.loads(l) for l in VALID.read_text(encoding="utf-8").splitlines() if l.strip()]
    total = len(rows)

    missing_answer = [r for r in rows if "answer" not in r or not str(r.get("answer", "")).strip()]
    missing_steps = [r for r in rows if not str(r.get("steps", "")).strip()]

    level_dist = collections.Counter(str(r.get("level")) for r in rows)
    with_file = [r for r in rows if r.get("file_name")]
    atypes = collections.Counter(answer_type(r.get("answer")) for r in rows if r.get("answer") is not None)

    level_file = collections.Counter(
        (str(r.get("level")), "有附件" if r.get("file_name") else "无附件") for r in rows
    )
    # 附件扩展名（含解析异常）
    exts = collections.Counter()
    bad_file_name = []
    for r in rows:
        for n in parse_file_name(r.get("file_name")):
            e = ext_of(n)
            exts[e] += 1
            if e not in {"mp4", "mp3", "pdf", "pptx", "xlsx", "jpg", "jpeg", "png", "log", "txt"}:
                bad_file_name.append((r["task_id"], r.get("file_name")))

    dup = [q for q, c in collections.Counter(str(r.get("query", "")).strip() for r in rows).items() if c > 1]

    L = []
    L.append("# 验证集结构分析\n")
    L.append(f"- 总条数：**{total}**")
    L.append(f"- 缺 answer：{len(missing_answer)} 条" + ("（实验前必须剔除）" if missing_answer else ""))
    L.append(f"- 缺 steps：{len(missing_steps)} 条")
    L.append(f"- 有附件：{len(with_file)} 条 / 无附件：{total - len(with_file)} 条")
    L.append(f"- 重复 query：{len(dup)} 组\n")

    L.append("## 难度分布\n")
    L.append("| level | 数量 | 占比 |")
    L.append("|---|---|---|")
    for lv in sorted(level_dist):
        n = level_dist[lv]
        L.append(f"| {lv} | {n} | {n / total:.0%} |")

    L.append("\n## 难度 × 附件\n")
    L.append("| level | 有附件 | 无附件 |")
    L.append("|---|---|---|")
    for lv in sorted(level_dist):
        L.append(f"| {lv} | {level_file[(lv, '有附件')]} | {level_file[(lv, '无附件')]} |")

    L.append("\n## 答案类型\n")
    L.append("| 类型 | 数量 | 匹配特点 |")
    L.append("|---|---|---|")
    hint = {
        "number": "数值规范化后比对，容错低",
        "short": "短字符串，须完全一致",
        "url": "URL 精确匹配",
        "text": "长文本，规范化后比对，实际近乎不可命中",
    }
    for t, n in atypes.most_common():
        L.append(f"| {t} | {n} | {hint.get(t, '')} |")

    L.append("\n## 附件类型\n")
    L.append("| 扩展名 | 数量 |")
    L.append("|---|---|")
    for e, n in exts.most_common():
        L.append(f"| {e} | {n} |")

    L.append("\n## 数据质量问题\n")
    if bad_file_name:
        L.append(f"- `file_name` 字段有 {len(bad_file_name)} 处格式异常（如 `['辣妹子辣,mp3']` 用逗号代替点号，"
                 f"`['202504/']` 指向目录而非文件）。实现时**不能直接按此字段拼接路径**。")
        for tid, fn in bad_file_name[:5]:
            L.append(f"  - `{tid[:8]}` → `{fn}`")
    if missing_answer:
        L.append(f"- {len(missing_answer)} 条缺答案，无法用于计分。")
    L.append("- 多数 level 2/3 任务依赖**实时网页**（京东商详页、GitHub issue、豆瓣词条等），"
             "答案会随时间漂移，实验需固定采集时间或改用可缓存的快照。")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")

    print("\n".join(L))
    print(f"\n报告已写入 {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
