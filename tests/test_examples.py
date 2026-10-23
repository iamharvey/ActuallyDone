"""examples/ 里的基线配置能被读成 adone.toml，步骤种类没有标错。"""

from __future__ import annotations

import unittest
from pathlib import Path

from actuallydone.config import Config

REPO = Path(__file__).resolve().parents[1]


class TestBaselineExamples(unittest.TestCase):
    def test_java_基线盖住格式风格测试和技能(self):
        cfg = Config.load(REPO / "examples" / "java")
        steps = {s["name"]: s for s in cfg.get("gate.step")}
        self.assertEqual(set(steps), {
            "敏感信息", "格式化", "Checkstyle", "SpotBugs", "技能检查",
            "单元测试", "API 测试", "打包", "端到端",
        })
        self.assertNotIn("kind", steps["格式化"])
        for name in ("单元测试", "API 测试", "端到端"):
            self.assertEqual(steps[name]["kind"], "test")
            self.assertEqual(steps[name]["adapter"], "java")
        self.assertEqual(cfg.get("coverage.source"), "单元测试")
        self.assertIn("jacoco:prepare-agent", steps["单元测试"]["argv"])
        self.assertNotIn("jacoco:report", steps["API 测试"]["argv"])

    def test_go_基线的格式化步骤标成_fmt(self):
        cfg = Config.load(REPO / "examples" / "go")
        steps = {s["name"]: s for s in cfg.get("gate.step")}
        self.assertEqual(set(steps), {
            "敏感信息", "gofmt", "goimports", "go vet", "staticcheck",
            "技能检查", "go build", "单元测试", "API 测试", "端到端",
        })
        self.assertEqual(steps["gofmt"]["kind"], "fmt")
        self.assertEqual(steps["goimports"]["kind"], "fmt")
        self.assertNotIn("kind", steps["staticcheck"])
        for name in ("单元测试", "API 测试", "端到端"):
            self.assertEqual(steps[name]["kind"], "test")
            self.assertEqual(steps[name]["adapter"], "go")
        self.assertIn("-v", steps["单元测试"]["argv"])
        self.assertIn("-coverprofile={cover_out}", steps["单元测试"]["argv"])
        self.assertEqual(cfg.get("coverage.source"), "单元测试")
