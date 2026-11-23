"""内核：配置、树哈希、契约、假绿基线、锚点核验。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from actuallydone import bootstrap, contracts, gate, integrity, ledger
from actuallydone.config import Config, ConfigError, find_root
from tests.helpers import ProjectCase


class TestConfig(ProjectCase):
    def test_找不到配置时报错而不是用默认值凑合(self):
        with self.assertRaises(ConfigError):
            Config.load(self.root)

    def test_从子目录往上找配置(self):
        (self.root / "adone.toml").write_text("version = 1\n", encoding="utf-8")
        (self.root / "a" / "b").mkdir(parents=True)
        self.assertEqual(find_root(self.root / "a" / "b"), self.root.resolve())

    def test_体检报出空的受监视树(self):
        cfg = self.config(gate={"watch_roots": [], "watch_exts": [], "step": []})
        self.assertTrue(any("watch_roots 是空的" in p for p in cfg.problems()))

    def test_体检报出不存在的步骤目录(self):
        self.make_go_project()
        cfg = self.config(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                                "min_tree_files": 1,
                                "step": [{"name": "构建", "cwd": "不存在",
                                          "argv": ["go", "build"]}]})
        self.assertTrue(any("cwd 不存在" in p for p in cfg.problems()))


class TestBootstrap(ProjectCase):
    """入口自愈：钩子里的 PATH 与终端里的不是一回事，这条路真的被踩塌过。"""

    def fakes(self, on_path: dict[str, str], ok: set[str]):
        return {"which": lambda n: on_path.get(n),
                "isfile": lambda p: False,
                "probe": lambda exe: exe in ok}

    def test_明写版本号的名字优先于裸python3(self):
        f = self.fakes({"python3.13": "/b/python3.13", "python3": "/b/python3"},
                       {"/b/python3.13", "/b/python3"})
        self.assertEqual(bootstrap.find_modern_python(**f), "/b/python3.13")

    def test_名字撒谎的候选要被探测挡下(self):
        # python3.12 软链指向老解释器：只看名字就会换到一个同样跑不了的 Python
        f = self.fakes({"python3.12": "/b/python3.12", "python3.11": "/b/python3.11"},
                       {"/b/python3.11"})
        self.assertEqual(bootstrap.find_modern_python(**f), "/b/python3.11")

    def test_不会换成当前这个解释器(self):
        f = self.fakes({"python3": sys.executable}, {sys.executable})
        self.assertIsNone(bootstrap.find_modern_python(**f))

    def test_一个都不行时返回None而不是硬换(self):
        f = self.fakes({"python3.13": "/b/python3.13"}, set())
        self.assertIsNone(bootstrap.find_modern_python(**f))

    def test_PATH里没有时去常见位置翻(self):
        seen = bootstrap.candidates(which=lambda n: None,
                                    isfile=lambda p: p == "/opt/homebrew/bin/python3.13")
        self.assertEqual(seen, ["/opt/homebrew/bin/python3.13"])

    def test_Linux用户目录也在候选里(self):
        local = os.path.expanduser("~/.local/bin/python3.12")
        seen = bootstrap.candidates(which=lambda n: None, isfile=lambda p: p == local)
        self.assertEqual(seen, [local])

    def test_Windows安装目录在候选函数里(self):
        dirs = bootstrap.windows_extra_dirs()
        self.assertTrue(any("Programs" in d and "Python" in d and "Launcher" in d
                            for d in dirs), dirs)

    def test_解释器够新时什么都不做(self):
        self.assertGreaterEqual(sys.version_info, bootstrap.MIN_VERSION)
        bootstrap.ensure_modern_python(__file__)   # 不该 exec，也不该退出


class TestTreeHash(ProjectCase):
    def test_改一个字符哈希就变(self):
        self.make_go_project()
        cfg = self.config()
        before, n = gate.tree_hash(cfg)
        self.assertEqual(n, 2)
        (self.root / "internal/calc.go").write_text("package internal\n", encoding="utf-8")
        after, _ = gate.tree_hash(cfg)
        self.assertNotEqual(before, after)

    def test_文件数低于下限直接报错免得空哈希恒等(self):
        self.make_go_project()
        cfg = self.config(gate={"watch_roots": ["internal"], "watch_exts": [".go"],
                                "min_tree_files": 999})
        with self.assertRaises(gate.GateError):
            gate.tree_hash(cfg)

    def test_不在受监视后缀里的改动不影响哈希(self):
        self.make_go_project()
        cfg = self.config()
        before, _ = gate.tree_hash(cfg)
        self.write("internal/readme.md", "随便写点什么")
        self.assertEqual(gate.tree_hash(cfg)[0], before)

    def test_依赖与构建产物不进受监视树(self):
        # 把 node_modules 算进去，回执会在每次 npm install 后过期，
        # 而「回执已过期」这句话本该指向人改了源码
        self.make_node_project()
        self.write("node_modules/left-pad/index.js", "module.exports = 1\n")
        self.write("dist/bundle.js", "var a=1\n")
        self.write("target/generated/Gen.js", "var g=1\n")
        cfg = self.config(gate={"watch_roots": ["."], "watch_exts": [".js", ".ts"],
                                "min_tree_files": 1})
        files = [p.name for p in gate.tree_files(cfg)]
        self.assertIn("order.ts", files)
        self.assertNotIn("index.js", files)
        self.assertNotIn("bundle.js", files)
        self.assertNotIn("Gen.js", files)

    def test_嵌套的受监视根不会把同一个文件算两遍(self):
        self.make_go_project()
        cfg = self.config(gate={"watch_roots": [".", "internal"], "watch_exts": [".go"],
                                "min_tree_files": 1})
        files = gate.tree_files(cfg)
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual(len(files), 2)


class TestCommandResolution(ProjectCase):
    """Windows 上 mvn / npm 是 .cmd 批处理，CreateProcess 不查 PATHEXT。

    不解析就会 FileNotFoundError，而 doctor 用的 shutil.which 查 PATHEXT 说命令在，
    于是「体检通过、门禁说命令不存在」。两边必须用同一套解析。
    """

    WIN_EXTS = (".com", ".exe", ".bat", ".cmd")

    def exe(self, rel: str) -> None:
        p = self.write(rel, "echo hi\n")
        p.chmod(0o755)

    def test_Windows下相对路径的包装器补出cmd后缀(self):
        self.exe("mvnw.cmd")
        got = gate.resolve_cmd("./mvnw", self.root, exts=self.WIN_EXTS)
        self.assertIsNotNone(got)
        self.assertTrue(got.endswith("mvnw.cmd"))

    def test_cmd优先于同名的bash包装器(self):
        # mvnw 与 mvnw.cmd 常常并存，前者是 bash 脚本，在 Windows 上跑不起来
        self.exe("mvnw")
        self.exe("mvnw.cmd")
        got = gate.resolve_cmd("./mvnw", self.root, exts=self.WIN_EXTS)
        self.assertTrue(got.endswith("mvnw.cmd"))

    def test_非Windows下不补后缀(self):
        self.exe("mvnw")
        got = gate.resolve_cmd("./mvnw", self.root, exts=())
        self.assertTrue(got.endswith("mvnw"))

    def test_相对路径按步骤目录解析(self):
        self.exe("mod/gradlew")
        self.assertIsNotNone(gate.resolve_cmd("./gradlew", self.root / "mod", exts=()))
        self.assertIsNone(gate.resolve_cmd("./gradlew", self.root, exts=()))

    def test_没有执行位不算找到(self):
        self.write("mvnw", "echo hi\n")
        self.assertIsNone(gate.resolve_cmd("./mvnw", self.root, exts=()))

    def test_PATH里的命令解析成全路径(self):
        got = gate.resolve_cmd(Path(sys.executable).name, self.root)
        self.assertIsNotNone(got)
        self.assertTrue(Path(got).is_absolute())

    def test_Windows批处理要经cmd启动(self):
        got = gate.launch_argv(r"C:\maven\bin\mvn.cmd", ["-B", "test"], os_name="nt")
        self.assertEqual(got[1], "/c")
        self.assertTrue(got[2].lower().endswith("mvn.cmd"))
        self.assertEqual(got[3:], ["-B", "test"])
        self.assertTrue(got[0].lower().endswith("cmd.exe") or Path(got[0]).name.lower() == "cmd.exe")

    def test_POSIX不包一层cmd(self):
        self.assertEqual(gate.launch_argv("/usr/bin/mvn", ["test"], os_name="posix"),
                         ["/usr/bin/mvn", "test"])

    def test_找不到的命令返回None(self):
        self.assertIsNone(
            gate.resolve_cmd("绝对不存在的命令-adone", self.root, exts=()))

    def test_命令不存在时报出命令名而不是None(self):
        # WinError 2 的 e.filename 是 None，直接打出来就是「命令不存在: None」
        cfg = self.config()
        st = gate.run_step(cfg, {"name": "mvn test", "cwd": ".",
                                 "argv": ["绝对不存在的命令-adone", "test"]})
        self.assertFalse(st.ok)
        self.assertEqual(st.exit_code, 127)
        self.assertIn("绝对不存在的命令-adone", st.note)
        self.assertNotIn("None", st.note)

    def test_步骤目录不存在时说目录而不是命令(self):
        cfg = self.config()
        st = gate.run_step(cfg, {"name": "前端测试", "cwd": "没这个目录",
                                 "argv": ["python3", "-c", "pass"]})
        self.assertFalse(st.ok)
        self.assertIn("没这个目录", st.note)

    def test_命令没跑起来时不报成解析不出测试结果(self):
        # 报「适配器不认这种输出格式」会把人引到适配器上去查，真正要修的是 PATH
        cfg = self.config()
        spec = {"name": "mvn test", "cwd": ".", "kind": "test", "adapter": "java",
                "argv": ["绝对不存在的命令-adone", "test"]}
        st = gate.run_step(cfg, spec)
        gate.judge_step(cfg, spec, st)
        self.assertFalse(st.ok)
        self.assertIn("命令不存在", st.note)
        self.assertNotIn("解析不出", st.note)

    def test_启动失败的原因不进回执字段(self):
        cfg = self.config()
        st = gate.run_step(cfg, {"name": "x", "cwd": ".", "argv": ["不存在-adone"]})
        self.assertNotIn("launch_error", st.as_receipt())

    def test_体检与门禁对命令的判断一致(self):
        import argparse
        import io
        from contextlib import redirect_stdout

        from actuallydone.detect import cmd_doctor
        self.make_go_project()
        self.write("adone.toml", "version = 1\n")
        cfg = self.config(gate={
            "watch_roots": ["internal"], "watch_exts": [".go"], "min_tree_files": 1,
            "step": [{"name": "mvn test", "cwd": ".",
                      "argv": ["绝对不存在的命令-adone", "test"], "kind": "test"}]})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_doctor(cfg, argparse.Namespace())
        self.assertNotEqual(rc, 0)
        self.assertIn("绝对不存在的命令-adone", buf.getvalue())


class TestStepJudging(ProjectCase):
    def test_格式化步骤有输出即失败哪怕退出码为零(self):
        cfg = self.config()
        st = gate.Step(name="fmt", cwd=".", argv=["x"])
        st.exit_code, st.ok, st.stdout = 0, True, "internal/a.go\n"
        gate.judge_step(cfg, {"kind": "fmt"}, st)
        self.assertFalse(st.ok)

    def test_测试输出里出现失效标记时判证据无效(self):
        cfg = self.config()
        st = gate.Step(name="test", cwd=".", argv=["x"])
        st.exit_code, st.ok = 0, True
        st.stdout = "--- PASS: TestA (0.01s)\n需要 MySQL，跳过\nok\n"
        gate.judge_step(cfg, {"kind": "test", "adapter": "go",
                              "invalid_marks": ["需要 MySQL"]}, st)
        self.assertFalse(st.ok)
        self.assertIn("证据无效", st.note)

    def test_解析不出测试结果不算通过(self):
        cfg = self.config()
        st = gate.Step(name="test", cwd=".", argv=["x"])
        st.exit_code, st.ok, st.stdout = 0, True, "ok  fixture  0.2s\n"
        gate.judge_step(cfg, {"kind": "test", "adapter": "go"}, st)
        self.assertFalse(st.ok)

    def test_端口冲突写进步骤note(self):
        cfg = self.config()
        st = gate.Step(name="test", cwd=".", argv=["x"])
        st.exit_code, st.ok = 1, False
        st.stdout = "Port 8080 was already in use.\nTests run: 1, Failures: 1, Errors: 0, Skipped: 0\n"
        gate.judge_step(cfg, {"kind": "test", "adapter": "java"}, st)
        self.assertFalse(st.ok)
        self.assertIn("8080", st.note)
        self.assertIn("RANDOM_PORT", st.note)

    def test_coverage_source对不上时仍能从磁盘报告读覆盖率(self):
        from tests.helpers import JAVA_JACOCO_XML
        self.write("reports/jacoco.xml", JAVA_JACOCO_XML)
        cfg = self.config(project={"ecosystems": ["java"]},
                          tests={"adapter": "java", "roots": ["."]},
                          coverage={"threshold": 80.0, "source": "并不存在的步骤"})
        self.assertEqual(gate._coverage_from_disk(cfg), 85.0)

    def test_读不到覆盖率时点名断在哪一环(self):
        """「没解析到覆盖率数字」本身没有信息量：没装插件、没跑 report、探针没挂上、
        测试整批被跳过，处理办法完全不同。"""
        self.write("pom.xml", "<project/>")
        cfg = self.config(project={"ecosystems": ["java"]},
                          tests={"adapter": "java", "roots": ["."]},
                          coverage={"threshold": 80.0, "source": "mvn test"})
        st = gate.Step(name="mvn test", cwd=".", argv=["mvn", "test"])
        st.stdout = ("[INFO] Skipping JaCoCo execution due to missing execution "
                     "data file.\n[INFO] BUILD SUCCESS\n")
        note = gate._coverage_missing_note(cfg, [st], "mvn test")
        self.assertIn("prepare-agent", note)

    def test_java适配器能解析mvn_test输出(self):
        cfg = self.config()
        st = gate.Step(name="mvn test", cwd=".", argv=["mvn", "test"])
        st.exit_code, st.ok, st.stdout = 0, True, (
            "Tests run: 2, Failures: 0, Errors: 0, Skipped: 0\n")
        st.started_at = 0
        res = gate.judge_step(cfg, {"kind": "test", "adapter": "java"}, st)
        self.assertTrue(st.ok)
        self.assertIsNotNone(res)
        self.assertEqual(res.passed, 2)


class TestContracts(ProjectCase):
    def receipt(self, names) -> dict:
        return {"id": "x", "created_at": "now", "ok": True,
                "tests": {"passed_names": names}}

    def contract(self, body: str) -> Config:
        cfg = self.config()
        cfg.acceptance_dir.mkdir(parents=True)
        (cfg.acceptance_dir / "t.toml").write_text(body, encoding="utf-8")
        return cfg

    def test_用例不存在时报错(self):
        self.make_go_project()
        cfg = self.contract('task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestNotThere"\n')
        problems = contracts.check_contracts(cfg, self.receipt(["TestAdd"]))
        self.assertTrue(any("根本不存在" in p for p in problems))

    def test_用例存在但没跑过时报错(self):
        self.make_go_project()
        cfg = self.contract('task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n')
        problems = contracts.check_contracts(cfg, self.receipt(["TestSkipped"]))
        self.assertTrue(any("通过名单" in p for p in problems))

    def test_子用例名能对上顶层用例(self):
        self.make_go_project()
        cfg = self.contract('task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n')
        self.assertEqual(contracts.check_contracts(cfg, self.receipt(["TestAdd/子用例"])), [])

    def test_impl行号越界时报错(self):
        self.make_go_project()
        cfg = self.contract('task = "t"\n[[item]]\n"要求" = "x"\ntest = "TestAdd"\n'
                            'impl = "internal/calc.go:9999"\n')
        problems = contracts.check_contracts(cfg, self.receipt(["TestAdd"]))
        self.assertTrue(any("行号越界" in p for p in problems))

    def test_契约本身写坏了算不通过(self):
        self.make_go_project()
        cfg = self.contract('要求 = "中文裸键会解析失败"\n')
        problems = contracts.check_contracts(cfg, self.receipt(["TestAdd"]))
        self.assertTrue(any("解析失败" in p for p in problems))


class TestIntegrity(ProjectCase):
    def base(self) -> Config:
        self.make_go_project()
        cfg = self.config()
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        integrity.write_baseline(cfg, integrity.scan(cfg), "建立初始基线")
        return cfg

    def test_删用例会被点名(self):
        cfg = self.base()
        (self.root / "internal/calc_test.go").write_text(
            "package internal\n\nimport \"testing\"\n\n"
            "func TestAdd(t *testing.T) { if Add(1,2)!=3 { t.Fatal(\"x\") } }\n",
            encoding="utf-8")
        problems = integrity.compare(cfg, integrity.scan(cfg),
                                     integrity.load_baseline(cfg))
        self.assertTrue(any("用例消失" in p for p in problems))

    def test_新增跳过会被点名(self):
        cfg = self.base()
        p = self.root / "internal/calc_test.go"
        p.write_text(p.read_text() + '\nfunc TestMore(t *testing.T) { t.Skip("懒得跑") }\n',
                     encoding="utf-8")
        problems = integrity.compare(cfg, integrity.scan(cfg),
                                     integrity.load_baseline(cfg))
        self.assertTrue(any("跳过标记" in p for p in problems))

    def test_下调覆盖率下限会被点名(self):
        self.make_go_project()
        cfg = self.config(coverage={"threshold": 85.0})
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        integrity.write_baseline(cfg, integrity.scan(cfg), "初始")
        loose = self.config(coverage={"threshold": 60.0})
        problems = integrity.compare(loose, integrity.scan(loose),
                                     integrity.load_baseline(cfg))
        self.assertTrue(any("覆盖率下限" in p for p in problems))

    def test_没有基线时不放行(self):
        self.make_go_project()
        cfg = self.config()
        problems = integrity.integrity_problems(cfg, None)
        self.assertTrue(any("建立初始基线" in p for p in problems))

    def test_坏基线不当成没有基线(self):
        self.make_go_project()
        cfg = self.config()
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        cfg.baseline.write_text("{", encoding="utf-8")
        problems = integrity.integrity_problems(cfg, None)
        self.assertTrue(any("读不成" in p for p in problems))
        self.assertFalse(any("建立初始基线" in p for p in problems))
        cfg.baseline.write_text('{"reason": "不是基线"}\n', encoding="utf-8")
        problems = integrity.integrity_problems(cfg, None)
        self.assertTrue(any("不像一份基线" in p for p in problems))
        self.assertFalse(any("建立初始基线" in p for p in problems))

    def test_扫不到用例时报错而不是判无松动(self):
        cfg = self.config(tests={"adapter": "go", "roots": ["不存在"]})
        problems = integrity.integrity_problems(cfg, None)
        self.assertTrue(any("一个用例都没扫到" in p for p in problems))


class TestAnchors(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.make_go_project()
        self.write("migrate/migrate.go",
                   '-- 注释里谈论 CREATE TABLE 不该被当成表\n'
                   'CREATE TABLE IF NOT EXISTS `orders` (id int);\n'
                   'CREATE TABLE users (id int);\n')
        self.cfg = self.config(requirements={"tables_from": "migrate/migrate.go"})
        self.idx = ledger.build_anchor_index(self.cfg)

    def test_表锚点(self):
        self.assertEqual(ledger.verify_anchor(self.cfg, "table:orders", self.idx)[0], "")
        sev, msg = ledger.verify_anchor(self.cfg, "table:ghost", self.idx)
        self.assertEqual(sev, "错误")

    def test_注释行不该被当成建表(self):
        self.assertNotIn("CREATE", " ".join(self.idx["tables"]))
        self.assertEqual(self.idx["tables"], {"orders", "users"})

    def test_用例锚点核到源码(self):
        self.assertEqual(ledger.verify_anchor(self.cfg, "test:TestAdd", self.idx)[0], "")
        self.assertEqual(ledger.verify_anchor(self.cfg, "test:TestGhost", self.idx)[0], "错误")

    def test_没配来源的锚点报无法核验而不是通过(self):
        sev, msg = ledger.verify_anchor(self.cfg, "route:/x", self.idx)
        self.assertEqual(sev, "警告")
        self.assertIn("无法核验", msg)

    def test_未知锚点类型(self):
        sev, _ = ledger.verify_anchor(self.cfg, "臆造:x", self.idx)
        self.assertEqual(sev, "警告")
