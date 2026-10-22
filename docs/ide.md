# 按 IDE 接入钩子

[← 回到 README](../README.md)

`adone init` / `gate` / `doctor` 在 Cursor 和 Qoder 上一样。不一样的是钩子写到哪、Agent 用哪套事件拦。
本机 `.git/hooks/pre-commit` 两边共用：你在终端敲的 `git commit` 靠它。

`--ide`：`auto`（默认）看不出 Qoder 就只装 Cursor；`cursor` / `qoder` 只动一边；`all` 两份都写。
钩子登记是本机生成物（里面是这台机器的绝对路径），**不要入库**。

## Cursor

```bash
adone install --with-hooks              # 默认就是这条
adone install --with-hooks --ide cursor # 显式，不看环境里有没有 Qoder
adone install --hooks-only --force      # 升完 adone 后重渲
```

写 `.cursor/skills/`、`.cursor/hooks.json`，Windows 上还有 `.cursor/hooks/*.exe`（不要提交）。
macOS / Linux 登记 `python3 -m actuallydone hook …`；Windows 登记 `.cursor/hooks/<名>.exe`。

确认装好：`adone doctor` 显示「钩子：已装」；新开一轮对话、改一个受监视文件后，
`.adone/hook.log` 里出现 `mark-dirty launched`。Windows 上 `hooks.json` 的 command 必须是 `.exe`，
不能是 `.cmd` / `.py`（`CreateProcess` 跑不了批处理，`.py` 会打开编辑器）。

## Qoder

Qoder 不读 `.cursor/hooks.json`，要写 `.qoder/settings.json`。

```bash
# 在 Qoder 自己的终端里（有 QODER_PROJECT_DIR），auto 会走到 Qoder
adone install --with-hooks

# 普通终端、或 auto 没认出来时，显式指定（不碰 .cursor/）
adone install --with-hooks --ide qoder
adone install --hooks-only --force --ide qoder
```

写 `.qoder/skills/`、`.qoder/settings.json`（exec 形式：`command` + `args`，绝对路径）。
改完配置**重启 Qoder**（官方尚未热重载）。相对路径解不开时 `PreToolUse` 会把每条 shell 命令都拦下，
所以这份 settings **不要入库、不要抄别人的**。

确认装好：`adone doctor` 显示「Qoder 钩子：已装」；改一个受监视文件后 `hook.log` 有 `记下 …`；
让 Agent 提交一次，应当被拦**并且看到理由**。

## 一个仓库两种 IDE 都开

```bash
adone install --with-hooks --ide all
adone install --hooks-only --force --ide all
```

两边各写各的目录，pre-commit 仍是一份。

## 事件对照

| 做什么 | Cursor | Qoder |
| --- | --- | --- |
| 记 dirty | `afterFileEdit` / `afterTabFileEdit` / `postToolUse` | `PostToolUse`（Write / Edit / search_replace / create_file） |
| 回合结束跑相关用例 | `stop` → stdout `followup_message` | `Stop` → exit 2 + stderr（`stop_hook_active` 为真立刻放行） |
| Agent 跑 `git commit` | `beforeShellExecution` matcher `git commit` | `PreToolUse` matcher `Bash` / `Shell` |
| Agent 自己放宽判据 | `beforeShellExecution` 拒绝 `--accept-baseline` / `policy --accept` / `waive-tests` | `PreToolUse` 同样拒绝 |
| 人在终端 `git commit` | `.git/hooks/pre-commit` | 同一份 |

三个钩子跑的是同一套 `adone hook`：`mark-dirty` 记 dirty，`gate-guard` 跑相关用例，`commit-guard` 拦提交。
`stop` 的「说完了」不是「做完了」，完成只认全量回执。

## 多模块工作区

`adone.toml` 常在子目录。pre-commit 仍写进上层仓库的 `.git/hooks/`（配了 `core.hooksPath` 就写到那边），
脚本会 `cd` 回 `adone.toml` 那一层。装完看一眼 `adone install` 打印的路径。

IDE 的工作区要开在放 `adone.toml` 的那一层。只开子模块时，钩子的工作目录和
`CURSOR_PROJECT_DIR` 都对不上。
