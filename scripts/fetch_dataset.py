#!/usr/bin/env python3
"""拉取赛题数据集（验证集 100 条 + 测试集 200 条）。

数据来源：https://github.com/juzixiaoren/MetaJD （MIT）
原始版权归 CCF BDCI 赛方，仅用于课程研究，请勿再分发原始文件。

用法:
    python scripts/fetch_dataset.py                # 只拉 data.jsonl（约 100KB）
    python scripts/fetch_dataset.py --with-files   # 同时拉附件（约 380MB，谨慎）
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "juzixiaoren/MetaJD"
BRANCH = "main"
DATASET_DIR = "data/初赛数据集"

#: 仓库里 test 被放在了 valid/ 下面（valid/test/data.jsonl），顺序尝试多个候选路径
CANDIDATES = {
    "valid": [f"{DATASET_DIR}/valid/data.jsonl"],
    "test": [f"{DATASET_DIR}/test/data.jsonl", f"{DATASET_DIR}/valid/test/data.jsonl"],
}

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def raw_url(path: str) -> str:
    quoted = urllib.parse.quote(path)
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{quoted}"


def download(path: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = raw_url(path)
    print(f"  ↓ {path}")
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    dest.write_bytes(data)
    print(f"    → {dest.relative_to(ROOT)}  ({len(data) / 1024:.0f} KB)")


def download_any(paths: list[str], dest: Path) -> bool:
    for p in paths:
        try:
            download(p, dest)
            return True
        except urllib.error.HTTPError as exc:
            print(f"    ! {exc.code} {p}")
    return False


def verify(path: Path, expect: int) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != expect:
        print(f"  ! 期望 {expect} 条，实际 {len(rows)} 条", file=sys.stderr)
    else:
        print(f"  ✓ {path.name}: {len(rows)} 条")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-files", action="store_true", help="同时下载附件（很大）")
    args = ap.parse_args()

    print("拉取赛题数据集")
    valid = DATA / "valid.jsonl"
    test = DATA / "test.jsonl"

    ok_valid = download_any(CANDIDATES["valid"], valid)
    ok_test = download_any(CANDIDATES["test"], test)
    if not ok_valid:
        print("验证集拉取失败，请检查网络或仓库路径", file=sys.stderr)
        return 1
    verify(valid, 100)
    if ok_test:
        verify(test, 200)
    else:
        print("  ! 测试集拉取失败（可用性不影响实验，实验只用验证集）", file=sys.stderr)

    if args.with_files:
        print("\n附件下载：仓库内附件散落在 valid/ 与 valid/test/ 下，文件名不可靠。")
        print("建议只在需要时手动下载单个文件，避免占用 380MB+。")

    print("\n完成。下一步: python scripts/analyze_dataset.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
