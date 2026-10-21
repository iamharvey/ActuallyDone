"""Propose：一次会话，两个候选补丁。

输入只有当前技能、参照轨迹、人审过的教训。没有隐藏验收，没有打分表。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .executor import SKILLS_SRC, codex_ask
from .guard import INVARIANT, PROJECT, diff_paths

_MARK = re.compile(r"^===\s*(invariant|project)\s*===\s*$")


def skill_texts(root: Path | None = None) -> dict[str, str]:
    base = root or SKILLS_SRC
    out = {}
    for path in sorted(base.rglob("*.md")):
        out[path.relative_to(base).as_posix()] = path.read_text(encoding="utf-8")
    return out


def build_context(*, task_id: str, prompt: str, skills: dict[str, str],
                  traces: list[dict], lessons: list[tuple[str, str]]) -> dict:
    """给模型的全部材料。不要往这里加隐藏验收或信号比率。"""
    return {
        "task_id": task_id,
        "prompt": prompt,
        "skills": skills,
        "traces": [
            {
                "run_id": t["run_id"],
                "assistant_text": t.get("assistant_text") or "",
                "hook_log": t.get("hook_log") or "",
            }
            for t in traces
        ],
        "lessons": [{"name": name, "text": text} for name, text in lessons],
        "invariant_skills": list(INVARIANT),
        "project_skills": list(PROJECT),
    }


def _split_unmarked(text: str) -> dict[str, str]:
    chunks = re.split(r"(?=^--- )", text, flags=re.M)
    buckets = {"invariant": [], "project": [], "other": []}
    for chunk in chunks:
        if "--- " not in chunk:
            continue
        paths = diff_paths(chunk)
        skill = paths[0].split("/", 1)[0] if paths else ""
        if skill in INVARIANT:
            buckets["invariant"].append(chunk)
        elif skill in PROJECT:
            buckets["project"].append(chunk)
        else:
            buckets["other"].append(chunk)
    return {k: "".join(v).strip() for k, v in buckets.items()}


def parse_candidates(text: str) -> dict[str, str]:
    parts: dict[str, list[str]] = {"invariant": [], "project": [], "other": []}
    current = None
    saw_mark = False
    for line in text.splitlines(keepends=True):
        mark = _MARK.match(line.strip())
        if mark:
            saw_mark = True
            current = mark.group(1)
            continue
        if current is not None:
            parts[current].append(line)
    if not saw_mark:
        return _split_unmarked(text)
    return {k: "".join(v).strip() for k, v in parts.items()}


def prompt_for(context: dict) -> str:
    return (
        "你在改 adone 的技能模板，不是改用户项目。\n"
        "只根据下面这份材料里的技能原文、参照运行轨迹和教训。\n"
        "不要假设还有别的测试或打分。占位符 {{...}} 保持原样。\n"
        "产出两段 unified diff，路径相对技能目录。\n"
        "不变候选只能改这些技能："
        + "、".join(context["invariant_skills"]) + "。\n"
        "项目候选只能改这些技能："
        + "、".join(context["project_skills"]) + "。\n"
        "没有把握就留空。用下面的标记，不要别的格式：\n"
        "=== invariant ===\n"
        "=== project ===\n"
    )


def files_for(context: dict) -> dict[str, str]:
    files = {"context.json": json.dumps(context, ensure_ascii=False, indent=2)}
    for rel, text in context["skills"].items():
        files[f"skills/{rel}"] = text
    for trace in context["traces"]:
        files[f"traces/{trace['run_id']}.txt"] = (
            trace["assistant_text"] + "\n" + trace["hook_log"]
        )
    for lesson in context["lessons"]:
        files[f"lessons/{lesson['name']}"] = lesson["text"]
    return files


def ask_codex(context: dict, timeout: int) -> str:
    return codex_ask(prompt_for(context), files_for(context), timeout)
