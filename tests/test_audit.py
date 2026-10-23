"""独立复核：换一个不知道实现过程的执行者来查。

这些用例守的是复核者的三条底线：不覆盖被审证据、不替实现者宣布完成、
说自己核到了哪一层就是哪一层。
"""

from __future__ import annotations

import contextlib
import io
import json
from argparse import Namespace

from actuallydone import audit, gate, integrity, policy
from actuallydone.config import Config
from tests.helpers import ProjectCase


def _args(**over) -> Namespace:
    base = {"json": False, "rerun": False, "spotcheck": None, "brief": False,
            "out": None, "open": False}
    base.update(over)
    return Namespace(**base)


class AuditCase(ProjectCase):
    def cfg(self, argv=("sh", "-c", "exit 0")) -> Config:
        """一个「实现者已经把该记的账都记了」的项目：剩下的问题才是复核查出来的。"""
        self.make_go_project()
        cfg = self.config(gate={
            "watch_roots": ["internal"], "watch_exts": [".go"], "min_tree_files": 1,
            "step": [{"name": "测试", "cwd": ".", "argv": list(argv)}]})
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        integrity.write_baseline(cfg, integrity.scan(cfg), "建立初始基线")
        policy.write_baseline(cfg, policy.snapshot(cfg), "建立初始基线")
        return cfg

    def receipt(self, cfg: Config, **over) -> dict:
        """按实现者的样子留一份回执：树哈希取当前代码，默认全绿。"""
        h, n = gate.tree_hash(cfg)
        r = {"tool": "actuallydone", "id": "20260101-000000", "created_at": "now",
             "ok": True, "complete": True, "seq": 1, "prev": None,
             "steps": [{"name": "测试", "ok": True}],
             "tests": {"passed_names": ["TestAdd"]},
             "evidence": gate.evidence_of(cfg, {}),
             "tree": {"hash": h, "file_count": n}}
        r.update(over)
        r["self_hash"] = gate.self_hash(r)
        cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
        body = json.dumps(r, ensure_ascii=False)
        (cfg.receipts_dir / f"receipt-{r['id']}.json").write_text(body, encoding="utf-8")
        cfg.latest_receipt.write_text(body, encoding="utf-8")
        gate.write_chain_head(cfg, r)
        return r

    def audit_run(self, cfg: Config, **kw) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = audit.run_audit(cfg, **kw)
        return rc, buf.getvalue()


class TestAuditKeepsEvidenceIntact(AuditCase):
    def test_复核不覆盖实现者的回执与链头(self):
        # 复核者顺手写一份自己的回执，等于把被审的证据抹掉
        cfg = self.cfg()
        self.receipt(cfg)
        before = (cfg.latest_receipt.read_text(encoding="utf-8"),
                  cfg.chain.read_text(encoding="utf-8"))
        self.audit_run(cfg, spotcheck=0, rerun=True)
        after = (cfg.latest_receipt.read_text(encoding="utf-8"),
                 cfg.chain.read_text(encoding="utf-8"))
        self.assertEqual(before, after)
        self.assertEqual(list(cfg.receipts_dir.glob("receipt-*.json")).__len__(), 1)

    def test_结论落在独立的审计文件里(self):
        cfg = self.cfg()
        self.receipt(cfg)
        rc, _ = self.audit_run(cfg, spotcheck=0)
        self.assertEqual(rc, 0)
        v = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
        self.assertEqual(v["role"], "auditor")
        self.assertEqual(v["audited_receipt"]["id"], "20260101-000000")
        self.assertEqual(v["self_hash"], gate.self_hash(v))
        self.assertEqual(len(list(cfg.audits_dir.glob("audit-*.json"))), 1)


class TestAuditVerdict(AuditCase):
    def test_同一个模型复核则不通过_缺一边只记依据(self):
        cfg = self.cfg()
        self.receipt(cfg, runner={"model": "claude"})
        rc, out = self.audit_run(cfg, spotcheck=0, reviewer="claude")
        self.assertEqual(rc, 1)
        self.assertIn("同一个模型（claude）", out)
        rc, out = self.audit_run(cfg, spotcheck=0, reviewer="codex")
        self.assertEqual(rc, 0, out)
        self.assertIn("复核者 codex，跑出门禁的是 claude", out)
        rc, out = self.audit_run(cfg, spotcheck=0)
        self.assertEqual(rc, 0, out)
        self.assertIn("未标明复核者", out)

    def test_通过时说的是复核通过而不是替它宣布完成(self):
        cfg = self.cfg()
        self.receipt(cfg)
        rc, out = self.audit_run(cfg, spotcheck=0)
        self.assertEqual(rc, 0)
        self.assertIn("独立复核通过", out)
        self.assertNotIn("可以宣称完成", out)

    def test_没抽跑就不许说经得起抽跑(self):
        cfg = self.cfg()
        self.receipt(cfg)
        _, out = self.audit_run(cfg, spotcheck=0)
        self.assertIn("本次只读证据，没有当场重跑", out)
        self.assertNotIn("经得起", out)

    def test_重跑通过时说的是重跑而不是抽跑(self):
        cfg = self.cfg()
        self.receipt(cfg)
        _, out = self.audit_run(cfg, spotcheck=0, rerun=True)
        self.assertIn("独立重跑门禁得到同样的结果", out)

    def test_不通过时明说实现者不能宣称完成(self):
        cfg = self.cfg()
        self.receipt(cfg)
        self.write("internal/calc.go", "package internal\n\n// 跑完门禁又改了一笔\n")
        rc, out = self.audit_run(cfg, spotcheck=0)
        self.assertEqual(rc, 1)
        self.assertIn("实现者不能宣称完成", out)
        self.assertIn("回执已过期", out)

    def test_没有回执时也给得出结论(self):
        cfg = self.cfg()
        rc, out = self.audit_run(cfg, spotcheck=0)
        self.assertEqual(rc, 1)
        self.assertIn("还没跑过", out)


class TestAuditRerun(AuditCase):
    def test_重跑发现回执说全绿其实跑不过(self):
        cfg = self.cfg(argv=("sh", "-c", "echo 炸了; exit 1"))
        self.receipt(cfg)
        rc, out = self.audit_run(cfg, spotcheck=0, rerun=True)
        self.assertEqual(rc, 1)
        self.assertIn("回执写着全绿，我独立重跑却没过", out)

    def test_重跑发现回执证明的是另一份代码(self):
        cfg = self.cfg()
        self.receipt(cfg, tree={"hash": "别的代码的哈希", "file_count": 1})
        rc, out = self.audit_run(cfg, spotcheck=0, rerun=True)
        self.assertEqual(rc, 1)
        self.assertIn("证明的是另一份", out)

    def test_重跑发现回执列了根本没跑出来的用例名(self):
        # go 的假被试：只跑得出 TestAdd，回执却还列着另一个名字
        cfg = self.cfg(argv=("sh", "-c", 'echo "--- PASS: TestAdd (0.00s)"'))
        cfg.data["tests"]["adapter"] = "go"
        cfg.data["gate"]["step"][0].update({"kind": "test", "adapter": "go"})
        self.receipt(cfg, tests={"passed_names": ["TestAdd", "Test编出来的"]})
        rc, out = self.audit_run(cfg, spotcheck=0, rerun=True)
        self.assertEqual(rc, 1)
        self.assertIn("没有出现：Test编出来的", out)

    def test_配置本身有问题时重跑不算数(self):
        # 一个 step 都没有的话「全绿」毫无意义，不能当成复核通过
        self.make_go_project()
        cfg = self.config()
        self.receipt(cfg)
        rc, out = self.audit_run(cfg, spotcheck=0, rerun=True)
        self.assertEqual(rc, 1)
        self.assertIn("独立重跑不算数", out)

    def test_重跑的结果记进审计文件供第三方复现(self):
        cfg = self.cfg()
        self.receipt(cfg)
        self.audit_run(cfg, spotcheck=0, rerun=True)
        v = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
        self.assertEqual(v["mode"], "rerun")
        self.assertTrue(v["rerun"]["ok"])
        self.assertEqual([s["name"] for s in v["rerun"]["steps"]], ["测试"])


class TestAuditEvidenceLine(AuditCase):
    def test_核到哪一层就说哪一层(self):
        self.assertIn("只读证据核对", audit._evidence_line("证据强度：自述（本地跑）", False, 0))
        self.assertIn("抽 2 条当场真跑", audit._evidence_line("证据强度：自述（本地跑）", False, 2))
        self.assertIn("全量重跑核对", audit._evidence_line("证据强度：自述（本地跑）", True, 2))

    def test_没有回执时不许含糊(self):
        self.assertIn("没有回执可依", audit._evidence_line("", False, 0))

    def test_审计文件里带上复核方式(self):
        cfg = self.cfg()
        self.receipt(cfg)
        self.audit_run(cfg, spotcheck=0)
        v = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
        self.assertEqual(v["evidence"]["audited_by"], "independent-local")
        self.assertEqual(v["evidence"]["audit_mode"], "review")


class TestBrief(AuditCase):
    def brief_text(self, cfg: Config) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(audit.brief(cfg), 0)
        return buf.getvalue()

    def test_简报把判据在哪说清楚(self):
        cfg = self.cfg()
        self.receipt(cfg)
        text = self.brief_text(cfg)
        for want in ("独立复核者", "验收契约", "判据基线", "假绿基线", "证据链头",
                     "调用之后", "断言比「要求」弱",
                     "adone audit --rerun", "adone audit report", "20260101-000000"):
            self.assertIn(want, text)

    def test_简报点名复核者不许自己给自己放行(self):
        text = self.brief_text(self.cfg())
        self.assertIn("policy --accept", text)
        self.assertIn("integrity --accept-baseline", text)
        self.assertIn("只报告，不修复", text)

    def test_还没有回执时简报照样能出(self):
        self.assertIn("还没有", self.brief_text(self.cfg()))


class TestAuditCli(AuditCase):
    def test_默认抽查两条(self):
        cfg = self.cfg()
        self.receipt(cfg)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            audit.cmd_audit(cfg, _args())
        v = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
        self.assertEqual(v["spotcheck"]["asked"], 2)

    def test_json输出可直接被脚本读(self):
        cfg = self.cfg()
        self.receipt(cfg)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = audit.cmd_audit(cfg, _args(json=True, spotcheck=0))
        v = json.loads(buf.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(v["ok"])
        self.assertEqual(v["role"], "auditor")

    def test_抽查条数不许是负数(self):
        cfg = self.cfg()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(audit.cmd_audit(cfg, _args(spotcheck=-1)), 2)

    def test_cli认出audit_report子命令(self):
        from actuallydone.cli import build_parser
        args = build_parser().parse_args(["audit", "report", "--out", "x.html"])
        self.assertEqual(args.func.__name__, "cmd_audit_report")
        self.assertEqual(args.out, "x.html")


class TestAuditHtml(AuditCase):
    def html(self, cfg: Config) -> str:
        return cfg.audit_report.read_text(encoding="utf-8")

    def test_跑完审计会写出可离线打开的html(self):
        cfg = self.cfg()
        self.receipt(cfg)
        _, out = self.audit_run(cfg, spotcheck=0)
        self.assertTrue(cfg.audit_report.is_file(), "该写出 .adone/audit.html")
        html = self.html(cfg)
        self.assertIn("独立复核通过", html)
        self.assertIn("20260101-000000", html)
        self.assertNotIn("可以宣称完成", html)
        self.assertNotIn("<script", html)
        self.assertIn("HTML 报告", out)

    def test_未通过的html写明实现者不能宣称完成(self):
        cfg = self.cfg()
        self.receipt(cfg)
        self.write("internal/calc.go", "package internal\n\n// 跑完门禁又改了一笔\n")
        self.audit_run(cfg, spotcheck=0)
        html = self.html(cfg)
        self.assertIn("实现者不能宣称完成", html)
        self.assertIn("回执已过期", html)
        self.assertIn("未通过", html)

    def test_html如实写复核强度且点明同机不是不可伪造(self):
        cfg = self.cfg()
        self.receipt(cfg)
        self.audit_run(cfg, spotcheck=0)
        html = self.html(cfg)
        self.assertIn("只读证据", html)
        self.assertNotIn("抽查的用例当场真跑仍然通过", html)
        self.assertIn("不是不可伪造", html)
        self.assertIn("不可能造假", html)

    def test_out指定路径时写到那里(self):
        cfg = self.cfg()
        self.receipt(cfg)
        dest = self.root / "share" / "audit.html"
        self.audit_run(cfg, spotcheck=0, html_out=str(dest))
        self.assertTrue(dest.is_file())
        self.assertIn("独立复核通过", dest.read_text(encoding="utf-8"))

    def test_report命令只渲已有结论不重跑(self):
        cfg = self.cfg()
        self.receipt(cfg)
        self.audit_run(cfg, spotcheck=0)
        first = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
        dest = self.root / "share" / "from-report.html"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = audit.cmd_audit_report(cfg, Namespace(out=str(dest), open=False))
        self.assertEqual(rc, 0)
        self.assertTrue(dest.is_file())
        self.assertIn("独立复核通过", dest.read_text(encoding="utf-8"))
        again = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(again["self_hash"], first["self_hash"])

    def test_还没有结论时report拒绝(self):
        cfg = self.cfg()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                audit.cmd_audit_report(cfg, Namespace(out=None, open=False)), 2)

    def test_report对未通过的结论退出码为1(self):
        cfg = self.cfg()
        self.receipt(cfg)
        self.write("internal/calc.go", "package internal\n\n// 过期\n")
        self.audit_run(cfg, spotcheck=0)
        dest = self.root / "fail.html"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = audit.cmd_audit_report(cfg, Namespace(out=str(dest), open=False))
        self.assertEqual(rc, 1)
