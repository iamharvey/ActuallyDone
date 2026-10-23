#!/usr/bin/env python3
"""本项目自己加的门禁：正例会合并、反例不会，测试也没有在调用之后改条件字段。

adone 的 integrity 不扫 SQL，也不把「return 常量」当成失败。要挡造数，把这一步写进 adone.toml。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_CALL = re.compile(r"\b(ingest|decide)\s*\(")
_MUTATE = re.compile(
    r"(?:"
    r"(?:user_email|subject|sender|status)\s*="
    r"|\[\s*[\"'](?:user_email|subject|sender|status)[\"']\s*\]\s*="
    r"|\.(?:user_email|subject|sender|status)\s*="
    r"|\bUPDATE\b"
    r"|\$set"
    r")"
)
_NEGATIVE = re.compile(r"assertNotEqual|assertFalse|!=")


def _texts(rel: str) -> list[tuple[Path, str]]:
    base = ROOT / rel
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.rglob("*.py")):
        if path.name == "merge_mail.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _CALL.search(text):
            out.append((path, text))
    return out


def _mutates_after_call(text: str) -> bool:
    armed = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            armed = False
        if _CALL.search(line):
            armed = True
            continue
        if armed and _MUTATE.search(line):
            return True
    return False


def _oracle() -> str | None:
    import merge_mail

    def same(email_a: str, email_b: str) -> bool:
        store: list = []
        merge_mail.ingest(store, {"subject": "", "user_email": email_a})
        merge_mail.ingest(store, {"subject": "", "user_email": email_b})
        return store[0]["ticket_no"] == store[1]["ticket_no"]

    if not same("a@x", "a@x"):
        return "正例没有合并：空标题、同邮箱应该合成一单"
    if same("a@x", "b@x"):
        return "反例也被合并：邮箱不同却合成了一单，判定可能被写成了恒真"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查合并规则的夹具是否老实")
    parser.add_argument("--scan", default="tests", help="扫哪个目录里的调用，默认 tests")
    args = parser.parse_args(argv)

    texts = _texts(args.scan)
    if not texts:
        print(f"FAIL {args.scan} 里没有调用 ingest 的代码")
        return 1
    for path, text in texts:
        if _mutates_after_call(text):
            rel = path.relative_to(ROOT)
            print(f"FAIL {rel} 调用之后改了规则要读的字段")
            return 1
    if not any(_NEGATIVE.search(text) for _, text in texts):
        print(f"FAIL {args.scan} 没有走同一入口的反例")
        return 1
    try:
        problem = _oracle()
    except Exception as e:
        print(f"FAIL 入口跑不起来：{type(e).__name__}: {e}")
        return 1
    if problem:
        print("FAIL " + problem)
        return 1
    print(f"PASS 正例合并、反例不合并，{args.scan} 没有在调用之后改条件字段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
