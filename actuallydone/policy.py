"""判据锁：门禁自己有多严，也要留档。

树哈希盯的是代码，但「完成」的判据不止代码——受监视范围、门禁步骤的命令、
覆盖率下限、验收契约里绑了几条需求，这些都写在仓库里，也都能改。
改代码让门禁变绿要费力气，改判据让门禁变绿不费吹灰之力，而后者原本一声不吭。

所以这里做的事和假绿检测完全一样：拍一张快照存进基线，之后只报**放松**，
收紧只提示。确属合理的放松，用 `adone policy --accept "理由"` 记账——
谁在什么时候把门槛降到哪儿，一眼可查。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime

from .config import Config

# 这些段落里「条目变少」就意味着检查项变少
CHECK_KEYS = ("consistency.pair", "docs.required", "docs.excerpt", "docs.claim",
              "code.unused", "probe")


def _script_sha(cfg: Config, argv0: str) -> str | None:
    """步骤命令若指向仓库里的脚本，连它的内容一起纳入快照。

    否则「把 go test 换成一个打印完美输出的脚本」这条路仍然无声：argv 一个字没变，
    脚本内容全变了。PATH 上的命令（go、gofmt）不在仓库里，管不着，返回 None。
    """
    p = cfg.root / argv0
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _contracts(cfg: Config) -> dict:
    from .contracts import load_contracts
    out: dict[str, dict] = {}
    for path, data in load_contracts(cfg):
        rel = path.relative_to(cfg.root).as_posix()
        items = data.get("item") or []
        out[rel] = {
            "items": len(items),
            "tests": [str(i.get("test") or "") for i in items],
        }
    return out


def _build_files(cfg: Config) -> dict[str, str]:
    """已配置生态的构建/清单文件指纹。改这些能让测试静默少跑，树哈希却看不见。"""
    from .adapters import REGISTRY
    from .config import PRUNE_DIRS
    out: dict[str, str] = {}
    for name in cfg.get("project.ecosystems") or []:
        cls = REGISTRY.get(str(name).strip().lower())
        if cls is None or not getattr(cls, "markers", ()):
            continue
        for pat in cls.markers:
            for found in sorted(cfg.root.glob(pat)):
                if not found.is_file():
                    continue
                try:
                    rel = found.relative_to(cfg.root)
                except ValueError:
                    continue
                if any(part in PRUNE_DIRS for part in rel.parts):
                    continue
                key = rel.as_posix()
                out[key] = hashlib.sha256(found.read_bytes()).hexdigest()[:16]
    return out


def snapshot(cfg: Config) -> dict:
    steps = []
    for s in cfg.get("gate.step", []) or []:
        argv = list(s.get("argv") or [])
        steps.append({
            "name": s.get("name", ""),
            "kind": s.get("kind", ""),
            "adapter": s.get("adapter", ""),
            "cwd": s.get("cwd", "."),
            "argv": argv,
            "invalid_marks": sorted(s.get("invalid_marks") or []),
            "script": _script_sha(cfg, argv[0]) if argv else None,
        })
    return {
        "watch_roots": sorted(cfg.get("gate.watch_roots") or []),
        "watch_exts": sorted(cfg.get("gate.watch_exts") or []),
        "min_tree_files": int(cfg.get("gate.min_tree_files", 1) or 1),
        "steps": steps,
        "coverage_threshold": cfg.get("coverage.threshold"),
        "coverage_source": cfg.get("coverage.source") or "",
        "tests_adapter": cfg.get("tests.adapter") or "",
        "tests_roots": sorted(cfg.get("tests.roots") or []),
        "baseline_exempt": sorted(cfg.get("tests.baseline_exempt") or []),
        "checks": {k: len(cfg.get(k) or []) for k in CHECK_KEYS},
        "contracts": _contracts(cfg),
        "build_files": _build_files(cfg),
    }


def snapshot_hash(snap: dict) -> str:
    return hashlib.sha256(
        json.dumps(snap, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# --------------------------------------------------------------------------- 比对

def diff(base: dict, cur: dict) -> tuple[list[str], list[str]]:
    """返回（放松，收紧）。放松是阻断项，收紧只报给人看。"""
    loose: list[str] = []
    tight: list[str] = []

    for key, label in (("watch_roots", "受监视目录"), ("watch_exts", "受监视后缀"),
                       ("tests_roots", "测试根")):
        gone = sorted(set(base.get(key) or []) - set(cur.get(key) or []))
        added = sorted(set(cur.get(key) or []) - set(base.get(key) or []))
        if gone:
            loose.append(f"{label}少了 {'、'.join(gone)}：这些文件不再参与判定")
        if added:
            tight.append(f"{label}多了 {'、'.join(added)}")

    b, c = base.get("min_tree_files", 1), cur.get("min_tree_files", 1)
    if c < b:
        loose.append(f"min_tree_files 从 {b} 降到 {c}：扫不到文件时更难被发现")
    elif c > b:
        tight.append(f"min_tree_files 从 {b} 升到 {c}")

    b, c = base.get("coverage_threshold"), cur.get("coverage_threshold")
    if b is not None and c is None:
        loose.append(f"覆盖率下限（原 {b}%）被取消，覆盖率不再参与门禁判定")
    elif b is not None and c is not None and c < b:
        loose.append(f"覆盖率下限从 {b}% 降到 {c}%")
    elif b is None and c is not None:
        tight.append(f"新设了覆盖率下限 {c}%")
    elif b is not None and c is not None and c > b:
        tight.append(f"覆盖率下限从 {b}% 升到 {c}%")

    for key, label in (("tests_adapter", "测试适配器"), ("coverage_source", "覆盖率来源步骤")):
        if base.get(key) != cur.get(key):
            loose.append(f"{label}从「{base.get(key) or '空'}」改成"
                         f"「{cur.get(key) or '空'}」：判定口径变了，说明一下")

    gone = sorted(set(cur.get("baseline_exempt") or []) - set(base.get("baseline_exempt") or []))
    if gone:
        loose.append(f"假绿检测豁免名单新增 {'、'.join(gone)}："
                     f"进了这份名单的用例，假绿检测就看不见它了")

    loose.extend(_diff_steps(base.get("steps") or [], cur.get("steps") or []))
    loose.extend(_diff_contracts(base.get("contracts") or {}, cur.get("contracts") or {}))
    # 老基线没有这个字段就不比：强行比等于逼所有人立刻重记账
    if "build_files" in base:
        loose.extend(_diff_build_files(base.get("build_files") or {},
                                       cur.get("build_files") or {}))

    for k in CHECK_KEYS:
        b, c = (base.get("checks") or {}).get(k, 0), (cur.get("checks") or {}).get(k, 0)
        if c < b:
            loose.append(f"{k} 的检查项从 {b} 条减到 {c} 条")
        elif c > b:
            tight.append(f"{k} 的检查项从 {b} 条加到 {c} 条")
    return loose, tight


def _diff_steps(base: list[dict], cur: list[dict]) -> list[str]:
    loose: list[str] = []
    by_name = {s["name"]: s for s in cur}
    for s in base:
        now = by_name.get(s["name"])
        if now is None:
            loose.append(f"门禁步骤「{s['name']}」被删掉了")
            continue
        if now.get("argv") != s.get("argv"):
            # 命令变了，方向机器判不出来（-run 收窄和多加一个包都是改 argv），一律记账
            loose.append(f"门禁步骤「{s['name']}」的命令变了："
                         f"{' '.join(s.get('argv') or [])} → {' '.join(now.get('argv') or [])}")
        if now.get("kind") != s.get("kind"):
            loose.append(f"门禁步骤「{s['name']}」的 kind 从「{s.get('kind') or '空'}」"
                         f"改成「{now.get('kind') or '空'}」：判定方式变了")
        if now.get("cwd", ".") != s.get("cwd", "."):
            loose.append(f"门禁步骤「{s['name']}」的工作目录从「{s.get('cwd') or '.'}」改成"
                         f"「{now.get('cwd') or '.'}」：跑的可能已经不是同一份代码了")
        if now.get("adapter") != s.get("adapter"):
            loose.append(f"门禁步骤「{s['name']}」的适配器从「{s.get('adapter') or '空'}」"
                         f"改成「{now.get('adapter') or '空'}」：判定口径变了")
        gone = sorted(set(s.get("invalid_marks") or []) - set(now.get("invalid_marks") or []))
        if gone:
            loose.append(f"门禁步骤「{s['name']}」不再把 {'、'.join(gone)} 判为证据无效")
        if s.get("script") and now.get("script") != s.get("script"):
            loose.append(f"门禁步骤「{s['name']}」跑的是仓库内脚本，而脚本内容变了"
                         f"（{s['script']} → {now.get('script')}）")
    return loose


def _diff_build_files(base: dict, cur: dict) -> list[str]:
    loose: list[str] = []
    for rel, sha in sorted(base.items()):
        now = cur.get(rel)
        if now is None:
            loose.append(f"构建文件 {rel} 不见了：它能改变测试跑什么")
        elif now != sha:
            loose.append(f"构建文件 {rel} 的内容变了：它能改变测试跑什么")
    return loose


def _diff_contracts(base: dict, cur: dict) -> list[str]:
    loose: list[str] = []
    for rel, b in sorted(base.items()):
        c = cur.get(rel)
        if c is None:
            loose.append(f"验收契约 {rel} 不见了（{b['items']} 条需求）："
                         f"契约没了不等于需求做完了")
            continue
        if c["items"] < b["items"]:
            loose.append(f"验收契约 {rel} 的条目从 {b['items']} 条减到 {c['items']} 条")
        changed = [(x, y) for x, y in zip(b["tests"], c["tests"]) if x != y]
        if changed:
            shown = "、".join(f"{x}→{y or '空'}" for x, y in changed[:3])
            loose.append(f"验收契约 {rel} 里有 {len(changed)} 条改了绑定的用例：{shown}")
    return loose


# --------------------------------------------------------------------------- 基线

class BaselineBroken(Exception):
    """基线文件在，但读不成。

    这与「还没建立」必须分开：读不成按没有处理的话，把基线改成一段乱码
    就等于悄悄关掉判据锁——而那正是判据锁要防的动作。
    """


def load_baseline(cfg: Config) -> dict | None:
    if not cfg.policy_baseline.exists():
        return None
    try:
        data = json.loads(cfg.policy_baseline.read_text(encoding="utf-8"))
    except Exception as e:
        raise BaselineBroken(f"{cfg.policy_baseline.name} 读不成：{e}") from e
    if not isinstance(data, dict) or "snapshot" not in data:
        raise BaselineBroken(f"{cfg.policy_baseline.name} 里没有 snapshot 段，不像一份基线")
    return data


def write_baseline(cfg: Config, snap: dict, reason: str) -> dict:
    data = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
        "hash": snapshot_hash(snap),
        "snapshot": snap,
    }
    cfg.policy_baseline.parent.mkdir(parents=True, exist_ok=True)
    cfg.policy_baseline.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return data


def ensure_baseline(cfg: Config, receipt: dict | None) -> str:
    """gate run 时调用。返回一句要打印的话（没有就返回空串）。

    首次自动建立，省掉一次「先去跑另一条命令」的折腾；但**绝不替已有的基线重建**——
    那等于给「删掉基线再跑一次」洗白，而删基线正是最省事的绕过。
    """
    try:
        if load_baseline(cfg) is not None:
            return ""
    except BaselineBroken as e:
        return f"判据锁基线读不成（{e}）：这次不替你重建，check 会拦下来。"
    if receipt and (receipt.get("policy") or {}).get("hash"):
        return ("判据锁基线不见了，而上一份回执记着它的指纹——这次不替你重建。"
                "恢复它，或者 adone policy --accept \"理由\" 说明为什么重建。")
    write_baseline(cfg, snapshot(cfg), "首次建立（由 gate run 自动记账）")
    return f"判据锁基线已建立：{cfg.policy_baseline.relative_to(cfg.root)}"


def policy_problems(cfg: Config, receipt: dict | None) -> tuple[list[str], list[str]]:
    """给 gate check 用：返回（问题，依据）。"""
    problems: list[str] = []
    details: list[str] = []
    cur = snapshot(cfg)
    cur_hash = snapshot_hash(cur)
    try:
        base = load_baseline(cfg)
    except BaselineBroken as e:
        return [f"判据锁基线坏了：{e}。恢复它，或者 adone policy --accept 重建并说明原因"], []

    if base is None:
        if receipt and (receipt.get("policy") or {}).get("hash"):
            problems.append(
                f"判据锁基线不见了（上一份回执记着它的指纹 "
                f"{str((receipt.get('policy') or {}).get('hash'))[:12]}）："
                f"门禁有多严这件事失去了对照。恢复它，或者 adone policy --accept 记一笔")
        else:
            details.append('判据锁还没建立（跑一次 adone gate run，或 adone policy --accept "理由"）')
        return problems, details

    loose, tight = diff(base.get("snapshot") or {}, cur)
    for t in tight:
        details.append(f"判据收紧：{t}")
    if loose:
        problems.append("判据被放松且没有记账（adone policy --accept \"理由\"）："
                        + "；".join(loose))
    elif base.get("hash") == cur_hash:
        details.append(f"判据与基线一致 {cur_hash[:12]}"
                       f"（{base.get('created_at', '?')}「{base.get('reason', '')}」）")

    # 回执是在另一套判据下跑出来的：和「跑完门禁再改代码」是同一种事，只不过改的是尺子
    rec_hash = (receipt.get("policy") or {}).get("hash") if receipt else None
    if rec_hash and rec_hash != cur_hash:
        problems.append(f"回执是在另一套判据下跑出来的（回执 {rec_hash[:12]} ≠ 当前 "
                        f"{cur_hash[:12]}）：改完判据要重跑门禁")
    return problems, details


# --------------------------------------------------------------------------- 命令

def cmd_policy(cfg: Config, args) -> int:
    cur = snapshot(cfg)

    if args.accept is not None:
        reason = args.accept.strip()
        if len(reason) < 4:
            print('更新判据基线必须写理由，例如 --accept "把 go vet 并进 build 步骤，命令因此变了"',
                  file=sys.stderr)
            return 2
        data = write_baseline(cfg, cur, reason)
        print(f"判据基线已更新：{data['hash'][:12]}，理由「{reason}」")
        return 0

    try:
        base = load_baseline(cfg)
    except BaselineBroken as e:
        print(f"判据锁基线坏了：{e}", file=sys.stderr)
        return 1
    if base is None:
        msg = ('还没有判据基线。跑一次 adone gate run 会自动建立，'
               '或者 adone policy --accept "建立初始基线"')
        if args.json:
            print(json.dumps({"loosened": [], "tightened": [], "baseline": None},
                             ensure_ascii=False))
        else:
            print(msg)
        return 1

    loose, tight = diff(base.get("snapshot") or {}, cur)
    if args.json:
        print(json.dumps({"loosened": loose, "tightened": tight,
                          "baseline": {"hash": base.get("hash"),
                                       "created_at": base.get("created_at"),
                                       "reason": base.get("reason")},
                          "hash": snapshot_hash(cur)}, ensure_ascii=False))
        return 0 if not loose else 1

    if not loose and not tight:
        print(f"判据与基线一致：{snapshot_hash(cur)[:12]}"
              f"（{base.get('created_at')}「{base.get('reason')}」）")
        return 0
    for t in tight:
        print(f"  [收紧] {t}")
    if not loose:
        print("\n只有收紧，没有放松。要把当前状态记成新基线："
              'adone policy --accept "理由"')
        return 0
    print("判据被放松了：")
    for p in loose:
        print(f"  - {p}")
    print('\n确属合理时，用 adone policy --accept "理由" 记账后再谈完成。')
    return 1
