"""读 bench/tasks/<id>/。隐藏目录只把路径交出去，不读内容。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASKS = Path(__file__).resolve().parent / "tasks"
LESSONS = Path(__file__).resolve().parent / "lessons"

STATUS_LINE = "最后一行只能是 `STATUS: DONE` 或 `STATUS: BLOCKED <原因>`。"


@dataclass
class Task:
    id: str
    demo: Path
    prompt: str
    timeout_seconds: int
    budget_tokens: int
    hidden_dir: Path
    hidden_argv: list[str]
    # 开工前就在工作区里的东西，agent 看得到，不算它的改动
    setup_dir: Path | None = None


def list_ids() -> list[str]:
    if not TASKS.is_dir():
        return []
    return sorted(p.name for p in TASKS.iterdir() if (p / "task.toml").is_file())


def load(task_id: str) -> Task:
    root = TASKS / task_id
    path = root / "task.toml"
    if not path.is_file():
        known = "、".join(list_ids()) or "（空）"
        raise FileNotFoundError(f"没有题目 {task_id}。现有：{known}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    demo = Path(str(data.get("demo") or ""))
    if not demo.parts:
        raise ValueError(f"{task_id} 的 task.toml 没有 demo")
    if not demo.is_absolute():
        demo = REPO / demo
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        raise ValueError(f"{task_id} 的 task.toml 没有 prompt")
    argv = data.get("hidden_argv") or ["python3", "bench-hidden/check.py"]
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        raise ValueError(f"{task_id} 的 hidden_argv 必须是字符串数组")
    return Task(
        id=task_id,
        demo=demo,
        prompt=prompt,
        timeout_seconds=int(data.get("timeout_seconds") or 600),
        budget_tokens=int(data.get("budget_tokens") or 0),
        hidden_dir=root / "hidden",
        hidden_argv=[str(x) for x in argv],
        setup_dir=root / "setup" if (root / "setup").is_dir() else None,
    )


def load_lessons() -> list[tuple[str, str]]:
    """人审过才放进 bench/lessons/。没有也可以跑。"""
    if not LESSONS.is_dir():
        return []
    out = []
    for path in sorted(LESSONS.glob("*.md")):
        out.append((path.name, path.read_text(encoding="utf-8")))
    return out


def agent_prompt(task: Task) -> str:
    extra = []
    if STATUS_LINE not in task.prompt:
        extra.append(STATUS_LINE)
    if task.budget_tokens:
        extra.append(f"预算大约 {task.budget_tokens} token。超时 {task.timeout_seconds} 秒。")
    if not extra:
        return task.prompt
    return task.prompt.rstrip() + "\n\n" + "\n".join(extra) + "\n"
