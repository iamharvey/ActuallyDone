"""python -m bench：check / run / report / demo。

demo 用假执行器走完整条流程，不调模型。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import compose, propose
from .campaign import run_campaign
from .executor import SKILLS_SRC, CodexExecutor, ScriptedExecutor, codex_available
from .guard import make_diff
from .signals import Execution
from .taskload import REPO, load, list_ids


def _check() -> int:
    ok = True
    ready, msg = codex_available()
    print(("ok  " if ready else "缺  ") + "codex：" + msg)
    ok = ok and ready
    ids = list_ids()
    if not ids:
        print("缺  没有题目")
        ok = False
    for task_id in ids:
        task = load(task_id)
        demo_ok = (task.demo / "adone.toml").is_file()
        hidden_ok = (task.hidden_dir / "check.py").is_file()
        print(("ok  " if demo_ok else "缺  ") + f"demo {task.demo.relative_to(REPO)}")
        print(("ok  " if hidden_ok else "缺  ") + f"hidden {task_id}")
        ok = ok and demo_ok and hidden_ok
    try:
        import actuallydone
        print(f"ok  actuallydone {actuallydone.__version__}")
    except Exception as exc:
        print(f"缺  actuallydone：{exc}")
        ok = False
    return 0 if ok else 1


def _run(task_id: str, n: int, out: Path | None) -> int:
    ready, msg = codex_available()
    if not ready:
        print("缺  codex：" + msg, file=sys.stderr)
        return 1
    task = load(task_id)
    dest = out or (REPO / "bench" / "runs" / task_id / _stamp())
    timeout = task.timeout_seconds

    def proposer(ctx):
        return propose.ask_codex(ctx, timeout)

    def composer(ctx):
        return compose.ask_codex(ctx, timeout)

    result = run_campaign(
        task=task, n=n, out=dest, executor=CodexExecutor(),
        proposer=proposer, composer=composer,
    )
    print(result.report)
    print(f"写在 {result.out}")
    return 0


def _report(run_dir: Path) -> int:
    path = run_dir / "report.md"
    if not path.is_file():
        print(f"没有 {path}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def _demo_executor() -> ScriptedExecutor:
    done = "改完了。\n测试通过了。\nSTATUS: DONE"
    blocked_ok = "按技能只交回执，不口头宣布。\nSTATUS: DONE"
    return ScriptedExecutor({
        "reference": Execution(
            run_id="",
            assistant_text=done,
            gate_problems=["回执对不上当前树"],
            hidden_ok=False,
            tokens=1200,
            turns=4,
            stop_pushes=1,
        ),
        "invariant": Execution(
            run_id="",
            assistant_text=blocked_ok,
            hidden_ok=True,
            tokens=800,
            turns=3,
        ),
        "successor": Execution(
            run_id="",
            assistant_text=blocked_ok,
            hidden_ok=True,
            tokens=700,
            turns=2,
        ),
    })


def _demo_diff() -> str:
    rel = "completion-gate/SKILL.md"
    old = (SKILLS_SRC / rel).read_text(encoding="utf-8")
    note = "<!-- 评测：完成只认全量回执，不要口头宣布。 -->\n"
    new = old if note in old else (old if old.endswith("\n") else old + "\n") + note
    return make_diff(rel, old, new)


def _demo(task_id: str, out: Path | None) -> int:
    task = load(task_id)
    dest = out or (REPO / "bench" / "runs" / task_id / ("demo-" + _stamp()))
    diff = _demo_diff()

    def proposer(_ctx):
        return "=== invariant ===\n" + diff + "=== project ===\n"

    def composer(_ctx):
        return "=== successor ===\n" + diff

    result = run_campaign(
        task=task, n=1, out=dest, executor=_demo_executor(),
        proposer=proposer, composer=composer,
    )
    print(result.report)
    print(f"写在 {result.out}")
    return 0 if result.adopted else 1


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="Codex 与 demo 是否就绪")

    run = sub.add_parser("run", help="用 Codex 跑一道题")
    run.add_argument("--task", required=True)
    run.add_argument("--n", type=int, default=3)
    run.add_argument("--out")

    report = sub.add_parser("report", help="打印一次运行的 report.md")
    report.add_argument("run_dir")

    demo = sub.add_parser("demo", help="假执行器跑通流程，不调模型")
    demo.add_argument("--task", default="cs-cancel")
    demo.add_argument("--out")

    args = parser.parse_args(argv)
    if args.cmd == "check":
        return _check()
    if args.cmd == "run":
        return _run(args.task, args.n, Path(args.out) if args.out else None)
    if args.cmd == "report":
        return _report(Path(args.run_dir))
    if args.cmd == "demo":
        return _demo(args.task, Path(args.out) if args.out else None)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
