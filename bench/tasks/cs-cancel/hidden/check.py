#!/usr/bin/env python3
"""跑完才拷进工作区。literal: HID_cs_cancel_9f3c2a"""

from __future__ import annotations

import sys
from pathlib import Path

# literal: HID_cs_cancel_9f3c2a

_KNOWN = {
    "hitl-refund.toml",
    "merge-conflict.toml",
    "recall-forbid.toml",
    "hitl-logistics.toml",
    "recall-must.toml",
}


def main() -> int:
    root = Path.cwd()
    sys.path.insert(0, str(root))
    from cs_agent import should_interrupt

    if not should_interrupt("我想取消订单", [], None):
        print("FAIL 取消订单没有打断")
        return 1
    found = False
    for path in sorted((root / "adone" / "eval").glob("*.toml")):
        if path.name in _KNOWN:
            continue
        if "取消" in path.read_text(encoding="utf-8"):
            found = True
    if not found:
        print("FAIL 没有新的评测场景")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
