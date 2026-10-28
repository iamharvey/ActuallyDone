# 变更记录

版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## v1.8.0 — 2026-10-28

`.adone/chain.json` 和 `.adone/new-tests-waiver.json` 改成一行一条、只追加。`.gitattributes` 的 `merge=union` 让两边都留。已经冲突的用 `adone gate repair-chain` 收。

- 回执、`latest.json`、钩子登记不入库。演示仓库里已经跟踪的回执和 `hooks.json` 从版本库拿掉。技能不再写入本机绝对路径，重渲时也不再因本机有没有钩子而改字。
- 两份基线仍是整份快照。两边都记账时会冲突；合完重新记账。落盘时键排序，避免同一份快照因键顺序不同而看起来像改过。

## v1.7.0 — 2026-10-23

全绿回执仍只表示契约里的用例在当前代码树上通过。补上复核时要看的两种假绿：调用之后改数据凑条件，以及把判定写成恒真。

- `test-integrity` 增加第 7 种假绿，`acceptance-contract` 要求规则类需求配一条走同一入口的反例。这两句进评测闸门的必留句。写测试、独立复核、评审清单、可验证交付各收一句。
- `adone brief` 印出这段：打开契约点名的用例，调用之后改了规则要读的字段，或断言比「要求」弱，按未通过写。不新增 `audit` 失败码。
- `bench/` 新增 `cs-fixture-cheat`。隐藏验收自己用诚实输入跑正例和反例，并检查测试有没有在调用之后改主题、发件人、邮箱、状态。
- `demo/merge-mail` 是同一件事的可运行范例：unittest 照样绿，项目自己加的第二步才抓调用之后改邮箱；反面教材在 `demo/merge-mail/examples/`。
- `examples/java`、`examples/go` 是两份基线 `adone.toml`：格式化、风格、敏感信息、单元测试、API 测试、端到端、技能检查。抄到仓库里用，本身跑不起来。

## v1.6.1 — 2026-10-22

修两个用户反馈的 Bug，README 重写。门禁判定不变：有既有失败时全量门禁照样不绿，提交照样被拦，由人决定。

- **遇到与本次改动无关的失败用例就停工**：`completion-gate` 新增「有用例失败，但不是这次改的」。先用上一份回执的 `tests.failed_names` 或在 `HEAD` 上单跑判归属，确认无关就做完本轮的事，不修、不跳过、不删那条用例，交付时单列。stop 钩子推回时也这么说，不再只说「先修这些问题」。
- **照着接口文档返回示例值，没真的调接口**：`completion-gate`、`test-driven-dev`、`verified-delivery` 要求真的发请求，用例断言请求本身（方法、路径、参数）。细则在 `completion-gate/references/external-api.md`。
- `bench/` 新增两道题 `cs-unrelated-red`、`cs-logistics-api` 测这两种情况。题目可以带 `setup/`，放进基线提交，agent 看得到，但不算它的改动。
- `completion-gate` 的「诚实的边界」挪到 `references/limits.md`，正文回到 120 行以内。
- README 从近 800 行缩到一页：是什么、怎么装、怎么上手、日常怎么用。安装、IDE 钩子、门禁、配置、基线、复核、健康报告、常见问题拆到 `docs/` 下各自一页，评测流程写在 `bench/README.md`。

## v1.6.0 — 2026-10-21

技能怎么改，改到仓库顶层的 `bench/` 里用 Propose–Probe–Compose 评，不进 `actuallydone` 的包。门禁、钩子和安装命令与 v1.5.0 相同。

- 三道固定题分别看会不会补测试、会不会把失败用例跳过、会不会在「先讨论」时改代码。隐藏验收在 agent 退出后才拷进工作区，Propose 和 Compose 看不到用例正文。
- 虚假完成、越权、降标准和隐藏验收只要有一项比参照差，就不进合并池。后继再跑一轮，仍差就报告「保持现状」，不写 `skills.patch`。
- 补丁和 `EXPERIENCE.md` 只落在 `bench/runs/`。人看完再 `git apply` 到模板；教训要自己抄进 `bench/lessons/`。
- 题目从已提交的 demo 拷出。工作区里没入库的放宽不会被记成这一轮降了标准。

## v1.5.0 — 2026-10-06

门禁通过不再被说成「可以宣称完成」。回执是交给另一个模型的证据。

- **实现变了、测试没变**：全量回执分开记实现哈希和测试哈希。相对上一份带这两个字段的全量回执，实现变了而测试文件没变，`gate check` 不通过，提交也会被拦住。扫不到测试文件时标成未评估。老回执不回溯。
  人可以 `adone gate waive-tests "理由"`，豁免绑在当前实现哈希上，实现再变则失效。只改测试注释会让测试哈希变化从而放行，删用例仍由 `integrity` 抓。
- **模型不能自己放宽尺子**：钩子拒绝 `integrity --accept-baseline`、`policy --accept`、`gate waive-tests`。人在 IDE 外的终端敲，钩子看不到。Cursor 的 `beforeShellExecution` matcher 放宽到这几条，已装过的仓库要重新 `adone install --hooks-only`。
- **同一个模型自己审自己**：钩子 payload 里有 `model` 时写入 `.adone/runner.json`，全量回执抄一份 `runner.model`。`adone audit --reviewer` 与它相同则多一条问题；缺任何一边只写进依据。没有 `audit` 不拒绝提交。

## v1.4.2 — 2026-09-03

中文 Windows 上 pre-commit 跑 `gate run` 会 `UnicodeEncodeError: 'gbk' codec can't encode`。
Maven 按 UTF-8 吐日志，Python 却按 GBK 写控制台。用户在钩子里加
`PYTHONIOENCODING=utf-8` 能救急，但 `install --hooks-only` 会盖掉。

- 入口把 stdout / stderr 改成 UTF-8（`errors=replace`），终端、Cursor 钩子、
  pre-commit 同一条路。
- 新装的 `.git/hooks/pre-commit` 和 Windows 启动器带上 `PYTHONIOENCODING=utf-8`。

## v1.4.1 — 2026-09-03

Qoder 那条路上四处会让门禁静默失效的地方。Cursor 的登记与出口仍然一个字不改。

- **拒绝提交时理由到不了 Agent**：官方只在 `exit 0` 时解析 stdout 的 JSON，
  `exit 2` 交回 Agent 的是 stderr。原来 `permissionDecisionReason` 只写 stdout，
  Agent 收到的是一次没有原因的拒绝——它会当成环境抽风，换个说法再提交一次。
  理由现在同时走 stderr。
- **一个环境变量就能改掉 Cursor 的出口**：原来只要环境里有 `QODER_HOME` /
  `QODER_PROJECT_DIR` 就走 Qoder 协议。装过 Qoder 的机器可能把它导在全局 shell 里，
  于是 Cursor 的 stop 回推变成 exit 2，对话里一个字都收不到。改为 payload 的
  `hook_event_name` 说了算（Qoder 每个事件都带它），环境只在没有事件名时兜底，
  且 `CURSOR_PROJECT_DIR` 优先。
- **每条 shell 命令都解一遍 adone.toml、写一行 hook.log**：Qoder 的 matcher 只到
  工具名（Bash / Shell），每条 `ls` 都会进 commit-guard。改为先判命令再读配置。
- **仓库内入口改写绝对路径**：exec 形式不过 shell，而 Qoder 没承诺钩子进程的工作目录
  是项目根。相对路径解不开时 python 的退出码正好是 2，而 `PreToolUse` 上的 2 就是
  「拒绝」——每条 shell 命令都被拦，理由还是一句 python 报错。Windows 上 `adone`
  解析成 `.cmd` / `.bat` 时改走 `cmd.exe /c`（exec 不了批处理）。
- **`--ide qoder` 不再要 `--force`**：合并只替换带我们标记的条目，别人的登记原样留下；
  而 auto 认出 Qoder 的条件之一正是「settings.json 已经在」，要 `--force` 才肯写的话，
  最常见的那条安装命令会什么都不做还说自己成功了。已是最新则明说没改。
- **`adone doctor` 核 Qoder 登记起不起得来**：命令能否解析、argv 里的脚本是否存在。
  原来只查事件在不在——这正是 Cursor 侧踩过的坑。

## v1.4.0 — 2026-09-03

范围化全量：只跑相对上一份全量绿回执变过的模块，串行照旧，工作量降一个数量级。

- **`adone gate run --affected`**：按 `watch_roots` 各算一份单元哈希，变过的交给
  Maven `-pl … -amd`（依赖闭包 maven 自己算）。Gradle 没有 `-amd`，明确拒绝，
  不许偷偷少跑。回执写 `scope=affected`、`units`、`carried`、`tests.ran_names`；
  `passed_names` 是本轮真跑与继承的并集——契约校验靠它，少写会把未跑模块的契约全打红。
- **`gate check` 校验继承**：源头必须在链上且通过、继承单元哈希与源头一致、
  本轮单元与当前一致。证据强度写成「部分重跑（继承自回执 X）」，不能和全量说同一句话。
- **提交默认仍是全量。** 要让 pre-commit 走范围化，显式写 `gate.commit_scope = "affected"`。
  钩子改为 `gate run --for-commit`。
- **`adone doctor`** 报告单元划分、能不能缩范围、链上有没有可继承的全量绿回执。
  `commit_scope = affected` 却缩不了或没有源头时，标成问题。
- **Qoder 钩子**：`--ide {auto,cursor,qoder,all}`。`auto` 看不出 Qoder 就只装 Cursor。
  `--ide qoder` 只写 `.qoder/` 和本机 pre-commit。运行时同一套 `adone hook`：
  Qoder 拦 stop 用 exit 2 + stderr，拦 commit 用 `permissionDecision`；
  Cursor 的 `followup_message` / `permission` 一个字不改。

## v1.3.23 — 2026-09-03

- **端口冲突要被叫出名字**：失败步骤的 note 会写「端口 8080 被占」，Java 还会点出
  Spring 测试上下文缓存——前一个上下文没关，串行也会撞。建议 `RANDOM_PORT`。
- **`adone gate slow`**：读 surefire XML 的 `time`，按用例和按模块出耗时榜。
  `gate run` 测完打最慢 5 条。耗时不写进回执。
- README 加「全量跑太久怎么查」：先看卡住和端口冲突，再看耗时榜，最后才谈并发。
  固定端口的测试连上本机旧服务然后通过，是真的假绿。

## v1.3.22 — 2026-09-03

卡死和慢跑以前长得一模一样。这是后面所有判断成立的前提。

- **步骤边跑边打输出**，步骤名开跑前就打印。静默超过 60 秒打一行心跳。
- **`timeout_seconds` / `stall_seconds`**（每步可选，默认不限时）。超时退出码 124，
  `timed_out` 进回执。超时不进判据快照——造不出假绿，塞进去只会逼所有人重记账。
- **杀进程树**：POSIX `start_new_session` + `killpg`，Windows `taskkill /T /F`。
  孤儿 surefire JVM 会占着端口，这个坑会自己复制自己。钩子模板同步修。

## v1.3.21 — 2026-09-02

- **`adone clean`**：拆除当前项目里的配置、`.adone`、物料目录、我们渲染的技能、
  hooks.json 里的 adone 登记、钩子启动器和本机 pre-commit。拆完门禁不再跑。
  默认先列出再问（`[y/N]`）；`--yes` 直接拆，`--dry-run` 只看不删。
  别人的钩子和不是我们写的技能留下。

## v1.3.20 — 2026-09-02

- **交互式命令会问要不要升级**：`adone doctor` / `gate` / `install` 这类人敲的命令，
  发现 GitHub 上有新版本时先问一句 `[y/N]`。回车继续手头的事；`y` 走
  `adone upgrade` 同一条路径，升完请重新跑刚才那条命令（当前进程里还是旧代码）。
  钩子、`--json`、管道、CI 不问。联网结果缓存半天，避免每次都打 GitHub。
  设 `ADONE_NO_UPDATE_CHECK=1` 可关掉。
- **判据锁补上 `cwd` / `adapter` 和构建文件**：只改步骤工作目录、不改 argv
  就能把测试指到另一份代码，以前不报。`pom.xml` 等 marker 文件的内容指纹
  也纳入快照（老基线没有这个字段不比对）。
- **eval 的 FAIL 行带原因不再被丢掉**；**pytest 汇总行不再依赖字段顺序**
  （`5 passed, 1 failed` 以前会解析成 0 失败）。

## v1.3.19 — 2026-09-02

提交时的全量门禁在多模块工作区里从来没生效过，而它失效的样子和「装好了」一模一样。

- **`adone.toml` 不在仓库根上时 pre-commit 装不上**：以前硬拼 `项目目录/.git`，
  只要仓库根在上层就当成「不是 git 仓库」跳过，手工 `git commit` 一路畅通。
  改成用 `git rev-parse` 定位，顺带认了两种以前也会被跳过的情形：
  `.git` 是文件（submodule / worktree，钩子在主仓库的 common dir 里）、
  仓库配了 `core.hooksPath` 把钩子目录挪走（写进 `.git/hooks` 的东西 git 根本不看）。
- **pre-commit 进错目录**：脚本原来 `cd` 到仓库根就跑 `adone gate check`。
  项目在子目录时 adone 往上找不到 `adone.toml`，反而把「没配置」当成「不许提交」。
  现在 `cd` 到 `adone.toml` 那一层。找解释器也补上了 `python` 与 `py -3`。
- **`adone doctor` 补上两个盲区**：`.git/hooks/pre-commit` 不在时点名
  （Cursor 钩子只看得见 Agent 跑的 shell，你自己在终端敲的 `git commit` 只有它拦得住）；
  `hooks.json` 里没有 `commit-guard` 登记时点名（v1.3.14 之前装的登记没有
  `beforeShellExecution`，Agent 提交时没人拦，`hook.log` 里连一行都不会出现）。
- 跳过 pre-commit 时把原因和后果一起打出来，不再只是一句「不是 git 仓库」。

从 v1.3.13 及更早升上来的项目，必须 `adone install --hooks-only --force` 才会补上
提交门禁；装完 `adone doctor` 应当同时报出 `commit-guard` 与 `git pre-commit` 两行。

## v1.3.18 — 2026-09-01

- **新增 `project.source_encoding`**：`adone init` / `detect` 采样受监视树自动判断
  （`utf-8` / `gbk` / 混着放就 `auto`），写进 `adone.toml` 并标「请确认」，人可以改。
  UTF-8 永远先试，这一项只决定解不动时退到哪；逐个文件判断，迁移期混编码也不怕。
- **GBK 源码不再被读成乱码**：源码、文档、技能的读取统一走 `textio`。
  GBK 尾字节范围含 ASCII，`亄`（81 7B）硬按 UTF-8 读会凭空多出一个 `{`，
  大括号一乱就会切错函数体，"相关用例"因此少认几条却不报错。
- `adone.toml` 自己不是 UTF-8 时给一句人话（TOML 规范只认 UTF-8），
  并说明源码编码归 `source_encoding` 管。

## v1.3.17 — 2026-09-01

- **中文 Windows 上钩子读不动 payload**：`sys.stdin.read()` 按本机代码页解码，
  cp936 把 UTF-8 的中文正文解坏（双字节前导会吞掉后面的引号），
  于是每次编辑都记成「读不动 payload」，dirty 永远为空。改成按字节读，
  依次试 BOM / UTF-8 / 本机编码；整串解不动就逐段捞 JSON；再不行用正则从原文
  抽 `file_path`（路径是 ASCII，正文乱码也还在）。
- **子目录是独立 git 仓库时 git 名单为空**：只在项目根跑 `git status` 的话，
  `aics-bank/aics-api` 这类自带 `.git` 的子项目一条都看不到。现在按项目根与
  各 `watch_roots` 分别定位仓库，逐个取名单再收回项目根的相对路径。
- **git 的输出也按代码页解坏了**：git 的路径一律是 UTF-8，`text=True` 却按 cp936 解。
  加上 git 默认把非 ASCII 路径转义成 `"\346\226\207"`，中文文件名根本对不上磁盘。
  改成显式 UTF-8 解码 + `core.quotepath=false` + `-z`（顺带修好带空格和改名的路径）。
- **git 不在钩子进程 PATH 上时不再装作干净**：找不到 git、不在仓库里、改动都在
  项目目录外，这三种都会写进 hook.log，`gate run --changed` 也会打印原因。
- Windows 上盘符大小写不一致时不再整批丢弃（改用不区分大小写的前缀比较）。

## v1.3.16 — 2026-09-01

- **嵌在父仓库里的项目 git 路径对不上 watch_roots**：`demo/pet-store-java`
  这类布局里，`git status` / `git diff` 给出的是 `demo/pet-store-java/src/Foo.java`，
  对 `watch_roots = ["src"]` 判不成受监视，stop 就写「dirty 与 git 都没有受监视改动」。
  现在把路径收成相对 `adone.toml` 所在目录；父仓库里的兄弟文件不计入。
- dirty 与 git 名单合并，不再「有 dirty 就不再看 git」。跳过时 hook.log 会写下
  dirty/git 条数和例子，避免再对不上却看不出原因。

## v1.3.15 — 2026-09-01

- **afterFileEdit 记不下 dirty**：只认 `file_path` 时，Cursor 给 `filePath` /
  `tool_input.path` / 空 stdin 都会让 dirty 永远为空，`stop` 把大量改动当成没改。
  现在从多种字段抽路径；`sessionStart` 无路径不再当失败；记成功会在 hook.log 写「记下 …」。
- **stop 兜底**：dirty 为空时看 `git status`（含未跟踪新文件），只对受监视后缀跑 `--changed`。
  上一轮 `partial.json` 已通过且文件哈希没变则跳过，避免问答反复跑。
- 额外登记 `afterTabFileEdit` 与 `postToolUse`（Write / StrReplace / Edit）。
  已装项目要 `adone install --hooks-only --force`。

## v1.3.14 — 2026-08-31

- **开发中增量、提交时全量**：Cursor `stop` 的 `completed` 只表示这轮说完了，不是「做完了」。
  dirty 为空时不回推（问答、读代码不再被推去跑全量）；有 dirty 时只跑
  `adone gate run --changed`（相关用例，写 `.adone/partial.json`，不覆盖 `latest.json`）。
  找不到相关用例就回推「写一条再继续」，不退回全量。
- **提交才写完成回执**：`install --with-hooks` 写入本机 `.git/hooks/pre-commit`
  （回执不新鲜则 `gate run`）；Cursor `beforeShellExecution` 命中 `git commit`
  （含 `--no-verify`）时先 `gate check`，不对就拒绝。
- 已装钩子的项目要 `adone install --hooks-only --force` 才会更新技能与登记。

## v1.3.13 — 2026-08-31

- **C++ 适配器**：认 `CMakeLists.txt` / `meson.build`。CMake 步骤同一份 argv
  覆盖 Windows（`cmake.exe` + Visual Studio `--config` / `ctest -C`）、macOS 与
  Linux（Ninja / Makefiles）。解析 GoogleTest / CTest / Catch2；覆盖率认 lcov。
- **演示**：`demo/task-store-cpp`（C++17 内存任务清单，零 GoogleTest 依赖）。

## v1.3.12 — 2026-08-31

- **可选场景门禁**：新增 `adapter = "eval"`（无探测标志，不会被 `adone init` 选中）。
  解析 `PASS` / `FAIL` / `SKIP` 行；契约可绑 `scenario`；仅当存在 eval 步骤时
  integrity 才把 `adone/eval` 场景算进基线。Java / Go / Python / Node 默认路径不变。
- **演示**：`demo/cs-agent-eval`（内存客服召回 / 合并 / HITL，无 LangGraph 依赖）。

## v1.3.11 — 2026-08-28

- **三系统适配**：init / install / gate / audit / upgrade / 钩子按本机环境分支。
  - **macOS / Linux**：`install --hooks-only` 不再写出 `.cmd` / `.exe`（那是 Windows
    启动器）；Cursor 跑 `hooks.json` 里的 `python3 -m actuallydone hook …`。
    重渲时清掉以前误装的 `.cmd`。
  - **Windows**：门禁 / 抽查 / 探针跑 `mvn.cmd` / `npm.cmd` 时经 `cmd /c` 启动，
    不再把批处理直接交给 CreateProcess。
  - **解释器自愈**：Windows 会去 `%LOCALAPPDATA%\Programs\Python` 和 `py.exe` 找
    3.11+；升级识别 `adone.exe`。
  - **审计开报告**：没有 `xdg-open` 的 Linux 退回系统浏览器；技能扫描在
    Windows 上不再要求 chmod。

## v1.3.10 — 2026-08-28

- **Java 演示**：`demo/pet-store-java` 门禁按本机核数并行跑 JUnit 5（`dynamic` × factor=2），
  开关锁在 `argv` / 判据基线里。控制器用例改成可并行（`@WebMvcTest`，不写死 id / 空列表）。

## v1.3.9 — 2026-08-28

- **Java 演示项目**：`demo/pet-store-java`（Spring Boot + Maven 内存宠物店），
  已接入钩子并跑通一次 `gate run`。
- **Linux**：`--open` 用 `xdg-open`（macOS 仍用 `open`，Windows 改 `os.startfile`）。
  钩子换解释器时会去 `~/.local/bin`、`~/.pyenv/shims`、`/usr/bin` 找 3.11+。
- README 按「内涵 → 架构 → 安装 → 上手 → 门禁 → 基线 → 审计 → 健康报告 → Q&A」重排。

## v1.3.8 — 2026-08-28

1.3.7 之后手跑 `gate-guard.cmd` 有 `hook.log`，Cursor 自动触发仍然没有。

### 修

- **`CreateProcess` 不能直接跑 `.cmd`**：终端里手跑会经 cmd.exe / PowerShell 转发，
  所以脚本是好的；Cursor 把 `hooks.json` 的 command 当可执行文件名去启动，
  批处理起不来，`.adone` 里就没有 `hook.log`。Windows 改为登记
  `.cursor/hooks/gate-guard.exe`，安装时复制本机 `adone.exe` 或专用入口
  `adone-hook-*.exe`。cli 按 `argv[0]` 文件名分发到 `hook mark-dirty` /
  `hook gate-guard`。`.cmd` 仍写出，只给手跑对照。
- **`adone doctor`** 看见还登记着 `.cmd` 就点名：手跑可以、Cursor 调不起来。

升上来必须 `adone upgrade` 再 `adone install --hooks-only --force`。
重渲后 `hooks.json` 的 command 必须是 `.exe`，不能再是 `.cmd`。
`.exe` 是本机生成物，不要提交。

## v1.3.7 — 2026-08-27

### 修

- **Windows 上日志写了「已回推」，Agent 窗口却没有**：`adone hook` 的 JSON
  改为按 UTF-8 立刻刷出，有 `followup_message` 时再多停 200ms。Cursor 在
  Windows 上经过 PowerShell 收 stdout，进程一退出就把管道当收完，Execution
  Log 里变成 `{}`，对话不会出现回推——这是官方承认的 bug，不是脚本没输出。
  升 `adone` 即可，不必重渲钩子。
- **Cursor 在 Windows 上可能用 Git Bash 起钩子**：纯 `.cmd` 被当成 shell 脚本，
  第一行 `@echo off` 就失败。启动器改成 cmd/bash 双语。文件必须按字节写 LF
  （`Path.write_text` 在 Windows 上会变成 CRLF，heredoc 合不上）。
- **`sessionStart` 探针**：打开一轮 Agent 对话就会写 `hook.log`。

## v1.3.6 — 2026-08-27

1.3.5 之后不弹 `.py` 了，但 `.adone` 里没有 `hook.log`，钩子仍然不生效。

### 修

- **`cmd /c .cursor\hooks\gate-guard.cmd` 根本起不来**：Cursor 把整串当成一个
  可执行文件名交给 `CreateProcess`，找不到这个文件，默认放行。所以不弹编辑器，
  也不写 `hook.log`。hooks.json 改回官方那种**单独一条相对路径**：
  `.cursor/hooks/gate-guard.cmd`。`.cmd` 是 Windows 认的可执行文件。
- **`.cmd` 一启动就写 `hook.log`**：不再等 Python 起来才留痕。没有这行，
  就是 Cursor 没拉起进程。
- **`.cmd` 用 CRLF 写出**：从 Mac 写出的 LF 批处理，有的 Windows 会当空文件跳过。
- **不再先跑 `where`**：`where` 可能吃掉 Cursor 喂给钩子的 stdin，后面的
  `adone hook` 拿到空 payload。
- **`adone doctor`** 认「`cmd /c …cmd`」这种登记，点名要重渲。

升上来必须 `adone install --hooks-only --force`。重渲后 `hooks.json` 里不能再有
`cmd /c`。

## v1.3.5 — 2026-08-27

Windows 上升到 1.3.4 之后，**还是弹出 `gate-guard.py`**。

### 修

- **`.cursor/hooks/` 里不能留 `.py`**：v1.3.4 登记了 `.cmd`，但启动器仍去跑旁边的
  `gate-guard.py`，而且那个文件还在钩子目录里。Windows 按文件关联打开 `.py`
  （Cursor 自己就是默认应用），于是每次弹出文件，钩子仍没执行。
  官方论坛的修法是 `command` 以 `cmd` 开头，且**整条命令里不能出现 `.py` 路径**。
- **钩子逻辑改走 `adone hook`**：`mark-dirty` / `gate-guard` 进了包本身。
  Windows 的 `hooks.json` 登记 `cmd /c .cursor\hooks\gate-guard.cmd`，
  `.cmd` 只调用 `adone hook gate-guard`（或 `py -3 -m actuallydone hook …`），
  不再点任何 `.py` 文件。安装时会**删掉**残留的 `gate-guard.py` / `mark-dirty.py`。
- **`adone doctor`**：钩子目录里还留着 `.py` 就点名「会被编辑器打开」。

升上来必须 `adone install --hooks-only --force`。然后确认：
`.cursor\hooks\` 里没有 `.py`，`hooks.json` 的 `command` 里也没有 `.py`。

## v1.3.4 — 2026-08-27

Windows 上钩子「已安装」但每次弹出 `gate-guard.py`、改完代码不重跑门禁。

### 修

- **登记 `.py` 等于打开文件**：Cursor 把 `hooks.json` 的 `command` 交给操作系统
  去启动。`.py` 的默认关联是编辑器（常常就是 Cursor 自己），于是 stop 钩子一触发
  就弹出 `gate-guard.py`，脚本一行都没跑——回执过期检查从未发生，Agent 改完
  代码没人提醒。v1.3.3 的 `cmd /c py -3 …py` 命令里仍有 `.py`，一样会被打开。
  现在 Windows 上登记的是 `.cursor/hooks/gate-guard.cmd` / `mark-dirty.cmd`：
  `.cmd` 才是 Windows 认的可执行文件，启动器找到解释器再跑旁边的 `.py`。
- **`adone doctor` 认这件事**：hooks.json 里还登记着 `.py` 时，点名「会打开文件
  而不是执行」，而不是报「钩子：已装」。
- **stdin 带 BOM**：Windows 上 Cursor 喂给钩子的 JSON 有时带 UTF-8 BOM，
  不剥掉就解析失败，改动记不下来。两个钩子都剥。

从 v1.3.3 升上来也必须 `adone install --hooks-only --force`。重渲后
`hooks.json` 的 `command` 里不能再出现 `.py`。

## v1.3.3 — 2026-08-27

Java 团队在 Windows 上反馈的两件事。它们是同一类病，和 v1.3.2 修的 `mvn` 一样：
**体检用的判断和操作系统实际执行的判断不一致**，于是「检查失效」长得像「检查通过」。

### 修

- **Windows 上钩子静默不触发，Agent 改完代码没人提醒**：`afterFileEdit` 挂的是
  `mark-dirty.sh`（bash + jq），`stop` 挂的是靠 shebang 加可执行位启动的
  `gate-guard.py`——这三样在 Windows 上都不成立，Cursor 起不动，钩子什么都不做。
  而 `doctor` 查的是 `os.access(X_OK)`，那在 Windows 上对任何存在的文件恒为真，
  所以体检还报「钩子：已装」。现在：
  - `mark-dirty` 从 bash 移植成 Python（`mark-dirty.py`），去掉 bash 与 jq 依赖，
    顺带认 Windows 给的反斜杠 `file_path`；旧的 `.sh` 会被摘掉登记并删除。
  - `hooks.json` 里注册**显式解释器调用**（Windows 上是 `cmd /c py -3 …`），
    不再依赖 shebang 与可执行位。这也是官方文档 Python 示例的写法。
  - `doctor` 改为真的去解析登记命令里的解释器，起不来就报出来；
    还登记着旧版 `.sh` 时点名要求重渲。
  - `gate-guard` 在 Windows 上能找到 `adone.exe` / `adone.cmd`，
    并会翻 `Scripts` 这类 Windows 专有的脚本目录。
- **`mvn test jacoco:report` 成功了却读不到覆盖率**：pom 只声明了插件、没把
  `prepare-agent` 绑进生命周期时，`mvn test` 不挂探针，`jacoco:report` 打一行
  `Skipping JaCoCo execution due to missing execution data file` 就 BUILD SUCCESS，
  一份报告都不写。现在 `adone init` 生成的步骤是
  `mvn -B -ntp jacoco:prepare-agent test jacoco:report`（CLI 显式跑，不依赖 pom 绑定）；
  读不到覆盖率时会指出断在哪一环——探针没挂上 / 只有 `.exec` 没有 xml /
  一份报告都没找到 / 报告里行计数为空——而不是只说「没解析到覆盖率数字」。
- **多模块覆盖率报的是第一个模块**：以前返回「第一份能解析出数字的报告」，
  在 aics-api + aics-gateway 这种仓库里既不是整体水位，还会随模块改名而跳变。
  改成把各模块的行数加起来；有 `jacoco-aggregate` 聚合报告时只认聚合报告，
  免得重复计数。

### 文档

- README 新增「Windows」与「Java 的覆盖率读不到」两节。
- 限制声明写清：Windows 的支持是「按 Windows 语义实现并有针对性用例」，
  不是「在 Windows CI 上跑过」——仓库里没有 Windows runner。

## v1.3.2 — 2026-08-27

### 修

- **Windows 上 `mvn` / `npm` 一律「命令不存在」**：这两个在 Windows 上是 `.cmd`
  批处理，而 `CreateProcess` 不查 `PATHEXT`，`subprocess` 直接抛 `FileNotFoundError`；
  偏偏 `doctor` 用的 `shutil.which` 认 `PATHEXT`，于是「体检说命令在、门禁说命令不存在」。
  现在门禁、抽查、探针、doctor 全部走同一个 `resolve_cmd`：先解析成带后缀的全路径再执行。
  `./mvnw` 在 Windows 上会自动对上 `mvnw.cmd`，同一份 `adone.toml` 两边都跑得动。
- **`命令不存在: None`**：`WinError 2` 的 `e.filename` 是 `None`，报错等于什么都没说。
  现在报出命令名，并分清「PATH 里没有」与「步骤目录不存在」两种情况。
- **真实原因被「解析不出测试结果」盖掉**：命令没启动起来时，`kind = "test"` 的判定
  会把 note 覆写成「适配器不认这种输出格式」，把人引到适配器上去查。现在启动失败的
  步骤保留原因，不再冒充解析失败。
- **依赖与构建产物不再进受监视树**：`node_modules`、`target`、`build`、`dist` 等
  会被裁掉。以前 `watch_roots = ["."]` 能扫出四万多个文件，回执在每次
  `npm install` / `mvn package` 后就过期，而「回执已过期」本该指向人改了源码。
  互相嵌套的 `watch_roots`（`"."` 加上几个子模块）也不再把同一个文件算两遍。
  **注意**：这会让树哈希变一次，已有回执需要重跑一次 `adone gate run`。
- **Windows 中文 locale 下解码炸掉**：`mvn` 的输出常常不是 `cp936`，
  解码异常会把「测试失败」误报成「命令跑不起来」。改为 `errors="replace"`。

## v1.3.1 — 2026-08-27

### 修

- **`adone upgrade` 改错对象**：从仓库里的 `bin/adone` 跑时按源码位置判断是 git，
  去 checkout 这份源码，PATH 上的 pipx 还是 1.2.0。现在优先覆盖 `which adone`
  指向的那一份，并用它的 `--version` 跟远端比，升完再核一次 PATH。
- **版本发现取最新**：Release / tag / 默认分支都看，装版本号最高的。
  以前没有 Release 就停在旧 tag，main 上的补丁装不到。
- **Java 覆盖率认不到报告**：不再只认 `target/site/jacoco/jacoco.xml`，
  会扫 `jacoco.xml` / `jacoco.csv` / jacoco 目录下的 `index.html`。
  `coverage.source` 对不上步骤名时，改从任意测试步骤或磁盘报告回退，
  不再因为「没解析到数字」让覆盖率门禁形同虚设。

## v1.3.0 — 2026-08-27

### Java / JVM 适配器

接入的 Java 团队配了 `kind = "test"` 的 `mvn test`，适配器却退回无能力基类，
解析不出 Surefire 输出，门禁把「全部通过」判成「解析不出」。这一版补上。

- **内置 `java` 适配器**：认 `pom.xml` / `build.gradle[.kts]`，Maven 与 Gradle
  （`./mvnw` / `./gradlew` 优先），JUnit 4/5 与 TestNG。用例名规范形式是
  `CalcTest#testAdd`，带 `@DisplayName` 时两种写法都能对上契约与抽查。
- **JUnit XML + 新鲜度**：控制台只有汇总数，逐条名字从 surefire / failsafe /
  Gradle `test-results` 的 XML 读。用步骤开始时间丢掉上一轮残留报告；
  XML 合计与控制台对不上时只给计数、不给名字——抽查标未评估，不标通过。
- **JaCoCo、Spring 路由、JPA 表名**：覆盖率从 `jacoco.xml` 读；
  `@GetMapping` 等与类级 `@RequestMapping` 前缀拼接；抽取器新增 `jpa_tables`。
- **`adone detect --merge`**：给已经配好的项目增量追加步骤和 `watch_*`，
  不冲掉 `coverage.threshold`。`--write` 仍是整份覆盖。改 `tests.adapter`
  必须显式 `--adopt-tests`，否则假绿基线与判据锁会对不上。
- **`adone upgrade`**：从 GitHub 拉最新版，识别 pipx / pip / git 三种装法并覆盖。
  没有 Release 时回退到 tag、再回退到默认分支。远端更旧拒绝降级。
  在本仓库的脏工作树上跑会被拦住。

### 修

- `coverage.source` 指向 `kind=test` 的步骤，不再误取第一步（Java 第一步可能是 spotless）。
- `adone doctor` 按步骤 cwd 解析 `./mvnw` / `./gradlew`，不再谎报「不在 PATH 里」。
- 适配器协议新增 `parse_test_run(text, *, cwd, since)`，Go / Node / Python 行为不变。

## v1.2.0 — 2026-08-14

### 审计结论也能出一页离线 HTML

`adone health` 一直能出 HTML，`adone audit` 却只落 JSON——复核结论要给人看、
要丢进聊天窗口时，还得自己转一道。这一版补上。

- **`adone audit` 每次都会写出 `.adone/audit.html`**，与 `audit.json` 同一份结论、
  同一套口吻：通过说「独立复核通过」，不通过说「实现者不能宣称完成」，
  核到哪一层就写哪一层。单文件、零外链，双击就能看。`--out` 改路径，`--open` 生成后打开。
- **`adone audit report`**：只把已有 `audit.json` 渲成 HTML，**不重跑检查**。
  还没有结论时拒绝（退出码 2），结论未通过时退出码 1。复核者不该为了出一份报告
  再抽一次、再改一次审计 ID。
- 报告底部写明本机复核不是不可伪造——不要把「独立复核通过」写成「不可能造假」。

## v1.1.0 — 2026-08-13

### 对抗检查：把复核交给另一个模型

判据一直都在磁盘上而不在会话里，所以第二个模型本来就有能力独立得出结论——
缺的只是一条命令、一个身份、一份不覆盖被审证据的结论文件。这一版补的就是这三样。

- **`adone audit`**：独立复核。与 `gate check` 共用同一套判定（口径分家等于给
  「换个命令再问一次」留后门），但**默认开抽查**（`--spotcheck` 默认 2）、
  结论写进 `.adone/audit.json` 与 `.adone/audits/*`，**不碰** `latest.json` 与证据链——
  复核者顺手覆盖被审的回执，等于把证据抹掉。口吻也是复核者的：通过时说「独立复核通过」，
  不通过时说「实现者不能宣称完成」，不替实现者宣布完成。
- **`adone audit --rerun`**：不信任那份回执时，复核者自己把门禁全量跑一遍再逐项比对——
  树哈希对不上、回执写着全绿而重跑没过、回执列着的用例名在重跑里根本没出现，都会被点名。
  重跑产物同样只落 `audits/`。
- **`adone brief`**：复核者的冷启动简报。不看聊天记录也能上手：判据在哪、现有几份契约、
  实现者留的是哪份回执、要跑哪几条命令、以及复核者不许碰的东西
  （`policy --accept`、`integrity --accept-baseline`、改配置改代码）。
- **`independent-check` 技能**（随包发布，`adone install` 渲染进 `.cursor/skills/`）：
  复核者的三条铁律（不看自述看证据、只报告不修复、不替它记账）、结论怎么读、报告怎么写。
  `verified-delivery` 相应从五段扩成六段，末段是换会话换模型的独立复核；
  `completion-gate` 加了一节「交付时把结论交给别人验」。
- **复核强度如实标注**：结论末行区分「只读证据核对 / 抽 N 条当场真跑 / 全量重跑核对」——
  三档强度写成同一句话，等于把最弱的一档冒充最强的。
- 重构：`gate.run_gate` 抽出 `execute_steps`、`check_gate` 抽出 `collect_check`，
  两条命令共用同一份判定与执行逻辑。
- README 新增「对抗检查：换一个模型来核」完整用法，并说明边界——工具不验证复核者身份，
  「换个模型、不给它实现过程」得由流程保证。

### 修

- **`.gitignore` 里的三份基线其实一直没入库**：写成 `.adone/` 会让 git 连目录都不下去看，
  后面的 `!.adone/xxx.json` 一条都不生效，而且不报错——README 让人把基线入库，
  仓库自带的忽略规则却在悄悄拦住。改成 `.adone/*` 并逐条放行三份基线，README 附上正确写法。

## v1.0.0 — 2026-08-12

第一个正式版本。此前的形态是某个项目里的一组脚本，从这一版起它是一个独立、可安装、
可被别的项目直接用起来的工具，接口（`adone.toml` 字段、回执格式、命令行）从此按语义化版本管理。

### 证据强度加固

把几条原本「无声就能走通」的绕过路径，变成「要么留下一条署名记账，要么留下明显痕迹」。

- **判据锁**（新增 `adone policy`）：把「门禁有多严」拍成快照存进 `.adone/policy-baseline.json`——
  受监视范围、每个步骤的命令与失效标记、覆盖率下限、假绿豁免名单、各类检查项条数、
  以及契约面。与假绿检测同一套路：只报放松，收紧只提示，合理的放松用
  `adone policy --accept "理由"` 署名记账。步骤命令指向仓库内脚本时，脚本内容的 sha256
  一并入快照——否则「把 `go test` 换成一个打印完美输出的脚本」这条路仍然无声。
- **回执自哈希与链**：回执新增 `seq` / `prev` / `self_hash`，链头写进 `.adone/chain.json`。
  手写一份全绿回执从此要重算自哈希、改链头、让 `prev` 追得到。升级前产生的老回执
  优雅降级为链起点，不会让已装项目一升级就全红。
- **证据强度标注**：回执新增 `evidence` 段，`gate check` 的结论与健康度报告头部都会写明
  「自述（本地跑）· 判据已锁 · 回执链完整」。字段结构为后续 CI 签名留好了位置。
- **抽查真跑**（`adone gate check --spotcheck [N]`，默认关闭）：从契约绑定的用例里随机抽 N 条
  当场再跑一遍。退出码 0 但一条用例都没跑起来同样判为问题——那不叫通过，那叫没跑。
  适配器新增 `single_test_argv` 能力，go 与 python 支持，其余显示未评估而不是静默通过。
- README 新增「威胁模型与证据强度」：按无意漂移 / 敷衍作弊 / 蓄意对抗三档对手，
  逐条说明挡得住什么、挡不住什么，以及要跨过最后一档必须走 CI 的路线。

### 此前已有的能力（首个正式版一并记录）

- 完成门禁：`adone gate run` 产出与受监视代码树内容哈希绑死的回执，`adone gate check` 秒级复核。
- 假绿检测：`adone integrity` 抓删用例、加跳过、删断言、调低下限等六种「把门禁改绿」的手法。
- 验收契约与需求台账：把每条需求钉到一个用例名上，由脚本核；跨迭代的证据锚点失联即报。
- 健康度报告：六个维度汇成一页离线 HTML，只按真跑过的维度计分，跑不了的检查一律标未评估。
- 适配器：go / node / python / generic，缺能力就标未评估，绝不返回空结果冒充「查过了」。
- `adone init` / `detect` / `doctor` 零配置上手，`adone install` 把技能与 Cursor 钩子渲染进项目。
