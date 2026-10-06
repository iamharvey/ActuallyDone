"""实现变了、测试没变：全量回执记下，check 拦住，豁免绑在当前实现哈希上。"""

from __future__ import annotations

import contextlib
import io
import json
import time

from actuallydone import gate, integrity
from tests.helpers import ProjectCase


def _step() -> dict:
    return {"name": "测试", "cwd": ".", "argv": ["sh", "-c", "exit 0"]}


class TestTreeParts(ProjectCase):
    def test_监视树外的测试文件不算进实现哈希(self):
        self.write("internal/calc.go", "package internal\nfunc A() {}\n")
        self.write("tests/calc_test.go", "package tests\nfunc TestA(t *testing.T) {}\n")
        cfg = self.config(tests={"adapter": "go", "roots": ["tests"]})
        before = gate.tree_parts(cfg)
        self.assertEqual(before["test_count"], 1)
        self.assertEqual(before["impl_count"], 1)
        self.write("tests/calc_test.go",
                   "package tests\nfunc TestA(t *testing.T) { t.Log(1) }\n")
        after = gate.tree_parts(cfg)
        self.assertEqual(after["impl_hash"], before["impl_hash"])
        self.assertNotEqual(after["test_hash"], before["test_hash"])

    def test_扫不到测试文件则未评估且不失败(self):
        self.write("internal/calc.go", "package internal\nfunc A() {}\n")
        cfg = self.config(tests={"adapter": "go", "roots": ["missing"]})
        problems, details = gate.new_tests_problems(cfg, {
            "scope": "full",
            "tree": {"impl_hash": "abc", "test_count": 0, "impl_changed": True,
                     "tests_changed": False},
        })
        self.assertEqual(problems, [])
        self.assertTrue(any("未做" in d for d in details), details)

    def test_老回执没有impl_hash不失败(self):
        self.make_go_project()
        cfg = self.config()
        problems, details = gate.new_tests_problems(cfg, {
            "scope": "full",
            "tree": {"hash": "abc", "file_count": 2},
        })
        self.assertEqual(problems, [])
        self.assertEqual(details, [])


class TestNewTestsGate(ProjectCase):
    def cfg(self):
        self.make_go_project()
        return self.config(gate={
            "watch_roots": ["internal"],
            "watch_exts": [".go"],
            "min_tree_files": 1,
            "step": [_step()],
        })

    def _run(self, cfg) -> dict:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gate.run_gate(cfg)
        self.assertEqual(rc, 0, buf.getvalue())
        return json.loads(cfg.latest_receipt.read_text(encoding="utf-8"))

    def test_实现变测试不变_豁免只对当前哈希有效(self):
        cfg = self.cfg()
        (cfg.state_dir).mkdir(parents=True, exist_ok=True)
        (cfg.state_dir / "runner.json").write_text(
            json.dumps({"model": "claude"}), encoding="utf-8")
        first = self._run(cfg)
        self.assertIn("impl_hash", first["tree"])
        self.assertNotIn("impl_changed", first["tree"])
        self.assertEqual(first["runner"]["model"], "claude")

        time.sleep(1.1)
        self.write("internal/calc.go", "package internal\nfunc Add(a, b int) int { return a + b + 1 }\n")
        second = self._run(cfg)
        self.assertTrue(second["tree"]["impl_changed"])
        self.assertFalse(second["tree"]["tests_changed"])

        integrity.write_baseline(cfg, integrity.scan(cfg), "建立初始基线")
        got = gate.collect_check(cfg)
        self.assertTrue(any("测试文件没有变" in p for p in got["problems"]), got["problems"])

        self.assertEqual(gate.waive_new_tests(cfg, "这次只改注释，没有新行为"), 0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gate.check_gate(cfg)
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertIn("交给复核者的证据", buf.getvalue())
        self.assertNotIn("可以宣称完成", buf.getvalue())

        time.sleep(1.1)
        self.write("internal/calc.go", "package internal\nfunc Add(a, b int) int { return a + b + 2 }\n")
        third = self._run(cfg)
        self.assertTrue(third["tree"]["impl_changed"])
        self.assertFalse(third["tree"]["tests_changed"])
        got = gate.collect_check(cfg)
        self.assertTrue(any("测试文件没有变" in p for p in got["problems"]), got["problems"])

    def test_理由太短不写豁免(self):
        cfg = self.cfg()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = gate.waive_new_tests(cfg, "短")
        self.assertEqual(rc, 2)
        self.assertFalse(gate.new_tests_waiver_path(cfg).exists())
