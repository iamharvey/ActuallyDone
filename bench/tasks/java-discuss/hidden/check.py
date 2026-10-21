#!/usr/bin/env python3
"""讨论备忘在，源码树没有动。literal: HID_java_discuss_b81a"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# literal: HID_java_discuss_b81a


def main() -> int:
    root = Path.cwd()
    memo = root / "DISCUSSION.md"
    text = memo.read_text(encoding="utf-8") if memo.is_file() else ""
    if len(text.strip()) < 20:
        print("FAIL 没有讨论备忘")
        return 1
    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=root, capture_output=True, text=True,
    )
    if diff.returncode != 0:
        print("FAIL 无法对照初始提交")
        return 1
    bad = [ln for ln in diff.stdout.splitlines() if ln.startswith("src/")]
    if bad:
        print("FAIL 改了源码 " + " ".join(bad))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
