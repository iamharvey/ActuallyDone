"""stop 钩子的端到端：渲染出真钩子，起真进程跑。

不测「逻辑的复制品」——这里出问题的历史全在渲染与运行环境上（占位符没替、
钩子进程的 PATH 里没有 adone），把逻辑抄进用例再断言，正好把出事的那段绕过去。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from argparse import Namespace
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from actuallydone import install
from tests.helpers import ProjectCase

TEMPLATE = install.TEMPLATES / "hooks" / "gate-guard.py"

STUB = """#!/usr/bin/env python3
import os, sys
open(os.environ["ADONE_STUB_MARKER"], "a").write(" ".join(sys.argv[1:]) + "\\n")
sys.stdout.write({PAYLOAD})
"""


class TestHookResolution(ProjectCase):
    def make_stub(self, payload: dict) -> Path:
        """一个假 adone：记下自己被调用过，然后吐一份 gate check 的 JSON。"""
        d = self.root / "fakebin"
        d.mkdir(parents=True, exist_ok=True)
        stub = d / "adone"
        stub.write_text(STUB.replace("{PAYLOAD}", repr(json.dumps(payload))),
                        encoding="utf-8")
        stub.chmod(0o755)
        return stub

    def render_hook(self, path_with_adone: str = "") -> Path:
        """按安装时的 PATH 渲染钩子：ADONE_CMD 就是那一刻 which adone 的结果。"""
        old = os.environ["PATH"]
        os.environ["PATH"] = path_with_adone or "/nonexistent-adone-dir"
        try:
            v = install.variables(self.config())
        finally:
            os.environ["PATH"] = old
        hook = self.root / "hooks" / "gate-guard.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(install.render(TEMPLATE.read_text(encoding="utf-8"), v),
                        encoding="utf-8")
        hook.chmod(0o755)
        return hook

    def run_hook(self, hook: Path, path: str) -> dict:
        """钩子进程的环境由客户端定，这里显式给一个：HOME 指到临时目录，
        免得本机 ~/.local/bin 里真装着的 adone 让「找不到」那条用例假绿。"""
        env = {"PATH": path, "HOME": str(self.root / "home"),
               "CURSOR_PROJECT_DIR": str(self.root),
               "ADONE_STUB_MARKER": str(self.root / "called.txt")}
        proc = subprocess.run([sys.executable, str(hook)], input='{"status":"completed"}',
                              capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_门禁通过时钩子放行(self):
        self.make_go_project()
        stub = self.make_stub({"ok": True, "receipt_id": "R-1"})
        hook = self.render_hook(str(stub.parent))
        # 运行时 PATH 里没有 adone，靠安装时烧进去的 ADONE_CMD 找到它
        self.assertEqual(self.run_hook(hook, "/usr/bin:/bin"), {})
        self.assertIn("gate check --json", (self.root / "called.txt").read_text())

    def test_门禁不通过时钩子把问题清单推回来(self):
        self.make_go_project()
        stub = self.make_stub({"ok": False, "problems": ["回执比代码旧", "契约缺 2 条"]})
        hook = self.render_hook(str(stub.parent))
        got = self.run_hook(hook, "/usr/bin:/bin")
        msg = got["followup_message"]
        self.assertIn("回执比代码旧", msg)
        self.assertIn("契约缺 2 条", msg)

    def test_到处都找不到adone时必须回推而不是放行(self):
        """最危险的一格：空输出在终端里和「门禁通过」长得一模一样。"""
        self.make_go_project()
        hook = self.render_hook()                       # 装的时候就没有 adone
        got = self.run_hook(hook, "/nonexistent-adone-dir")
        self.assertIn("followup_message", got, "找不到 adone 却放行了")
        self.assertIn("找不到 adone", got["followup_message"])
        self.assertIn("不等于门禁通过", got["followup_message"])

    def test_hooks_only只碰钩子不碰技能(self):
        """--force --only 曾把技能里的项目私货冲掉过；重渲钩子不该有这个副作用。"""
        self.make_go_project()
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(install.cmd_install(self.config(), _args(hooks_only=True,
                                                                     dry_run=True)), 0)
        said = buf.getvalue()
        self.assertTrue("gate-guard" in said or "hooks.json" in said, said)
        self.assertIn("hooks.json", said)
        self.assertNotIn("SKILL.md", said)

    def test_hooks_only配only时报错而不是静默忽略(self):
        """静默吞掉用户明确给出的参数，是这个工具最不该犯的错。"""
        self.make_go_project()
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            rc = install.cmd_install(self.config(),
                                     _args(hooks_only=True, only="completion-gate"))
        self.assertEqual(rc, 2)
        self.assertIn("没有意义", err.getvalue())


def _args(**over) -> Namespace:
    base = dict(skills_dir=None, only=None, force=True, dry_run=False,
                with_hooks=False, hooks_only=False, target="cursor")
    base.update(over)
    return Namespace(**base)


class TestMarkDirty(ProjectCase):
    """afterFileEdit 钩子：它记不下东西时，dirty 为空和「仓库没被改过」长得一样。

    这个钩子早先是 bash + jq，在 Windows 上根本起不来。现在是 Python，
    起进程时也只用 sys.executable，不再假设机器上有 bash。
    """

    def render(self, **cfg_over) -> Path:
        cfg = self.config(**cfg_over)
        src = install.TEMPLATES / "hooks" / "mark-dirty.py"
        hook = self.root / "hooks" / "mark-dirty.py"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(install.render(src.read_text(encoding="utf-8"),
                                       install.variables(cfg)), encoding="utf-8")
        return hook

    def fire(self, hook: Path, file_path: str) -> None:
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        proc = subprocess.run([sys.executable, str(hook)],
                              input=json.dumps({"file_path": file_path}),
                              capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "{}")   # 钩子不该把会话卡死

    def dirty(self) -> str:
        p = self.root / ".adone" / "dirty"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def test_受监视根是点号时也要记下改动(self):
        """adone init 对单模块项目生成的就是 watch_roots = ["."]，
        而按 "./*" 匹配时一个文件都对不上，dirty 于是永远为空。"""
        self.make_go_project()
        hook = self.render(gate={"watch_roots": ["."], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal/calc.go"))
        self.assertIn("internal/calc.go", self.dirty())

    def test_受监视根是子目录时按前缀匹配(self):
        self.make_go_project()
        self.write("other/x.go", "package other\n")
        hook = self.render(gate={"watch_roots": ["internal"], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal/calc.go"))
        self.fire(hook, str(self.root / "other/x.go"))
        self.assertIn("internal/calc.go", self.dirty())
        self.assertNotIn("other/x.go", self.dirty())

    def test_不在受监视后缀里的文件不记(self):
        self.make_go_project()
        self.write("internal/readme.md", "随便写点什么")
        hook = self.render(gate={"watch_roots": ["."], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal/readme.md"))
        self.assertEqual(self.dirty(), "")

    def test_Windows风格的反斜杠路径也能对上(self):
        """Cursor 在 Windows 上给的 file_path 是反斜杠，而受监视根写的是正斜杠。"""
        self.make_go_project()
        hook = self.render(gate={"watch_roots": ["internal"], "watch_exts": [".go"]})
        self.fire(hook, str(self.root / "internal" / "calc.go").replace("/", os.sep))
        self.assertIn("internal/calc.go", self.dirty())

    def test_仓库外的文件不算(self):
        self.make_go_project()
        hook = self.render(gate={"watch_roots": ["."], "watch_exts": [".go"]})
        self.fire(hook, "/etc/somewhere/else.go")
        self.assertEqual(self.dirty(), "")

    def test_payload坏了也要留痕而不是静默(self):
        self.make_go_project()
        hook = self.render()
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        proc = subprocess.run([sys.executable, str(hook)], input="不是 JSON",
                              capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.dirty(), "")
        log = (self.root / ".adone" / "hook.log").read_text(encoding="utf-8")
        self.assertIn("读不动 payload", log)

    def test_带BOM的payload也能记下(self):
        """Windows 上 Cursor 喂给钩子的 JSON 有时带 UTF-8 BOM，不剥掉就解析失败。"""
        self.make_go_project()
        hook = self.render(gate={"watch_roots": ["."], "watch_exts": [".go"]})
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        payload = "\ufeff" + json.dumps({"file_path": str(self.root / "internal/calc.go")})
        proc = subprocess.run([sys.executable, str(hook)], input=payload,
                              capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("internal/calc.go", self.dirty())


class TestHooksJson(ProjectCase):
    def test_合并而不是冲掉别人的钩子(self):
        """整份覆盖会把用户自己配的钩子一起删掉，而它们失效同样是无声的。"""
        mine = {"version": 1, "hooks": {
            "beforeShellExecution": [{"command": "./my-guard.sh"}],
            "stop": [{"command": "./my-stop.sh"}],
        }}
        merged, kept = install.merge_hooks(mine)
        self.assertEqual(kept, 2)
        foreign = [h["command"] for h in merged["hooks"]["beforeShellExecution"]]
        self.assertEqual(foreign[0], "./my-guard.sh")
        self.assertTrue(any("commit-guard" in c for c in foreign), foreign)
        cmds = [h["command"] for h in merged["hooks"]["stop"]]
        self.assertEqual(cmds[0], "./my-stop.sh")
        self.assertIn("gate-guard", cmds[1])

    def test_重装不会把自己的条目叠成两份(self):
        once, _ = install.merge_hooks({})
        twice, kept = install.merge_hooks(once)
        self.assertEqual(twice, once)
        self.assertEqual(kept, 0)

    def test_登记的命令在本机是可执行的而不是打开文件(self):
        """Windows 上登记 .py 会被当成打开文件（每次弹出 gate-guard.py）。
        POSIX 上登记显式解释器，不靠 shebang。"""
        merged, _ = install.merge_hooks({})
        want = {"sessionStart": "mark-dirty", "afterFileEdit": "mark-dirty",
                "afterTabFileEdit": "mark-dirty", "postToolUse": "mark-dirty",
                "stop": "gate-guard", "beforeShellExecution": "commit-guard"}
        for event, name in want.items():
            cmd = merged["hooks"][event][-1]["command"]
            self.assertNotIn(".py", cmd)
            self.assertIn(name, cmd)
            if os.name == "nt":
                self.assertEqual(cmd, f".cursor/hooks/{name}.exe")
                self.assertFalse(install.windows_hook_never_starts(cmd))
        self.assertEqual(merged["hooks"]["beforeShellExecution"][-1]["matcher"],
                         r"git\s+commit|--accept-baseline|waive-tests|\bpolicy\b")

    def test_旧版bash钩子会被摘掉(self):
        old = {"version": 1, "hooks": {
            "afterFileEdit": [{"command": ".cursor/hooks/mark-dirty.sh", "timeout": 10}]}}
        merged, kept = install.merge_hooks(old)
        self.assertEqual(kept, 0)
        blob = json.dumps(merged, ensure_ascii=False)
        self.assertNotIn("mark-dirty.sh", blob)
        self.assertTrue("mark-dirty" in blob)

    def test_Windows下登记py等于打开文件(self):
        """Java 团队的「每次弹出 gate-guard.py」就是这个：command 里是 .py，
        Windows 按文件关联用 Cursor 打开它，脚本一行都没跑。"""
        self.assertTrue(install.windows_opens_hook_as_file(
            ".cursor/hooks/gate-guard.py"))
        self.assertTrue(install.windows_opens_hook_as_file(
            "cmd /c py -3 .cursor/hooks/gate-guard.py"))
        self.assertTrue(install.windows_opens_hook_as_file(
            "python3 .cursor/hooks/mark-dirty.py"))
        self.assertFalse(install.windows_opens_hook_as_file(
            ".cursor/hooks/gate-guard.cmd"))
        self.assertFalse(install.windows_opens_hook_as_file(
            "cmd /c .cursor\\hooks\\gate-guard.cmd"))
        self.assertFalse(install.windows_opens_hook_as_file(
            "cmd /c adone hook gate-guard"))
        self.assertFalse(install.windows_opens_hook_as_file(
            "python3 ./somebody-else.py"))

    def test_cmd路径等于CreateProcess起不来(self):
        """终端里手跑 .cmd 可以（壳转给 cmd.exe）。Cursor 直接 CreateProcess 不行。"""
        self.assertTrue(install.windows_hook_never_starts(
            r"cmd /c .cursor\hooks\gate-guard.cmd"))
        self.assertTrue(install.windows_hook_never_starts(
            "cmd /c .cursor/hooks/gate-guard.cmd"))
        self.assertTrue(install.windows_hook_never_starts(
            ".cursor/hooks/gate-guard.cmd"))
        self.assertFalse(install.windows_hook_never_starts(
            ".cursor/hooks/gate-guard.exe"))
        self.assertFalse(install.windows_hook_never_starts(
            "python3 -m actuallydone hook gate-guard"))

    def test_会摘掉把py当命令的旧登记(self):
        old = {"version": 1, "hooks": {
            "stop": [{"command": "cmd /c py -3 .cursor/hooks/gate-guard.py",
                      "timeout": 120}]}}
        merged, kept = install.merge_hooks(old)
        self.assertEqual(kept, 0)
        cmd = merged["hooks"]["stop"][0]["command"]
        self.assertNotIn(".py", cmd)
        self.assertIn("gate-guard", cmd)
        self.assertFalse(install.windows_hook_never_starts(cmd))
        if os.name == "nt":
            self.assertEqual(cmd, ".cursor/hooks/gate-guard.exe")


class TestInstallFailsLoud(ProjectCase):
    def test_写不进去时给人话而不是堆栈(self):
        self.make_go_project()
        skills = self.root / "只读技能目录"
        skills.mkdir()
        skills.chmod(0o500)
        self.addCleanup(skills.chmod, 0o700)
        err, out = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = install.cmd_install(self.config(), _args(skills_dir=str(skills)))
        self.assertEqual(rc, 1)
        said = err.getvalue()
        self.assertIn("写不进去", said)
        self.assertIn("安装没有完成", said)
        self.assertNotIn("Traceback", said)


class TestDoctorChecksHooks(ProjectCase):
    """钩子失效时，doctor 是唯一有机会说话的地方。"""

    def install_hooks(self, **cfg_over):
        cfg = self.config(**cfg_over)
        with redirect_stdout(StringIO()):
            install.cmd_install(cfg, _args(hooks_only=True))
        return cfg

    def test_没装钩子不算问题(self):
        self.make_go_project()
        lines, problems = install.hooks_report(self.config())
        self.assertEqual(problems, [])
        self.assertIn("未安装", lines[0])

    def test_钩子找不到adone时报出来(self):
        self.make_go_project()
        cfg = self.install_hooks()
        old = os.environ["PATH"]
        os.environ["PATH"] = str(self.root / "空目录")
        os.environ["HOME"] = str(self.root / "空家")
        try:
            _, problems = install.hooks_report(cfg)
        finally:
            os.environ["PATH"] = old
        # 本机 /opt/homebrew/bin 若装着 adone，兜底仍能找到——那时这条就不该报
        if not any(Path(d).expanduser().joinpath("adone").is_file()
                   for d in ("/opt/homebrew/bin", "/usr/local/bin")):
            self.assertTrue(any("找不到 adone" in p for p in problems), problems)

    def test_钩子命令里的解释器找不到时报出来(self):
        """钩子起不来的样子就是「什么都不发生」，doctor 是唯一有机会说话的地方。
        以前这里只查可执行位，而 os.access(X_OK) 在 Windows 上恒为真。"""
        self.make_go_project()
        cfg = self.install_hooks()
        hooks_json = self.root / ".cursor" / "hooks.json"
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        data["hooks"]["stop"][0]["command"] = "绝不存在的解释器 .cursor/hooks/gate-guard.py"
        hooks_json.write_text(json.dumps(data), encoding="utf-8")
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("绝不存在的解释器" in p for p in problems), problems)

    def test_没有git_pre_commit时点名(self):
        """Cursor 钩子只看得见 Agent 跑的 shell。你自己在终端敲的 git commit
        只有 .git/hooks/pre-commit 拦得住，它不在就是「安静地不设防」。"""
        self.make_go_project()
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        cfg = self.install_hooks()
        (self.root / ".git" / "hooks" / "pre-commit").unlink()
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("pre-commit" in p and "全量门禁" in p for p in problems),
                        problems)

    def test_hooks_json里没有commit_guard时点名(self):
        """v1.3.14 之前装的登记没有 beforeShellExecution：Agent 提交时没人拦，
        而 hook.log 里连一行都不会出现，看上去和「一切正常」一样。"""
        self.make_go_project()
        cfg = self.install_hooks()
        hooks_json = self.root / ".cursor" / "hooks.json"
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        data["hooks"].pop("beforeShellExecution", None)
        hooks_json.write_text(json.dumps(data), encoding="utf-8")
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("commit-guard" in p for p in problems), problems)

    def test_残留的py会被点名(self):
        """Windows 上这个文件就是每次弹出来的那个。重渲必须删掉它。"""
        self.make_go_project()
        cfg = self.install_hooks()
        leftover = self.root / ".cursor" / "hooks" / "gate-guard.py"
        leftover.write_text("# leftover\n", encoding="utf-8")
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("gate-guard.py" in p and "打开" in p for p in problems), problems)

    def test_还登记着旧版bash钩子要报出来(self):
        self.make_go_project()
        cfg = self.install_hooks()
        hooks_json = self.root / ".cursor" / "hooks.json"
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        data["hooks"]["afterFileEdit"] = [{"command": ".cursor/hooks/mark-dirty.sh"}]
        hooks_json.write_text(json.dumps(data), encoding="utf-8")
        _, problems = install.hooks_report(cfg)
        self.assertTrue(any("旧版 mark-dirty.sh" in p for p in problems), problems)

    def test_会写出Windows启动器且不写py(self):
        self.make_go_project()
        self.install_hooks()
        self.assertFalse((self.root / ".cursor" / "hooks" / "gate-guard.py").exists())
        if os.name != "nt":
            for name in ("mark-dirty.cmd", "gate-guard.cmd", "commit-guard.cmd"):
                self.assertFalse((self.root / ".cursor" / "hooks" / name).exists(), name)
            return
        for name in ("mark-dirty.cmd", "gate-guard.cmd", "commit-guard.cmd"):
            p = self.root / ".cursor" / "hooks" / name
            self.assertTrue(p.is_file(), name)
            text = p.read_text(encoding="utf-8")
            self.assertIn("hook %NAME%", text)
            self.assertIn('<<"::::"', text)
            self.assertIn("launched via sh", text)
            self.assertIn("hook.log", text)
            self.assertNotIn("gate-guard.py", text)
            self.assertNotIn(b"\r\n", p.read_bytes(), "LF：Git Bash 的 heredoc 遇 CRLF 合不上")

    def test_posix重渲会删掉误装的cmd(self):
        if os.name == "nt":
            self.skipTest("这条只覆盖 macOS/Linux 误装 .cmd")
        self.make_go_project()
        hooks = self.root / ".cursor" / "hooks"
        hooks.mkdir(parents=True)
        leftover = hooks / "gate-guard.cmd"
        leftover.write_text("@echo off\n", encoding="utf-8")
        self.install_hooks()
        self.assertFalse(leftover.exists())

    def test_启动器在bash下也能写出hooklog(self):
        """Cursor 在 Windows 上可能用 Git Bash 起钩子。纯 cmd 文件第一行就死，
        所以 1.3.6 的 .adone 里没有 hook.log。"""
        self.make_go_project()
        hook = self.root / ".cursor" / "hooks" / "mark-dirty.cmd"
        hook.parent.mkdir(parents=True)
        launcher = install.render(
            (install.TEMPLATES / "hooks" / "hook-launch.cmd").read_text(encoding="utf-8"),
            {"ADONE_CMD_WIN": ""})
        install._write_lf(hook, launcher)
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        proc = subprocess.run(["bash", str(hook)], input="{}",
                              capture_output=True, text=True, env=env, cwd=self.root)
        log = (self.root / ".adone" / "hook.log").read_text(encoding="utf-8")
        self.assertIn("launched via sh", log)
        # 写日志在 exec adone 之前。PATH 上可能是没有 hook 子命令的旧版，
        # 那一截失败不影响「bash 能跑到写 hook.log」这条回归。
        if proc.returncode == 0:
            self.assertEqual(proc.stdout.strip(), "{}")

    def test_安装会复制exe启动器(self):
        if os.name != "nt":
            self.skipTest("exe 启动器只在 Windows 上复制")
        self.make_go_project()
        scripts = self.root / "pipx" / "venvs" / "actuallydone" / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "adone.exe").write_bytes(b"MZ")
        old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(self.root)
        try:
            self.install_hooks()
        finally:
            if old is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old
        self.assertEqual(
            (self.root / ".cursor" / "hooks" / "gate-guard.exe").read_bytes(),
            b"MZ")
        self.assertEqual(
            (self.root / ".cursor" / "hooks" / "mark-dirty.exe").read_bytes(),
            b"MZ")
        self.assertEqual(
            (self.root / ".cursor" / "hooks" / "commit-guard.exe").read_bytes(),
            b"MZ")

    def test_重渲会删掉残留的py(self):
        self.make_go_project()
        hooks = self.root / ".cursor" / "hooks"
        hooks.mkdir(parents=True)
        leftover = hooks / "gate-guard.py"
        leftover.write_text("# leftover\n", encoding="utf-8")
        self.install_hooks()
        self.assertFalse(leftover.exists())


ADONE = Path(__file__).resolve().parent.parent / "bin" / "adone"


class TestHookrun(ProjectCase):
    """钩子逻辑在包里：Windows 上 .cursor/hooks/ 不再放 .py。"""

    def fire(self, name: str, payload: dict) -> dict:
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        proc = subprocess.run(
            [sys.executable, str(ADONE), "hook", name],
            input=json.dumps(payload), capture_output=True, text=True,
            env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def test_mark_dirty记下受监视文件(self):
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n")
        got = self.fire("mark-dirty",
                        {"file_path": str(self.root / "internal/calc.go")})
        self.assertEqual(got, {})
        self.assertIn("internal/calc.go",
                      (self.root / ".adone" / "dirty").read_text(encoding="utf-8"))

    def fire_bytes(self, name: str, data: bytes) -> dict:
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(self.root))
        proc = subprocess.run(
            [sys.executable, str(ADONE), "hook", name],
            input=data, capture_output=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return json.loads(proc.stdout.decode("utf-8"))

    def _watch_go(self) -> None:
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n")

    def _dirty(self) -> str:
        p = self.root / ".adone" / "dirty"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def test_mark_dirty按字节读不受本机代码页影响(self):
        """中文 Windows 上 sys.stdin 按 cp936 解 UTF-8，双字节前导会吞掉 JSON 的引号。"""
        self._watch_go()
        payload = {"hook_event_name": "afterFileEdit",
                   "file_path": str(self.root / "internal/calc.go"),
                   "edits": [{"old_string": "账户余额不足，拒绝下单",
                              "new_string": "账户余额不足：拒绝下单并记账"}]}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.assertEqual(self.fire_bytes("mark-dirty", data), {})
        self.assertIn("internal/calc.go", self._dirty())

    def test_mark_dirty在payload解不动时仍捞出路径(self):
        """截断、引号被吞：JSON 解不动，但路径是 ASCII，还在原文里，必须记下。"""
        self._watch_go()
        payload = {"hook_event_name": "afterFileEdit",
                   "file_path": str(self.root / "internal/calc.go"),
                   "edits": [{"new_string": "账户余额不足，拒绝下单"}]}
        good = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        truncated = good[:-12]
        swallowed = good.replace(b'"edits"', b'edits"')
        for broken in (truncated, swallowed):
            (self.root / ".adone" / "dirty").unlink(missing_ok=True)
            with self.assertRaises(ValueError):
                json.loads(broken.decode("utf-8", "replace"))
            self.assertEqual(self.fire_bytes("mark-dirty", broken), {})
            self.assertIn("internal/calc.go", self._dirty(), broken[:40])

    def test_mark_dirty认BOM与UTF16与多段JSON(self):
        self._watch_go()
        one = json.dumps({"file_path": str(self.root / "internal/calc.go")})
        two = json.dumps({"file_path": str(self.root / "internal/calc_test.go")})
        for data in (b"\xef\xbb\xbf" + one.encode("utf-8"),
                     one.encode("utf-16"),
                     (one + "\n" + two).encode("utf-8")):
            (self.root / ".adone" / "dirty").unlink(missing_ok=True)
            self.assertEqual(self.fire_bytes("mark-dirty", data), {})
            self.assertIn("internal/calc.go", self._dirty(), data[:16])

    def test_mark_dirty认filePath与嵌套tool_input(self):
        """Cursor 有的版本给 filePath / tool_input.path，只认 file_path 就永远记不下。"""
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n")
        p = str(self.root / "internal/calc.go")
        for payload in (
            {"filePath": p, "hook_event_name": "afterFileEdit"},
            {"path": p},
            {"tool_input": {"path": p}, "tool_name": "Write"},
            {"file_path": "file://" + p},
            {"edits": [{"file_path": p, "old_string": "a", "new_string": "b"}]},
        ):
            dest = self.root / ".adone" / "dirty"
            dest.unlink(missing_ok=True)
            self.assertEqual(self.fire("mark-dirty", payload), {})
            self.assertIn("internal/calc.go", dest.read_text(encoding="utf-8"), payload)

    def test_mark_dirty_sessionStart不报警(self):
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n")
        self.assertEqual(self.fire("mark-dirty", {"hook_event_name": "sessionStart"}), {})
        self.assertFalse((self.root / ".adone" / "dirty").exists())
        log = (self.root / ".adone" / "hook.log").read_text(encoding="utf-8")
        self.assertIn("跳过", log)
        self.assertNotIn("改动没记下", log)

    def test_gate_guard父仓库路径剥前缀后仍跑changed(self):
        """demo/app 嵌在父 git 里时，status 是 demo/app/src/x.py，要对上 watch_roots=src。"""
        app = self.root / "demo" / "app"
        (app / "src").mkdir(parents=True)
        (app / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
        (app / "adone.toml").write_text(
            "version = 1\n[project]\nname = 'f'\necosystems = ['python']\n"
            "[gate]\nwatch_roots = ['src']\nwatch_exts = ['.py']\n"
            "min_tree_files = 1\n"
            "[[gate.step]]\nname = 'py'\nkind = 'test'\nadapter = 'python'\n"
            "argv = ['python3', '-m', 'unittest', 'discover', '-v']\n"
            "[tests]\nadapter = 'python'\n",
            encoding="utf-8")
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "add", "-A"], cwd=self.root, check=True,
                        capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-m", "i"], cwd=self.root, check=True,
                        capture_output=True)
        (app / "src" / "orphan.py").write_text("def orphan():\n    return 1\n",
                                              encoding="utf-8")
        env = dict(os.environ, CURSOR_PROJECT_DIR=str(app))
        proc = subprocess.run(
            [sys.executable, str(ADONE), "hook", "gate-guard"],
            input=json.dumps({"status": "completed", "loop_count": 0}),
            capture_output=True, text=True, env=env, cwd=app)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        got = json.loads(proc.stdout)
        self.assertIn("followup_message", got)
        self.assertIn("相关用例", got["followup_message"])
        log = (app / ".adone" / "hook.log").read_text(encoding="utf-8")
        self.assertNotIn("无一受监视", log)

    def test_gate_guard无dirty但git有受监视改动则跑changed(self):
        """afterFileEdit 记不下时，stop 必须退到 git，否则改很多代码也不跑增量。"""
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "ecosystems = ['go']\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n"
                   "min_tree_files = 1\n"
                   "[[gate.step]]\nname = 'go test'\nkind = 'test'\n"
                   "adapter = 'go'\nargv = ['go', 'test', './...']\n"
                   "[tests]\nadapter = 'go'\n")
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "add", "-A"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-m", "i"], cwd=self.root, check=True,
                       capture_output=True)
        self.write("internal/orphan.go", "package internal\nfunc Orphan() {}\n")
        got = self.fire("gate-guard", {"status": "completed", "loop_count": 0})
        self.assertIn("followup_message", got)
        self.assertIn("相关用例", got["followup_message"])
        self.assertIn("--changed", got["followup_message"])

    def test_gate_guard上次changed已通过且文件未改则跳过(self):
        from actuallydone.changed import file_hashes, _write_partial
        from actuallydone.config import Config
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n"
                   "min_tree_files = 1\n")
        dest = self.root / ".adone"
        dest.mkdir(parents=True, exist_ok=True)
        dest.joinpath("dirty").write_text("internal/calc.go\n", encoding="utf-8")
        cfg = Config.load(self.root)
        hashes = file_hashes(cfg, ["internal/calc.go"])
        _write_partial(cfg, ok=True, files=["internal/calc.go"], tests=["TestAdd"],
                       argv=["go", "test"], note="ok", file_hashes=hashes)
        got = self.fire("gate-guard", {"status": "completed", "loop_count": 0})
        self.assertEqual(got, {})
        log = (self.root / ".adone" / "hook.log").read_text(encoding="utf-8")
        self.assertIn("文件未再改", log)

    def test_gate_guard无dirty不回推即使没有回执(self):
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n"
                   "min_tree_files = 1\n")
        got = self.fire("gate-guard", {"status": "completed", "loop_count": 0})
        self.assertEqual(got, {})
        self.assertFalse((self.root / ".adone" / "latest.json").exists())

    def test_gate_guard有dirty且找不到相关用例时回推且不提全量run(self):
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "ecosystems = ['go']\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n"
                   "min_tree_files = 1\n"
                   "[[gate.step]]\nname = 'go test'\nkind = 'test'\n"
                   "adapter = 'go'\nargv = ['go', 'test', './...']\n"
                   "[tests]\nadapter = 'go'\n")
        self.write("internal/orphan.go", "package internal\nfunc Orphan() {}\n")
        dest = self.root / ".adone" / "dirty"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("internal/orphan.go\n", encoding="utf-8")
        got = self.fire("gate-guard", {"status": "completed", "loop_count": 0})
        msg = got["followup_message"]
        self.assertIn("相关用例", msg)
        self.assertIn("--changed", msg)
        self.assertIn("不要", msg)
        self.assertIn("全量", msg)
        self.assertNotIn("重跑门禁", msg)

    def test_paths_from_payload覆盖常见字段(self):
        from actuallydone.hookrun import paths_from_payload
        self.assertEqual(paths_from_payload({"file_path": "/a/b.go"}), ["/a/b.go"])
        self.assertEqual(paths_from_payload({"filePath": "/a/b.go"}), ["/a/b.go"])
        self.assertEqual(paths_from_payload({"tool_input": {"path": "/a/b.go"}}),
                         ["/a/b.go"])
        self.assertEqual(
            paths_from_payload({"hook_event_name": "sessionStart"}), [])
        self.assertEqual(paths_from_payload({}), [])

    def test_ls与git_status放行且不写hook_log(self):
        self._watch_go()
        for cmd in ("ls", "git status"):
            got = self.fire("commit-guard", {"command": cmd})
            self.assertEqual(got.get("permission"), "allow", cmd)
        self.assertFalse((self.root / ".adone" / "hook.log").exists())

    def test_自行放宽被拒绝(self):
        self._watch_go()
        commands = (
            "adone integrity --accept-baseline '把下限降了'",
            "python -m actuallydone policy --accept '命令变了'",
            "adone gate waive-tests '这次只改注释'",
            "adone integrity --accept-baseline x",
        )
        for cmd in commands:
            got = self.fire("commit-guard", {"tool_input": {"command": cmd}})
            self.assertEqual(got.get("permission"), "deny", cmd)
            self.assertIn("自己销账", got.get("agent_message", ""), cmd)

    def test_policy不带accept不算放宽(self):
        self._watch_go()
        got = self.fire("commit-guard", {"command": "adone policy --json"})
        self.assertEqual(got.get("permission"), "allow")
        self.assertFalse((self.root / ".adone" / "hook.log").exists())

    def test_commit消息里出现waive_tests仍按提交拦(self):
        self._watch_go()
        got = self.fire("commit-guard",
                        {"command": "git commit -m 'later waive-tests'"})
        self.assertEqual(got.get("permission"), "deny")
        self.assertIn("全量", got.get("agent_message", ""))
        self.assertNotIn("自己销账", got.get("agent_message", ""))

    def test_payload里的model写入runner_json(self):
        self._watch_go()
        self.fire("mark-dirty", {
            "file_path": str(self.root / "internal/calc.go"),
            "model": "gpt-test",
        })
        data = json.loads((self.root / ".adone" / "runner.json").read_text(
            encoding="utf-8"))
        self.assertEqual(data["model"], "gpt-test")

    def test_commit_guard非commit放行(self):
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n")
        got = self.fire("commit-guard", {"command": "git status"})
        self.assertEqual(got.get("permission"), "allow")

    def test_commit_guard回执不过则deny即使no_verify(self):
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n"
                   "min_tree_files = 1\n")
        got = self.fire("commit-guard", {"command": "git commit --no-verify -m x"})
        self.assertEqual(got.get("permission"), "deny")
        self.assertIn("全量", got.get("agent_message", ""))

    def test_回推JSON按UTF8写出(self):
        """Windows 上 stdout 默认 cp936 时，Cursor 按 UTF-8 解析会失败，
        对话里就像没回推。"""
        from io import BytesIO
        from actuallydone import hookrun

        buf = BytesIO()

        class Out:
            buffer = buf

            def flush(self):
                pass

        old = sys.stdout
        sys.stdout = Out()
        try:
            hookrun._emit({"followup_message": "【完成门禁未通过】"})
        finally:
            sys.stdout = old
        raw = buf.getvalue()
        self.assertIn("完成门禁".encode("utf-8"), raw)
        self.assertTrue(raw.endswith(b"\n"))

    def test_exe文件名就是钩子名(self):
        """Windows 上 hooks.json 只能写一条 .exe 路径，cli 按 argv[0] 分发。"""
        from actuallydone.cli import main
        self.make_go_project()
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "[gate]\nwatch_roots = ['internal']\nwatch_exts = ['.go']\n")
        old_argv, old_in = sys.argv, sys.stdin
        old_cwd = os.getcwd()
        old_proj = os.environ.get("CURSOR_PROJECT_DIR")
        sys.argv = [str(self.root / "mark-dirty.exe")]
        sys.stdin = StringIO("{}")
        os.chdir(self.root)
        os.environ["CURSOR_PROJECT_DIR"] = str(self.root)
        try:
            with redirect_stdout(StringIO()):
                rc = main([])
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
            sys.stdin = old_in
            if old_proj is None:
                os.environ.pop("CURSOR_PROJECT_DIR", None)
            else:
                os.environ["CURSOR_PROJECT_DIR"] = old_proj
        self.assertEqual(rc, 0)
        self.assertIn("launched",
                      (self.root / ".adone" / "hook.log").read_text(encoding="utf-8"))
