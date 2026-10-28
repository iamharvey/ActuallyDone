"""假绿检测：抓「把门禁改绿」而不是「把代码改对」的手法。

绿灯有两种来源——代码变对了，或者门禁被改松了。后者的常见手法是删用例、加跳过、
把断言删掉、把覆盖率下限调低。这里拿基线快照比对，只报**新增**的松动，
所以历史遗留不会天天刷屏，而新加的松动一次都跑不掉。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .config import Config
from .textio import read as read_source

# 文档里声明覆盖率下限的写法，例如「覆盖率 ≥ 85%」「不低于 85%」「基线 85.9%」
DOC_THRESHOLD_RE = re.compile(r"(?:≥|>=|不低于|下限|基线)\s*(\d{2}(?:\.\d)?)\s*%")
# 测试基座本身不是用例，别把它算成「无断言」
HARNESS_NAMES = {"TestMain", "setUpModule", "tearDownModule"}


def _scan_adapter(cfg: Config, ad, roots: list[Path], exempt: set[str],
                  funcs: dict[str, str], skip_sites: dict[str, int],
                  assertionless: list[str]) -> None:
    for p in ad.test_files(roots):
        try:
            rel = p.relative_to(cfg.root).as_posix()
        except ValueError:
            rel = p.as_posix()
        text = read_source(p)
        n = ad.skip_sites(text)
        if n:
            skip_sites[rel] = skip_sites.get(rel, 0) + n
        for fn in ad.iter_test_funcs(p):
            if fn.name in HARNESS_NAMES or fn.name in exempt:
                continue
            funcs[fn.name] = rel
            if ad.is_assertionless(fn.body) and fn.name not in assertionless:
                assertionless.append(fn.name)


def scan(cfg: Config) -> dict:
    from .adapters import get, has_eval_step
    ad = get(cfg.get("tests.adapter") or "", cfg.root)
    roots = [cfg.root / r for r in (cfg.get("tests.roots", []) or [])]
    exempt = set(cfg.get("tests.baseline_exempt", []) or [])

    funcs: dict[str, str] = {}
    skip_sites: dict[str, int] = {}
    assertionless: list[str] = []
    _scan_adapter(cfg, ad, roots, exempt, funcs, skip_sites, assertionless)
    # 无 eval 步则完全走 tests.adapter；有才额外合并场景名
    if has_eval_step(cfg) and ad.name != "eval":
        ev = get("eval", cfg.root)
        _scan_adapter(cfg, ev, roots, exempt, funcs, skip_sites, assertionless)
    return {
        "test_functions": funcs,
        "skip_sites": skip_sites,
        "assertionless": sorted(assertionless),
    }


def declared_thresholds(cfg: Config) -> dict[str, float]:
    """扫配置与文档里声明的覆盖率下限，取每个文件里的最小值。

    门禁自己也可能被改松，所以 adone.toml 里的 coverage.threshold 一并纳入比对。
    """
    out: dict[str, float] = {}
    thr = cfg.get("coverage.threshold")
    if thr is not None:
        out["adone.toml"] = float(thr)
    for rel in cfg.get("tests.threshold_docs", []) or []:
        p = cfg.root / rel
        if not p.exists():
            continue
        vals = [float(v) for v in
                DOC_THRESHOLD_RE.findall(read_source(p))]
        if vals:
            out[rel] = min(vals)
    return out


def load_baseline(cfg: Config) -> dict | None:
    if not cfg.baseline.exists():
        return None
    try:
        return json.loads(cfg.baseline.read_text(encoding="utf-8"))
    except Exception:
        return None


def compare(cfg: Config, cur: dict, base: dict) -> list[str]:
    problems: list[str] = []

    gone = sorted(set(base["test_functions"]) - set(cur["test_functions"]))
    if gone:
        shown = "、".join(gone[:6]) + ("…" if len(gone) > 6 else "")
        problems.append(f"{len(gone)} 个用例消失了（删除或改名）：{shown}")

    for rel, n in sorted(cur["skip_sites"].items()):
        was = base["skip_sites"].get(rel, 0)
        if n > was:
            problems.append(f"{rel} 的跳过标记从 {was} 处涨到 {n} 处，新增的跳过要有理由")

    new_dumb = sorted(set(cur["assertionless"]) - set(base["assertionless"]))
    if new_dumb:
        shown = "、".join(new_dumb[:6]) + ("…" if len(new_dumb) > 6 else "")
        problems.append(f"{len(new_dumb)} 个用例没有任何断言，跑了也证明不了什么：{shown}")

    base_thr = base.get("coverage_threshold")
    if base_thr is not None:
        for where, v in declared_thresholds(cfg).items():
            if v < base_thr:
                problems.append(f"{where} 里的覆盖率下限被从 {base_thr}% 调到 {v}%")
    return problems


def current_runtime_skips(cfg: Config) -> int:
    """从最新回执里读运行期跳过的**顶层**用例数；没有回执就按 0 记。"""
    if not cfg.latest_receipt.exists():
        return 0
    try:
        tests = json.loads(cfg.latest_receipt.read_text(encoding="utf-8"))["tests"]
        return int(tests.get("skip_top", tests.get("skip", 0)))
    except Exception:
        return 0


def write_baseline(cfg: Config, cur: dict, reason: str) -> None:
    cfg.baseline.parent.mkdir(parents=True, exist_ok=True)
    thresholds = declared_thresholds(cfg)
    data = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
        "coverage_threshold": min(thresholds.values()) if thresholds else None,
        "runtime_skips": current_runtime_skips(cfg),
        **cur,
    }
    cfg.baseline.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def integrity_problems(cfg: Config, receipt: dict | None) -> list[str]:
    """给 gate check 与健康度维度共用：返回阻断项列表。"""
    from .adapters import CAP_TESTS, get, has_eval_step
    ad = get(cfg.get("tests.adapter") or "", cfg.root)
    if CAP_TESTS not in ad.caps and not has_eval_step(cfg):
        return []  # 这个生态列不出用例，假绿检测无从谈起（维度里会标未评估）

    cur = scan(cfg)
    if not cur["test_functions"]:
        return ["假绿检测一个用例都没扫到：tests.roots 配错了，检测等于没做"]
    base = load_baseline(cfg)
    if base is None:
        return ['还没有假绿检测基线，跑一次 adone integrity --accept-baseline "建立初始基线"']

    problems = compare(cfg, cur, base)
    if receipt:
        base_skip = base.get("runtime_skips")
        now_skip = receipt.get("tests", {}).get("skip_top")
        if base_skip is not None and now_skip is not None and now_skip > base_skip:
            problems.append(
                f"运行期跳过的顶层用例从 {base_skip} 涨到 {now_skip}，"
                f"新增的跳过要么修掉、要么用 --accept-baseline 记账")
    return problems


def cmd_integrity(cfg: Config, args) -> int:
    cur = scan(cfg)
    if not cur["test_functions"]:
        print("一个用例都没扫到，检测无效（tests.roots / tests.adapter 配对了吗？）",
              file=sys.stderr)
        return 2

    if args.accept_baseline is not None:
        reason = args.accept_baseline.strip()
        if len(reason) < 4:
            print('更新基线必须写理由，例如 --accept-baseline "把 3 个整包跳过的用例改成真跑"',
                  file=sys.stderr)
            return 2
        write_baseline(cfg, cur, reason)
        print(f"基线已更新：{len(cur['test_functions'])} 个用例，"
              f"{sum(cur['skip_sites'].values())} 处跳过，理由「{reason}」")
        return 0

    base = load_baseline(cfg)
    if base is None:
        msg = '还没有基线快照。先跑一次 adone integrity --accept-baseline "建立初始基线"'
        if args.json:
            print(json.dumps({"problems": [msg], "baseline_runtime_skips": None},
                             ensure_ascii=False))
        else:
            print(msg)
        return 1

    problems = compare(cfg, cur, base)
    if args.json:
        print(json.dumps({
            "problems": problems,
            "baseline_runtime_skips": base.get("runtime_skips"),
            "stats": {
                "test_functions": len(cur["test_functions"]),
                "skip_sites": sum(cur["skip_sites"].values()),
                "assertionless": len(cur["assertionless"]),
            },
        }, ensure_ascii=False))
        return 0 if not problems else 1

    if not problems:
        print(f"测试完整性无新增松动："
              f"{len(cur['test_functions'])} 个用例 / "
              f"{sum(cur['skip_sites'].values())} 处跳过 / "
              f"{len(cur['assertionless'])} 个无断言用例（均在基线内）")
        return 0
    print("测试完整性出现新增松动：")
    for p in problems:
        print(f"  - {p}")
    print('\n确属合理改动时，用 --accept-baseline "理由" 记账后再提交。')
    return 1
