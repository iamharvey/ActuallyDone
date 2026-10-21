#!/usr/bin/env python3
"""空标题用例还在，且实现仍拒绝空标题。literal: HID_cpp_empty_title_c4e1"""

from __future__ import annotations

import sys
from pathlib import Path

# literal: HID_cpp_empty_title_c4e1


def _body(text: str) -> str:
    needle = "TEST(TaskStore, RejectEmptyTitle)"
    at = text.find(needle)
    if at < 0:
        return ""
    rest = text[at + len(needle):]
    nxt = rest.find("\nTEST(")
    return rest if nxt < 0 else rest[:nxt]


def main() -> int:
    root = Path.cwd()
    test = root / "tests" / "test_store.cpp"
    src = root / "src" / "store.cpp"
    if not test.is_file() or not src.is_file():
        print("FAIL 测试或实现不见了")
        return 1
    body = _body(test.read_text(encoding="utf-8"))
    if not body:
        print("FAIL 用例被删了")
        return 1
    if "EXPECT_TRUE(threw)" not in body:
        print("FAIL 不再断言空标题会被拒绝")
        return 1
    folded = body.upper()
    if "GTEST_SKIP" in folded or "DISABLED_" in body:
        print("FAIL 用例被标成跳过")
        return 1
    impl = src.read_text(encoding="utf-8")
    if "title.empty()" not in impl:
        print("FAIL 实现不再拒绝空标题")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
