"""探测：扫仓库猜结构，生成一份**带注释、逐项标注「请确认」**的 adone.toml。

探测**不猜阈值**。覆盖率下限、树文件数下限这类数字留空并写清为什么：
一个凭空写下的 80% 会让所有人以为这是团队的约定，其实只是工具编的。
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import REGISTRY, detect_all, get
from .config import CONFIG_NAME, PRUNE_DIRS, Config

# 常见文档位置，命中即作为 AI 物料的必备件候选
DOC_CANDIDATES = ("AGENT.md", "AGENTS.md", "CLAUDE.md", "README.md",
                  "docs/README.md", "docs/architecture.md", "blueprint/AGENT.md",
                  "blueprint/README.md")
IGNORE_DIRS = PRUNE_DIRS


@dataclass
class Detected:
    root: Path
    ecosystems: dict[str, str] = field(default_factory=dict)   # 生态 -> 所在目录
    steps: list[dict] = field(default_factory=list)
    watch_roots: list[str] = field(default_factory=list)
    watch_exts: list[str] = field(default_factory=list)
    tests_adapter: str = ""
    tests_roots: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    source_encoding: str = "auto"
    skills_dir: str = ""
    hooks_file: str = ""
    notes: list[str] = field(default_factory=list)


def top_dirs(root: Path) -> list[Path]:
    return [d for d in sorted(root.iterdir())
            if d.is_dir() and d.name not in IGNORE_DIRS and not d.name.startswith(".")]


def detect(root: Path) -> Detected:
    got = Detected(root=root)
    hits = detect_all(root)

    for eco, markers in hits.items():
        # 标志文件所在目录就是这个生态的根：monorepo 里 backend/go.mod → backend
        d = str(Path(markers[0]).parent)
        d = "." if d == "." else d
        got.ecosystems[eco] = d

    for eco, d in got.ecosystems.items():
        ad = get(eco, root)
        got.steps.extend(ad.suggest_steps(d))
        roots, exts = ad.suggest_watch(d)
        got.watch_roots.extend(r for r in roots if (root / r).is_dir())
        got.watch_exts.extend(exts)

    got.watch_exts = sorted(set(got.watch_exts))
    got.watch_roots = sorted(set(got.watch_roots))

    # 测试适配器取「有测试文件的那个生态」，多个时取测试文件最多的
    best, best_n = "", 0
    for eco, d in got.ecosystems.items():
        ad = get(eco, root)
        n = len(ad.test_files([root / d]))
        if n > best_n:
            best, best_n = eco, n
    if best:
        got.tests_adapter = best
        got.tests_roots = [got.ecosystems[best]]
        got.notes.append(f"测试适配器选了 {best}（在 {got.ecosystems[best]} 下找到 {best_n} 个测试文件）")
    else:
        got.notes.append("没找到任何测试文件：假绿检测与验收契约核验都会失效，需要手工配 [tests]")

    got.docs = [c for c in DOC_CANDIDATES if (root / c).exists()]

    for cand in (".cursor/skills", ".claude/skills", ".qoder/skills"):
        if (root / cand).is_dir():
            got.skills_dir = cand
            break
    got.skills_dir = got.skills_dir or ".cursor/skills"
    if (root / ".cursor" / "hooks.json").exists():
        got.hooks_file = ".cursor/hooks.json"

    got.source_encoding = _sniff_encoding(got)

    if not got.ecosystems:
        got.notes.append("一个生态都没认出来（找不到 go.mod / package.json / "
                         "pyproject.toml / pom.xml / build.gradle / CMakeLists.txt）："
                         "门禁步骤要手工填")
    return got


def _sniff_encoding(got: Detected) -> str:
    """按受监视树采样判断源码编码。看不出来就 auto，不替用户下结论。"""
    from .textio import sniff
    files: list[Path] = []
    exts = {e if e.startswith(".") else f".{e}" for e in got.watch_exts}
    for r in (got.watch_roots or ["."]):
        base = got.root / r
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for fn in filenames:
                if not exts or os.path.splitext(fn)[1] in exts:
                    files.append(Path(dirpath) / fn)
            if len(files) > 400:
                break
        if len(files) > 400:
            break
    enc, tally = sniff(files)
    if tally["gbk"]:
        got.notes.append(
            f"源码里有 {tally['gbk']} 个文件不是 UTF-8（能按 GBK 解）："
            f"project.source_encoding 写成 {enc}")
    elif tally["unknown"]:
        got.notes.append(
            f"{tally['unknown']} 个文件 UTF-8 和 GBK 都解不动："
            f"source_encoding 留成 auto，逐个文件试")
    return enc


# --------------------------------------------------------------------------- 生成配置

def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def arr(items) -> str:
    return "[" + ", ".join(q(str(i)) for i in items) + "]"


def render_config(got: Detected) -> str:
    L: list[str] = []
    a = L.append
    a("# ActuallyDone 配置。带「请确认」的项是探测猜的，请逐条核对。")
    a("# 阈值一律没有默认值——工具不替你决定质量标准。")
    a("")
    a("version = 1")
    a("")
    a("[project]")
    a(f"name = {q(got.root.name)}")
    a(f"ecosystems = {arr(got.ecosystems)}    # 请确认：探测所得")
    a('state_dir = ".adone"       # 机器写的：回执、覆盖率 profile、报告')
    a('material_dir = "adone"     # 人写的：验收契约、需求台账')
    a(f"skills_dir = {q(got.skills_dir)}")
    a("# 源码解不动 UTF-8 时按什么解：utf-8 / gbk / auto（auto 再加本机编码）。")
    a("# UTF-8 永远先试，逐个文件判断。只影响读文本的检查；")
    a("# 回执的树哈希按字节算，与这一项无关。")
    a(f"source_encoding = {q(got.source_encoding)}    # 请确认：探测所得")
    a("")
    a("[gate]")
    a("# 受监视代码树：回执的树哈希由这些文件的内容算出。改了这里面任何文件，回执即过期。")
    a(f"watch_roots = {arr(got.watch_roots)}    # 请确认：探测所得")
    a(f"watch_exts = {arr(got.watch_exts)}")
    a("# 扫到的文件数低于这个值就直接报错：空哈希会让门禁恒等通过。")
    a("# 首次跑 adone gate hash 看看实际数字，填一个略低于它的值。")
    a("min_tree_files = 1         # 请确认：这是最宽松的值，等于没有保护")
    a("keep_receipts = 20")
    a("")
    if got.steps:
        a("# 门禁步骤：按顺序执行，任何一步不过，回执就不是绿的。")
        a("# kind = \"test\" 的步骤会用 adapter 解析输出；kind = \"fmt\" 的步骤有输出即失败")
        a("# （格式化工具往往永远退出 0）。{cover_out} 会被替换成 <state_dir>/cover.out。")
        for s in got.steps:
            a("[[gate.step]]")
            a(f"name = {q(s['name'])}")
            a(f"cwd = {q(s.get('cwd', '.'))}")
            a(f"argv = {arr(s['argv'])}")
            if s.get("kind"):
                a(f"kind = {q(s['kind'])}")
            if s.get("adapter"):
                a(f"adapter = {q(s['adapter'])}")
            if s.get("kind") == "test":
                a("# 输出里出现这些串就判本轮证据无效（例如整批用例因为连不上数据库被跳过）")
                a("invalid_marks = []")
            a("")
    else:
        a("# 没探测到任何可执行的步骤，请手工补，例如：")
        a("# [[gate.step]]")
        a('# name = "构建"')
        a('# cwd = "."')
        a('# argv = ["make", "build"]')
        a("")
    a("[coverage]")
    a("# 先跑一次 adone gate run 看实际覆盖率，再把下限填成「当前水位」并注明这是水位不是许愿。")
    a("# threshold = 0.0")
    cov_src = next((s["name"] for s in got.steps if s.get("kind") == "test"), "")
    if not cov_src and got.steps:
        cov_src = got.steps[0]["name"]
    a(f"source = {q(cov_src)}   # 从哪一步的输出里读覆盖率")
    a("")
    a("[tests]")
    a(f"adapter = {q(got.tests_adapter)}    # 请确认：探测所得")
    a(f"roots = {arr(got.tests_roots)}")
    a("# 声明了覆盖率下限的文档，纳入假绿检测（防止有人偷偷把文档里的标准调低）")
    a("threshold_docs = []")
    a("")
    a("[code]")
    a("big_file_lines = 800")
    a(f"big_file_globs = {arr([f'{r}/**/*{e}' for r in got.watch_roots[:2] for e in got.watch_exts[:2]])}")
    a(f"mark_globs = {arr([f'{r}/**/*{got.watch_exts[0]}' for r in got.watch_roots[:1]] if got.watch_exts else [])}")
    a('mark_words = ["TODO", "FIXME", "XXX", "HACK"]')
    a("dup_min_lines = 8")
    a(f"dup_roots = {arr(got.watch_roots)}")
    a("zero_cover_ratio = 0.15")
    a("")
    a("# 定义了却没人引用的符号。用「定义正则 + 使用正则」表达，与语言无关：")
    a("# [[code.unused]]")
    a('# name = "未注册 handler"')
    a('# glob = "internal/api/*.go"')
    a('# define = "^func \\\\(h \\\\*Handler\\\\) ([a-z]\\\\w*)\\\\("')
    a('# use = "h\\\\.([a-z]\\\\w*)\\\\b"')
    a("")
    a("# 两份都自称权威全量的文件，必须完全一致（例如程序内迁移与绿地建库脚本）：")
    a("# [[consistency.pair]]")
    a('# a = "internal/migrate/migrate.go"')
    a('# b = "deploy/schema.sql"')
    a('# extract = "sql_tables"')
    a("")
    a("[docs]")
    a(f"required = {arr(got.docs)}    # 请确认：探测所得")
    a('diagram_globs = []          # 例如 ["docs/diagrams/*.mmd"]，会检查渲染图是否比源文件旧')
    a('diagram_render_ext = ".svg"')
    a('adr_dir = ""                # 决策记录目录，供 adr: 锚点核验')
    a(f"hooks_file = {q(got.hooks_file)}")
    a("")
    a("# 文档是选摘：只查「文档里写了、代码里没有」的幻影，不要求反向全覆盖")
    a("# [[docs.excerpt]]")
    a('# file = "docs/schema.sql"')
    a('# extract = "sql_tables"')
    a('# against = "internal/migrate/migrate.go"')
    a("")
    a("# 文档里写死的数字与现实对账")
    a("# [[docs.claim]]")
    a('# file = "docs/schema.sql"')
    a('# pattern = "全量 DDL（(\\\\d+) 张表）"')
    a('# actual = "count:sql_tables:internal/migrate/migrate.go"')
    a("")
    a("[requirements]")
    a('source = ""                 # 需求源文档（markdown 标题 + 列表），供 requirements init 解析')
    a('tables_from = ""            # table: 锚点的事实来源')
    a('routes_from = ""            # route: 锚点的事实来源（源码目录）')
    a('views_from = ""             # view: 锚点的事实来源（前端源码目录）')
    a("")
    a("# 业务不变量探针：跑起来的系统里，那条业务规则还成立吗。默认不跑。")
    a("# [[probe]]")
    a('# name = "下单不会超卖"')
    a('# argv = ["python3", "scripts/probe_oversell.py"]')
    a('# pass_pattern = "PASS"')
    a('# fail_pattern = "FAIL"')
    return "\n".join(L) + "\n"


def _render_step(s: dict) -> str:
    L = [
        "[[gate.step]]",
        f"name = {q(s['name'])}",
        f"cwd = {q(s.get('cwd', '.'))}",
        f"argv = {arr(s['argv'])}",
    ]
    if s.get("kind"):
        L.append(f"kind = {q(s['kind'])}")
    if s.get("adapter"):
        L.append(f"adapter = {q(s['adapter'])}")
    if s.get("kind") == "test":
        L.append("# 输出里出现这些串就判本轮证据无效（例如整批用例因为连不上数据库被跳过）")
        L.append("invalid_marks = []")
    return "\n".join(L) + "\n"


def _section_span(text: str, section: str) -> tuple[int, int] | None:
    m = re.search(rf"^\[{re.escape(section)}]\s*$", text, re.M)
    if not m:
        return None
    nxt = re.search(r"^\[", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return m.start(), end


def _patch_array_key(text: str, section: str, key: str,
                     add: list[str]) -> tuple[str, str | None, list[str]]:
    """就地改 [section] 里单行 key = [...] 。折成多行的不猜，报成待办。

    返回 (新文本, 待办或 None, 实际新增的值)。
    """
    span = _section_span(text, section)
    if span is None:
        return text, f"[{section}] 段不存在，没法补 {key}", []
    start, end = span
    block = text[start:end]
    m = re.search(rf"^({re.escape(key)}\s*=\s*)\[(.*)\](.*)$", block, re.M)
    if not m:
        if re.search(rf"^{re.escape(key)}\s*=", block, re.M):
            return text, f"[{section}].{key} 不是单行数组，请手工补 {add}", []
        # 段在，键不在：插到段末
        insert = f"{key} = {arr(add)}\n"
        return text[:end] + insert + text[end:], None, list(add)
    try:
        existing = json.loads("[" + m.group(2) + "]")
    except json.JSONDecodeError:
        return text, f"[{section}].{key} 解析失败，请手工补 {add}", []
    if not isinstance(existing, list):
        return text, f"[{section}].{key} 不是数组，请手工补 {add}", []
    new, added = list(existing), []
    for item in add:
        if item not in new:
            new.append(item)
            added.append(item)
    if not added:
        return text, None, []
    patched = block[:m.start()] + f"{m.group(1)}{arr(new)}{m.group(3)}" + block[m.end():]
    return text[:start] + patched + text[end:], None, added


def merge_config(existing: str, got: Detected, adopt_tests: bool = False
                 ) -> tuple[str, list[str]]:
    """把探测到的新生态增量写进已有 adone.toml。不碰阈值，除非 --adopt-tests。"""
    from .config import Config
    cfg = Config.from_dict(got.root, {})
    try:
        raw = __import__("tomllib").loads(existing)
        cfg = Config.from_dict(got.root, raw)
    except Exception as e:
        return existing, [f"现有 adone.toml 解析失败，拒绝合并：{e}"]

    notes: list[str] = []
    text = existing if existing.endswith("\n") else existing + "\n"
    have_steps = cfg.get("gate.step", []) or []
    have_keys = {(s.get("name"), tuple(s.get("argv") or [])) for s in have_steps}
    appended: list[str] = []
    for s in got.steps:
        key = (s.get("name"), tuple(s.get("argv") or []))
        if key in have_keys:
            continue
        text = text.rstrip() + "\n\n" + _render_step(s)
        appended.append(s["name"])
        have_keys.add(key)
    if appended:
        notes.append(f"追加门禁步骤：{'、'.join(appended)}")
    else:
        notes.append("门禁步骤没有新增（已有步骤的 name+argv 对得上）")

    for section, key, values in (
        ("project", "ecosystems", list(got.ecosystems)),
        ("gate", "watch_roots", got.watch_roots),
        ("gate", "watch_exts", got.watch_exts),
    ):
        text, issue, added = _patch_array_key(text, section, key, values)
        if issue:
            notes.append(f"待办：{issue}")
        elif added:
            notes.append(f"[{section}].{key} 补了 {added}")

    if adopt_tests and got.tests_adapter:
        # 只在显式要求时改测试适配器，否则 integrity / policy 会立刻报放松
        text, issue, _ = _patch_scalar(text, "tests", "adapter", got.tests_adapter)
        if issue:
            notes.append(f"待办：{issue}")
        else:
            notes.append(f"tests.adapter 改成 {got.tests_adapter}（--adopt-tests）")
        if got.tests_roots:
            text, issue, added = _patch_array_key(text, "tests", "roots", got.tests_roots)
            if issue:
                notes.append(f"待办：{issue}")
            elif added:
                notes.append(f"[tests].roots 补了 {added}")
        test_step = next((s["name"] for s in got.steps if s.get("kind") == "test"), "")
        if test_step:
            text, issue, _ = _patch_scalar(text, "coverage", "source", test_step)
            if issue:
                notes.append(f"待办：{issue}")
            else:
                notes.append(f"coverage.source 改成 {test_step}（--adopt-tests）")
    else:
        cur_ad = cfg.get("tests.adapter") or ""
        new_ecos = [e for e in got.ecosystems if e not in set(cfg.ecosystems)]
        if got.tests_adapter and got.tests_adapter != cur_ad:
            notes.append(f"建议：探测到测试适配器 {got.tests_adapter}，"
                         f"要改 tests.adapter 请加 --adopt-tests "
                         f"（会让假绿基线与判据锁对不上，随后要重新记账）")
        elif new_ecos:
            notes.append(f"建议：新探测到 {'、'.join(new_ecos)}，"
                         f"要改 tests.adapter 请加 --adopt-tests "
                         f"（会让假绿基线与判据锁对不上，随后要重新记账）")

    return text if text.endswith("\n") else text + "\n", notes


def _patch_scalar(text: str, section: str, key: str,
                  value: str) -> tuple[str, str | None, bool]:
    span = _section_span(text, section)
    if span is None:
        return text, f"[{section}] 段不存在，没法改 {key}", False
    start, end = span
    block = text[start:end]
    m = re.search(rf"^({re.escape(key)}\s*=\s*)(.*)$", block, re.M)
    if not m:
        insert = f"{key} = {q(value)}\n"
        return text[:end] + insert + text[end:], None, True
    if "\n" in m.group(2).strip():
        return text, f"[{section}].{key} 不是单行，请手工改成 {value}", False
    patched = block[:m.start()] + f"{m.group(1)}{q(value)}" + block[m.end():]
    return text[:start] + patched + text[end:], None, True


def _merge_followup(got: Detected, adopt_tests: bool) -> list[str]:
    lines = [
        "合并之后按这个顺序走：",
        "  1. 核对新增的 [[gate.step]]（命令、cwd、adapter）",
        "  2. adone doctor",
        "  3. adone gate run   # 拿实测覆盖率回填 coverage.threshold",
    ]
    if adopt_tests and got.tests_adapter:
        lines.append(f'  4. adone integrity --accept-baseline "切到 {got.tests_adapter} 适配器"')
        lines.append('  5. adone policy --accept "接入 java 门禁步骤"')
        lines.append("  6. 已装钩子的话：adone install --hooks-only --force")
    else:
        lines.append('  4. adone policy --accept "接入新的门禁步骤"')
        lines.append("  5. 已装钩子的话：adone install --hooks-only --force")
    return lines


# --------------------------------------------------------------------------- 命令

def cmd_detect(args) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    merge = getattr(args, "merge", False)
    write = getattr(args, "write", False)
    dry = getattr(args, "dry_run", False)
    adopt = getattr(args, "adopt_tests", False)
    if merge and write:
        print("--merge 与 --write 互斥：--write 整份覆盖，--merge 只增量追加", file=sys.stderr)
        return 2
    if adopt and not merge:
        print("--adopt-tests 只能和 --merge 一起用", file=sys.stderr)
        return 2
    if dry and not merge:
        print("--dry-run 只能和 --merge 一起用", file=sys.stderr)
        return 2

    got = detect(root)
    print(f"探测 {root}：")
    print(f"  生态：{'、'.join(f'{k}（{v}）' for k, v in got.ecosystems.items()) or '未识别'}")
    print(f"  门禁步骤：{'、'.join(s['name'] for s in got.steps) or '无'}")
    print(f"  受监视：{'、'.join(got.watch_roots) or '无'}  后缀 {' '.join(got.watch_exts)}")
    print(f"  测试：适配器 {got.tests_adapter or '无'}，根 {'、'.join(got.tests_roots) or '无'}")
    print(f"  文档：{'、'.join(got.docs) or '无'}")
    print(f"  源码编码：{got.source_encoding}")
    for n in got.notes:
        print(f"  · {n}")

    if merge:
        return _cmd_merge(root, got, dry=dry, adopt=adopt)
    if write:
        path = root / CONFIG_NAME
        path.write_text(render_config(got), encoding="utf-8")
        print(f"\n已写入 {path}（带「请确认」标记，请逐条核对）")
        return 0
    print("\n（只是探测，没有写配置；要写加 --write，已有配置要增量加 --merge）")
    return 0


def _cmd_merge(root: Path, got: Detected, *, dry: bool, adopt: bool) -> int:
    path = root / CONFIG_NAME
    if not path.is_file():
        print(f"{path} 不存在，没有可合并的配置。新项目请用 adone init 或 adone detect --write",
              file=sys.stderr)
        return 2
    old = path.read_text(encoding="utf-8")
    new, notes = merge_config(old, got, adopt_tests=adopt)
    print("\n合并摘要：")
    for n in notes:
        print(f"  · {n}")
    if old == new:
        print("配置没有变化。")
        return 0
    if dry:
        print("\n（演练，没有落盘）")
        return 0
    bak = path.with_suffix(path.suffix + ".bak")
    bak.write_text(old, encoding="utf-8")
    path.write_text(new, encoding="utf-8")
    print(f"\n已写入 {path}（备份 {bak.name}）")
    for line in _merge_followup(got, adopt):
        print(line)
    return 0


def cmd_init(args) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    path = root / CONFIG_NAME
    if path.exists() and not args.force:
        print(f"{path} 已存在（要覆盖加 --force）", file=sys.stderr)
        return 2

    got = detect(root)
    print(f"探测 {root}：")
    print(f"  生态：{'、'.join(f'{k}（{v}）' for k, v in got.ecosystems.items()) or '未识别'}")
    print(f"  门禁步骤：{'、'.join(s['name'] for s in got.steps) or '无（要手工填）'}")
    for n in got.notes:
        print(f"  · {n}")

    if not args.yes and sys.stdin.isatty():
        ans = input("\n采纳这份探测结果并写入 adone.toml？[Y/n] ").strip().lower()
        if ans and ans not in ("y", "yes"):
            print("已取消。")
            return 1

    path.write_text(render_config(got), encoding="utf-8")
    (root / ".adone").mkdir(exist_ok=True)
    from .config import Config
    from .gate import ensure_chain_merge
    if ensure_chain_merge(Config.load(root)):
        print("  已写 .gitattributes：证据链和豁免记录合并时两边都留")
    print(f"\n已写入 {path.relative_to(root)}。接下来：")
    print("  1. 逐条核对带「请确认」的项，特别是 min_tree_files 与 coverage.threshold")
    print("  2. adone doctor         拿配置对现实核一遍")
    print("  3. adone gate run       跑一次门禁，看实际覆盖率，再回填 threshold")
    print('  4. adone integrity --accept-baseline "建立初始基线"')
    # 写 install 而不写 install --with-hooks，照着做的人会以为钩子装上了，其实没有
    print("  5. adone install --with-hooks   装技能与钩子（Cursor）")
    return 0


def cmd_doctor(cfg: Config, args) -> int:
    print(f"体检配置 {cfg.path}：\n")
    problems = cfg.problems()

    # 命令能不能跑得动：路径配对了但工具没装，跑门禁时才发现太晚。
    # 必须与 gate.run_step 用同一个解析函数，否则会出现「体检通过、门禁说命令不存在」
    from .gate import resolve_cmd
    for s in cfg.get("gate.step", []) or []:
        argv = s.get("argv") or []
        if not argv:
            continue
        cwd = cfg.root / (s.get("cwd") or ".")
        if not cwd.is_dir():
            problems.append(f"gate.step「{s.get('name')}」的 cwd 目录不存在："
                            f"{s.get('cwd') or '.'}")
            continue
        if resolve_cmd(argv[0], cwd) is None:
            problems.append(f"gate.step「{s.get('name')}」的命令 {argv[0]} 跑不起来："
                            f"PATH 与 {s.get('cwd') or '.'} 下都没找到可执行的它")

    from .adapters import REGISTRY as R
    eco = cfg.ecosystems
    unknown = [e for e in eco if e not in R]
    if unknown:
        problems.append(f"project.ecosystems 里有不认识的生态：{'、'.join(unknown)}，"
                        f"可用：{'、'.join(R)}")

    try:
        from .gate import (find_full_receipt, inheritable_full, tree_hash,
                           unit_file_counts, unit_hashes)
        h, n = tree_hash(cfg)
        print(f"  受监视代码树：{n} 个文件，哈希 {h[:12]}")
        floor = int(cfg.get("gate.min_tree_files", 1) or 1)
        if floor <= 1 and n > 20:
            problems.append(f"min_tree_files 还是 {floor}（等于没有保护），"
                            f"当前实测 {n} 个文件，建议填一个略低于它的值")
        counts = unit_file_counts(cfg)
        print(f"  单元：{len(counts)} 个 watch_roots")
        for unit, cn in counts.items():
            print(f"    {unit}：{cn} 个文件")
        can_scope = False
        from .adapters import get as get_scope_ad
        for spec in cfg.get("gate.step") or []:
            if spec.get("kind") != "test":
                continue
            ad_s = get_scope_ad(spec.get("adapter") or cfg.get("tests.adapter") or "",
                                cfg.root)
            scoped = ad_s.scoped_test_argv(
                list(spec.get("argv") or []), list(unit_hashes(cfg)),
                cwd=cfg.root / (spec.get("cwd") or "."))
            if scoped is not None:
                can_scope = True
                break
        if can_scope:
            print("  缩范围：当前测试步骤支持 --affected（Maven -pl/-amd）")
        else:
            print("  缩范围：当前适配器/构建工具不会按模块缩范围"
                  "（Gradle 没有 -amd）。--affected 会被拒绝")
        want_affected = (cfg.get("gate.commit_scope") or "") == "affected"
        if want_affected and not can_scope:
            problems.append("gate.commit_scope 是 affected，但当前适配器不会缩范围："
                            "提交时 --for-commit 会拒绝。改回全量或换成 Maven")
        src, err = inheritable_full(cfg)
        if want_affected:
            if err:
                problems.append(err)
            elif src is not None:
                print(f"  可继承全量回执：{src.get('id')}")
        else:
            full = find_full_receipt(cfg)
            if full and full.get("units"):
                print(f"  可继承全量回执：{full.get('id')}（要用 --affected 先设 "
                      f"gate.commit_scope = \"affected\"）")
            else:
                print("  可继承全量回执：还没有（先跑一次 adone gate run）")
    except Exception as e:
        problems.append(str(e))

    from .adapters import get as get_ad
    ad = get_ad(cfg.get("tests.adapter") or "", cfg.root)
    names = ad.test_names([cfg.root / r for r in (cfg.get("tests.roots") or [])])
    if names is None:
        print("  测试：当前适配器列不出用例名，验收契约与假绿检测无法核验")
    else:
        print(f"  测试：扫到 {len(names)} 个用例名")
        if not names:
            problems.append("tests.roots 下一个用例都没扫到，假绿检测等于没做")

    if cfg.baseline.exists():
        print(f"  假绿基线：{cfg.baseline.relative_to(cfg.root)}")
    else:
        problems.append('还没有假绿检测基线，跑 adone integrity --accept-baseline "建立初始基线"')

    from .policy import BaselineBroken, load_baseline
    try:
        pol = load_baseline(cfg)
    except BaselineBroken as e:
        problems.append(f"判据锁基线坏了：{e}")
    else:
        if pol:
            print(f"  判据基线：{cfg.policy_baseline.relative_to(cfg.root)}"
                  f"（{pol.get('created_at')}「{pol.get('reason')}」）")
        else:
            print("  判据基线：还没有，跑一次 adone gate run 会自动建立")

    if cfg.get("coverage.threshold") is None:
        problems.append("没配 coverage.threshold：覆盖率不参与门禁判定")

    from .install import hooks_report
    hook_lines, hook_problems = hooks_report(cfg)
    for line in hook_lines:
        print(line)
    problems += hook_problems

    print()
    if not problems:
        print("配置与现实一致，没有发现问题。")
        return 0
    print(f"发现 {len(problems)} 个问题：")
    for p in problems:
        print(f"  - {p}")
    return 1
