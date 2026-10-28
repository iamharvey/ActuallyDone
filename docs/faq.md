# 常见问题

[← 回到 README](../README.md)

遇到问题先跑 `adone doctor`，它会拿配置对现实核一遍，指出路径、命令、钩子哪里不对。

## 安装与升级

**`adone` 敲不出来？**
把 pipx 的 bin 加进 PATH（`~/.local/bin` 或 `%USERPROFILE%\.local\bin`），见 [install.md](install.md)。

**`pipx upgrade actuallydone` 说「已是最新」，GitHub 上明明有新版？**
当初带了 `@v1.x` 这样的 tag 装，pipx 记成了升级源。改用 `adone upgrade`，或不带 tag 重装：
`pipx install --force git+https://github.com/iamharvey/ActuallyDone.git`。

**升级了 adone，钩子却还是旧的？**
钩子里烧着安装时的绝对路径。`adone upgrade` 之后必须 `adone install --hooks-only --force`，再 `adone doctor`。

**每次敲 adone 都问要不要升级？**
设 `ADONE_NO_UPDATE_CHECK=1`。钩子、`--json`、管道和 CI 本来就不问。

## 钩子

**`git commit` 没触发全量门禁？**
两条路各管一半，缺哪条都是安静地不设防。Agent 跑的 `git commit` 靠 commit-guard：`hook.log` 里没有
`commit-guard launched` 就是登记里没有它，重跑 `adone install --hooks-only --force`。
你在终端敲的 `git commit` 只有 `.git/hooks/pre-commit` 拦得住。

**日志写了「已回推」，对话里没有那条消息？**
钩子已经跑完。Cursor 在 Windows 上经常没收齐 stdout，Execution Log 里变成 `{}`。
看 View → Output → Hooks 里这次 `stop` 的输出。以 `hook.log` 和 `adone gate check` 为准。

**Windows 上手跑 `gate-guard.cmd` 有日志，Agent 里却没触发？**
登记必须是 `.cursor/hooks/gate-guard.exe`。`.cmd` 和 `cmd /c …cmd` 都不行，`.py` 会打开编辑器。

**问一句设计、没改代码，也被推去跑测试？**
那是旧钩子。升级后跑 `adone install --hooks-only --force`。现在没改受监视文件时 `stop` 静默放行。

**同一份配置能在 Windows、macOS、Linux 跑吗？**
`adone.toml` 能：写 `mvn` / `npm` / `./mvnw` 即可，Windows 上会解析成 `.cmd` 并由 `cmd /c` 拉起。
钩子不行：按安装那台机器生成，各人在本机重渲，不要提交对方的 command 和 `.exe`。

## 门禁与基线

**Agent 遇到别人留下的失败用例怎么办？**
它应该做完本轮的事，不修、不跳过、不删那条用例，交付时附归属证据单列。全量门禁照样不绿、提交照样被拦，
由人决定先修还是另开任务。见 [gate.md](gate.md#有用例失败但不是这次改的)。

**Java 覆盖率读不到，但 `mvn` 是绿的？**
步骤写成 `mvn -B -ntp jacoco:prepare-agent test jacoco:report`。只跑 `test jacoco:report` 时没挂探针也会成功。

**Windows 上 pre-commit 报 `gbk codec can't encode`？**
v1.4.2 已修。重渲 `adone install --hooks-only --force` 后钩子里会带 `PYTHONIOENCODING=utf-8`。
不要手改 `.git/hooks/pre-commit`，下次重渲会盖掉。

**`adone detect --write` 把阈值冲掉了？**
新接入一门生态用 `adone detect --merge`，它不碰阈值。

**合并代码时 `.adone/chain.json` 或 `new-tests-waiver.json` 冲突了？**
这两份是各人追加一行。序号是各人自己数的。跑 `adone gate repair-chain`，两边都留，并把 `.gitattributes` 里的两行 `merge=union` 一并提交。见 [baselines.md](baselines.md)。

**两份基线也冲突了？**
只有两边都记账才会改这两个文件。合完在合并结果上重新 `adone policy --accept` 或 `adone integrity --accept-baseline`。留任意一边都可以当起点，对方放宽的部分会再被报出来。

**`latest.json`、回执、`hooks.json` 要不要入库？**
不要。回执每人跑一次就整份换掉。`hooks.json` 在 Windows 上是 `.exe`，在 macOS / Linux 上是 `python3 -m`，提交了必冲突。技能可以入库；里面不写本机绝对路径。

**删了基线想让检查闭嘴？**
上一份回执记着基线指纹，会被拦。要放宽就 `--accept` / `--accept-baseline` 写理由，见 [baselines.md](baselines.md)。

**`generic` 项目为什么很多检查是未评估？**
generic 适配器只能跑步骤，列不出用例名。假绿、契约、`--spotcheck` 显示未评估，而不是假装通过。

**测试是绿的，数据却是跑完才改的？**
门禁看不见这种。打开契约点名的用例：调用之后改了规则要读的字段，或断言比「要求」弱，复核按未通过写。见 [audit.md](audit.md#全绿不证明夹具老实)。

**独立复核通过 = 不可能造假？**
不是。复核者和实现者有同一套写权限，`--rerun` 只是抬高成本。要硬证据，把门禁放到 CI。
