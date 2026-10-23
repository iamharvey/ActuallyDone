"""独立复核：给**另一个**模型用的那条命令。

最硬的检查不是自己检查自己，而是换一个不知道实现过程的执行者来查。
门禁的判据从一开始就在磁盘上（树哈希、契约、三份基线、回执链），不在谁的会话里，
所以第二个模型本来就有能力独立得出结论——缺的只是一条命令、一个身份、一份不覆盖
被审证据的结论文件。这个模块补的就是这三样。

与 `gate check` 的三点区别，每一点都是刻意的：

- **默认开抽查**。收工钩子每次都跑 `check`，抽查的几秒不该压在那条路径上；
  但复核只跑一次，省这几秒等于放掉「回执写着通过其实没跑」这一类。
- **不写 latest.json、不推进证据链**。复核者顺手覆盖被审的回执，等于把证据抹掉。
- **口吻是复核者的**。`check` 通过时把回执交给另一个模型，这里说「独立复核通过」——
  复核者不该替实现者宣布完成，它只能说自己核过了什么。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from .config import Config
from .gate import (GateError, collect_check, evidence_of, execute_steps,
                   load_latest, self_hash, tree_hash)
from .report import open_report, render_audit

# 复核者不该动的东西：动了就等于自己给自己放行
FORBIDDEN = (
    "adone policy --accept（把被放松的判据记成新基线）",
    "adone integrity --accept-baseline（把新增的松动记成新基线）",
    "adone gate waive-tests（把「没新测试」记成豁免）",
    "改 adone.toml、删验收契约、手改 .adone/ 下的回执与基线",
    "改代码去「修」门禁——复核者只报告，修由实现者做",
)


def _rerun(cfg: Config) -> dict:
    """复核者自己跑一遍门禁，产出一份审计回执（只落 audits/）。"""
    problems = cfg.problems()
    if problems:
        return {"error": "配置本身有问题，独立重跑不算数：" + "；".join(problems)}

    print("\n独立重跑门禁（不覆盖实现者的回执）：\n")
    ran = execute_steps(cfg)
    steps = ran["steps"]
    h, n = tree_hash(cfg)
    return {
        "tree": {"hash": h, "file_count": n},
        "complete": ran["complete"],
        "seconds": ran["seconds"],
        "tests": (ran["tests"].as_dict() if ran["tests"] is not None else None),
        "coverage": {"percent": ran["coverage"], "threshold": ran["threshold"]},
        "steps": [s.as_receipt() for s in steps],
        "ok": bool(steps) and all(s.ok for s in steps),
        "failed_steps": [s.name for s in steps if not s.ok],
    }


def _compare(receipt: dict | None, mine: dict) -> list[str]:
    """把实现者的回执与我自己跑出来的结果对一遍。"""
    out: list[str] = []
    if receipt is None:
        out.append("实现者没有留下任何回执，只能以本次独立重跑为准")
        return out
    theirs, ours = (receipt.get("tree") or {}).get("hash"), mine["tree"]["hash"]
    if theirs != ours:
        out.append(f"实现者回执的树哈希与当前代码对不上（{str(theirs)[:12]} ≠ {ours[:12]}）："
                   f"我跑的是当前这份代码，那份回执证明的是另一份")
    theirs_names = set((receipt.get("tests") or {}).get("passed_names") or [])
    ours_names = set(((mine.get("tests") or {}).get("passed_names")) or [])
    if theirs_names and ours_names:
        # 回执里列着、我这一遍根本没跑出来的用例名：要么后来被删了，要么当初就是编的
        gone = sorted(theirs_names - ours_names)
        if gone:
            out.append(f"回执声称通过的用例，有 {len(gone)} 条在我这一遍里没有出现："
                       f"{'、'.join(gone[:5])}{'…' if len(gone) > 5 else ''}")

    bad = "、".join(mine["failed_steps"]) or "未知步骤"
    if not mine["ok"]:
        # 「它说全绿我没跑过」比「我没跑过」重得多，两句只留更重的那句
        out.append(f"实现者回执写着全绿，我独立重跑却没过：{bad}"
                   if receipt.get("ok") else f"独立重跑未通过：{bad}")
    return out


def _evidence_line(base: str, rerun: bool, spotcheck: int) -> str:
    """在被审证据的强度后面，如实补一句「复核者核到了哪一层」。

    三档差别很实：读证据只证明自洽，抽查证明用例现在真能跑，全量重跑才是复核者
    自己的一份结果。写成同一句话，等于把最弱的那档冒充最强的。
    """
    how = ("全量重跑核对" if rerun
           else f"抽 {spotcheck} 条当场真跑" if spotcheck else "只读证据核对")
    return f"{base or '证据强度：没有回执可依'} · 已由独立复核者{how}"


def reviewer_notes(receipt: dict | None, reviewer: str | None) -> tuple[list[str], list[str]]:
    """两边模型都有且相同，才是问题。缺任何一边只写进依据。"""
    theirs = ((receipt or {}).get("runner") or {}).get("model") or ""
    if not isinstance(theirs, str):
        theirs = ""
    theirs = theirs.strip()
    mine = (reviewer or "").strip()
    if theirs and mine:
        if theirs == mine:
            return [f"复核者与跑出门禁的是同一个模型（{theirs}）"], []
        return [], [f"复核者 {mine}，跑出门禁的是 {theirs}"]
    if not mine:
        return [], ["未标明复核者（--reviewer），无法判断是不是同一个模型"]
    return [], ["回执没有 runner.model，无法对照复核者"]


def run_audit(cfg: Config, spotcheck: int = 2, rerun: bool = False,
              as_json: bool = False, html_out: str | None = None,
              html_open: bool = False, reviewer: str | None = None) -> int:
    got = collect_check(cfg, with_integrity=True, spotcheck=spotcheck)
    problems = list(got["problems"])
    details = list(got["details"])
    receipt = got["receipt"]
    rev_bad, rev_detail = reviewer_notes(receipt, reviewer)
    problems.extend(rev_bad)
    details.extend(rev_detail)

    mine: dict | None = None
    if rerun:
        try:
            mine = _rerun(cfg)
        except GateError as e:
            mine = {"error": str(e)}
        if "error" in mine:
            problems.append(mine["error"])
        else:
            problems.extend(_compare(receipt, mine))

    ok = not problems
    verdict = {
        "tool": "actuallydone",
        "role": "auditor",
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "rerun" if rerun else "review",
        "ok": ok,
        "problems": problems,
        "details": details,
        "audited_receipt": {
            "id": got["receipt_id"],
            "self_hash": (receipt or {}).get("self_hash"),
            "tree_hash": (receipt or {}).get("tree", {}).get("hash"),
        },
        "tree": {"hash": got["tree_hash"], "file_count": got["tree_files"]},
        "spotcheck": {"asked": spotcheck, "notes": got["spotcheck"]},
        "rerun": mine,
        "evidence": (got["evidence"] or evidence_of(cfg, {})) | {
            "audited_by": "independent-local",
            "audit_mode": ("rerun" if rerun else "spotcheck" if spotcheck else "review"),
        },
        "evidence_line": _evidence_line(got["evidence_line"], rerun, spotcheck),
    }
    verdict["self_hash"] = self_hash(verdict)
    _write_verdict(cfg, verdict)
    html_path = _write_html(cfg, verdict, html_out)
    if html_open:
        open_report(html_path)

    if as_json:
        print(json.dumps(verdict, ensure_ascii=False))
        return 0 if ok else 1
    _say(cfg, verdict, html_path)
    return 0 if ok else 1


def _write_html(cfg: Config, verdict: dict, html_out: str | None = None) -> Path:
    out = Path(html_out).resolve() if html_out else cfg.audit_report
    out.parent.mkdir(parents=True, exist_ok=True)
    render_audit(verdict, out, cfg.name)
    return out


def _write_verdict(cfg: Config, verdict: dict) -> None:
    cfg.audits_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(verdict, ensure_ascii=False, indent=2)
    (cfg.audits_dir / f"audit-{verdict['id']}.json").write_text(body, encoding="utf-8")
    cfg.latest_audit.write_text(body, encoding="utf-8")
    keep = int(cfg.get("gate.keep_receipts", 20) or 20)
    for p in sorted(cfg.audits_dir.glob("audit-*.json"), reverse=True)[keep:]:
        p.unlink(missing_ok=True)


def _how_far(v: dict) -> str:
    """通过的那句话只能说到复核者真做过的那一步。

    「经得起当场抽跑」这种话，在没抽跑的那一次说出来就是替实现者吹牛。
    抽查要求的条数不等于真跑成了——适配器不会单跑用例时会标未评估。
    """
    if v["mode"] == "rerun":
        return "，且复核者独立重跑门禁得到同样的结果"
    if any("抽查真跑" in n for n in v["spotcheck"]["notes"]):
        return "，且抽查的用例当场真跑仍然通过"
    return "（本次只读证据，没有当场重跑）"


def _say(cfg: Config, v: dict, html_path: Path | None = None) -> None:
    aud = v["audited_receipt"]
    print(f"\n独立复核（{'重跑门禁' if v['mode'] == 'rerun' else '复核现有回执'}）"
          f"：对照回执 {aud['id'] or '无'}，当前树 {str(v['tree']['hash'])[:12] or '算不出'}"
          f"（{v['tree']['file_count']} 个文件）")
    if v["ok"]:
        print("\n独立复核通过：这份交付的证据自洽" + _how_far(v) + "。")
    else:
        print("\n独立复核未通过，实现者不能宣称完成：")
        for p in v["problems"]:
            print(f"  - {p}")
    for d in v["details"]:
        print(f"  · {d}")
    print(v["evidence_line"])
    print(f"\n结论写入 {cfg.latest_audit.relative_to(cfg.root)}"
          f"（不覆盖实现者的回执与证据链）")
    if html_path is not None:
        try:
            shown = html_path.relative_to(cfg.root)
        except ValueError:
            shown = html_path
        print(f"HTML 报告：{shown}")


# --------------------------------------------------------------------------- 简报

def brief(cfg: Config) -> int:
    """给复核者的冷启动简报：不看聊天记录，只看仓库，该读什么、跑什么、不许动什么。"""
    rel = lambda p: p.relative_to(cfg.root)   # noqa: E731
    contracts = sorted(cfg.acceptance_dir.glob("*.toml")) if cfg.acceptance_dir.is_dir() else []
    receipt = load_latest(cfg)

    print(f"""你是这份交付的**独立复核者**，不是实现者。

项目：{cfg.name}（{cfg.root}）
你的任务：在不看实现者的聊天记录、不听它的自述的前提下，判断「做完了」这句话是否成立。

要读的（都在仓库里，自解释）：
  {rel(cfg.path) if cfg.path else 'adone.toml'}  判据本身：受监视代码树、门禁步骤、覆盖率下限
  {rel(cfg.acceptance_dir)}/*.toml  验收契约：每条需求绑定的用例名（现有 {len(contracts)} 份）
  {rel(cfg.latest_receipt)}  实现者留下的回执{'（回执 ' + receipt['id'] + '）' if receipt else '（还没有）'}
  {rel(cfg.policy_baseline)}  判据基线：门禁本身有没有被放松
  {rel(cfg.baseline)}  假绿基线：用例有没有被删、跳过有没有变多
  {rel(cfg.chain)}  证据链头：回执有没有被换过

还要打开验收契约里每个 test 的源码：
  调用之后如果改了规则要读的字段（主题、发件人、邮箱、状态），或断言比「要求」弱，
  按未通过写进问题清单。全绿回执只说明这些用例跑过，不说明夹具老实。

要跑的：
  adone doctor           配置与现实是否一致、钩子还灵不灵
  adone audit --reviewer <模型名>
                         独立复核，并与回执里的 runner.model 对照；相同则不通过
  adone audit --rerun    不信任回执时：自己把门禁全量跑一遍再比对
  adone audit report     把已有结论渲成一页 HTML，不重跑检查

不许做的：
""" + "\n".join(f"  - {x}" for x in FORBIDDEN) + f"""

报告口径：给出对照的回执 ID、当前树哈希、问题逐条、结论文件路径
（{rel(cfg.latest_audit)} / {rel(cfg.audit_report)}）。只报告，不修复——修是实现者的事。
未通过时明说：实现者不能宣称完成。""")
    return 0


def cmd_audit_report(cfg: Config, args) -> int:
    """把已有审计结论渲成 HTML，不重跑检查——被审的证据不能由渲报告改掉。"""
    if not cfg.latest_audit.is_file():
        print("还没有审计结论，先跑 adone audit", file=sys.stderr)
        return 2
    try:
        verdict = json.loads(cfg.latest_audit.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"审计结论读不出来：{e}", file=sys.stderr)
        return 2
    out = _write_html(cfg, verdict, getattr(args, "out", None))
    print(f"HTML 报告：{out}")
    if getattr(args, "open", False):
        open_report(out)
    return 0 if verdict.get("ok") else 1


def cmd_audit(cfg: Config, args) -> int:
    if getattr(args, "brief", False):
        return brief(cfg)
    n = args.spotcheck if args.spotcheck is not None else 2
    if n < 0:
        print("--spotcheck 不能是负数", file=sys.stderr)
        return 2
    return run_audit(cfg, spotcheck=n, rerun=args.rerun, as_json=args.json,
                     html_out=getattr(args, "out", None),
                     html_open=getattr(args, "open", False),
                     reviewer=getattr(args, "reviewer", None))
