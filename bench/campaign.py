"""整条 Propose–Probe–Compose。写报告，不改模板。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import compose, propose
from .executor import SKILLS_SRC, Job
from .guard import INVARIANT, PROJECT, check as guard_check, hidden_literals, normalize_diff
from .signals import Signals, score
from .taskload import Task, agent_prompt, load_lessons


@dataclass
class Result:
    out: Path
    adopted: bool
    report: str
    propose_context: dict
    compose_context: dict | None
    reasons: list[str] = field(default_factory=list)


def run_campaign(*, task: Task, n: int, out: Path, executor,
                 proposer, composer, skills: Path = SKILLS_SRC) -> Result:
    if n < 1:
        raise ValueError("n 至少是 1")
    out.mkdir(parents=True, exist_ok=True)
    literals = hidden_literals(task.hidden_dir)
    texts: dict[str, tuple[str, str]] = {}
    columns: list[tuple[str, dict, list[str]]] = []

    reference_rows = _probe(executor, task, "reference", n, "", skills, out, texts)
    ref = compose.summarize_rates(reference_rows)
    columns.append(("参照", ref["rates"], ref["run_ids"]))

    propose_context = propose.build_context(
        task_id=task.id,
        prompt=agent_prompt(task),
        skills=propose.skill_texts(skills),
        traces=[
            {
                "run_id": row.run_id,
                "assistant_text": texts[row.run_id][0],
                "hook_log": texts[row.run_id][1],
            }
            for row in reference_rows
        ],
        lessons=load_lessons(),
    )
    _write_json(out / "propose_context.json", propose_context)
    parsed = propose.parse_candidates(proposer(propose_context))

    reasons: list[str] = []
    probed: dict[str, dict] = {}
    rejected: list[dict] = []
    allowed = {"invariant": INVARIANT, "project": PROJECT}

    for name in ("invariant", "project"):
        diff = (parsed.get(name) or "").strip()
        if not diff:
            reasons.append(f"{_zh(name)}没有产出补丁")
            continue
        problems = [
            _redact(item, literals)
            for item in guard_check(diff, skills=skills, literals=literals,
                                    allowed=allowed[name])
        ]
        if problems:
            reasons.append(f"{_zh(name)}被闸门拒绝：" + "；".join(problems))
            rejected.append({"name": name, "reasons": problems, "run_ids": []})
            continue
        rows = _probe(executor, task, name, n, diff, skills, out, texts)
        summary = compose.summarize_rates(rows)
        summary["diff"] = diff
        columns.append((_zh(name), summary["rates"], summary["run_ids"]))
        bad = compose.hard_worse(summary["rates"], ref["rates"])
        if bad:
            why = "、".join(bad)
            reasons.append(
                f"{_zh(name)}未进合并池：{why} 差于参照"
                f"（{'、'.join(summary['run_ids'])} 对比 {'、'.join(ref['run_ids'])}）"
            )
            rejected.append({
                "name": name,
                "reasons": [f"{why} 差于参照"],
                "run_ids": summary["run_ids"],
            })
            continue
        probed[name] = summary
        (out / name / "candidate.patch").write_text(
            normalize_diff(diff), encoding="utf-8",
        )

    if (parsed.get("other") or "").strip():
        reasons.append("有一段补丁落在不变候选和项目候选之外，已丢弃")

    adopted = False
    patch = ""
    successor_ids: list[str] = []
    compose_context = None

    if not probed:
        reasons.append("合并池是空的，保持现状")
    else:
        compose_context = compose.build_context(
            task_id=task.id,
            prompt=agent_prompt(task),
            reference={"rates": ref["rates"], "run_ids": ref["run_ids"]},
            candidates={
                name: {
                    "diff": item["diff"],
                    "rates": item["rates"],
                    "run_ids": item["run_ids"],
                }
                for name, item in probed.items()
            },
            rejected=rejected,
        )
        _write_json(out / "compose_context.json", compose_context)
        successor = compose.parse_successor(composer(compose_context)).strip()
        if not successor:
            reasons.append("合成选择保持现状")
        else:
            problems = [
                _redact(item, literals)
                for item in guard_check(
                    successor, skills=skills, literals=literals,
                    allowed=INVARIANT + PROJECT,
                )
            ]
            if problems:
                reasons.append("后继被闸门拒绝：" + "；".join(problems))
            else:
                rows = _probe(executor, task, "successor", n, successor, skills, out, texts)
                summary = compose.summarize_rates(rows)
                successor_ids = summary["run_ids"]
                columns.append(("后继", summary["rates"], successor_ids))
                bad = compose.hard_worse(summary["rates"], ref["rates"])
                if bad:
                    reasons.append(
                        "后继不优于参照的底线：" + "、".join(bad)
                        + f"（{'、'.join(successor_ids)} 对比 {'、'.join(ref['run_ids'])}），保持现状"
                    )
                else:
                    adopted = True
                    patch = normalize_diff(successor)
                    reasons.append(
                        "后继不劣于参照，写出 skills.patch"
                        f"（{'、'.join(successor_ids)} 对比 {'、'.join(ref['run_ids'])}）"
                    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = compose.render_report(
        task_id=task.id, stamp=stamp, adopted=adopted,
        reasons=reasons, columns=columns,
    )
    (out / "report.md").write_text(report, encoding="utf-8")
    (out / "EXPERIENCE.md").write_text(compose.render_experience(
        adopted=adopted, reasons=reasons, patch=patch,
        reference_ids=ref["run_ids"], successor_ids=successor_ids,
    ), encoding="utf-8")
    patch_path = out / "skills.patch"
    if adopted:
        patch_path.write_text(patch, encoding="utf-8")
    elif patch_path.exists():
        patch_path.unlink()
    _write_json(out / "decision.json", {"adopted": adopted, "reasons": reasons})
    return Result(
        out=out, adopted=adopted, report=report,
        propose_context=propose_context, compose_context=compose_context,
        reasons=reasons,
    )


def _probe(executor, task, role, n, diff, skills, out, texts) -> list[Signals]:
    rows = []
    for i in range(1, n + 1):
        run_id = f"{role}-{i}"
        execution = executor.run(Job(
            task=task, role=role, index=i, run_id=run_id,
            skills_diff=diff, skills_root=skills,
        ))
        got = score(execution)
        rows.append(got)
        texts[run_id] = (execution.assistant_text, execution.hook_log)
        dest = out / role / run_id
        dest.mkdir(parents=True, exist_ok=True)
        payload = got.as_dict()
        payload["assistant_text"] = execution.assistant_text
        payload["hook_log"] = execution.hook_log
        _write_json(dest / "trace.json", payload)
    return rows


def _redact(text: str, literals: list[str]) -> str:
    for lit in literals:
        if lit:
            text = text.replace(lit, "[隐藏字面量]")
    return text


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _zh(name: str) -> str:
    return {
        "invariant": "不变候选",
        "project": "项目候选",
        "successor": "后继",
        "reference": "参照",
    }.get(name, name)
