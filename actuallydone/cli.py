"""命令行入口。

子命令里的重活都是懒导入的：`adone init` 不该因为健康度维度里某个模块出问题而起不来，
而且钩子每次会话都可能被拉起，启动时间是要计较的。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Config, ConfigError

HOOK_STEMS = ("mark-dirty", "gate-guard", "commit-guard")


def _cfg(args) -> Config:
    root = Path(args.root).resolve() if getattr(args, "root", None) else None
    return Config.load(root)


# --------------------------------------------------------------------------- 子命令

def cmd_init(args) -> int:
    from .detect import cmd_init as run
    return run(args)


def cmd_detect(args) -> int:
    from .detect import cmd_detect as run
    return run(args)


def cmd_doctor(args) -> int:
    from .detect import cmd_doctor as run
    return run(_cfg(args), args)


def cmd_gate_run(args) -> int:
    if getattr(args, "changed", False) and (
            getattr(args, "affected", False) or getattr(args, "for_commit", False)):
        print("--changed 与 --affected / --for-commit 不能一起用", file=sys.stderr)
        return 2
    if getattr(args, "changed", False):
        from .changed import cmd_run_changed
        return cmd_run_changed(_cfg(args))
    cfg = _cfg(args)
    affected = bool(getattr(args, "affected", False))
    if getattr(args, "for_commit", False):
        affected = (cfg.get("gate.commit_scope") or "") == "affected"
    from .gate import run_gate
    return run_gate(cfg, skip=args.skip or [], affected=affected)


def cmd_gate_slow(args) -> int:
    from .gate import cmd_gate_slow as run
    return run(_cfg(args), n=args.n or 20)


def cmd_gate_check(args) -> int:
    from .gate import check_gate
    return check_gate(_cfg(args), as_json=args.json, explain=args.explain,
                      with_integrity=not args.no_integrity,
                      spotcheck=args.spotcheck or 0)


def cmd_gate_hash(args) -> int:
    from .gate import tree_hash
    cfg = _cfg(args)
    h, n = tree_hash(cfg)
    print(f"{h}  {n} 个文件")
    return 0


def cmd_gate_contract(args) -> int:
    from .contracts import verify_only
    return verify_only(_cfg(args))


def cmd_gate_waive(args) -> int:
    from .gate import waive_new_tests
    return waive_new_tests(_cfg(args), args.reason)


def cmd_integrity(args) -> int:
    from .integrity import cmd_integrity as run
    return run(_cfg(args), args)


def cmd_policy(args) -> int:
    from .policy import cmd_policy as run
    return run(_cfg(args), args)


def cmd_audit(args) -> int:
    from .audit import cmd_audit as run
    return run(_cfg(args), args)


def cmd_audit_report(args) -> int:
    from .audit import cmd_audit_report as run
    return run(_cfg(args), args)


def cmd_brief(args) -> int:
    from .audit import brief
    return brief(_cfg(args))


def cmd_health(args) -> int:
    from .health import cmd_health as run
    return run(_cfg(args), args)


def cmd_requirements(args) -> int:
    from .ledger import cmd_requirements as run
    return run(_cfg(args), args)


def cmd_install(args) -> int:
    from .install import cmd_install as run
    return run(_cfg(args), args)


def cmd_clean(args) -> int:
    from .clean import cmd_clean as run
    return run(args)


def cmd_upgrade(args) -> int:
    from .upgrade import cmd_upgrade as run
    return run(args)


def cmd_hook(args) -> int:
    from .hookrun import cmd_hook as run
    return run(args)


# --------------------------------------------------------------------------- 装配

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="adone",
        description="ActuallyDone：完成门禁、假绿检测与项目健康度报告",
        epilog="没有配置文件时先跑 adone init。文档：README.md")
    ap.add_argument("--version", action="version", version=f"actuallydone {__version__}")
    ap.add_argument("--root", help="项目根，默认从当前目录往上找 adone.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="探测项目并生成 adone.toml")
    p.add_argument("--force", action="store_true", help="覆盖已存在的配置")
    p.add_argument("--root", help="项目根，默认当前目录")
    p.add_argument("--yes", action="store_true", help="不交互，直接采纳探测结果")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("detect", help="重新探测项目结构（默认只打印，不改配置）")
    p.add_argument("--write", action="store_true", help="整份覆盖写入 adone.toml（已有配置会丢）")
    p.add_argument("--merge", action="store_true",
                   help="增量合并进已有 adone.toml：追加新步骤、补数组键，不碰阈值")
    p.add_argument("--dry-run", action="store_true", help="和 --merge 一起：只打印摘要，不落盘")
    p.add_argument("--adopt-tests", action="store_true",
                   help="和 --merge 一起：把 tests.adapter / coverage.source 改成探测结果")
    p.add_argument("--root", help="项目根")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("doctor", help="拿配置对现实核一遍")
    p.set_defaults(func=cmd_doctor)

    p_gate = sub.add_parser("gate", help="完成门禁：执行检查并产出回执")
    gsub = p_gate.add_subparsers(dest="sub", required=True)

    g = gsub.add_parser("run", help="跑全量门禁并写回执")
    g.add_argument("--skip", action="append", metavar="步骤名",
                   help="跳过某一步（回执会被标记为不完整，check 仍会拒绝）")
    g.add_argument("--changed", action="store_true",
                   help="只跑与 dirty / git diff 相关的用例，写 partial.json，不覆盖 latest.json")
    g.add_argument("--affected", action="store_true",
                   help="只跑相对上一份全量绿回执变过的模块（Maven -pl/-amd），"
                        "其余从那份回执继承。没有可继承的全量回执会拒绝")
    g.add_argument("--for-commit", action="store_true",
                   help="提交钩子用：按 gate.commit_scope 决定全量还是 --affected")
    g.set_defaults(func=cmd_gate_run)

    g = gsub.add_parser("check", help="校验回执是否新鲜且全绿")
    g.add_argument("--json", action="store_true", help="供钩子消费")
    g.add_argument("--explain", action="store_true", help="附带每一步的判定依据")
    g.add_argument("--no-integrity", action="store_true", help="不跑假绿检测")
    g.add_argument("--spotcheck", nargs="?", type=int, const=2, default=0,
                   metavar="N",
                   help="抽 N 条（默认 2）回执里声称通过的用例当场真跑一遍；"
                        "默认不开，交付前或 CI 里显式开")
    g.set_defaults(func=cmd_gate_check)

    g = gsub.add_parser("hash", help="打印当前受监视代码树的哈希")
    g.set_defaults(func=cmd_gate_hash)

    g = gsub.add_parser("slow", help="读最近一轮测试报告，打印最慢的用例和模块")
    g.add_argument("-n", type=int, default=20, metavar="N",
                   help="列出最慢的 N 条，默认 20")
    g.set_defaults(func=cmd_gate_slow)

    g = gsub.add_parser("verify-contract", help="只校验验收契约")
    g.set_defaults(func=cmd_gate_contract)

    g = gsub.add_parser("waive-tests",
                        help="人来豁免这一次「实现变了但测试没变」，绑在当前实现哈希上")
    g.add_argument("reason", help="理由，写给人看；实现再变则失效")
    g.set_defaults(func=cmd_gate_waive)

    p = sub.add_parser("integrity", help="假绿检测：抓「把门禁改绿」而不是「把代码改对」")
    p.add_argument("--json", action="store_true")
    p.add_argument("--accept-baseline", metavar="理由",
                   help="把当前状态记为新基线，理由会连同时间一起入账")
    p.set_defaults(func=cmd_integrity)

    p = sub.add_parser("policy", help="判据锁：门禁自己有没有被悄悄放松")
    p.add_argument("--json", action="store_true")
    p.add_argument("--accept", metavar="理由",
                   help="把当前判据记为新基线，理由会连同时间一起入账")
    p.set_defaults(func=cmd_policy)

    p = sub.add_parser("audit", help="独立复核：给另一个模型用的那条命令（默认开抽查）")
    p.add_argument("--rerun", action="store_true",
                   help="不信任实现者的回执，自己把门禁全量跑一遍再比对；"
                        "产物只写 audits/，不覆盖 latest.json 与证据链")
    p.add_argument("--spotcheck", type=int, default=None, metavar="N",
                   help="抽 N 条契约绑定的用例当场真跑，默认 2；0 表示不抽")
    p.add_argument("--brief", action="store_true", help="只打印复核者简报，不做检查")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", help="HTML 报告路径，默认 <state_dir>/audit.html")
    p.add_argument("--open", action="store_true", help="生成后打开 HTML")
    p.add_argument("--reviewer", metavar="模型名",
                   help="复核者的模型。与回执 runner.model 相同则判不通过；缺一边只记入依据")
    p.set_defaults(func=cmd_audit)
    asub = p.add_subparsers(dest="audit_cmd")
    r = asub.add_parser("report", help="把已有审计结论渲成一页 HTML，不重跑检查")
    r.add_argument("--out", help="报告路径，默认 <state_dir>/audit.html")
    r.add_argument("--open", action="store_true", help="生成后打开")
    r.set_defaults(func=cmd_audit_report)

    p = sub.add_parser("brief", help="复核者冷启动简报：该读什么、跑什么、不许动什么")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("health", help="体检：六个维度汇成一页 HTML")
    p.add_argument("--all", action="store_true", help="重跑全量门禁，而不是读最新回执")
    p.add_argument("--only", help="只跑这些维度，逗号分隔")
    p.add_argument("--skip", help="排除这些维度，逗号分隔")
    p.add_argument("--with-probes", action="store_true",
                   help="加跑自定义探针（可能要服务在跑、可能会写库）")
    p.add_argument("--list", action="store_true", help="列出维度与各自成本")
    p.add_argument("--json", action="store_true", help="结果打到 stdout")
    p.add_argument("--out", help="报告路径，默认 <state_dir>/report.html")
    p.add_argument("--open", action="store_true", help="生成后打开")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("requirements", help="需求台账")
    rsub = p.add_subparsers(dest="sub", required=True)
    r = rsub.add_parser("init", help="从需求源生成台账骨架")
    r.add_argument("--force", action="store_true", help="覆盖已存在的台账")
    r.set_defaults(func=cmd_requirements)
    r = rsub.add_parser("check", help="核验台账里的证据锚点")
    r.set_defaults(func=cmd_requirements)

    p = sub.add_parser("install", help="把技能与钩子模板装进项目")
    p.add_argument("--target", default="cursor", choices=["cursor", "dir"],
                   help="装到哪个 Agent 平台；dir 表示只写到 --skills-dir")
    p.add_argument("--ide", default="auto", choices=["auto", "cursor", "qoder", "all"],
                   help="钩子装到哪个 IDE：auto 看不出 Qoder 就只装 Cursor；"
                        "qoder 只写 .qoder/，不碰 .cursor/")
    p.add_argument("--skills-dir", help="覆盖配置里的技能目录")
    p.add_argument("--with-hooks", action="store_true", help="同时写入钩子配置")
    p.add_argument("--hooks-only", action="store_true",
                   help="只重装钩子，一个技能文件都不碰（隐含 --with-hooks）；"
                        "换了 adone 的装法之后重渲钩子用这个，别拿 --force 冲掉技能里的项目私货")
    p.add_argument("--only", help="只装这几个技能，逗号分隔")
    p.add_argument("--force", action="store_true", help="覆盖已存在的技能文件")
    p.add_argument("--dry-run", action="store_true", help="只说要做什么，不落盘")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("clean", help="拆除当前项目里的 ActuallyDone（和 init 配套）")
    p.add_argument("--root", help="项目根，默认从当前目录往上找 adone.toml")
    p.add_argument("--yes", action="store_true", help="不交互，直接拆")
    p.add_argument("--dry-run", action="store_true", help="只说要删什么，不落盘")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("hook", help="给 Agent 钩子调用：逻辑在包里，不在平台目录的 .py 里")
    p.add_argument("hook", choices=["mark-dirty", "gate-guard", "commit-guard"],
                   help="记 dirty 用 mark-dirty，stop/Stop 用 gate-guard，"
                        "拦 git commit 用 commit-guard")
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("upgrade", help="从 GitHub 拉最新版并覆盖当前安装")
    p.add_argument("--check", action="store_true",
                   help="只报告有没有新版本：0=已最新 / 1=有新版 / 2=查不到")
    p.add_argument("--ref", metavar="tag|branch",
                   help="装指定的 tag 或分支，而不是最新")
    p.add_argument("--force", action="store_true",
                   help="允许降级，或在脏的 git 工作树上强制更新")
    p.add_argument("--dry-run", action="store_true", help="只说要做什么，不执行")
    p.set_defaults(func=cmd_upgrade)

    return ap


def main(argv: list[str] | None = None) -> int:
    from .textio import force_utf8_stdio
    force_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Windows 上 hooks.json 只能写一条 .exe 路径：CreateProcess 不能直接跑 .cmd。
    # 安装时把 adone.exe 复制成 .cursor/hooks/gate-guard.exe，这里按文件名分发。
    stem = Path(sys.argv[0]).stem.lower()
    if stem in HOOK_STEMS and (not argv or argv[0] != "hook"):
        argv = ["hook", stem, *argv]
    ap = build_parser()
    args = ap.parse_args(argv)
    from .upgrade import maybe_offer_upgrade
    offered = maybe_offer_upgrade(args)
    if offered is not None:
        return offered
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"配置有问题：{e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
