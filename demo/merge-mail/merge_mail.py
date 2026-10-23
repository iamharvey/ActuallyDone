"""两封标题都空、邮箱相同才合并。入口只读调用前已经写好的字段。"""

from __future__ import annotations


def decide(left: dict, right: dict) -> bool:
    title_a = str(left.get("subject") or "").strip()
    title_b = str(right.get("subject") or "").strip()
    email_a = str(left.get("user_email") or "").strip()
    email_b = str(right.get("user_email") or "").strip()
    return title_a == "" and title_b == "" and bool(email_a) and email_a == email_b


def ingest(store: list, message: dict) -> dict:
    """按调用这一刻 message 里的字段入库，再决定是否沿用已有单号。"""
    row = {
        "subject": message.get("subject") or "",
        "user_email": message.get("user_email") or "",
        "sender": message.get("sender") or "",
        "status": message.get("status") or "",
        "ticket_no": None,
    }
    for prev in store:
        if decide(prev, row):
            row["ticket_no"] = prev["ticket_no"]
            break
    if row["ticket_no"] is None:
        row["ticket_no"] = f"T{len(store) + 1}"
    store.append(row)
    return row
