"""完成门禁：真正执行检查，产出与代码状态绑死的回执。

「完成」的唯一口径是：存在一份回执，它的树哈希等于当前代码的树哈希，且其中每一步都通过。
Agent 贴的日志、勾的清单、说的话都不算数——回执由本模块写，哈希由本模块算。

回执还带自哈希与指向上一份的 `prev`，链记在 `.adone/chain.json`：一行一环，只追加。
手写一份全绿回执要重算自哈希、让 prev 追得到。两人各跑门禁时各追加一行，
`.gitattributes` 里 `merge=union` 让合并两边都留。

诚实的边界：这套机制**提高伪造成本，不是密码学级不可伪造**。
能写文件的人理论上能重算整条链。缓解是回执内容含树哈希与命令输出，
任何人可以用 `adone gate check --explain` 独立复核、`--spotcheck` 当场抽跑。
要做到真正不可伪造，需要一个 Agent 无权写入的执行者（CI）。
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import PRUNE_DIRS, Config
from .model import Step, TestResult


# 静默这么久打一行心跳。纯显示，不杀进程，所以给默认值不违反「不许替用户猜阈值」。
HEARTBEAT_SECONDS = 60
# 杀进程树时 SIGTERM 之后再等这么久，还活着就 SIGKILL
_KILL_GRACE = 3
# 超时步骤的退出码：跟 GNU timeout 一样用 124，绝不能是 0
_TIMEOUT_EXIT = 124


# --------------------------------------------------------------------------- 树哈希

def tree_files(cfg: Config) -> list[Path]:
    roots = cfg.get("gate.watch_roots", []) or []
    exts = {e if e.startswith(".") else f".{e}"
            for e in (cfg.get("gate.watch_exts", []) or [])}
    seen: set[Path] = set()
    for r in roots:
        base = cfg.root / r
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
            here = Path(dirpath)
            for fn in filenames:
                if os.path.splitext(fn)[1] in exts:
                    seen.add(here / fn)
    # watch_roots 常常互相嵌套（"." 加上几个子模块），去重否则同一个文件哈希两遍
    return sorted(seen)


class GateError(Exception):
    pass


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def test_paths(cfg: Config) -> list[Path]:
    """适配器扫到的测试文件。扫不到就是空列表，上层把这项标成未评估。"""
    from .adapters import get

    ad = get(cfg.get("tests.adapter") or "", cfg.root)
    roots = [cfg.root / r for r in (cfg.get("tests.roots") or [])]
    seen: dict[Path, Path] = {}
    for p in ad.test_files(roots):
        if not p.is_file():
            continue
        try:
            p.relative_to(cfg.root)
        except ValueError:
            continue
        seen[_resolved(p)] = p
    return [seen[k] for k in sorted(seen, key=lambda p: p.as_posix())]


def tree_parts(cfg: Config) -> dict:
    """实现与测试分开哈希。

    测试文件即使不在 watch_roots 里也计入测试哈希，这样「只改了测试」
    不会被当成实现变动。实现集是受监视文件减去测试文件。
    """
    watched = tree_files(cfg)
    tests = test_paths(cfg)
    test_ids = {_resolved(p) for p in tests}
    impl = [p for p in watched if _resolved(p) not in test_ids]
    return {
        "impl_hash": _hash_files(cfg, impl),
        "impl_count": len(impl),
        "test_hash": _hash_files(cfg, tests) if tests else "",
        "test_count": len(tests),
    }


def tree_hash(cfg: Config) -> tuple[str, int]:
    """返回 (哈希, 文件数)。文件数过少直接报错——空哈希会让门禁恒等通过。"""
    files = tree_files(cfg)
    floor = int(cfg.get("gate.min_tree_files", 1) or 1)
    if len(files) < floor:
        raise GateError(
            f"只扫描到 {len(files)} 个受监视文件（下限 {floor}）。"
            f"这通常意味着 gate.watch_roots / watch_exts 配错了；"
            f"此时算出的哈希会恒等，门禁将形同虚设。")
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(cfg.root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest(), len(files)


def _hash_files(cfg: Config, files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(cfg.root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def unit_files(cfg: Config, unit: str) -> list[Path]:
    """某个 watch_roots 项下的受监视文件。算法与 tree_files 一致，只是不跨单元去重。"""
    exts = {e if e.startswith(".") else f".{e}"
            for e in (cfg.get("gate.watch_exts", []) or [])}
    base = cfg.root / unit
    if not base.is_dir():
        return []
    seen: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        here = Path(dirpath)
        for fn in filenames:
            if os.path.splitext(fn)[1] in exts:
                seen.add(here / fn)
    return sorted(seen)


def unit_hashes(cfg: Config) -> dict[str, str]:
    """每个 watch_roots 项一份哈希。总哈希算法一个字不动，老回执还能校验。"""
    out: dict[str, str] = {}
    for r in cfg.get("gate.watch_roots", []) or []:
        files = unit_files(cfg, str(r))
        out[str(r)] = _hash_files(cfg, files)
    return out


def unit_file_counts(cfg: Config) -> dict[str, int]:
    return {str(r): len(unit_files(cfg, str(r)))
            for r in (cfg.get("gate.watch_roots", []) or [])}


# --------------------------------------------------------------------------- 执行

def pathext() -> tuple[str, ...]:
    """Windows 上可执行文件的后缀。非 Windows 返回空。"""
    if os.name != "nt":
        return ()
    raw = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return tuple(e.lower() for e in raw.split(os.pathsep) if e.strip().startswith("."))


def launch_argv(exe: str, rest: list[str] | None = None, *,
                os_name: str | None = None) -> list[str]:
    """交给 subprocess 的 argv。Windows 上 .cmd / .bat 必须经 cmd.exe。

    CreateProcess 不跑批处理：解析出 mvn.cmd 的全路径之后若直接 run，
    会报「不是有效的 Win32 应用程序」。终端里手敲 mvn 能跑，是因为壳转了一层。
    """
    rest = list(rest or [])
    if (os_name or os.name) == "nt" and Path(exe).suffix.lower() in {".cmd", ".bat"}:
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", exe, *rest]
    return [exe, *rest]


def resolve_cmd(cmd: str, cwd: Path, *, exts: tuple[str, ...] | None = None) -> str | None:
    """把 argv[0] 解析成能直接交给操作系统的路径；找不到返回 None。

    Windows 上 mvn / npm / gradle 都是 .cmd 批处理，而 CreateProcess 不查 PATHEXT，
    所以 subprocess.run(["mvn", ...]) 会直接 FileNotFoundError（且 e.filename 是 None）。
    doctor 用的 shutil.which 认 PATHEXT，于是「体检说命令在，门禁说命令不存在」。
    两边必须走这同一个函数，判断才一致。
    """
    exts = pathext() if exts is None else exts
    seps = [s for s in (os.sep, os.altsep) if s]
    if any(s in cmd for s in seps):
        # ./mvnw、bin/x 这种相对路径按步骤 cwd 解析，不查 PATH
        base = Path(cmd) if Path(cmd).is_absolute() else cwd / cmd
        for cand in _ext_candidates(base, exts):
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
        return None
    # shutil.which 自己会按 PATHEXT 补后缀，拿到带后缀的全路径 CreateProcess 才认
    return shutil.which(cmd)


def _ext_candidates(base: Path, exts: tuple[str, ...]) -> list[Path]:
    if not exts or base.suffix.lower() in exts:
        return [base]
    # Windows 上 mvnw 与 mvnw.cmd 常常并存，前者是 bash 脚本，跑不起来，所以后缀优先
    return [base.with_name(base.name + e) for e in exts] + [base]


def _popen_kw() -> dict:
    """自成进程组，超时才能连 surefire fork 出的 JVM 一起杀掉。"""
    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flag} if flag else {}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    """把步骤的进程树杀掉。孤儿 JVM 会占着端口，下一次全量再冲突一次。"""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except OSError:
            pass
    deadline = time.time() + _KILL_GRACE
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _seconds(spec: dict, key: str) -> float | None:
    raw = spec.get(key)
    if raw is None or raw == "":
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _pump(proc: subprocess.Popen, *, timeout: float | None,
          stall: float | None) -> tuple[str, bool, str]:
    """读步骤输出：边打边留全文。按字节块读，不按行——mvn 有时只吐 \\r。

    返回 (全文, 是否超时, 超时说明)。必须用 print 而不是抓 sys.stdout：
    health --json 用 redirect_stdout 把门禁进度导去 stderr。
    """
    if proc.stdout is None:
        proc.wait()
        return "", False, ""

    chunks: queue.Queue[bytes | None] = queue.Queue()

    def reader() -> None:
        try:
            while True:
                buf = proc.stdout.read(4096)
                if not buf:
                    break
                chunks.put(buf)
        finally:
            chunks.put(None)

    threading.Thread(target=reader, daemon=True).start()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    parts: list[str] = []
    t0 = time.time()
    last_out = t0
    last_beat = t0
    timed_out = False
    why = ""

    while True:
        now = time.time()
        if timeout is not None and now - t0 >= timeout:
            timed_out = True
            why = (f"超时 {timeout:g} 秒被中断（已跑 {now - t0:.1f}s，"
                   f"输出 {sum(p.count(chr(10)) for p in parts)} 行）")
            kill_tree(proc)
            break
        if stall is not None and now - last_out >= stall:
            timed_out = True
            why = (f"超过 {stall:g} 秒没有新输出，按卡死中断"
                   f"（已跑 {now - t0:.1f}s）")
            kill_tree(proc)
            break
        if now - last_out >= HEARTBEAT_SECONDS and now - last_beat >= HEARTBEAT_SECONDS:
            print(f"  … 已跑 {now - t0:.0f}s，{now - last_out:.0f}s 没有新输出",
                  flush=True)
            last_beat = now
        try:
            item = chunks.get(timeout=0.2)
        except queue.Empty:
            continue
        if item is None:
            break
        last_out = time.time()
        text = decoder.decode(item)
        if text:
            print(text, end="", flush=True)
            parts.append(text)

    tail = decoder.decode(b"", final=True)
    if tail:
        print(tail, end="", flush=True)
        parts.append(tail)
    # 把杀完之后还堵在队列里的尾巴也捞出来
    while True:
        try:
            item = chunks.get_nowait()
        except queue.Empty:
            break
        if item is None:
            break
        text = codecs.decode(item, "utf-8", "replace")
        if text:
            print(text, end="", flush=True)
            parts.append(text)
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except OSError:
            pass
    return "".join(parts), timed_out, why


def run_step(cfg: Config, spec: dict) -> Step:
    argv = [a.replace("{cover_out}", str(cfg.cover_out)).replace("{root}", str(cfg.root))
            for a in spec["argv"]]
    st = Step(name=spec.get("name") or argv[0], cwd=spec.get("cwd", "."), argv=argv)
    wd = cfg.root / st.cwd
    t0 = time.time()
    st.started_at = t0

    def dead(msg: str) -> Step:
        st.seconds = round(time.time() - t0, 2)
        st.exit_code = 127
        st.ok = False
        st.launch_error = msg
        st.note = msg
        st.output_tail = msg
        return st

    if not wd.is_dir():
        return dead(f"步骤目录不存在：{spec.get('cwd', '.')}")
    exe = resolve_cmd(argv[0], wd)
    if exe is None:
        return dead(f"命令不存在：{argv[0]}（在 PATH 与 {spec.get('cwd', '.')} 下都没找到）")
    try:
        proc = subprocess.Popen(
            launch_argv(exe, argv[1:]), cwd=wd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, **_popen_kw())
    except OSError as e:
        return dead(f"命令跑不起来：{argv[0]}（{e.strerror or e}）")
    timeout = _seconds(spec, "timeout_seconds")
    stall = _seconds(spec, "stall_seconds")
    st.stdout, st.timed_out, why = _pump(proc, timeout=timeout, stall=stall)
    st.seconds = round(time.time() - t0, 2)
    if st.timed_out:
        st.exit_code = _TIMEOUT_EXIT
        st.ok = False
        st.note = why
    else:
        st.exit_code = proc.returncode if proc.returncode is not None else _TIMEOUT_EXIT
        st.ok = st.exit_code == 0
    st.output_tail = "\n".join(st.stdout.splitlines()[-25:])
    return st


def _fold_test_result(acc: TestResult | None, res: TestResult) -> TestResult:
    """多步测试时保留通过人数更多的那份计数，并把各步的通过名单并起来。

    名单合并是为了让 eval 场景名和 Java/Go 用例名能写进同一份回执；
    单步项目的计数与以前完全一样。
    """
    if acc is None:
        return res
    keep, other = (res, acc) if res.passed > acc.passed else (acc, res)
    keep.passed_names = sorted(set(keep.passed_names) | set(other.passed_names))
    keep.failed_names = sorted(set(keep.failed_names) | set(other.failed_names))
    keep.skipped_names = sorted(set(keep.skipped_names) | set(other.skipped_names))
    keep.ran_names = sorted(set(keep.ran_names) | set(other.ran_names))
    return keep


def _append_note(st: Step, extra: str) -> None:
    extra = (extra or "").strip()
    if not extra:
        return
    if st.note and extra not in st.note:
        st.note = f"{st.note}；{extra}"
    elif not st.note:
        st.note = extra


def judge_step(cfg: Config, spec: dict, st: Step) -> TestResult | None:
    """按 kind 做额外判定。光看退出码会漏掉两类最常见的假绿。"""
    kind = spec.get("kind", "")
    timed_note = st.note if st.timed_out else ""

    if kind == "fmt":
        # 格式化检查工具往往永远退出 0，未格式化的文件名走 stdout
        bad = [ln for ln in st.stdout.splitlines() if ln.strip()]
        st.ok = st.exit_code == 0 and not bad and not st.timed_out
        if bad:
            st.note = f"{len(bad)} 个文件未格式化"
        if timed_note:
            st.ok = False
            st.note = timed_note + (f"；{st.note}" if st.note and st.note != timed_note else "")
        return None

    if kind != "test":
        if st.timed_out:
            st.ok = False
            if timed_note:
                st.note = timed_note
        return None

    if st.launch_error:
        # 命令压根没启动。这时候说「解析不出测试结果」会把人引到适配器上去查，
        # 而真正要修的是 PATH 或步骤目录
        return None

    from .adapters import get
    ad = get(spec.get("adapter") or "", cfg.root)
    res = ad.parse_test_run(st.stdout, cwd=cfg.root / st.cwd,
                            since=st.started_at or None)
    if res is None or not res.parsed:
        st.ok = False
        if st.exit_code != 0:
            # 退出码已经说明它失败了，这时候提「这种通过不能作为证据」是自相矛盾，
            # 还会把人引去查适配器
            st.note = (f"测试没跑出结果，退出码 {st.exit_code}"
                       f"——多半是命令本身失败了，看下面的输出")
        else:
            st.note = ("退出码 0 但解析不出测试结果——要么适配器不认这种输出格式，"
                       "要么测试根本没跑起来。这种「通过」不能作为证据")
    else:
        if res.ran_names is not None and not res.ran_names:
            res.ran_names = list(res.passed_names)
        for mark in spec.get("invalid_marks", []) or []:
            if mark in st.stdout:
                st.ok = False
                st.note = (f"输出里出现「{mark}」，说明有用例是被条件跳过的，"
                           f"这轮证据无效")
                _finish_judge(st, timed_note, ad)
                return res
        if res.failed:
            st.ok = False
            st.note = f"{res.failed} 个用例失败"
        elif res.passed == 0:
            st.ok = False
            st.note = "没有任何用例真正跑过"
        else:
            st.note = (f"{res.passed} 通过 / {res.skipped} 跳过（顶层 {res.skip_top}）"
                       + (f" / 覆盖率 {res.coverage}%" if res.coverage is not None else ""))
        _print_slowest(ad, cfg.root / st.cwd, st.started_at or None)

    _finish_judge(st, timed_note, ad)
    return res


def _finish_judge(st: Step, timed_note: str, ad) -> None:
    if timed_note:
        st.ok = False
        st.note = timed_note + (f"；{st.note}" if st.note and st.note != timed_note else "")
    if not st.ok:
        fn = getattr(ad, "failure_diagnosis", None)
        if callable(fn):
            said = fn(st.stdout)
            if said:
                _append_note(st, said)


def _print_slowest(ad, cwd: Path, since: float | None, n: int = 5) -> None:
    fn = getattr(ad, "slowest_tests", None)
    if not callable(fn):
        return
    rows = fn(cwd, since=since, n=n)
    if not rows:
        return
    print("  最慢的用例：", flush=True)
    for name, sec, *_rest in rows:
        print(f"    {sec:.2f}s  {name}", flush=True)


def _maybe_scope_spec(cfg: Config, spec: dict, affected: list[str] | None) -> dict:
    """测试步骤按受影响单元改 argv。做不到就拒绝，不许少跑还装成全量。"""
    if not affected or spec.get("kind") != "test":
        return spec
    from .adapters import get
    ad = get(spec.get("adapter") or cfg.get("tests.adapter") or "", cfg.root)
    fn = getattr(ad, "scoped_test_argv", None)
    if not callable(fn):
        raise GateError(
            f"步骤「{spec.get('name')}」的适配器不会按模块缩范围。"
            f"Gradle 没有 -amd 的等价物。跑全量 adone gate run，不要用 --affected")
    cwd = cfg.root / (spec.get("cwd") or ".")
    scoped = fn(list(spec.get("argv") or []), affected, cwd=cwd)
    if scoped is None:
        raise GateError(
            f"步骤「{spec.get('name')}」拼不出只跑 {', '.join(affected)} 的命令。"
            f"跑全量 adone gate run，不要用 --affected")
    out = dict(spec)
    out["argv"] = scoped
    print(f"  缩范围：{' '.join(scoped)}", flush=True)
    return out


def execute_steps(cfg: Config, skip: list[str] | None = None,
                  *, affected: list[str] | None = None) -> dict:
    """真跑配置里的每一步，返回原始结果，不落任何盘。

    `gate run` 与 `audit --rerun` 共用它：复核者要能跑出自己的一份结果，
    又不能顺手覆盖实现者的回执——那等于把被审的证据抹掉。

    affected 非空时，测试步骤的 argv 会按受影响单元缩范围；缩不了就抛 GateError，
    不许偷偷少跑。
    """
    skip = skip or []
    started = time.time()
    specs = cfg.get("gate.step", []) or []
    print(f"跑门禁：{len(specs)} 步\n", flush=True)

    steps: list[Step] = []
    tests: TestResult | None = None
    test_step_name = cfg.get("coverage.source") or ""
    coverage: float | None = None
    coverage_any: float | None = None
    skipped_any = False

    for spec in specs:
        name = spec.get("name", "?")
        if name in skip:
            print(f"  [跳过] {name}（本次回执会被标记为不完整）", flush=True)
            skipped_any = True
            continue
        spec = _maybe_scope_spec(cfg, spec, affected)
        print(f"  ── {name} ──", flush=True)
        st = run_step(cfg, spec)
        res = judge_step(cfg, spec, st)
        if res is not None and res.parsed:
            tests = _fold_test_result(tests, res)
            if res.coverage is not None:
                coverage_any = res.coverage
                if not test_step_name or test_step_name == name:
                    coverage = res.coverage
        steps.append(st)
        mark = "通过" if st.ok else "不通过"
        print(f"  [{mark}] {name}  {st.seconds}s" + (f"  {st.note}" if st.note else ""),
              flush=True)

    if coverage is None:
        coverage = coverage_any
    if coverage is None:
        coverage = _coverage_from_disk(cfg)

    thr = cfg.get("coverage.threshold")
    if thr is not None:
        cov_step = Step(name="覆盖率", cwd=".", argv=["(读自测试步骤的输出)"])
        cov_step.exit_code = 0
        if coverage is None:
            cov_step.ok = False
            cov_step.note = _coverage_missing_note(cfg, steps, test_step_name)
        else:
            cov_step.ok = coverage >= float(thr)
            cov_step.note = f"{coverage}%（下限 {thr}%）"
        steps.append(cov_step)
        print(f"  [{'通过' if cov_step.ok else '不通过'}] 覆盖率  {cov_step.note}",
              flush=True)

    return {"steps": steps, "tests": tests, "coverage": coverage, "threshold": thr,
            "complete": not skipped_any, "seconds": round(time.time() - started, 1)}


def _cov_roots(cfg: Config) -> list[Path]:
    """找覆盖率报告的起点：仓库根，加上每个测试步骤的目录（多模块仓库报告在子模块下）。"""
    roots = [cfg.root]
    for s in cfg.get("gate.step") or []:
        if s.get("kind") == "test":
            roots.append(cfg.root / (s.get("cwd") or "."))
    return roots


def _cov_adapters(cfg: Config):
    from .adapters import get
    for name in [cfg.get("tests.adapter") or "", *(cfg.ecosystems or [])]:
        yield get(name, cfg.root)


def _coverage_from_disk(cfg: Config) -> float | None:
    """测试输出里没带覆盖率时，直接从报告文件读。Java 的数字在 jacoco.xml 里，不在 stdout。"""
    roots = _cov_roots(cfg)
    for ad in _cov_adapters(cfg):
        fn = getattr(ad, "coverage_from_reports", None)
        if not callable(fn):
            continue
        got = fn(*roots)
        if got is not None:
            return got
    return None


def _coverage_missing_note(cfg: Config, steps: list[Step], source: str) -> str:
    """没读到覆盖率时，让适配器指出断在哪一环。

    「没解析到覆盖率数字」这句话本身没有信息量：它可能是没装插件、没跑 report、
    探针没挂上、或者测试整批被跳过，处理办法完全不同。
    """
    output = "\n".join(s.stdout for s in steps if s.stdout)
    roots = _cov_roots(cfg)
    for ad in _cov_adapters(cfg):
        fn = getattr(ad, "coverage_diagnosis", None)
        if not callable(fn):
            continue
        said = fn(*roots, output=output)
        if said:
            return f"没解析到覆盖率数字。{said}"
    return (f"没解析到覆盖率数字：coverage.source 现在是「{source or '空'}」，"
            f"确认那一步的输出里有覆盖率，或报告文件写到了磁盘上")


def run_gate(cfg: Config, skip: list[str] | None = None,
             *, affected: bool = False) -> int:
    problems = cfg.problems()
    if problems:
        print("配置有问题，门禁不跑（跑了也不算数）：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    now_units = unit_hashes(cfg)
    source = None
    changed: list[str] = []
    carried: list[str] = []
    if affected:
        source, err = inheritable_full(cfg)
        if err:
            print(err, file=sys.stderr)
            return 2
        src_units = (source or {}).get("units") or {}
        for unit, h in now_units.items():
            if src_units.get(unit) == h:
                carried.append(unit)
            else:
                changed.append(unit)
        if not changed:
            print("没有单元相对可继承的全量回执变过，现有回执仍然有效。"
                  "要重跑请用 adone gate run（不加 --affected）。")
            return 0
        print(f"范围化全量：本轮跑 {len(changed)} 个单元，"
              f"继承 {len(carried)} 个（来自回执 {source.get('id')}）")
        for u in changed:
            print(f"  跑  {u}")
        for u in carried:
            print(f"  继承 {u}")

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
    try:
        ran = execute_steps(cfg, skip, affected=changed or None)
    except GateError as e:
        print(str(e), file=sys.stderr)
        return 2
    steps = ran["steps"]
    tests, coverage, thr = ran["tests"], ran["coverage"], ran["threshold"]
    if affected and source is not None:
        tests = _carry_tests(tests, source)
        # 部分模块的覆盖率数字不能当全量用，继承源头的
        cov_src = (source.get("coverage") or {}).get("percent")
        if cov_src is not None:
            coverage = cov_src
        _carry_coverage_step(steps, source, thr)

    from .policy import ensure_baseline, snapshot, snapshot_hash

    h, n = tree_hash(cfg)
    said = ensure_baseline(cfg, load_latest(cfg))
    if said:
        print(f"\n{said}")
    pol = _policy_baseline_or_none(cfg)
    prev = chain_head(cfg)
    tree = {"hash": h, "file_count": n,
            "roots": cfg.get("gate.watch_roots"),
            "exts": sorted(cfg.get("gate.watch_exts"))}
    if not affected:
        tree.update(full_tree_delta(cfg))
    receipt = {
        "tool": "actuallydone",
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "complete": ran["complete"],
        "seconds": ran["seconds"],
        "scope": "affected" if affected else "full",
        "units": now_units,
        "tree": tree,
        "policy": {"hash": snapshot_hash(snapshot(cfg)),
                   "baseline_hash": (pol or {}).get("hash"),
                   "baseline_reason": (pol or {}).get("reason")},
        "tests": (tests or TestResult(parsed=False)).as_dict(),
        "coverage": {"percent": coverage, "threshold": thr},
        "steps": [s.as_receipt() for s in steps],
        "ok": bool(steps) and all(s.ok for s in steps),
        "seq": prev.get("seq", 0) + 1,
        "prev": prev.get("head"),
    }
    if affected and source is not None:
        receipt["carried"] = {"from_receipt": source.get("id"), "units": carried}
    runner = read_runner(cfg)
    if runner and not affected:
        receipt["runner"] = runner
    receipt["evidence"] = evidence_of(cfg, receipt)
    receipt["self_hash"] = self_hash(receipt)
    path = cfg.receipts_dir / f"receipt-{receipt['id']}.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(path, cfg.latest_receipt)
    write_chain_head(cfg, receipt)
    cfg.dirty.unlink(missing_ok=True)
    prune_receipts(cfg)

    print(f"\n回执 {receipt['id']}：{'全绿' if receipt['ok'] else '未通过'}"
          f"（树 {n} 个文件 / {h[:12]}"
          + ("，范围化" if affected else "") + "）")
    print(f"写入 {path.relative_to(cfg.root)}")
    if not receipt["ok"]:
        print("\n未通过的步骤：")
        for s in steps:
            if not s.ok:
                print(f"--- {s.name} ---\n{s.output_tail}\n")
    return 0 if receipt["ok"] else 1


def inheritable_full(cfg: Config) -> tuple[dict | None, str]:
    """沿证据链找一份可继承的全量绿回执。没有 units 的老回执不能当源头。"""
    src = find_full_receipt(cfg)
    if src is None:
        return None, ("链上没有可继承的全量绿回执。"
                      "先跑一次 adone gate run（全量），再谈 --affected。")
    if not (src.get("units") or {}):
        return None, (f"全量回执 {src.get('id')} 没有单元哈希（v1.4.0 之前写的）。"
                      f"先跑一次 adone gate run（全量）再谈 --affected。")
    if not src.get("ok") or not src.get("complete", True):
        return None, f"全量回执 {src.get('id')} 本身未通过或不完整，不能当继承源头。"
    return src, ""


def read_runner(cfg: Config) -> dict | None:
    """钩子在 payload 里看到 model 时写下的 .adone/runner.json。没有就不猜。"""
    path = cfg.state_dir / "runner.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, str) or not model.strip():
        return None
    return {"model": model.strip()}


def full_tree_delta(cfg: Config) -> dict:
    """全量回执上的实现/测试哈希，以及相对上一份带这些字段的全量回执的变化。

    上一份没有这两个字段（升级前的回执，或这是第一份）时不写 impl_changed：
    不能拿「没有对照」当成「测试没变」。
    """
    parts = tree_parts(cfg)
    out = {
        "impl_hash": parts["impl_hash"],
        "impl_count": parts["impl_count"],
        "test_hash": parts["test_hash"],
        "test_count": parts["test_count"],
    }
    if not parts["test_count"]:
        out["evaluated"] = False
        return out
    prev = previous_parted_full(cfg)
    if prev is None:
        return out
    old = prev.get("tree") or {}
    out["impl_changed"] = old.get("impl_hash") != parts["impl_hash"]
    out["tests_changed"] = old.get("test_hash") != parts["test_hash"]
    return out


def previous_parted_full(cfg: Config) -> dict | None:
    """最新一份带 impl_hash 的全量回执。范围化回执跳过。"""
    cur = load_latest(cfg)
    seen: set[str] = set()
    while cur:
        key = str(cur.get("self_hash") or cur.get("id") or "")
        if not key or key in seen:
            break
        seen.add(key)
        tree = cur.get("tree") or {}
        if cur.get("scope") != "affected" and "impl_hash" in tree:
            return cur
        prev = cur.get("prev")
        if not prev:
            break
        cur = _find_receipt_by_hash(cfg, prev)
    return None


def new_tests_waiver_path(cfg: Config) -> Path:
    return cfg.state_dir / "new-tests-waiver.json"


def _waiver_text(cfg: Config) -> str:
    path = new_tests_waiver_path(cfg)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_waiver_records(cfg: Config) -> list[dict]:
    text = _waiver_text(cfg)
    if not text.strip():
        return []
    records = []
    for rec in _objects_in(text, "impl_hash"):
        reason = rec.get("reason")
        if isinstance(reason, str) and len(reason.strip()) >= 4:
            records.append(rec)
    return records


def load_new_tests_waiver(cfg: Config) -> dict | None:
    """当前实现哈希对得上的那一条豁免。对不上就当没有。"""
    want = tree_parts(cfg).get("impl_hash")
    if not want:
        return None
    for rec in reversed(load_waiver_records(cfg)):
        if rec.get("impl_hash") == want:
            return rec
    return None


def waive_new_tests(cfg: Config, reason: str) -> int:
    """把「这次实现变了但没有新测试」记成一次人的豁免，绑在当前实现哈希上。"""
    reason = (reason or "").strip()
    if len(reason) < 4:
        print('豁免必须写理由，例如 adone gate waive-tests "这次只改注释，没有新行为"',
              file=sys.stderr)
        return 2
    parts = tree_parts(cfg)
    if not parts["test_count"]:
        print("一个测试文件都没扫到，这项检查本来就是未评估，不用豁免", file=sys.stderr)
        return 2
    path = new_tests_waiver_path(cfg)
    record = {
        "impl_hash": parts["impl_hash"],
        "reason": reason,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    text = _waiver_text(cfg)
    records = load_waiver_records(cfg)
    already = any(rec.get("impl_hash") == record["impl_hash"] for rec in records)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    if _clean_jsonl(text, "impl_hash"):
        if already:
            print(f"当前实现哈希 {parts['impl_hash'][:12]} 已经豁免过，没有再追加。")
            return 0
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    else:
        if not already:
            records.append(record)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                        encoding="utf-8")
    if ensure_chain_merge(cfg):
        print("已把 merge=union 写进 .gitattributes"
              "（chain.json 与 new-tests-waiver.json）。这个文件要入库。")
    print(f"已记下豁免，绑在当前实现哈希 {parts['impl_hash'][:12]}，"
          f"理由「{reason}」。实现再变则失效。")
    return 0


_NEW_TESTS_PROBLEM = (
    "实现相对上一份全量回执变了，测试文件没有变。"
    "新行为要有新用例；如果这次确实没有新行为，"
    "由人在终端执行 adone gate waive-tests \"理由\"（实现再变则失效）。"
)


def new_tests_problems(cfg: Config, receipt: dict | None) -> tuple[list[str], list[str]]:
    """全量回执记下「实现变了、测试没变」时，没有对得上的豁免就是问题。

    老回执没有 impl_hash，不回溯。测试文件一个都扫不到时只在依据里写未评估。
    """
    if not receipt or receipt.get("scope") == "affected":
        return [], []
    tree = receipt.get("tree") or {}
    if "impl_hash" not in tree:
        return [], []
    if not tree.get("test_count"):
        return [], ["测试文件没扫到，未做「实现变了要有新测试」这项检查"]
    if "impl_changed" not in tree:
        return [], []
    if not tree.get("impl_changed") or tree.get("tests_changed"):
        return [], []
    waiver = load_new_tests_waiver(cfg)
    if waiver and waiver.get("impl_hash") == tree_parts(cfg)["impl_hash"]:
        return [], [f"实现变了但测试没变，已按理由豁免：「{waiver['reason'].strip()}」"]
    return [_NEW_TESTS_PROBLEM], []


def find_full_receipt(cfg: Config) -> dict | None:
    """沿 latest → prev 找最近一份 scope≠affected 且通过的回执。"""
    cur = load_latest(cfg)
    seen: set[str] = set()
    while cur:
        key = str(cur.get("self_hash") or cur.get("id") or "")
        if not key or key in seen:
            break
        seen.add(key)
        if (cur.get("ok") and cur.get("complete", True)
                and cur.get("scope") != "affected"):
            return cur
        prev = cur.get("prev")
        if not prev:
            break
        cur = _find_receipt_by_hash(cfg, prev)
    return None


def _carry_tests(ran: TestResult | None, source: dict) -> TestResult:
    """passed_names = 本轮真跑 ∪ 源头。ran_names 只留本轮。契约校验靠并集。"""
    src = source.get("tests") or {}
    inherited = list(src.get("passed_names") or [])
    if ran is None or not ran.parsed:
        out = TestResult(
            passed=len(set(inherited)),
            failed=0,
            skipped=int(src.get("skip") or 0),
            skip_top=int(src.get("skip_top") or 0),
            passed_names=inherited,
            ran_names=[],
            coverage=src.get("coverage"),
            parsed=True,
        )
        return out
    ran.ran_names = list(ran.passed_names)
    ran.passed_names = sorted(set(ran.passed_names) | set(inherited))
    ran.passed = len(set(ran.passed_names))
    return ran


def _carry_coverage_step(steps: list[Step], source: dict, thr) -> None:
    """部分重跑的覆盖率数字会偏低，覆盖率步骤改成继承源头。"""
    src_cov = (source.get("coverage") or {}).get("percent")
    for s in steps:
        if s.name == "覆盖率":
            if src_cov is None:
                s.ok = False
                s.note = (f"源头回执 {source.get('id')} 也没有覆盖率数字，"
                          f"范围化全量不能凭空补一份")
            else:
                s.ok = thr is None or src_cov >= float(thr)
                s.note = (f"{src_cov}%（继承自回执 {source.get('id')}，"
                          f"本轮只跑了部分模块）")
            return


def prune_receipts(cfg: Config) -> None:
    keep = int(cfg.get("gate.keep_receipts", 20) or 20)
    for p in sorted(cfg.receipts_dir.glob("receipt-*.json"), reverse=True)[keep:]:
        p.unlink(missing_ok=True)


# --------------------------------------------------------------------------- 证据链

def self_hash(receipt: dict) -> str:
    """回执对自己内容的哈希（不含该字段本身）。

    手写一份回执从此不再是「填一个树哈希」：还得把这个数算对、把链头改掉、
    让 prev 对得上。挡不住铁了心重算整条链的人，但那已经不是顺手绕过了。
    """
    body = {k: v for k, v in receipt.items() if k != "self_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


_UNION_RULES = (
    ".adone/chain.json merge=union",
    ".adone/new-tests-waiver.json merge=union",
)
_CONFLICT_MARK = ("<<<<<<<", "=======", ">>>>>>>")


def _conflicted(text: str) -> bool:
    return any(line.startswith(_CONFLICT_MARK) for line in text.splitlines())


def _chain_text_conflicted(cfg: Config) -> bool:
    if not cfg.chain.exists():
        return False
    try:
        return _conflicted(cfg.chain.read_text(encoding="utf-8"))
    except Exception:
        return False


def _sides(text: str) -> list[str]:
    """一个冲突区拆成两边。公共的行（花括号）分别拼回每一边。"""
    if not _conflicted(text):
        return [text]
    pre: list[str] = []
    ours: list[str] = []
    theirs: list[str] = []
    after: list[str] = []
    mode = "pre"
    for line in text.splitlines(keepends=True):
        if line.startswith("<<<<<<<"):
            mode = "ours"
        elif line.startswith("=======") and mode == "ours":
            mode = "theirs"
        elif line.startswith(">>>>>>>"):
            mode = "after"
        elif mode == "pre":
            pre.append(line)
        elif mode == "ours":
            ours.append(line)
        elif mode == "theirs":
            theirs.append(line)
        else:
            after.append(line)
    return ["".join(pre + ours + after), "".join(pre + theirs + after)]


def _objects_in_plain(text: str, key: str) -> list[dict]:
    found: list[dict] = []

    def take(data: object) -> None:
        if isinstance(data, dict) and data.get(key):
            found.append(data)
        elif isinstance(data, list):
            for item in data:
                take(item)

    try:
        take(json.loads(text))
        if found:
            return found
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    i = 0
    while True:
        j = text.find("{", i)
        if j < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, j)
        except json.JSONDecodeError:
            i = j + 1
            continue
        take(obj)
        i = end if end > j else j + 1
    return found


def _objects_in(text: str, key: str = "head") -> list[dict]:
    """从整份 JSON、一行一条，或带着冲突标记的文本里抽出记录。"""
    found: list[dict] = []
    for side in _sides(text):
        found.extend(_objects_in_plain(side, key))
    return _dedupe_by(found, key)


def _dedupe_by(records: list[dict], key: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for rec in records:
        ident = str(rec.get(key) or "")
        if not ident or ident in seen:
            continue
        seen.add(ident)
        out.append(rec)
    return out


def load_chain_records(cfg: Config) -> list[dict]:
    if not cfg.chain.exists():
        return []
    try:
        return _objects_in(cfg.chain.read_text(encoding="utf-8"))
    except Exception:
        return []


def chain_tips(records: list[dict]) -> list[dict]:
    """没有被别的环当作 prev 的那些。两条分支各跑一轮，就会有两个尖。"""
    prevs = {r.get("prev") for r in records if r.get("prev")}
    return [r for r in records if r.get("head") not in prevs]


def chain_head(cfg: Config) -> dict:
    """下一份回执要接上的那一环。本机 latest 对得上某个尖，就接它。"""
    records = load_chain_records(cfg)
    if not records:
        return {}
    pool = chain_tips(records) or records
    latest = load_latest(cfg)
    want = (latest or {}).get("self_hash")
    for rec in pool:
        if want and rec.get("head") == want:
            return rec
    return max(enumerate(pool),
               key=lambda ir: (str(ir[1].get("updated_at") or ""), ir[0]))[1]


def _chain_line(receipt: dict) -> dict:
    return {
        "head": receipt["self_hash"],
        "seq": receipt["seq"],
        "receipt_id": receipt["id"],
        "updated_at": receipt["created_at"],
        "prev": receipt.get("prev"),
    }


def _write_chain(cfg: Config, records: list[dict]) -> None:
    cfg.chain.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    cfg.chain.write_text(body, encoding="utf-8")


def _clean_jsonl(text: str, key: str = "head") -> bool:
    if not text.strip() or _conflicted(text):
        return not text.strip()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict) or not data.get(key):
            return False
    return True


def ensure_chain_merge(cfg: Config) -> bool:
    """让 git 合并证据链和豁免记录时两边的行都留。缺哪行补哪行。"""
    path = cfg.root / ".gitattributes"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    have = {item.strip() for item in existing.splitlines()}
    missing = [line for line in _UNION_RULES if line not in have]
    if not missing:
        return False
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    with path.open("a", encoding="utf-8") as f:
        f.write(prefix)
        if ".adone/chain.json merge=union" in missing:
            f.write("# adone：证据链和豁免都是各人追加一行，合并时两边都留\n")
        for line in missing:
            f.write(line + "\n")
    return True


def write_chain_head(cfg: Config, receipt: dict) -> None:
    record = _chain_line(receipt)
    text = cfg.chain.read_text(encoding="utf-8") if cfg.chain.exists() else ""
    if _clean_jsonl(text):
        heads = {r.get("head") for r in load_chain_records(cfg)}
        if record["head"] not in heads:
            cfg.chain.parent.mkdir(parents=True, exist_ok=True)
            with cfg.chain.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    else:
        records = load_chain_records(cfg)
        if record["head"] not in {r.get("head") for r in records}:
            records.append(record)
        _write_chain(cfg, records)
    if ensure_chain_merge(cfg):
        print("已把 merge=union 写进 .gitattributes"
              "（chain.json 与 new-tests-waiver.json）。"
              "这个文件要入库，之后各人追加才不会在这两份上冲突。")


def repair_chain(cfg: Config) -> int:
    """把冲突标记收成一行一环，两边都留，并写上 union 合并。"""
    if not cfg.chain.exists():
        print("还没有 chain.json", file=sys.stderr)
        return 2
    text = cfg.chain.read_text(encoding="utf-8")
    records = _objects_in(text)
    if not records:
        print("chain.json 里读不出任何一环。冲突标记两边都要是完整的 JSON。",
              file=sys.stderr)
        return 1
    _write_chain(cfg, records)
    waiver_note = _repair_waiver(cfg)
    added = ensure_chain_merge(cfg)
    print(f"证据链收成 {len(records)} 环，两边都留着。")
    if waiver_note:
        print(waiver_note)
    if added:
        print("已在 .gitattributes 写上 chain.json 与 new-tests-waiver.json 的 merge=union。"
              "这个文件要入库。")
    else:
        print(".gitattributes 里已经有 merge=union。")
    return 0


def _repair_waiver(cfg: Config) -> str:
    """冲突或旧的整份 JSON 收成一行一条。没有这个文件就什么都不做。"""
    path = new_tests_waiver_path(cfg)
    if not path.is_file():
        return ""
    text = _waiver_text(cfg)
    if _clean_jsonl(text, "impl_hash"):
        return ""
    records = load_waiver_records(cfg)
    if not records:
        return "new-tests-waiver.json 里读不出豁免。冲突两边都要是完整的 JSON。"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")
    return f"豁免记录收成 {len(records)} 条，两边都留着。"


def chain_problems(cfg: Config, receipt: dict | None) -> tuple[list[str], list[str]]:
    """校验最新回执与链头。返回（问题，依据）。

    升级前写的回执没有这些字段，按「早于链机制」处理并给一句提示——
    否则所有已装项目一升级就全红，那只会让人把这套检查关掉。
    """
    if receipt is None:
        return [], []
    if "self_hash" not in receipt:
        head = chain_head(cfg)
        if head:
            # 链已经建起来了还冒出一份链外回执：不是升级遗留，是有人把 latest.json 换了
            return ([f"这份回执不在证据链上，而本仓库的链头已经指到回执 "
                     f"{head.get('receipt_id')}（第 {head.get('seq')} 环）："
                     f"latest.json 被换成了一份更老的回执"], [])
        return [], ["这份回执早于证据链机制（重跑一次 adone gate run 即可纳入链）"]

    problems: list[str] = []
    if self_hash(receipt) != receipt["self_hash"]:
        problems.append("回执的自哈希对不上：内容被改过（或被手写过），它不能作为证据")
        return problems, []

    records = load_chain_records(cfg)
    if _chain_text_conflicted(cfg):
        problems.append("证据链（chain.json）有合并冲突。跑 adone gate repair-chain，"
                        "两边都留，不要只留序号更大的那一边。")
    if not records:
        if not _chain_text_conflicted(cfg):
            problems.append("证据链头（chain.json）不见了：无法确认这份回执是不是最新的那一份")
    else:
        tips = chain_tips(records)
        tip_heads = {r.get("head") for r in tips}
        known = {r.get("head") for r in records}
        rh = receipt["self_hash"]
        if rh not in tip_heads:
            shown = tips[0].get("receipt_id") if tips else records[-1].get("receipt_id")
            why = "latest.json 被换成了更早的一环" if rh in known else "latest.json 被换过"
            problems.append(f"回执与证据链头对不上（链头指向回执 {shown}）：{why}")
    prev = receipt.get("prev")
    if prev:
        older = _find_receipt_by_hash(cfg, prev)
        if older is None and _receipts_on_disk(cfg) >= int(cfg.get("gate.keep_receipts", 20) or 20):
            pass   # 老回执被 prune 掉了，正常
        elif older is None:
            problems.append(f"上一份回执（自哈希 {str(prev)[:12]}）在 receipts/ 里找不到："
                            f"证据链断了，中间那份被删或被改过")
    details = [f"证据链第 {receipt.get('seq', '?')} 环，自哈希 {receipt['self_hash'][:12]}"]
    return problems, details


def _receipts_on_disk(cfg: Config) -> int:
    return len(list(cfg.receipts_dir.glob("receipt-*.json")))


def _find_receipt_by_hash(cfg: Config, want: str) -> dict | None:
    for p in sorted(cfg.receipts_dir.glob("receipt-*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("self_hash") == want:
            return data
    return None


def evidence_of(cfg: Config, receipt: dict) -> dict:
    """这份回执的证据强度。

    先只有「自述」一档：本地跑出来的东西，再怎么自洽也只是自述。
    字段结构给以后的 git 绑定与 CI 签名留好位置——「总分 91」这种数字
    自带可信度标签，比在脚注里写一句免责声明管用。
    """
    ev = {
        "level": "self-reported",
        "policy_locked": _policy_baseline_or_none(cfg) is not None,
        "chained": True,
        "scope": receipt.get("scope") or "full",
    }
    carried = receipt.get("carried") or {}
    if carried.get("from_receipt"):
        ev["carried_from"] = carried.get("from_receipt")
    return ev


def _policy_baseline_or_none(cfg: Config) -> dict | None:
    """基线坏了在这里按「没锁」算：真正把它报出来的是 check，不必两处都喊。"""
    from .policy import BaselineBroken, load_baseline
    try:
        return load_baseline(cfg)
    except BaselineBroken:
        return None


def evidence_line(receipt: dict | None) -> str:
    if not receipt:
        return ""
    ev = receipt.get("evidence") or {}
    if not ev:
        return "证据强度：自述（本地跑）· 这份回执早于证据链机制"
    bits = ["自述（本地跑）" if ev.get("level") == "self-reported" else str(ev.get("level")),
            "判据已锁" if ev.get("policy_locked") else "判据未锁",
            "回执链完整" if ev.get("chained") else "不在证据链上"]
    if ev.get("scope") == "affected":
        src = ev.get("carried_from") or (receipt.get("carried") or {}).get("from_receipt")
        bits.append(f"部分重跑（继承自回执 {src}）" if src else "部分重跑")
    return "证据强度：" + " · ".join(bits)


# --------------------------------------------------------------------------- 校验

def load_latest(cfg: Config) -> dict | None:
    if not cfg.latest_receipt.exists():
        return None
    try:
        return json.loads(cfg.latest_receipt.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_dirty(cfg: Config) -> list[str]:
    if not cfg.dirty.exists():
        return []
    seen: list[str] = []
    for ln in cfg.dirty.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and ln not in seen:
            seen.append(ln)
    return seen


def gate_problems(cfg: Config, receipt: dict | None, now_hash: str,
                  with_integrity: bool = True) -> tuple[list[str], list[str]]:
    """返回 (问题, 依据)。健康度维度与 check 共用这一套判定，避免两套口径。"""
    problems: list[str] = []
    details: list[str] = []

    if receipt is None:
        problems.append("没有任何回执：还没跑过 adone gate run")
        return problems, details

    details.append(f"回执 {receipt['id']}（{receipt['created_at']}）")
    if not receipt.get("ok"):
        bad = [s["name"] for s in receipt.get("steps", []) if not s.get("ok")]
        problems.append(f"回执本身未通过，失败步骤：{'、'.join(bad) or '未知'}")
    if not receipt.get("complete", True):
        problems.append("回执不完整（跑 run 时跳过了步骤），不能作为完成证据")

    old = receipt.get("tree", {}).get("hash")
    if old != now_hash:
        changed = read_dirty(cfg)
        hint = ("；钩子记录到的改动：" + "、".join(changed[:8])
                + ("…" if len(changed) > 8 else "")) if changed else ""
        problems.append(f"回执已过期：代码在跑完门禁之后又改过"
                        f"（回执 {str(old)[:12]} ≠ 当前 {now_hash[:12]}）{hint}")
    else:
        details.append(f"树哈希一致 {now_hash[:12]}"
                       f"（{receipt.get('tree', {}).get('file_count', '?')} 个文件）")
    return problems, details


def scope_problems(cfg: Config, receipt: dict | None) -> tuple[list[str], list[str]]:
    """范围化回执：源头必须在链上且通过，继承单元哈希必须与源头、与当前都一致。"""
    if receipt is None or receipt.get("scope") != "affected":
        return [], []
    problems: list[str] = []
    details: list[str] = []
    carried = receipt.get("carried") or {}
    src_id = carried.get("from_receipt")
    src = _find_receipt_by_id(cfg, src_id)
    if src is None:
        problems.append(f"继承的源头回执 {src_id or '（没写）'} 不在链上："
                        f"范围化全量不能当完成证据")
        return problems, details
    if not src.get("ok") or not src.get("complete", True):
        problems.append(f"继承的源头回执 {src_id} 本身未通过或不完整")
    if src.get("scope") == "affected":
        problems.append(f"继承的源头回执 {src_id} 自己也是范围化的：必须追溯到一份全量绿回执")
    src_units = src.get("units") or {}
    rec_units = receipt.get("units") or {}
    now_units = unit_hashes(cfg)
    inherited = list(carried.get("units") or [])
    for u in inherited:
        if src_units.get(u) != rec_units.get(u):
            problems.append(f"继承单元 {u} 的哈希与源头回执对不上：它其实改过，不能继承")
        elif rec_units.get(u) != now_units.get(u):
            problems.append(f"继承单元 {u} 在回执写出之后又改过")
    ran_units = [u for u in rec_units if u not in inherited]
    for u in ran_units:
        if rec_units.get(u) != now_units.get(u):
            problems.append(f"本轮跑过的单元 {u} 在回执写出之后又改过")
    for u in now_units:
        if u not in rec_units:
            problems.append(f"当前多了单元 {u}，这份范围化回执没覆盖它")
    tests = receipt.get("tests") or {}
    ran_n = len(tests.get("ran_names") or [])
    passed_n = len(tests.get("passed_names") or [])
    inherited_n = max(passed_n - ran_n, 0)
    details.append(f"本轮真跑 {ran_n} 条，继承 {inherited_n} 条（来自回执 {src_id}）")
    return problems, details


def _find_receipt_by_id(cfg: Config, rid: str | None) -> dict | None:
    if not rid:
        return None
    p = cfg.receipts_dir / f"receipt-{rid}.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    for cand in cfg.receipts_dir.glob("receipt-*.json"):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("id") == rid:
            return data
    return None


def collect_check(cfg: Config, with_integrity: bool = True,
                  spotcheck: int = 0) -> dict:
    """把一次复核的全部判定收成数据，不打印。

    `check` 与 `audit` 共用这一份判定：两条命令口径分家，等于给「换个命令再问一次」
    留了一条后门。
    """
    from .contracts import check_contracts, load_contracts
    from .integrity import integrity_problems
    from .policy import policy_problems

    receipt = load_latest(cfg)
    try:
        now_hash, now_files = tree_hash(cfg)
    except GateError as e:
        # 算不出树哈希本身就是结论（多半是有人把 watch_roots 缩没了），
        # 但不能就此崩掉：判据锁与证据链的结论此时恰恰是最该看见的
        now_hash, now_files = "", 0
        problems, details = [str(e)], []
    else:
        problems, details = gate_problems(cfg, receipt, now_hash)
        nt_bad, nt_detail = new_tests_problems(cfg, receipt)
        problems.extend(nt_bad)
        details.extend(nt_detail)
        if not problems and receipt is not None:
            cfg.dirty.unlink(missing_ok=True)  # 改了又改回来，清掉噪音标记

    chain_bad, chain_detail = chain_problems(cfg, receipt)
    problems.extend(chain_bad)
    details.extend(chain_detail)
    if _conflicted(_waiver_text(cfg)):
        problems.append("豁免记录（new-tests-waiver.json）有合并冲突。"
                        "跑 adone gate repair-chain，两边都留。")

    scope_bad, scope_detail = scope_problems(cfg, receipt)
    problems.extend(scope_bad)
    details.extend(scope_detail)

    policy_bad, policy_detail = policy_problems(cfg, receipt)
    problems.extend(policy_bad)
    details.extend(policy_detail)

    contract_problems = check_contracts(cfg, receipt)
    problems.extend(contract_problems)
    contracts = load_contracts(cfg)
    if contracts and not contract_problems:
        n = sum(len(d.get("item") or []) for _, d in contracts)
        details.append(f"验收契约 {len(contracts)} 份 / {n} 条，全部绑定到已通过的用例")
    elif not contracts:
        details.append(f"没有验收契约文件（{cfg.acceptance_dir.relative_to(cfg.root)}/*.toml）")

    if with_integrity:
        problems.extend(integrity_problems(cfg, receipt))

    spotchecked: list[str] = []
    if spotcheck and receipt is not None:
        from .spotcheck import spot_check
        sc_problems, sc_details = spot_check(cfg, receipt, spotcheck)
        problems.extend(sc_problems)
        details.extend(sc_details)
        spotchecked = sc_details

    return {
        "ok": not problems, "problems": problems, "details": details,
        "receipt_id": receipt["id"] if receipt else None,
        "receipt": receipt,
        "tree_hash": now_hash, "tree_files": now_files,
        "evidence": (receipt or {}).get("evidence") or {},
        "evidence_line": evidence_line(receipt),
        "spotcheck": spotchecked,
    }


def check_gate(cfg: Config, as_json: bool = False, explain: bool = False,
               with_integrity: bool = True, spotcheck: int = 0) -> int:
    got = collect_check(cfg, with_integrity=with_integrity, spotcheck=spotcheck)
    ok, problems, details = got["ok"], got["problems"], got["details"]
    line = got["evidence_line"]
    if as_json:
        print(json.dumps({
            "ok": ok, "problems": problems, "details": details,
            "receipt_id": got["receipt_id"],
            "tree_hash": got["tree_hash"], "tree_files": got["tree_files"],
            "evidence": got["evidence"],
            "evidence_line": line,
        }, ensure_ascii=False))
        return 0 if ok else 1

    if ok:
        print("门禁通过。这是交给复核者的证据，不是完成声明。"
              "换一个模型，按 independent-check 跑 "
              "adone audit --reviewer <模型名>。")
    else:
        print("门禁未通过，以下问题必须先处理：")
        for p in problems:
            print(f"  - {p}")
    if explain or ok:
        for d in details:
            print(f"  · {d}")
    if line and (explain or ok):
        print(line)
    return 0 if ok else 1


def cmd_gate_slow(cfg: Config, n: int = 20) -> int:
    """读最近一轮测试报告，按用例和按模块打印耗时榜。不写回执。"""
    from .adapters import get

    receipt = load_latest(cfg)
    cwd = cfg.root
    adapter = cfg.get("tests.adapter") or ""
    since: float | None = None
    if receipt:
        created = receipt.get("created_at") or ""
        try:
            since = datetime.fromisoformat(created).timestamp()
        except ValueError:
            since = None
        for s in receipt.get("steps") or []:
            if s.get("name") and (s.get("argv") or []):
                adapter = adapter or ""
        for spec in cfg.get("gate.step") or []:
            if spec.get("kind") == "test":
                cwd = cfg.root / (spec.get("cwd") or ".")
                adapter = spec.get("adapter") or adapter
                break
    else:
        for spec in cfg.get("gate.step") or []:
            if spec.get("kind") == "test":
                cwd = cfg.root / (spec.get("cwd") or ".")
                adapter = spec.get("adapter") or adapter
                break

    ad = get(adapter, cfg.root)
    fn = getattr(ad, "slowest_tests", None)
    if not callable(fn):
        print(f"适配器「{ad.name}」不会读用例耗时（目前只有 Java 的 surefire XML 带 time）")
        return 2
    rows = fn(cwd, since=since, n=max(int(n), 1))
    if rows is None:
        print(f"适配器「{ad.name}」不会读用例耗时")
        return 2
    if not rows:
        print("没有读到带耗时的测试报告。先跑一次门禁，或确认 surefire XML 还在。")
        return 1

    print(f"最慢的 {len(rows)} 条用例：")
    by_mod: dict[str, float] = {}
    for name, sec, *rest in rows:
        mod = rest[0] if rest else ""
        print(f"  {sec:8.2f}s  {name}" + (f"  ({mod})" if mod else ""))
        if mod:
            by_mod[mod] = by_mod.get(mod, 0.0) + sec
    if by_mod:
        print("\n按模块合计：")
        for mod, sec in sorted(by_mod.items(), key=lambda x: -x[1]):
            print(f"  {sec:8.2f}s  {mod}")
    return 0
