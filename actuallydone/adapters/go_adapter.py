"""Go 适配器。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..model import FuncBody, TestResult
from .base import (CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_SINGLE_TEST,
                   CAP_TESTS, Adapter, brace_funcs, read)

# 必须带 re.M：go test 的结果行散布在多行输出里，少了它 findall 只会看字符串开头，
# 解析出 0 个用例——而 0 个用例又长得很像「测试没跑」，会把门禁引向错误结论。
PASS_RE = re.compile(r"^\s*--- PASS: (\S+)", re.M)
FAIL_RE = re.compile(r"^\s*--- FAIL: (\S+)", re.M)
SKIP_RE = re.compile(r"^\s*--- SKIP: (\S+)", re.M)
COVER_RE = re.compile(r"coverage: ([\d.]+)% of statements")
# go tool cover -func 的汇总行。各包自己的 coverage: 不能相加，只有这一行是语句加权总数。
TOTAL_RE = re.compile(r"^total:.*\(statements\)\s+([\d.]+)%", re.M)
TESTFUNC_RE = re.compile(r"^func (Test\w+)\(", re.M)
FUNC_START = re.compile(r"^func\b")
ASSERT_WORDS = ("t.Error", "t.Fatal", "t.Errorf", "t.Fatalf", "require.", "assert.",
                "b.Error", "b.Fatal")
CHI_RE = re.compile(r'r\.(?:Get|Post|Put|Patch|Delete|Head|Options|Route|Handle)'
                    r'(?:Func)?\("([^"]*)"')


def func_name(decl: str) -> str:
    """从 func 声明行取名字，方法要跳过接收者：func (w *W) Start() -> Start。"""
    rest = decl[len("func "):].lstrip()
    if rest.startswith("("):
        depth = 0
        for i, ch in enumerate(rest):
            depth += (ch == "(") - (ch == ")")
            if depth == 0:
                rest = rest[i + 1:].lstrip()
                break
    return rest.split("(")[0].strip() or "?"


def total_percent(text: str) -> float | None:
    """从 go tool cover -func 的输出里取 total 行。没有就返回 None。"""
    found = TOTAL_RE.findall(text or "")
    if not found:
        return None
    return float(found[-1])


class GoAdapter(Adapter):
    name = "go"
    caps = {CAP_TESTS, CAP_COVERAGE, CAP_FUNCS, CAP_ROUTES, CAP_SINGLE_TEST}
    markers = ("go.mod", "*/go.mod")
    source_exts = (".go",)

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        return [
            {"name": "gofmt", "cwd": hint_dir, "argv": ["gofmt", "-l", "."],
             "kind": "fmt"},
            {"name": "go build", "cwd": hint_dir, "argv": ["go", "build", "./..."]},
            {"name": "go vet", "cwd": hint_dir, "argv": ["go", "vet", "./..."]},
            {"name": "go test", "cwd": hint_dir, "kind": "test", "adapter": "go",
             "argv": ["go", "test", "./...", "-count=1", "-v",
                      "-coverprofile={cover_out}"]},
        ]

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        return ([hint_dir], [".go"])

    # ------------------------------------------------------------ 测试

    def parse_test_output(self, text: str) -> TestResult | None:
        passed = PASS_RE.findall(text)
        failed = FAIL_RE.findall(text)
        skipped = SKIP_RE.findall(text)
        cov = COVER_RE.findall(text)
        if not (passed or failed or skipped):
            # 没有 -v 时 go test 只打 ok/FAIL，逐条数据无从谈起
            return TestResult(parsed=False)
        return TestResult(
            passed=len(passed), failed=len(failed), skipped=len(skipped),
            skip_top=len({n for n in skipped if "/" not in n}),
            passed_names=passed, failed_names=failed, skipped_names=skipped,
            # 每个包一行。两行及以上时最后一行不是总覆盖率，留空，改从 cover.out 读。
            coverage=float(cov[0]) if len(cov) == 1 else None,
        )

    def test_files(self, roots: list[Path]) -> list[Path]:
        out: list[Path] = []
        for r in roots:
            if r.is_dir():
                out.extend(sorted(r.rglob("*_test.go")))
        return out

    def test_names(self, roots: list[Path]) -> set[str] | None:
        names: set[str] = set()
        for p in self.test_files(roots):
            names |= set(TESTFUNC_RE.findall(read(p)))
        return names

    def single_test_argv(self, name: str) -> list[str] | None:
        # 子测试名（TestX/case_1）里的斜杠是 -run 的分隔符，只按顶层跑，
        # 上层核对 --- PASS 时也只认顶层，两边口径一致
        top = name.split("/")[0]
        if not top:
            return None
        return ["go", "test", "./...", "-run", f"^{top}$", "-count=1", "-v"]

    def related_tests(self, rel_paths: list[str]) -> list[str] | None:
        names: list[str] = []
        for rel in rel_paths:
            p = self.root / rel
            if p.suffix != ".go":
                continue
            target = p if p.name.endswith("_test.go") else p.with_name(p.stem + "_test.go")
            if target.is_file():
                names.extend(TESTFUNC_RE.findall(read(target)))
        return sorted(set(names))

    def related_test_argv(self, names: list[str]) -> list[str] | None:
        tops: list[str] = []
        seen: set[str] = set()
        for n in names:
            top = n.split("/")[0]
            if top and top not in seen:
                seen.add(top)
                tops.append(top)
        if not tops:
            return None
        pattern = "^(" + "|".join(re.escape(t) for t in tops) + ")$"
        return ["go", "test", "./...", "-run", pattern, "-count=1", "-v"]

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        return [f for f in brace_funcs(read(path).splitlines(), FUNC_START, func_name)
                if f.name.startswith("Test")]

    def is_assertionless(self, body: list[str]) -> bool:
        return not any(w in ln for ln in body for w in ASSERT_WORDS)

    def skip_sites(self, text: str) -> int:
        return len(re.findall(r"\bt\.Skip(?:f|Now)?\(", text))

    # ------------------------------------------------------------ 代码

    def iter_funcs(self, path: Path) -> list[FuncBody]:
        return brace_funcs(read(path).splitlines(), FUNC_START, func_name)

    def zero_cover(self, profile: Path, cwd: Path) -> tuple[int, int] | None:
        if not profile.exists():
            return None
        from ..gate import launch_argv, resolve_cmd
        exe = resolve_cmd("go", cwd) or "go"
        proc = subprocess.run(launch_argv(exe, ["tool", "cover", f"-func={str(profile)}"]),
                              cwd=cwd, capture_output=True, text=True,
                              errors="replace")
        if proc.returncode != 0:
            return None
        rows = [ln.split() for ln in proc.stdout.splitlines() if ln.strip()]
        # 末列精确比对："100.0%".endswith("0.0%") 是真，用 endswith 会把满覆盖当零覆盖
        zero = sum(1 for r in rows if r and r[-1] == "0.0%" and r[0] != "total:")
        total = sum(1 for r in rows if r and r[0] != "total:")
        return (zero, total) if total else None

    def coverage_from_reports(self, *roots: Path) -> float | None:
        """多包时 stdout 各写各的百分比。总覆盖率在 .adone/cover.out 的 total 行。"""
        for root in roots:
            if not isinstance(root, Path) or not root.is_dir():
                continue
            profile = root / ".adone" / "cover.out"
            if not profile.is_file():
                continue
            got = self._cover_total(profile, root)
            if got is not None:
                return got
        return None

    def _cover_total(self, profile: Path, cwd: Path) -> float | None:
        from ..gate import launch_argv, resolve_cmd
        exe = resolve_cmd("go", cwd)
        if not exe:
            return None
        try:
            proc = subprocess.run(
                launch_argv(exe, ["tool", "cover", f"-func={profile}"]),
                cwd=cwd, capture_output=True, text=True, errors="replace")
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        return total_percent(proc.stdout)

    def coverage_diagnosis(self, *roots: Path, output: str = "") -> str:
        n = len(COVER_RE.findall(output or ""))
        if n > 1:
            return ("go test 每个包打一行 coverage，不能把其中一行当总覆盖率。"
                    "测试命令要带 -coverprofile={cover_out}，总覆盖率从 cover.out 读。")
        return "go test 的输出里没有覆盖率。加上 -coverprofile={cover_out}。"

    def routes(self, target: Path) -> set[str] | None:
        files = sorted(target.rglob("*.go")) if target.is_dir() else [target]
        out: set[str] = set()
        for p in files:
            out |= set(CHI_RE.findall(read(p)))
        return out
