"""维度：测试与覆盖率。

默认不重跑测试，只读最新回执——重跑一次动辄几分钟，体检要能随手跑。
代价是数字可能过期，所以「回执是否与当前代码同哈希」本身就是这个维度的头号指标。
"""

from __future__ import annotations

import sys
from contextlib import redirect_stdout

from ..gate import gate_problems, load_latest, run_gate, tree_hash
from ..integrity import BaselineBroken, integrity_problems, load_baseline, scan
from ..model import DimResult, Metric


def run(ctx) -> DimResult:
    cfg = ctx.cfg
    res = DimResult("tests", "测试与覆盖率")

    if ctx.run_gate:
        # 在进程内跑，不再 spawn 一个 `python -m actuallydone`：没装 pip 包时那条路会
        # 报「No module named actuallydone」然后**接着拿旧回执算分**——--all 声称重跑了
        # 却没有重跑，是这个工具最不该犯的错。stdout 借给门禁的进度，--json 时它必须只有 JSON。
        print("  跑全量门禁中…", flush=True, file=sys.stderr)
        with redirect_stdout(sys.stderr):
            run_gate(cfg)

    receipt = load_latest(cfg)
    if receipt is None:
        return res.skip("还没有任何门禁回执，跑 adone gate run")

    now_hash, now_files = tree_hash(cfg)
    problems, _ = gate_problems(cfg, receipt, now_hash)
    for p in problems:
        res.add("错误", "门禁回执", p)

    tests = receipt.get("tests", {})
    cov = (receipt.get("coverage") or {}).get("percent")
    thr = (receipt.get("coverage") or {}).get("threshold")
    fresh = receipt.get("tree", {}).get("hash") == now_hash

    if tests.get("fail"):
        res.add("错误", "测试", f"{tests['fail']} 个用例失败")
    if not tests.get("parsed", True):
        res.add("错误", "测试", "回执里的测试结果解析失败，这轮数字不成立")
    if cov is not None and thr is not None and cov < thr:
        res.add("错误", "覆盖率", f"{cov}% 低于下限 {thr}%")

    for p in integrity_problems(cfg, receipt):
        res.add("错误", "测试完整性", p)

    cur = scan(cfg)
    try:
        base = load_baseline(cfg)
    except BaselineBroken:
        # 坏基线已经由 integrity_problems 记成错误。这里再提示「建立初始基线」
        # 就会把人引去用当前这棵树覆盖坏文件。
        base = None
    steps = {s["name"]: s for s in receipt.get("steps", [])}
    failed_steps = [n for n, s in steps.items() if not s.get("ok")]

    res.metrics = [
        Metric("回执", str(receipt.get("id", "无")),
               "与当前代码一致" if fresh else "已过期，不能作为证据",
               "good" if fresh else "bad"),
        Metric("用例", f"{tests.get('pass', 0)} 通过",
               f"{tests.get('fail', 0)} 失败 / {tests.get('skip', 0)} 跳过"
               f"（顶层 {tests.get('skip_top', '?')}）",
               "bad" if tests.get("fail") else "good"),
        Metric("覆盖率", f"{cov}%" if cov is not None else "未采集",
               f"下限 {thr}%" if thr is not None else "没配下限",
               "good" if cov is not None and thr is not None and cov >= thr
               else "warnv" if cov is None else "bad"),
        Metric("测试规模", f"{len(cur['test_functions'])} 个用例函数",
               f"{sum(cur['skip_sites'].values())} 处跳过 / "
               f"{len(cur['assertionless'])} 个无断言"),
        Metric("门禁步骤", f"{len(steps) - len(failed_steps)}/{len(steps)} 通过",
               "、".join(failed_steps) if failed_steps else "每步都过",
               "good" if not failed_steps else "bad"),
    ]
    if base is None and not any("基线坏了" in f.message for f in res.findings):
        res.notes.append('还没有假绿检测基线：跑 adone integrity --accept-baseline "建立初始基线"。')
    res.notes.append(f"回执生成于 {receipt.get('created_at', '?')}，"
                     f"树 {receipt.get('tree', {}).get('file_count', '?')} 个文件；"
                     f"当前树 {now_files} 个文件。")
    if not ctx.run_gate:
        res.notes.append("本轮没有重跑测试，上面的数字来自最新回执；要重跑加 --all。")
    return res
