"""正例和反例都在调用 ingest 之前把字段写好。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import merge_mail


class MergeMailTest(unittest.TestCase):
    def test_同邮箱空标题合并(self):
        store: list = []
        merge_mail.ingest(store, {"subject": "", "user_email": "a@x"})
        merge_mail.ingest(store, {"subject": "", "user_email": "a@x"})
        self.assertEqual(store[0]["ticket_no"], store[1]["ticket_no"])

    def test_邮箱不同不合并(self):
        store: list = []
        merge_mail.ingest(store, {"subject": "", "user_email": "a@x"})
        merge_mail.ingest(store, {"subject": "", "user_email": "b@x"})
        self.assertNotEqual(store[0]["ticket_no"], store[1]["ticket_no"])


if __name__ == "__main__":
    unittest.main()
