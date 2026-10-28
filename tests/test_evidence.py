"""证据强度：判据锁、回执自哈希与链、抽查真跑。

这些用例守的是「绕过成本」：每一条都对应一条曾经能无声走通的路。
"""

from __future__ import annotations

import json
from argparse import Namespace

from actuallydone import gate, policy
from actuallydone.config import Config
from tests.helpers import ProjectCase


def _args(**over) -> Namespace:
    base = {"json": False, "accept": None}
    base.update(over)
    return Namespace(**base)


class PolicyCase(ProjectCase):
    """先建立基线，再改配置，比对基线与改后的快照。"""

    def based(self, **over) -> Config:
        self.make_go_project()
        cfg = self.config(**over)
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        policy.write_baseline(cfg, policy.snapshot(cfg), "建立初始基线")
        return cfg

    def loosened(self, base: Config, **over) -> list[str]:
        now = self.config(**over)
        loose, _ = policy.diff(policy.load_baseline(base)["snapshot"],
                               policy.snapshot(now))
        return loose

    def tightened(self, base: Config, **over) -> list[str]:
        now = self.config(**over)
        _, tight = policy.diff(policy.load_baseline(base)["snapshot"],
                               policy.snapshot(now))
        return tight


class TestPolicyLock(PolicyCase):
    def test_缩小受监视范围会被点名(self):
        cfg = self.based(gate={"watch_roots": ["internal", "cmd"],
                               "watch_exts": [".go"], "min_tree_files": 1})
        loose = self.loosened(cfg, gate={"watch_roots": ["cmd"],
                                         "watch_exts": [".go"], "min_tree_files": 1})
        self.assertTrue(any("受监视目录少了 internal" in p for p in loose))

    def test_扩大受监视范围只提示不阻断(self):
        cfg = self.based()
        over = {"gate": {"watch_roots": ["internal", "cmd"], "watch_exts": [".go"],
                         "min_tree_files": 1}}
        self.assertEqual(self.loosened(cfg, **over), [])
        self.assertTrue(any("受监视目录多了 cmd" in t for t in self.tightened(cfg, **over)))

    def test_下调文件数下限会被点名(self):
        cfg = self.based(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                               "min_tree_files": 50})
        loose = self.loosened(cfg, gate={"watch_roots": ["internal"],
                                         "watch_exts": [".go"], "min_tree_files": 1})
        self.assertTrue(any("min_tree_files 从 50 降到 1" in p for p in loose))

    def test_删掉门禁步骤会被点名(self):
        step = {"name": "go vet", "cwd": ".", "argv": ["go", "vet", "./..."]}
        cfg = self.based(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                               "min_tree_files": 1, "step": [step]})
        loose = self.loosened(cfg, gate={"watch_roots": ["internal"],
                                         "watch_exts": [".go"], "min_tree_files": 1,
                                         "step": []})
        self.assertTrue(any("go vet」被删掉了" in p for p in loose))

    def test_把测试命令换成只跑一条会被点名(self):
        old = {"name": "测试", "cwd": ".", "kind": "test", "adapter": "go",
               "argv": ["go", "test", "./...", "-count=1", "-v"]}
        new = {**old, "argv": ["go", "test", "./...", "-run", "TestNothing", "-v"]}
        cfg = self.based(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                               "min_tree_files": 1, "step": [old]})
        loose = self.loosened(cfg, gate={"watch_roots": ["internal"],
                                         "watch_exts": [".go"], "min_tree_files": 1,
                                         "step": [new]})
        self.assertTrue(any("的命令变了" in p for p in loose))

    def test_删掉失效标记会被点名(self):
        old = {"name": "测试", "cwd": ".", "kind": "test", "argv": ["go", "test"],
               "invalid_marks": ["no test files", "build failed"]}
        new = {**old, "invalid_marks": ["build failed"]}
        cfg = self.based(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                               "min_tree_files": 1, "step": [old]})
        loose = self.loosened(cfg, gate={"watch_roots": ["internal"],
                                         "watch_exts": [".go"], "min_tree_files": 1,
                                         "step": [new]})
        self.assertTrue(any("不再把 no test files 判为证据无效" in p for p in loose))

    def test_门禁步骤跑的仓库内脚本被换掉会被点名(self):
        self.write("ci/test.sh", "#!/bin/sh\ngo test ./...\n")
        step = {"name": "测试", "cwd": ".", "kind": "test",
                "argv": ["ci/test.sh"]}
        cfg = self.based(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                               "min_tree_files": 1, "step": [step]})
        # argv 一个字没变，脚本改成印一段完美输出——这条路原本完全无声
        self.write("ci/test.sh", "#!/bin/sh\necho '--- PASS: TestAll'\n")
        loose = self.loosened(cfg, gate={"watch_roots": ["internal"],
                                         "watch_exts": [".go"], "min_tree_files": 1,
                                         "step": [step]})
        self.assertTrue(any("脚本内容变了" in p for p in loose))

    def test_豁免名单变长会被点名(self):
        cfg = self.based(tests={"adapter": "go", "roots": ["internal"],
                                "baseline_exempt": []})
        loose = self.loosened(cfg, tests={"adapter": "go", "roots": ["internal"],
                                          "baseline_exempt": ["TestAdd"]})
        self.assertTrue(any("豁免名单新增 TestAdd" in p for p in loose))

    def test_取消覆盖率下限会被点名(self):
        cfg = self.based(coverage={"threshold": 70.0, "source": "测试"})
        loose = self.loosened(cfg, coverage={"threshold": None, "source": "测试"})
        self.assertTrue(any("被取消" in p for p in loose))

    def test_删掉验收契约会被点名(self):
        self.make_go_project()
        cfg = self.config()
        cfg.acceptance_dir.mkdir(parents=True)
        (cfg.acceptance_dir / "t.toml").write_text(
            'task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n', encoding="utf-8")
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        policy.write_baseline(cfg, policy.snapshot(cfg), "初始")
        (cfg.acceptance_dir / "t.toml").unlink()
        loose, _ = policy.diff(policy.load_baseline(cfg)["snapshot"], policy.snapshot(cfg))
        self.assertTrue(any("不见了" in p for p in loose))

    def test_契约改绑到另一个用例会被点名(self):
        self.make_go_project()
        cfg = self.config()
        cfg.acceptance_dir.mkdir(parents=True)
        f = cfg.acceptance_dir / "t.toml"
        f.write_text('task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n',
                     encoding="utf-8")
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        policy.write_baseline(cfg, policy.snapshot(cfg), "初始")
        f.write_text('task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestNoAssert"\n',
                     encoding="utf-8")
        loose, _ = policy.diff(policy.load_baseline(cfg)["snapshot"], policy.snapshot(cfg))
        self.assertTrue(any("改了绑定的用例" in p for p in loose))

    def test_原样不动时没有任何放松(self):
        cfg = self.based()
        self.assertEqual(self.loosened(cfg), [])

    def test_记账之后不再报(self):
        cfg = self.based(coverage={"threshold": 70.0, "source": "测试"})
        loose_cfg = self.config(coverage={"threshold": 50.0, "source": "测试"})
        self.assertTrue(policy.policy_problems(loose_cfg, None)[0])
        policy.cmd_policy(loose_cfg, _args(accept="覆盖率下限暂时降到 50，理由：拆包期"))
        self.assertEqual(policy.policy_problems(loose_cfg, None)[0], [])

    def test_记账不写理由要被拒(self):
        cfg = self.based()
        self.assertEqual(policy.cmd_policy(cfg, _args(accept="嗯")), 2)

    def test_没有基线时只提示不阻断(self):
        self.make_go_project()
        cfg = self.config()
        problems, details = policy.policy_problems(cfg, None)
        self.assertEqual(problems, [])
        self.assertTrue(any("判据锁还没建立" in d for d in details))

    def test_删掉基线在回执记过指纹时要被抓(self):
        cfg = self.based()
        receipt = {"policy": {"hash": "deadbeefcafe"}}
        cfg.policy_baseline.unlink()
        problems, _ = policy.policy_problems(cfg, receipt)
        self.assertTrue(any("判据锁基线不见了" in p for p in problems))

    def test_跑完门禁再改判据要被抓(self):
        # 改了判据、也老老实实记了账，却没重跑门禁：那份回执证明的是另一把尺子
        cfg = self.based()
        problems, _ = policy.policy_problems(cfg, {"policy": {"hash": "老判据的指纹"}})
        self.assertTrue(any("另一套判据下跑出来的" in p for p in problems))

    def test_gate_run不给已有基线洗白(self):
        cfg = self.based()
        cfg.policy_baseline.unlink()
        said = policy.ensure_baseline(cfg, {"policy": {"hash": "abc"}})
        self.assertIn("不替你重建", said)
        self.assertFalse(cfg.policy_baseline.exists())

    def test_基线被写坏时按坏了报而不是按没建立(self):
        # 「读不成」当「没建立」处理的话，把基线改成一段乱码就等于悄悄关掉判据锁
        cfg = self.based()
        cfg.policy_baseline.write_text("{ 这不是 JSON", encoding="utf-8")
        problems, _ = policy.policy_problems(cfg, None)
        self.assertTrue(any("基线坏了" in p for p in problems))

    def test_基线被换成别的JSON也算坏了(self):
        cfg = self.based()
        cfg.policy_baseline.write_text('{"hash": "随便写的"}', encoding="utf-8")
        problems, _ = policy.policy_problems(cfg, None)
        self.assertTrue(any("基线坏了" in p for p in problems))

    def test_基线坏了时gate_run不替它重建(self):
        cfg = self.based()
        cfg.policy_baseline.write_text("坏的", encoding="utf-8")
        self.assertIn("读不成", policy.ensure_baseline(cfg, None))
        self.assertEqual(cfg.policy_baseline.read_text(encoding="utf-8"), "坏的")

    def test_第一次跑门禁自动建立基线(self):
        self.make_go_project()
        cfg = self.config()
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.assertIn("已建立", policy.ensure_baseline(cfg, None))
        self.assertTrue(cfg.policy_baseline.exists())


class ChainCase(ProjectCase):
    def receipt(self, **over) -> dict:
        r = {"tool": "actuallydone", "id": "20260101-000000", "created_at": "now",
             "ok": True, "complete": True, "seq": 1, "prev": None,
             "tests": {"passed_names": ["TestAdd"]},
             "tree": {"hash": "h", "file_count": 1}}
        r.update(over)
        r["self_hash"] = gate.self_hash(r)
        return r

    def put(self, cfg: Config, r: dict) -> None:
        cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
        (cfg.receipts_dir / f"receipt-{r['id']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")
        cfg.latest_receipt.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        gate.write_chain_head(cfg, r)


class TestReceiptChain(ChainCase):
    def test_正常回执自洽且与链头一致(self):
        cfg = self.config()
        r = self.receipt()
        self.put(cfg, r)
        problems, details = gate.chain_problems(cfg, r)
        self.assertEqual(problems, [])
        self.assertTrue(any("证据链第 1 环" in d for d in details))

    def test_手改回执里的通过状态会被自哈希抓住(self):
        cfg = self.config()
        r = self.receipt(ok=False)
        self.put(cfg, r)
        r["ok"] = True   # 只改内容不改自哈希，正是最省事的那种改法
        problems, _ = gate.chain_problems(cfg, r)
        self.assertTrue(any("自哈希对不上" in p for p in problems))

    def test_换掉latest指向另一份旧回执会被链头抓住(self):
        cfg = self.config()
        first = self.receipt(id="20260101-000000", ok=False)
        self.put(cfg, first)
        second = self.receipt(id="20260102-000000", seq=2, prev=first["self_hash"])
        self.put(cfg, second)
        cfg.latest_receipt.write_text(json.dumps(first, ensure_ascii=False),
                                      encoding="utf-8")
        problems, _ = gate.chain_problems(cfg, first)
        self.assertTrue(any("证据链头对不上" in p for p in problems))

    def test_删掉链头会被抓住(self):
        cfg = self.config()
        r = self.receipt()
        self.put(cfg, r)
        cfg.chain.unlink()
        problems, _ = gate.chain_problems(cfg, r)
        self.assertTrue(any("证据链头" in p and "不见了" in p for p in problems))

    def test_中间那份被删会报断链(self):
        cfg = self.config()
        first = self.receipt(id="20260101-000000")
        self.put(cfg, first)
        second = self.receipt(id="20260102-000000", seq=2, prev=first["self_hash"])
        self.put(cfg, second)
        (cfg.receipts_dir / "receipt-20260101-000000.json").unlink()
        problems, _ = gate.chain_problems(cfg, second)
        self.assertTrue(any("证据链断了" in p for p in problems))

    def test_老回执被裁剪掉不算断链(self):
        cfg = self.config(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                                "min_tree_files": 1, "keep_receipts": 1})
        r = self.receipt(seq=9, prev="早就被prune掉的自哈希")
        self.put(cfg, r)
        problems, _ = gate.chain_problems(cfg, r)
        self.assertEqual(problems, [])

    def test_升级前的老回执优雅降级(self):
        cfg = self.config()
        problems, details = gate.chain_problems(cfg, {"id": "old", "ok": True})
        self.assertEqual(problems, [])
        self.assertTrue(any("早于证据链机制" in d for d in details))

    def test_链建起来之后再冒出链外回执就是被换过(self):
        # 老回执的优雅降级不能变成后门：链头都有了，还有人拿一份链外回执当最新
        cfg = self.config()
        self.put(cfg, self.receipt())
        problems, _ = gate.chain_problems(cfg, {"id": "old", "ok": True})
        self.assertTrue(any("被换成了一份更老的回执" in p for p in problems))

    def test_没有回执时不该在这里报错(self):
        self.assertEqual(gate.chain_problems(self.config(), None), ([], []))

    def test_两条分支的链都算尖_换回更早一环不行(self):
        cfg = self.config()
        first = self.receipt(id="20260101-000000")
        self.put(cfg, first)
        second = self.receipt(id="20260102-000000", seq=2, prev=first["self_hash"])
        self.put(cfg, second)
        other = self.receipt(id="20260103-000000", seq=8, prev=None,
                             created_at="2026-10-14T14:12:33")
        gate.write_chain_head(cfg, other)
        problems, _ = gate.chain_problems(cfg, second)
        self.assertEqual(problems, [])
        problems, _ = gate.chain_problems(cfg, other)
        self.assertEqual(problems, [])
        problems, _ = gate.chain_problems(cfg, first)
        self.assertTrue(any("更早的一环" in p for p in problems))

    def test_冲突标记收成两边都留的链(self):
        cfg = self.config()
        left = self.receipt(id="20261015-110402", seq=9, created_at="2026-10-15T11:04:07")
        right = self.receipt(id="20261014-141233", seq=17, created_at="2026-10-14T14:12:33")
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        def body(rec: dict, seq: int) -> str:
            return json.dumps({
                "head": rec["self_hash"], "seq": seq,
                "receipt_id": rec["id"], "updated_at": rec["created_at"],
            }, ensure_ascii=False, indent=2)
        left_body = "\n".join(body(left, 9).splitlines()[1:-1])
        right_body = "\n".join(body(right, 17).splitlines()[1:-1])
        cfg.chain.write_text(
            "{\n"
            "<<<<<<< HEAD\n"
            + left_body + "\n"
            "=======\n"
            + right_body + "\n"
            ">>>>>>> master\n"
            "}\n",
            encoding="utf-8")
        self.assertEqual(gate.repair_chain(cfg), 0)
        text = cfg.chain.read_text(encoding="utf-8")
        self.assertNotIn("<<<<<<<", text)
        heads = {json.loads(line)["receipt_id"] for line in text.splitlines() if line.strip()}
        self.assertEqual(heads, {left["id"], right["id"]})
        self.assertIn("merge=union", (cfg.root / ".gitattributes").read_text(encoding="utf-8"))


class TestCheckSurvivesBrokenTree(ChainCase):
    def test_树哈希算不出来时给人话而不是堆栈并且继续核判据(self):
        # 把 watch_roots 缩没是最省事的一种改判据，它会先撞上文件数下限
        self.make_go_project()
        good = self.config()
        good.state_dir.mkdir(parents=True, exist_ok=True)
        policy.write_baseline(good, policy.snapshot(good), "建立初始基线")
        self.put(good, self.receipt())

        bad = self.config(gate={"watch_roots": ["不存在的目录"], "watch_exts": [".go"],
                                "min_tree_files": 5})
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gate.check_gate(bad, with_integrity=False)
        self.assertEqual(rc, 1)
        out = buf.getvalue()
        self.assertIn("受监视文件", out)          # 人话，不是堆栈
        self.assertIn("判据被放松", out)          # 崩了就看不到这条，而它才是真正的原因


class TestEvidenceLevel(ProjectCase):
    def test_判据锁上了就标出来(self):
        self.make_go_project()
        cfg = self.config()
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        policy.write_baseline(cfg, policy.snapshot(cfg), "初始")
        ev = gate.evidence_of(cfg, {})
        self.assertEqual(ev["level"], "self-reported")
        self.assertTrue(ev["policy_locked"])
        line = gate.evidence_line({"evidence": ev})
        self.assertIn("自述（本地跑）", line)
        self.assertIn("判据已锁", line)
        self.assertIn("回执链完整", line)

    def test_判据没锁时不许说锁了(self):
        self.make_go_project()
        cfg = self.config()
        self.assertFalse(gate.evidence_of(cfg, {})["policy_locked"])
        self.assertIn("判据未锁", gate.evidence_line({"evidence": gate.evidence_of(cfg, {})}))

    def test_老回执标成早于链机制(self):
        self.assertIn("早于证据链机制", gate.evidence_line({"id": "old"}))

    def test_报告头部要写明这些数字是怎么来的(self):
        from actuallydone.dimensions import DIMENSIONS
        from actuallydone.report import render
        out = self.root / "r.html"
        render([], out, 91, [], DIMENSIONS, "fixture", "证据强度：自述（本地跑）· 判据已锁")
        text = out.read_text(encoding="utf-8")
        self.assertIn("证据强度：自述（本地跑）· 判据已锁", text)

    def test_没有回执时报告不许含糊其辞(self):
        from actuallydone.dimensions import DIMENSIONS
        from actuallydone.report import render
        out = self.root / "r.html"
        render([], out, 0, [], DIMENSIONS, "fixture", "")
        self.assertIn("证据强度：未知", out.read_text(encoding="utf-8"))


class TestSpotCheck(ProjectCase):
    """用一个假的 go 命令当被试：抽查该跑什么、怎么判，不牵扯真的工具链。"""

    def fake_go(self, body: str) -> None:
        d = self.root / "bin"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "go"
        p.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        p.chmod(0o755)
        self.addCleanup(self.restore_path)
        import os
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = f"{d}:{self.old_path}"

    def restore_path(self) -> None:
        import os
        os.environ["PATH"] = self.old_path

    def cfg_with_test_step(self, **over) -> Config:
        self.make_go_project()
        return self.config(gate={
            "watch_roots": ["internal"], "watch_exts": [".go"], "min_tree_files": 1,
            "step": [{"name": "测试", "cwd": ".", "kind": "test", "adapter": "go",
                      "argv": ["go", "test", "./...", "-v"]}]}, **over)

    def test_抽中的用例真跑得过就放行(self):
        cfg = self.cfg_with_test_step()
        self.fake_go('echo "--- PASS: TestAdd (0.00s)"; echo ok')
        receipt = {"tests": {"passed_names": ["TestAdd"]}}
        from actuallydone.spotcheck import spot_check
        problems, details = spot_check(cfg, receipt, 1)
        self.assertEqual(problems, [])
        self.assertTrue(any("现在仍然通过" in d for d in details))

    def test_回执说通过但现在跑不过就拦下(self):
        cfg = self.cfg_with_test_step()
        self.fake_go('echo "--- FAIL: TestAdd (0.00s)"; exit 1')
        from actuallydone.spotcheck import spot_check
        problems, _ = spot_check(cfg, {"tests": {"passed_names": ["TestAdd"]}}, 1)
        self.assertTrue(any("现在跑不过" in p for p in problems))

    def test_一条都没跑起来不算通过(self):
        # 退出码 0 但没有任何用例记录：这是「没跑」，不是「通过」
        cfg = self.cfg_with_test_step()
        self.fake_go('echo "no test files"; exit 0')
        from actuallydone.spotcheck import spot_check
        problems, _ = spot_check(cfg, {"tests": {"passed_names": ["TestAdd"]}}, 1)
        self.assertTrue(any("一条都没跑起来" in p for p in problems))

    def test_优先抽契约绑定的用例(self):
        cfg = self.cfg_with_test_step()
        cfg.acceptance_dir.mkdir(parents=True)
        (cfg.acceptance_dir / "t.toml").write_text(
            'task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n', encoding="utf-8")
        self.fake_go('echo "--- PASS: TestAdd (0.00s)"')
        from actuallydone.spotcheck import spot_check
        _, details = spot_check(cfg, {"tests": {"passed_names": ["别的用例"]}}, 1)
        self.assertTrue(any("契约绑定用例" in d for d in details))

    def test_适配器不会单跑时说未评估而不是通过(self):
        self.make_go_project()
        cfg = self.config(gate={
            "watch_roots": ["internal"], "watch_exts": [".go"], "min_tree_files": 1,
            "step": [{"name": "测试", "cwd": ".", "kind": "test", "adapter": "generic",
                      "argv": ["make", "test"]}]})
        from actuallydone.spotcheck import spot_check
        problems, details = spot_check(cfg, {"tests": {"passed_names": ["TestAdd"]}}, 1)
        self.assertEqual(problems, [])
        self.assertTrue(any("未评估" in d for d in details))

    def test_没有测试步骤时说未评估(self):
        self.make_go_project()
        cfg = self.config()
        from actuallydone.spotcheck import spot_check
        problems, details = spot_check(cfg, {"tests": {"passed_names": ["TestAdd"]}}, 1)
        self.assertEqual(problems, [])
        self.assertTrue(any("未评估" in d for d in details))

    def test_回执里没有用例名时说未评估(self):
        cfg = self.cfg_with_test_step()
        from actuallydone.spotcheck import spot_check
        problems, details = spot_check(cfg, {"tests": {"passed_names": []}}, 1)
        self.assertEqual(problems, [])
        self.assertTrue(any("未评估" in d for d in details))
