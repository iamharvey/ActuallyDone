"""Agent 钩子的实现。由 `adone hook <名>` 调用，不在平台目录里放 .py。

Windows 上 .cursor/hooks/*.py 会被当成「要打开的文件」：Cursor 自己就是 .py
的默认应用，stop 一触发就弹出 gate-guard.py，脚本一行都没跑。
逻辑全部在本模块。Windows 登记 .exe（另写 .cmd 只给手跑）；
macOS / Linux 登记 `python3 -m actuallydone hook …`，不写 .cmd。

Qoder 读的是另一套事件和出口（exit 2 / permissionDecision）。同一套判定，
按 payload / 环境选协议；Cursor 的 stdout JSON 一个字不改。
"""

from __future__ import annotations

import codecs
import json
import locale
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config, ConfigError, find_root

MAX_LOOPS = 3

# 本轮 stdin 判定的协议。默认 cursor：老钩子没 Qoder 字段时出口必须和从前一样。
_protocol = "cursor"

# Qoder 的 hook_event_name 是 PascalCase。Cursor 即使用同一字段，写的也是
# afterFileEdit / stop / postToolUse。只认下面这些，才不会把 Cursor 回推改成 exit 2。
_QODER_EVENTS = frozenset({
    "SessionStart", "SessionEnd", "UserPromptSubmit",
    "PreToolUse", "PostToolUse", "PostToolUseFailure",
    "PermissionRequest", "PermissionDenied",
    "Stop", "StopFailure", "SubagentStart", "SubagentStop",
    "PreCompact", "PostCompact", "Notification", "InstructionsLoaded",
    "ConfigChange", "CwdChanged", "FileChanged",
    "WorktreeCreate", "WorktreeRemove", "Elicitation", "ElicitationResult",
})


def read_stdin_bytes() -> bytes:
    """按字节读 stdin。

    绝不用 `sys.stdin.read()`：那按本机代码页解码。中文 Windows 是 cp936，
    把 UTF-8 的中文当 cp936 解，双字节前导会吞掉后面那个 ASCII 字节——
    正好是 JSON 的引号或逗号，于是「payload 读不动」，改动全丢。
    """
    buf = getattr(sys.stdin, "buffer", None)
    try:
        if buf is not None:
            return buf.read() or b""
        return (sys.stdin.read() or "").encode("utf-8", "surrogateescape")
    except (OSError, ValueError, UnicodeError):
        return b""


def decode_stdin(data: bytes) -> str:
    """把钩子 stdin 解成文本。Cursor 发 UTF-8，但 BOM / UTF-16 都遇到过。"""
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8):]
    elif data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", locale.getpreferredencoding(False) or "utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def parse_payload(text: str):
    """解析钩子 payload，返回 (对象, 说明)。解不动返回 (None, 原因)。

    整串解不动时按 JSON 文档逐个捞：见过前后带杂字节、多个对象连着发的情况。
    """
    t = text.lstrip("\ufeff").strip()
    if not t:
        return None, "empty"
    try:
        return json.loads(t), ""
    except ValueError:
        pass
    dec = json.JSONDecoder()
    found: list = []
    i = 0
    while i < len(t):
        if t[i] not in "{[":
            i += 1
            continue
        try:
            obj, end = dec.raw_decode(t, i)
        except ValueError:
            i += 1
            continue
        found.append(obj)
        i = end
    if not found:
        return None, "unparsable"
    return (found[0] if len(found) == 1 else found), f"捞回 {len(found)} 段"


# payload 解不动时的最后一招：路径本身是 ASCII，即使正文乱码也还在。
_PATH_RE = re.compile(
    r'"(?:file_path|filePath|filepath|path|uri|target_file|targetFile)"'
    r'\s*:\s*"((?:[^"\\]|\\.)*)"')
_EVENT_RE = re.compile(r'"(?:hook_event_name|event)"\s*:\s*"([^"]*)"')


def paths_from_text(text: str) -> list[str]:
    out: list[str] = []
    for raw in _PATH_RE.findall(text):
        try:
            val = json.loads(f'"{raw}"')
        except ValueError:
            continue
        got = _as_path(val)
        if got and got not in out:
            out.append(got)
    return out


def _sample(text: str, n: int = 160) -> str:
    flat = " ".join(text.split())
    return (flat[:n] + "…") if len(flat) > n else flat


def _payload() -> dict:
    payload, _ = parse_payload(decode_stdin(read_stdin_bytes()))
    return _begin(payload)


def _root() -> Path:
    start = Path(os.environ.get("CURSOR_PROJECT_DIR")
                 or os.environ.get("QODER_PROJECT_DIR")
                 or os.getcwd())
    return find_root(start) or start.resolve()


def protocol_for(payload: dict | None = None) -> str:
    """本轮该按哪边的出口回话。

    payload 说了算：Qoder 每个事件都带 `hook_event_name`（官方的公共字段），
    值是 PascalCase；Cursor 同一字段写的是 afterFileEdit / stop 这种。
    只看环境不行——装过 Qoder 的机器可能把 QODER_HOME 导在全局 shell 里，
    那时 Cursor 的 stop 会被当成 Qoder，回推改成 exit 2，对话里一个字都收不到。
    """
    event = ""
    if isinstance(payload, dict):
        event = str(payload.get("hook_event_name") or payload.get("event") or "")
    if event:
        return "qoder" if event in _QODER_EVENTS else "cursor"
    # 没有事件名（Cursor 的 stop 就常常只给 status）：谁把我们起起来的谁说话
    if os.environ.get("CURSOR_PROJECT_DIR"):
        return "cursor"
    if os.environ.get("QODER_PROJECT_DIR") or os.environ.get("QODER_HOME"):
        return "qoder"
    return "cursor"


def _begin(payload: dict | None) -> dict:
    """记下本轮协议。payload 不是 dict 时按空对象，协议仍可能来自环境。"""
    global _protocol
    data = payload if isinstance(payload, dict) else {}
    _protocol = protocol_for(data)
    _note_model(data)
    return data


def _note_model(payload: dict) -> None:
    """Codex 的钩子 payload 带 model。没有这个字段就不写，不猜测。"""
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return
    root = _root()
    dest = root / ".adone"
    try:
        from .config import Config, ConfigError
        try:
            dest = Config.load(root).state_dir
        except ConfigError:
            pass
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "runner.json").write_text(json.dumps({
            "model": model.strip(),
            "at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _log(cfg: Config | None, event: str, msg: str, root: Path | None = None) -> None:
    try:
        base = cfg.state_dir if cfg is not None else (root or _root()) / ".adone"
        base.mkdir(parents=True, exist_ok=True)
        with open(base / "hook.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {event} {msg}\n")
    except OSError:
        pass


def _write_stdout(obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        sys.stdout.write(data.decode("utf-8"))
        sys.stdout.flush()


def _emit(obj: dict) -> int:
    """把钩子结果写到 stdout。Windows 上必须立刻刷出，并多等一小会儿。

    Cursor 在 Windows 上经过 PowerShell 收 stdout：进程一退出就当收完，
    管道里还没到的字节会被丢掉。Execution Log 里变成 `{}`，Agent 窗口
    看不到 followup_message——官方承认这是他们的 bug。
    中文走系统代码页（cp936）时，Node 端按 UTF-8 解析也会失败，同样像没回推。

    Qoder 不认 followup_message：拦 stop 用 exit 2 + stderr，拦 commit 用
    permissionDecision。Cursor 这条成功路径（exit 0 + JSON）一个字不改。
    """
    global _protocol
    try:
        if _protocol == "qoder":
            return _emit_qoder(obj)
        _write_stdout(obj)
        if obj.get("followup_message") and os.name == "nt":
            time.sleep(0.2)
        return 0
    finally:
        _protocol = "cursor"


def _emit_qoder(obj: dict) -> int:
    if obj.get("followup_message"):
        print(obj["followup_message"], file=sys.stderr)
        return 2
    if obj.get("permission") == "deny":
        reason = obj.get("agent_message") or obj.get("user_message") or "拒绝"
        _write_stdout({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        })
        # 理由必须同时走 stderr：官方只在 exit 0 时解析 stdout 的 JSON，
        # exit 2 交回 Agent 的是 stderr。只写 stdout 的话，Agent 收到的是
        # 一次没有原因的拒绝——它会以为是环境抽风，然后换个说法再提交一次。
        print(reason, file=sys.stderr)
        return 2
    _write_stdout({})
    return 0


def _load() -> tuple[Config | None, Path]:
    root = _root()
    try:
        return Config.load(root), root
    except ConfigError:
        return None, root


# Cursor 各版本 / 事件给的路径字段不统一。只认 file_path 时，afterFileEdit
# 会触发、dirty 却永远是空的，stop 就会把「改了很多代码」当成没改。
_PATH_KEYS = frozenset({
    "file_path", "filepath", "filePath", "path", "file", "uri",
    "target", "target_file", "targetFile",
})
_NEST_KEYS = frozenset({
    "edits", "files", "input", "tool_input", "toolInput",
    "arguments", "params", "data",
})
_SKIP_EVENTS = frozenset({"sessionStart", "sessionEnd"})


def _as_path(val) -> str:
    if isinstance(val, str):
        p = val.strip()
        if p.startswith("file://"):
            p = p[7:]
            if os.name == "nt" and p.startswith("/") and len(p) > 2 and p[2] == ":":
                p = p[1:]
        return p
    if isinstance(val, dict):
        for k in ("file_path", "filePath", "path", "uri"):
            got = _as_path(val.get(k))
            if got:
                return got
    return ""


def paths_from_payload(payload) -> list[str]:
    """从 afterFileEdit / afterTabFileEdit / postToolUse 的 JSON 里抽出路径。"""
    found: list[str] = []

    def add(val) -> None:
        if isinstance(val, list):
            for item in val:
                add(item)
            return
        p = _as_path(val)
        if p and p not in found:
            found.append(p)

    def walk(obj, depth: int = 0) -> None:
        if depth > 5 or not isinstance(obj, dict):
            return
        for key, val in obj.items():
            kl = str(key)
            if kl in _PATH_KEYS or kl.lower().endswith("path") or kl.lower().endswith("file"):
                if kl in ("workspace_roots", "transcript_path", "transcriptPath"):
                    continue
                add(val)
            elif kl in _NEST_KEYS:
                add(val)
                if isinstance(val, dict):
                    walk(val, depth + 1)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            walk(item, depth + 1)
            elif isinstance(val, dict) and depth < 2:
                walk(val, depth + 1)

    if isinstance(payload, list):
        for item in payload:
            walk(item)
    elif isinstance(payload, dict):
        walk(payload)
    return found


def _to_rel(path: str, base: Path) -> str | None:
    raw = path.strip()
    if not raw:
        return None
    p = Path(raw)
    try:
        abs_p = p if p.is_absolute() else (base / p)
        rel = os.path.relpath(os.path.realpath(abs_p), os.path.realpath(base))
    except (OSError, ValueError):
        return None
    rel = rel.replace(os.sep, "/")
    if rel.startswith("../"):
        return None
    return rel


def _append_dirty(cfg: Config | None, root: Path, rel: str) -> None:
    dest = (cfg.dirty if cfg is not None else root / ".adone" / "dirty")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(rel + "\n")


def cmd_mark_dirty(_args=None) -> int:
    cfg, root = _load()
    _log(cfg, "mark-dirty", "launched", root)
    data = read_stdin_bytes()
    raw = decode_stdin(data)
    payload, note = parse_payload(raw)
    _begin(payload if isinstance(payload, dict) else {})

    event = ""
    if isinstance(payload, dict):
        event = str(payload.get("hook_event_name") or payload.get("event") or "")
    if not event:
        m = _EVENT_RE.search(raw)
        event = m.group(1) if m else ""

    paths = paths_from_payload(payload) if payload is not None else []
    if not paths:
        # 解析失败或字段没认出来时，路径本身仍是 ASCII，直接从原文捞
        paths = paths_from_text(raw)
    if not paths:
        if event in _SKIP_EVENTS or not raw.strip():
            _log(cfg, "afterFileEdit", f"{event or 'empty'} 无路径，跳过", root)
        else:
            keys = list(payload) if isinstance(payload, dict) else type(payload).__name__
            _log(cfg, "afterFileEdit",
                 f"payload 无路径（{note or 'ok'} keys={keys} event={event} "
                 f"stdin={len(data)}B）：{_sample(raw)}", root)
        return _emit({})

    base = cfg.root if cfg is not None else root
    roots = (cfg.get("gate.watch_roots") or ["."]) if cfg else ["."]
    exts = (cfg.get("gate.watch_exts") or []) if cfg else []
    noted: list[str] = []
    for path in paths:
        rel = _to_rel(path, base)
        if rel is None:
            continue
        if not _watched(rel, roots, exts):
            continue
        try:
            _append_dirty(cfg, root, rel)
            noted.append(rel)
        except OSError as e:
            _log(cfg, "afterFileEdit", f"写 dirty 失败（{e}）：{rel}", root)
    if noted:
        tail = f"（{note}）" if note else ""
        _log(cfg, "afterFileEdit", f"记下 {'、'.join(noted[:8])}{tail}", root)
    else:
        _log(cfg, "afterFileEdit",
             f"{len(paths)} 个路径都不在受监视树里（roots={roots} exts={exts}）："
             f"{'、'.join(paths[:4])}", root)
    return _emit({})


def _watched(rel: str, roots: list, exts: list) -> bool:
    if exts and not any(rel.endswith(e) for e in exts):
        return False
    for r in roots:
        r = str(r).rstrip("/")
        if r in ("", "."):
            return True
        if rel == r or rel.startswith(f"{r}/"):
            return True
    return False


def cmd_gate_guard(_args=None) -> int:
    cfg, root = _load()
    _log(cfg, "stop", "gate-guard launched", root)
    payload = _payload()
    if payload.get("stop_hook_active") in (True, "true", "True", 1, "1"):
        _log(cfg, "stop", "stop_hook_active，放行", root)
        return _emit({})
    status = payload.get("status")
    loops = int(payload.get("loop_count") or 0)

    if status not in (None, "completed"):
        _log(cfg, "stop", f"status={status} 不拦", root)
        return _emit({})
    if loops >= MAX_LOOPS:
        _log(cfg, "stop", f"loop_count={loops} 到上限，放行", root)
        return _emit({})

    if cfg is None:
        _log(cfg, "stop", "找不到 adone.toml，已回推", root)
        return _emit({"followup_message": "\n".join([
            "【完成门禁没跑成】从当前目录往上找不到 adone.toml。",
            "",
            "这不等于门禁通过。把 Cursor 工作区开在放 adone.toml 的那一层"
            "（或它的子目录），再谈完成。",
        ])})

    from .changed import changed_paths, git_changed, run_changed, same_as_last_ok_partial
    from .gate import read_dirty
    roots = cfg.get("gate.watch_roots") or ["."]
    exts = cfg.get("gate.watch_exts") or []
    dirty = read_dirty(cfg)
    git_files, git_note = git_changed(cfg)
    files = [f for f in changed_paths(cfg) if _watched(f, roots, exts)]
    if not files:
        preview = "、".join((dirty or git_files)[:6]) or "空"
        _log(cfg, "stop",
             f"dirty {len(dirty)} / git {len(git_files)} 条（git：{git_note}），"
             f"无一受监视（roots={roots} exts={exts} 例如 {preview}），不回推", root)
        return _emit({})
    if same_as_last_ok_partial(cfg, files):
        _log(cfg, "stop", f"相关用例已通过且文件未再改（{len(files)}），跳过", root)
        return _emit({})

    try:
        data = run_changed(cfg, paths=files, quiet=True)
    except Exception as e:
        _log(cfg, "stop", f"--changed 跑不起来（{type(e).__name__}: {e}），已回推", root)
        return _emit({"followup_message": "\n".join([
            f"【相关用例没跑成】gate run --changed 没能给出结果（{type(e).__name__}）：",
            "", str(e), "",
            "只跑 `adone gate run --changed`，不要跑全量 `gate run`。",
            "全量是 git commit / 宣称完成时的事。",
        ])})

    if data.get("ok"):
        _log(cfg, "stop", f"相关用例通过（{len(files)} 个文件），放行")
        return _emit({})

    problems = data.get("problems") or []
    skills = cfg.get("project.skills_dir") or ".cursor/skills"
    lines = ["【相关用例未通过】本轮改了受监视文件，相关测试没过。是本轮改坏的就先修，不要跑全量门禁：", ""]
    lines += [f"{i}. {p}" for i, p in enumerate(problems, 1)]
    lines += [
        "",
        f"按 {skills}/completion-gate/SKILL.md：只跑 `adone gate run --changed`。",
        "不要跑 `adone gate run` 全量——那是 git commit 或宣称完成时的事。",
        "如果找不到相关用例，先写一条对着这些文件的测试再继续。",
        "失败的用例如果与本轮改动无关（改之前就失败），不要停下，也不要修、跳过或删掉它："
        "按「有用例失败，但不是这次改的」给出归属证据，做完本轮的事，交付时单独列出。",
        "如果确实跑不起来，直接告诉我卡在哪一步、看到什么输出。",
    ]
    _log(cfg, "stop", f"相关用例未通过（{len(problems)} 个问题，loop_count={loops}），已回推")
    return _emit({"followup_message": "\n".join(lines)})


_COMMIT_RE = re.compile(r"\bgit\b(?:\s+\S+)*\s+commit\b")
# --accept-baseline 也含有 --accept 这串，所以放宽判据的 --accept 不能吃到它。
_POLICY_ACCEPT_RE = re.compile(r"--accept(?!-)\b")


def _is_git_commit(command: str) -> bool:
    return bool(_COMMIT_RE.search(command or ""))


def _is_self_relax(command: str) -> bool:
    """模型自己销账：放宽假绿基线、放宽判据、豁免「没新测试」。"""
    cmd = command or ""
    if re.search(r"--accept-baseline\b", cmd) and re.search(r"\bintegrity\b", cmd):
        return True
    if re.search(r"\bwaive-tests\b", cmd):
        return True
    if re.search(r"\bpolicy\b", cmd) and _POLICY_ACCEPT_RE.search(cmd):
        return True
    return False


def _shell_command(payload: dict) -> str:
    command = payload.get("command") or ""
    if not command:
        tool_input = payload.get("tool_input")
        if isinstance(tool_input, dict):
            command = tool_input.get("command") or ""
    return command or ""


def cmd_commit_guard(_args=None) -> int:
    """拦 git commit（含 --no-verify）：必须先有新鲜的全量回执。
    也拦模型自己放宽尺子。

    Cursor 走 beforeShellExecution。Qoder 的 matcher 只能收到工具名（Bash / Shell），
    每一条 ls 都会进来，所以先判命令、再读配置写日志：否则每敲一条命令都要解一遍
    adone.toml，并往 hook.log 里堆一行，真正那条 commit 记录就淹了。
    """
    payload = _payload()
    command = _shell_command(payload)
    if not _is_git_commit(command) and not _is_self_relax(command):
        return _emit({"permission": "allow"})

    if _is_self_relax(command) and not _is_git_commit(command):
        cfg, root = _load()
        _log(cfg, "beforeShellExecution", "拒绝自行放宽", root)
        msg = ("放宽只能由人在终端里执行，不要在这一轮里自己销账。"
               "integrity --accept-baseline、policy --accept、"
               "gate waive-tests 都一样。")
        return _emit({"permission": "deny", "user_message": msg, "agent_message": msg})

    cfg, root = _load()
    _log(cfg, "beforeShellExecution", "commit-guard launched", root)
    if cfg is None:
        _log(cfg, "beforeShellExecution", "找不到 adone.toml，已拒绝提交", root)
        msg = ("找不到 adone.toml，不能在没有完成门禁的情况下提交。"
               "把工作区开在放 adone.toml 的那一层，先跑 adone gate run（全量）。")
        return _emit({"permission": "deny", "user_message": msg, "agent_message": msg})

    try:
        from .gate import collect_check
        data = collect_check(cfg)
    except Exception as e:
        _log(cfg, "beforeShellExecution", f"check 跑不起来（{type(e).__name__}: {e}）", root)
        msg = (f"gate check 没能给出结果（{type(e).__name__}）：{e}\n"
               "先跑 adone gate run（全量）再 git commit。")
        return _emit({"permission": "deny", "user_message": msg, "agent_message": msg})

    if data.get("ok"):
        _log(cfg, "beforeShellExecution", f"全量回执通过（{data.get('receipt_id')}），允许提交")
        return _emit({"permission": "allow"})

    problems = data.get("problems") or []
    msg = "\n".join([
        "全量门禁未通过，不能提交。先跑 adone gate run（全量），再 git commit。",
        *[f"- {p}" for p in problems],
    ])
    _log(cfg, "beforeShellExecution", f"拒绝提交（{len(problems)} 个问题）")
    return _emit({"permission": "deny", "user_message": msg, "agent_message": msg})


HOOKS = {
    "mark-dirty": cmd_mark_dirty,
    "gate-guard": cmd_gate_guard,
    "commit-guard": cmd_commit_guard,
}


def cmd_hook(args) -> int:
    fn = HOOKS.get(args.hook)
    if fn is None:
        print(f"不认识的钩子：{args.hook}（可用：{'、'.join(HOOKS)}）", file=sys.stderr)
        return 2
    return fn(args)
