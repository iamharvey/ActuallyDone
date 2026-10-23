"""demo/merge-mail：老实用例过，反面教材自己绿、夹具检查红。"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "demo" / "merge-mail"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT,
                          capture_output=True, text=True)


class TestMergeMailDemo(unittest.TestCase):
    def test_老实用例和夹具检查都过(self):
        unit = _run("-m", "unittest", "discover", "-s", "tests", "-q")
        self.assertEqual(unit.returncode, 0, unit.stdout + unit.stderr)
        honest = _run("scripts/check_honest.py")
        self.assertEqual(honest.returncode, 0, honest.stdout + honest.stderr)
        self.assertIn("PASS", honest.stdout)

    def test_反面教材断言是绿的_扫到它就红(self):
        cheat = _run("examples/cheat_after_call.py")
        self.assertEqual(cheat.returncode, 0, cheat.stdout + cheat.stderr)
        self.assertIn("断言过了", cheat.stdout)
        scanned = _run("scripts/check_honest.py", "--scan", "examples")
        self.assertNotEqual(scanned.returncode, 0)
        self.assertIn("调用之后改了规则要读的字段", scanned.stdout)
