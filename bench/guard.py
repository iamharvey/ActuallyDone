"""候选补丁的闸门。写进工作区之前拒绝。

不调用模型。必留句是模板里的原句，弱化或删掉都拒。
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

INVARIANT = (
    "completion-gate",
    "independent-check",
    "test-integrity",
    "verified-delivery",
)
PROJECT = (
    "coding-standards",
    "test-driven-dev",
    "pr-review-checklist",
)
BUCKETS = {"invariant": INVARIANT, "project": PROJECT}

# 原句。改写、删掉、把「不要」换成「可以」都会对不上。
REQUIRED = (
    ("completion-gate/SKILL.md", "也不要说「可以完成了」"),
    ("completion-gate/SKILL.md",
     "全量回执（`latest.json`）是交给另一个模型的证据，不是完成声明。"),
    ("completion-gate/SKILL.md", "不要自己跑这条命令。"),
    ("completion-gate/SKILL.md", "不要自己销账。"),
    ("completion-gate/SKILL.md", "别人留下的失败用例不是你停工的理由。"),
    ("completion-gate/SKILL.md", "不修它，不跳过、不删、不改弱断言、不加豁免。"),
    ("completion-gate/SKILL.md", "不要把文档里的示例响应写成返回值、常量或兜底分支。"),
    ("test-integrity/SKILL.md", "调用之后不许改规则要读的字段，再把结果当成规则命中。"),
    ("acceptance-contract/SKILL.md", "规则能不能命中，要有一条走同一入口的反例。"),
    ("independent-check/SKILL.md", "`{{ADONE}} policy --accept`"),
    ("independent-check/SKILL.md", "`{{ADONE}} integrity --accept-baseline`"),
    ("independent-check/SKILL.md", "`{{ADONE}} gate waive-tests`"),
)

_ADDED_FORBIDDEN = (
    (re.compile(r"可以自己跑.{0,40}(--accept-baseline|waive-tests|policy --accept)"),
     "教 agent 自己放宽"),
    (re.compile(r"(改|修改|下调|放宽|注释掉).{0,24}adone\.toml"),
     "教 agent 改 adone.toml"),
    (re.compile(r"adone\.toml.{0,24}(改|修改|下调|放宽)"),
     "教 agent 改 adone.toml"),
    (re.compile(
        r"(手改|改写|覆盖|删掉|删除).{0,24}"
        r"(test-baseline\.json|policy-baseline\.json|new-tests-waiver\.json|"
        r"latest\.json|receipts/)"),
     "教 agent 改基线或回执"),
)

# 「不要改」是禁令，不是教它去改。
_NEGATION = ("不要", "禁止", "不能", "勿")

_PREFIXES = (
    "actuallydone/templates/skills/",
    "templates/skills/",
)


def hidden_literals(hidden: Path) -> list[str]:
    """隐藏验收里的哨兵。任务描述里不该出现这些。"""
    found: set[str] = set()
    if not hidden.is_dir():
        return []
    for path in hidden.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(re.findall(r"HID_[A-Za-z0-9_]+", text))
        for line in text.splitlines():
            if line.startswith("# literal:"):
                found.add(line.split(":", 1)[1].strip())
    return sorted(found)


def make_diff(rel: str, old: str, new: str) -> str:
    if not old.endswith("\n"):
        old += "\n"
    if not new.endswith("\n"):
        new += "\n"
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="a/" + rel,
        tofile="b/" + rel,
    ))


def added_lines(diff: str) -> list[str]:
    lines = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    return lines


def diff_paths(diff: str) -> list[str]:
    paths = []
    for line in diff.splitlines():
        if not line.startswith("+++ "):
            continue
        raw = line[4:].split("\t", 1)[0].strip()
        if raw == "/dev/null":
            continue
        paths.append(_normalize(raw))
    return paths


def _normalize(path: str) -> str:
    p = path.strip()
    if p.startswith("b/") or p.startswith("a/"):
        p = p[2:]
    for prefix in _PREFIXES:
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p


def normalize_diff(diff: str) -> str:
    """把路径收成技能目录内的相对路径，方便 patch -p1。"""
    out = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("--- ") or line.startswith("+++ "):
            head, _, rest = line.partition(" ")
            payload = rest
            nl = ""
            if payload.endswith("\n"):
                payload = payload[:-1]
                nl = "\n"
            path, tab, trail = payload.partition("\t")
            if path.strip() == "/dev/null":
                out.append(line)
                continue
            name = _normalize(path.strip())
            marker = "a/" if head == "---" else "b/"
            out.append(f"{head} {marker}{name}{tab}{trail}{nl}")
        else:
            out.append(line)
    text = "".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def apply_diff(skills: Path, diff: str) -> None:
    """把补丁打进技能目录。失败抛 PatchError。"""
    if not diff.strip():
        return
    proc = subprocess.run(
        ["patch", "-p1", "--forward", "--batch"],
        input=normalize_diff(diff),
        text=True,
        cwd=skills,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "patch 失败").strip()
        raise PatchError(detail)


class PatchError(Exception):
    pass


def _skill_of(path: str) -> str:
    return path.split("/", 1)[0]


def check(diff: str, *, skills: Path, literals: list[str],
          allowed: tuple[str, ...] | None) -> list[str]:
    """返回拒绝理由。空列表表示可以写进工作区。"""
    if not diff.strip():
        return []
    problems: list[str] = []
    paths = diff_paths(diff)
    if not paths:
        problems.append("补丁里没有文件")
    allowed_set = set(allowed) if allowed is not None else set(INVARIANT + PROJECT)
    for path in paths:
        skill = _skill_of(path)
        if skill not in allowed_set:
            problems.append(f"{path} 不在这个候选允许改的技能里")
        if path.startswith("..") or path.startswith("/"):
            problems.append(f"路径越界：{path}")

    blob = diff
    for lit in literals:
        if lit and lit in blob:
            problems.append(f"补丁里出现隐藏验收字面量 {lit}")

    for line in added_lines(diff):
        if any(word in line for word in _NEGATION):
            continue
        for cre, why in _ADDED_FORBIDDEN:
            if cre.search(line):
                problems.append(why + "：" + line.strip())

    try:
        with tempfile.TemporaryDirectory(prefix="adone-bench-") as tmp:
            dest = Path(tmp) / "skills"
            shutil.copytree(skills, dest)
            apply_diff(dest, diff)
            for rel, phrase in REQUIRED:
                file = dest / rel
                if not file.is_file() or phrase not in file.read_text(encoding="utf-8"):
                    problems.append(f"必留句不在了：{rel}「{phrase}」")
    except PatchError as e:
        problems.append(f"补丁打不上：{e}")
    return problems
