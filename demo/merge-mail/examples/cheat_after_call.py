"""反面教材：调用之后改邮箱，断言仍然是绿的。

不要把这个文件放进 tests/。unittest 发现不到它，所以单跑测试门禁是绿的。
`scripts/check_honest.py --scan examples` 会失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import merge_mail


def main() -> int:
    store: list = []
    merge_mail.ingest(store, {"subject": "", "user_email": "a@x"})
    store[0]["user_email"] = "b@x"
    merge_mail.ingest(store, {"subject": "", "user_email": "b@x"})
    assert store[0]["ticket_no"] == store[1]["ticket_no"]
    print("断言过了。它只说明改完邮箱之后两条同号，说明不了决策前就是同邮箱。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
