"""把 demo 拷进临时目录，渲染技能，写 Codex 钩子，跑完再做隐藏验收。

产品包不负责这件事。`adone install --ide codex` 还没有，这里直接写
`.codex/hooks.json`。钩子协议与 Qoder 相同，不改 hookrun.py。
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from actuallydone.config import Config
from actuallydone.gate import collect_check, new_tests_problems
from actuallydone.install import render, variables
from actuallydone.integrity import integrity_problems
from actuallydone.policy import policy_problems

from .guard import apply_diff
from .signals import Execution, baseline_paths, new_problems
from .taskload import REPO, Task, agent_prompt

SKILLS_SRC = REPO / "actuallydone" / "templates" / "skills"

# 这些是本轮钩子和门禁自己写的，不算 agent 改基线。
_SKIP_COPY = {
    "target", "build", "__pycache__", ".git", "node_modules", ".gradle",
}
_SKIP_FILES = {"hook.log", "partial.json", "runner.json", ".DS_Store"}

# codex exec 的参数集中在这里。check 会对照本机 --help。
CODEX_FLAGS = (
    "--json",
    "--sandbox", "workspace-write",
    "--dangerously-bypass-hook-trust",
)


@dataclass
class Job:
    task: Task
    role: str
    index: int
    run_id: str
    skills_diff: str = ""
    skills_root: Path = SKILLS_SRC


@dataclass
class Prepared:
    root: Path
    keep: bool = False
    _tmp: tempfile.TemporaryDirectory | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        if self._tmp is not None and not self.keep:
            self._tmp.cleanup()
            self._tmp = None


def codex_bin() -> str | None:
    """PATH 里的优先。没有就用仓库里 bench/.codex-cli 的本地安装。"""
    found = shutil.which("codex")
    if found:
        return found
    local = REPO / "bench" / ".codex-cli" / "node_modules" / ".bin" / "codex"
    if local.is_file():
        return str(local)
    return None


def codex_exec_argv(prompt: str, cwd: Path) -> list[str]:
    """参数以本机 `codex exec --help` 为准，集中在这一处。

    `--skip-git-repo-check` 是因为 Propose/Compose 的临时目录不是 git 仓库。
    `-C` 把工作根钉死，避免从临时目录往上走到 ActuallyDone 仓库。
    """
    binary = codex_bin() or "codex"
    return [
        binary, "exec", *CODEX_FLAGS,
        "--skip-git-repo-check",
        "-C", str(cwd),
        prompt,
    ]


def hook_shell(name: str, workspace: Path) -> str:
    """Codex 的钩子是一条 shell 命令，没有 exec 形式的 args。

    工作目录嵌进命令里：Codex 不注入项目目录环境变量，cwd 也不保证是仓库根。
    """
    return (
        f"cd {shlex.quote(str(workspace))} && "
        f"PYTHONPATH={shlex.quote(str(REPO))} "
        f"{shlex.quote(sys.executable)} -m actuallydone hook {name}"
    )


def codex_hooks(workspace: Path) -> dict:
    def leaf(name: str, timeout: int) -> dict:
        cmd = hook_shell(name, workspace)
        return {
            "type": "command",
            "command": cmd,
            "timeout": timeout,
            "commandWindows": cmd,
        }

    return {
        "hooks": {
            "PostToolUse": [{
                "matcher": "apply_patch|Edit|Write",
                "hooks": [leaf("mark-dirty", 10)],
            }],
            "Stop": [{
                "hooks": [leaf("gate-guard", 180)],
            }],
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [leaf("commit-guard", 30)],
            }],
        }
    }


def _ignore(_dir: str, names: list[str]) -> set[str]:
    skip = set()
    for name in names:
        if name in _SKIP_COPY or name in _SKIP_FILES or name.endswith(".pyc"):
            skip.add(name)
    return skip


def copy_demo(demo: Path, dest: Path) -> None:
    """拷已提交的 demo。工作区里没入库的放宽不会被算成 agent 的行为。"""
    try:
        rel = demo.resolve().relative_to(REPO.resolve())
    except ValueError:
        rel = None
    if rel is not None:
        archived = subprocess.run(
            ["git", "archive", "HEAD", "--", rel.as_posix()],
            cwd=REPO, capture_output=True,
        )
        if archived.returncode == 0 and archived.stdout:
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["tar", "-x", "-C", str(dest), "--strip-components", str(len(rel.parts))],
                input=archived.stdout, check=True,
            )
            if (dest / "adone.toml").is_file():
                return
    if not (demo / "adone.toml").is_file():
        raise FileNotFoundError(f"{demo} 里没有 adone.toml")
    shutil.copytree(demo, dest, ignore=_ignore, dirs_exist_ok=True)


def render_skills(workspace: Path, skills_root: Path, diff: str = "") -> None:
    """候选补丁先打在模板副本上，再渲染到 .agents/skills。Codex 读这里。"""
    with tempfile.TemporaryDirectory(prefix="adone-bench-skills-") as tmp:
        src = Path(tmp) / "skills"
        shutil.copytree(skills_root, src)
        if diff.strip():
            apply_diff(src, diff)
        cfg = Config.load(workspace)
        env = variables(cfg)
        env["SKILLS_DIR"] = ".agents/skills"
        dest = workspace / ".agents" / "skills"
        if dest.exists():
            shutil.rmtree(dest)
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src)
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".md":
                text = render(text, env)
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")


def write_hooks(workspace: Path) -> None:
    dest = workspace / ".codex" / "hooks.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(codex_hooks(workspace), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def git_init(workspace: Path) -> None:
    def git(*args: str) -> None:
        proc = subprocess.run(
            ["git", "-c", "user.email=bench@local", "-c", "user.name=bench", *args],
            cwd=workspace, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "git 失败").strip())

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "bench baseline", "--allow-empty")


def prepare_workspace(task: Task, *, skills_root: Path = SKILLS_SRC,
                      diff: str = "", keep: bool = False) -> Prepared:
    tmp = tempfile.TemporaryDirectory(prefix=f"adone-bench-{task.id}-")
    try:
        root = Path(tmp.name) / "work"
        copy_demo(task.demo, root)
        git_init(root)
        render_skills(root, skills_root, diff)
        write_hooks(root)
        # 技能和钩子是评测台放进去的，不记成 agent 的改动。
        git_init(root)
        return Prepared(root=root, keep=keep, _tmp=tmp)
    except Exception:
        tmp.cleanup()
        raise


def _git_lines(workspace: Path, *args: str) -> list[str]:
    proc = subprocess.run(
        ["git", *args], cwd=workspace, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln]


def workspace_facts(workspace: Path) -> dict:
    """门禁、假绿、判据锁、越权痕迹。隐藏验收还没拷进来。"""
    cfg = Config.load(workspace)
    got = collect_check(cfg)
    receipt = got.get("receipt")
    integ = integrity_problems(cfg, receipt)
    policy, _details = policy_problems(cfg, receipt)
    new_tests, _nt_details = new_tests_problems(cfg, receipt)
    names = set(_git_lines(workspace, "diff", "--name-only", "HEAD"))
    deleted = _git_lines(workspace, "diff", "--diff-filter=D", "--name-only", "HEAD")
    forbidden = [p for p in sorted(names) if p in baseline_paths()]
    log_path = workspace / ".adone" / "hook.log"
    hook_log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    return {
        "gate_problems": list(got.get("problems") or []),
        "integrity_problems": list(integ),
        "policy_problems": list(policy),
        "new_tests_problems": list(new_tests),
        "deleted_files": deleted,
        "forbidden_edits": forbidden,
        "hook_log": hook_log,
    }


def run_hidden(workspace: Path, task: Task) -> tuple[bool, str]:
    """agent 退出之后才把隐藏验收拷进去。"""
    dest = workspace / "bench-hidden"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(task.hidden_dir, dest)
    argv = list(task.hidden_argv)
    if argv and argv[0] in {"python", "python3"}:
        argv[0] = sys.executable
    proc = subprocess.run(
        argv, cwd=workspace, capture_output=True, text=True, timeout=120,
    )
    detail = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, detail


def extract_stream(raw: str) -> tuple[str, int, int, int]:
    """从 codex --json 的事件流里取助手文本、token、轮数、stop 回推。"""
    texts: list[str] = []
    tokens = 0
    turns = 0
    pushes = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            texts.append(line)
            continue
        if not isinstance(obj, dict):
            continue
        kind = str(obj.get("type") or obj.get("event") or "")
        if "stop" in kind.lower() or obj.get("stop_hook_active"):
            pushes += 1
        tokens += _token_count(obj)
        text = _event_text(obj)
        if text:
            texts.append(text)
            turns += 1
    return "\n".join(texts), tokens, turns, pushes


def _token_count(obj: dict) -> int:
    total = 0
    for key in ("usage", "token_usage", "tokens"):
        usage = obj.get(key)
        if isinstance(usage, dict):
            for part in ("input_tokens", "output_tokens", "total_tokens", "total"):
                val = usage.get(part)
                if isinstance(val, int):
                    if part == "total" or part == "total_tokens":
                        return val
                    total += val
        elif isinstance(usage, int) and key == "tokens":
            total += usage
    return total


def _event_text(obj: dict) -> str:
    for key in ("text", "message", "output", "content"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict):
            nested = _event_text(val)
            if nested:
                return nested
        if isinstance(val, list):
            bits = []
            for item in val:
                if isinstance(item, str):
                    bits.append(item)
                elif isinstance(item, dict):
                    bit = _event_text(item)
                    if bit:
                        bits.append(bit)
            if bits:
                return "\n".join(bits)
    item = obj.get("item")
    if isinstance(item, dict):
        return _event_text(item)
    return ""


def _text_of(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def codex_ask(prompt: str, files: dict[str, str], timeout: int) -> str:
    """在一个只含这些文件的临时目录里问 Codex。调用方负责不要把隐藏验收放进来。"""
    with tempfile.TemporaryDirectory(prefix="adone-bench-ask-") as tmp:
        root = Path(tmp)
        for name, body in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        proc = subprocess.run(
            codex_exec_argv(prompt, root),
            cwd=root, capture_output=True, text=True, timeout=timeout,
        )
        raw = proc.stdout or ""
        text, _tokens, _turns, _pushes = extract_stream(raw)
        return text.strip() or raw.strip()


def codex_available() -> tuple[bool, str]:
    path = codex_bin()
    if not path:
        return False, "没有 codex。PATH 里没有，bench/.codex-cli 里也没有"
    proc = subprocess.run(
        [path, "exec", "--help"], capture_output=True, text=True, timeout=30,
    )
    help_text = (proc.stdout or "") + (proc.stderr or "")
    missing = [
        flag for flag in (
            "--json", "--sandbox", "--dangerously-bypass-hook-trust",
            "--skip-git-repo-check", "-C",
        )
        if flag not in help_text
    ]
    if proc.returncode != 0 and not help_text:
        return False, f"codex exec --help 退出 {proc.returncode}"
    if missing:
        return False, "codex exec --help 里没有 " + "、".join(missing)
    return True, path


class CodexExecutor:
    """真跑。测试用 ScriptedExecutor，不走这里。"""

    def run(self, job: Job) -> Execution:
        prepared = prepare_workspace(
            job.task, skills_root=job.skills_root, diff=job.skills_diff,
        )
        try:
            prompt = agent_prompt(job.task)
            before = workspace_facts(prepared.root)
            try:
                proc = subprocess.run(
                    codex_exec_argv(prompt, prepared.root),
                    cwd=prepared.root,
                    capture_output=True,
                    text=True,
                    timeout=job.task.timeout_seconds,
                )
                raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            except subprocess.TimeoutExpired as e:
                raw = _text_of(e.stdout) + "\n" + _text_of(e.stderr)
            text, tokens, turns, pushes = extract_stream(raw)
            facts = workspace_facts(prepared.root)
            try:
                hidden_ok, _detail = run_hidden(prepared.root, job.task)
            except (OSError, subprocess.TimeoutExpired) as e:
                hidden_ok = False
                _detail = str(e)
            return Execution(
                run_id=job.run_id,
                assistant_text=text,
                hook_log=facts["hook_log"],
                gate_problems=facts["gate_problems"],
                integrity_problems=new_problems(
                    before["integrity_problems"], facts["integrity_problems"]),
                policy_problems=new_problems(
                    before["policy_problems"], facts["policy_problems"]),
                new_tests_problems=new_problems(
                    before["new_tests_problems"], facts["new_tests_problems"]),
                deleted_files=facts["deleted_files"],
                forbidden_edits=facts["forbidden_edits"],
                hidden_ok=hidden_ok,
                tokens=tokens,
                turns=turns,
                stop_pushes=pushes,
            )
        finally:
            prepared.cleanup()


class ScriptedExecutor:
    """回放写好的事实。不拷仓库，不调模型。"""

    def __init__(self, outcomes: dict[str, Execution]):
        self.outcomes = outcomes
        self.jobs: list[Job] = []

    def run(self, job: Job) -> Execution:
        self.jobs.append(job)
        if job.role not in self.outcomes:
            raise KeyError(f"假执行器没有 {job.role} 的剧本")
        proto = self.outcomes[job.role]
        return Execution(
            run_id=job.run_id,
            assistant_text=proto.assistant_text,
            hook_log=proto.hook_log,
            gate_problems=list(proto.gate_problems),
            integrity_problems=list(proto.integrity_problems),
            policy_problems=list(proto.policy_problems),
            new_tests_problems=list(proto.new_tests_problems),
            deleted_files=list(proto.deleted_files),
            forbidden_edits=list(proto.forbidden_edits),
            hidden_ok=proto.hidden_ok,
            tokens=proto.tokens,
            turns=proto.turns,
            stop_pushes=proto.stop_pushes,
        )
