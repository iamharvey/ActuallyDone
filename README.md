# ActuallyDone - adone

当前版本 **v1.4.2**，变更记录见 [CHANGELOG.md](CHANGELOG.md)。
零第三方依赖，Python 3.11+（用到标准库 `tomllib`）。

<br/><br/>

## 1. 工具在解决什么

AI Agent 说「已完成，测试全部通过」的时候，你没有办法当场判断这句话是真是假。
它可能贴的是上一轮日志，可能转述而没真跑，可能跑完门禁之后又改了代码，
也可能为了让门禁变绿而把用例删了、把断言去了、把覆盖率下限调低了。

ActuallyDone 提供一条命令 `adone`，让「完成」变成**别人可以独立复核的证据**，
而不是会话里的一句自述。

构建思路就三句：

1. **完成 = 与代码内容绑死的回执。** `adone gate run` 真跑检查，把树哈希、每步退出码、
   通过用例名写进 `.adone/latest.json`。改一个被监视的文件，哈希就变，回执过期。
2. **判据自己也要留档。** 缩小监视范围、换测试命令、调低下限、删契约，都能让门禁变绿。
   `integrity` / `policy` 把这些拍成基线，只报放松，放宽必须署名记账。
3. **自己检查自己是最弱的一档。** 判据全在磁盘上，不在会话里。换一个模型、开一个新会话，
   跑 `adone audit`，复核者不看实现过程，结论也不覆盖被审的回执。

诚实的边界：这套机制提高伪造成本，不是密码学级不可伪造。能写工作区的人可以重算整条链。
真正不可伪造需要 CI 这种 Agent 无权写入的执行者。

<br/><br/>

## 2. 设计架构

会话层触发钩子，工具层写出证据，人写的判据与磁盘上的产物分开；适配器只负责「这个生态怎么跑、怎么读结果」。

![ActuallyDone 架构：会话层、工具层、人写的判据、磁盘证据与生态适配器](docs/architecture.png)

四层各自干什么：

| 层 | 职责 |
| --- | --- |
| 会话层 | Cursor / Qoder 钩子：改文件记 dirty；stop 有 dirty 时跑相关用例；`git commit` 时全量门禁 |
| 工具层 | `gate run --changed` 开发中增量；`gate run` 全量写回执；`gate check` 一秒复核；`integrity` / `policy` 锁基线；`audit` 独立复核；`health` 出健康页 |
| 人写的判据 | `adone.toml`、验收契约、需求台账。入库。 |
| 磁盘上的证据 | 回执、回执链、两份基线、审计结论、健康报告。基线与链头建议入库，回执本身不必。 |

实现者写回执；复核者只写 `.adone/audit.json` / `audit.html`，**不覆盖** `latest.json` 和证据链。

<br/><br/>

## 3. 安装

需要 Python 3.11+，零第三方依赖。推荐 pipx：它给 `adone` 单独建一个 venv，
自己挑一个够新的解释器，不碰你项目的环境。

### 装：一条命令，三个平台一样

```bash
pipx install git+https://github.com/iamharvey/ActuallyDone.git
adone --version
```

**地址后面不要加 `@v1.3.18` 这样的 tag。** pipx 会把你给的这串地址原样记下来当作以后的升级源，
钉了 tag 就是钉死在那一版：之后 `pipx upgrade` 只会回你「已是最新」，新版本永远进不来。
不带 tag 装，取的就是最新代码。

没有 pipx 先装一个（Windows 把 `python3` 换成 `py -3`）：

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

### 让 `adone` 敲得出来

pipx 把命令放在 `~/.local/bin`，Windows 上是 `%USERPROFILE%\.local\bin`。
这个目录常常不在 PATH 里——命令敲不出来，钩子也一样找不到它。

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # bash 改 ~/.bashrc
source ~/.zshrc
```

Windows 用 `pipx ensurepath`，然后重开终端。

`adone --version` 能打印版本号，再往下走。

交互式终端里敲 `adone doctor` / `gate` / `install` 这类命令时，如果 GitHub 上有新版本，
会先问一句要不要升。回车或 `n` 继续手头的事；`y` 走和 `adone upgrade` 同一条路径。
钩子、`--json`、管道、CI 里不问。不想被问设 `ADONE_NO_UPDATE_CHECK=1`。

### 升级：用 `adone upgrade`，不要用 `pipx upgrade`

```bash
adone upgrade --check                 # 只查有没有新版，不动安装
adone upgrade
adone install --hooks-only --force    # 每个装了钩子的项目各跑一次
```

`adone upgrade` 不看 pipx 记的那串地址，自己去 GitHub 把 Release、tag、默认分支的版本号
比一遍取最新的，认出你是 pipx / pip / git 工作树再覆盖过去。所以当初装的时候带没带 tag，
它都升得上去。它覆盖的是 PATH 上那份 `adone`，不是你当前所在的源码目录——
否则会出现「看起来升了，敲 `adone` 还是旧版」。

最后那条 `--hooks-only --force` 不能省：钩子里烧着安装时的绝对路径，换版本或换位置就会失效，
而失效的样子和「门禁通过」在终端里一模一样。Qoder 项目若 auto 没认出来，改成
`--ide qoder` 或 `--ide all`。写到哪、怎么确认，见第 4 节「按 IDE 接入」。

### 另外两种装法

```bash
# pip：装进当前解释器，和项目依赖共享环境
pip install git+https://github.com/iamharvey/ActuallyDone.git

# vendor：把本仓库拷进项目的 tools/，免安装
python3 tools/ActuallyDone/bin/adone --version
```

pip 那条若报 `requires a different Python: 3.10.x not in '>=3.11'`，是你敲的这个 `pip`
属于某个 3.10 环境（conda 里很常见），不是机器上没有新 Python。
换 `python3.12 -m pip install …`，或者回到上面的 pipx——pipx 会自己挑够新的解释器。

<br/><br/>

## 4. Quick start

在项目根目录（放 `go.mod` / `pom.xml` / `CMakeLists.txt` / `adone.toml` 的那一层）执行。

```bash
cd 你的项目
adone init                         # 探测生态，生成 adone.toml（不猜覆盖率阈值）
adone doctor                       # 核路径、命令、钩子
adone gate run                     # 全量门禁，按实测回填 coverage.threshold
adone integrity --accept-baseline "建立初始基线"
adone policy                       # 确认判据基线（首次 gate run 会自动建）
adone install --with-hooks         # 技能 + 钩子 + 本机 .git/hooks/pre-commit
adone health --open                # 出一页健康度报告并打开
```

`install --with-hooks` 默认 `--ide auto`：看不出 Qoder 就只装 Cursor。
Qoder 用户、或一个仓库两种 IDE 都开，见下面「按 IDE 接入」。

要拆掉（和 `init` 配套，拆完门禁和钩子都不再跑）：

```bash
adone clean                        # 先列出要删的，默认不拆
adone clean --yes                  # 不交互
```

别人写在 `.cursor/hooks.json` / `.qoder/settings.json` 里的钩子、以及不是 adone 渲染的技能，不会动。

`adone init` 探测出来的项都标着「请确认」。覆盖率下限留空，等你跑完门禁拿实测值回填。

源码编码也在探测之列，写在 `project.source_encoding`：

```toml
[project]
source_encoding = "gbk"    # utf-8 / gbk / auto，请确认：探测所得
```

UTF-8 永远先试，这一项决定解不动时退到哪（`auto` 再加本机编码），逐个文件判断，
所以迁移期两种编码混着放也没问题。它只影响读文本的检查；
回执的树哈希按字节算，与编码无关。

GBK 项目上这不是可有可无的：GBK 的尾字节范围含 ASCII，`亄` 是 `81 7B`，
硬按 UTF-8 读会凭空多出一个 `{`，大括号一乱，扫测试方法就会切错函数体——
结果是「相关用例」少认几条，而这和「这文件本来就没测试」长得一模一样。

### 装完之后长这样

```
你的项目/
  adone.toml                 # 配置，人写，入库
  adone/acceptance/*.toml    # 验收契约，入库
  adone/requirements/*.toml  # 需求台账，入库
  .adone/                    # 机器写的状态
    latest.json  receipts/   # 全量回执（完成证据只认 latest.json）
    partial.json             # --changed 的调试产物，不是完成证据
    dirty                    # 钩子记下的受监视改动
    chain.json               # 回执链头（建议入库）
    test-baseline.json       # 假绿基线（建议入库）
    policy-baseline.json     # 判据基线（建议入库）
    audit.json  audit.html   # 独立复核结论
    report.html              # 健康度报告
  .cursor/skills/            # Cursor：adone install 渲染
  .cursor/hooks.json         # Cursor 钩子（按本机生成，不要入库）
  .qoder/skills/             # Qoder：同一套技能，装 Qoder 时才有
  .qoder/settings.json       # Qoder 钩子（按本机生成，不要入库）
  .git/hooks/pre-commit      # 两边共用，本机生成，不入库
```

`.gitignore` 建议这样写（**不要写 `.adone/`**，否则后面的 `!` 全部失效且不报错）：

```gitignore
.adone/*
!.adone/test-baseline.json
!.adone/policy-baseline.json
!.adone/chain.json
```

### 按 IDE 接入

`adone init` / `gate` / `doctor` 两边一样。不一样的是钩子写到哪、Agent 用哪套事件拦。
本机 `.git/hooks/pre-commit` 共用：你在终端敲的 `git commit` 两边都靠它。

`--ide`：`auto`（默认）看不出 Qoder 就只装 Cursor；`cursor` / `qoder` 只动一边；`all` 两份都写。
钩子登记是本机生成物（里面是这台机器的路径），**不要入库**。

#### Cursor

```bash
adone install --with-hooks              # 默认就是这条
adone install --with-hooks --ide cursor # 显式，不看环境里有没有 Qoder
adone install --hooks-only --force      # 升完 adone 后重渲
```

会写 `.cursor/skills/`、`.cursor/hooks.json`，Windows 上还有 `.cursor/hooks/*.exe`（不要提交）。

日常：存盘即可。Agent 回合结束（`stop`）时若改了受监视文件，钩子跑相关用例。
Agent 跑 `git commit` 会先被 `beforeShellExecution` 拦住，过了再走 pre-commit；
`--no-verify` 也绕不过 Cursor 那条。

装完看 `adone doctor` 有「钩子：已装」。新开一轮对话，改一个受监视文件后
`.adone/hook.log` 里应出现 `mark-dirty launched`。
Windows 上确认 `hooks.json` 的 command 是 `.exe`，不是 `.cmd` / `.py`。

macOS / Linux 登记 `python3 -m actuallydone hook …`；Windows 登记 `.cursor/hooks/<名>.exe`。

#### Qoder

Qoder 不读 `.cursor/hooks.json`。要写 `.qoder/settings.json`。

```bash
# 在 Qoder 自己的终端里（有 QODER_PROJECT_DIR），auto 会走到 Qoder
adone install --with-hooks

# 普通终端、或 auto 没认出来时，显式指定（不碰 .cursor/）
adone install --with-hooks --ide qoder
adone install --hooks-only --force --ide qoder
```

会写 `.qoder/skills/`、`.qoder/settings.json`（exec 形式：`command` + `args`，绝对路径）。
改完配置**重启 Qoder**（官方尚未热重载）。相对路径解不开时 `PreToolUse` 会把每条
shell 命令都拦下，所以这份 settings **不要入库、不要抄别人的**。

日常和 Cursor 一样：改文件 → 回合结束跑相关用例 → 提交先过全量门禁。
Qoder 上 Agent 提交走 `PreToolUse`（Bash / Shell），不是 commit 的命令会立刻放行。

装完看 `adone doctor` 有「Qoder 钩子：已装」。改一个受监视文件后 `hook.log` 应有
`记下 …`；让 Agent 提交一次，应当被拦**并且看到理由**。

#### 一个仓库两种 IDE 都开

```bash
adone install --with-hooks --ide all
adone install --hooks-only --force --ide all
```

两边各写各的目录，pre-commit 仍是一份。

#### 事件对照

| 做什么 | Cursor | Qoder |
| --- | --- | --- |
| 记 dirty | `afterFileEdit` / `afterTabFileEdit` / `postToolUse` | `PostToolUse`（Write / Edit / search_replace / create_file） |
| 回合结束跑相关用例 | `stop` → stdout `followup_message` | `Stop` → exit 2 + stderr（`stop_hook_active` 为真立刻放行） |
| Agent 跑 `git commit` | `beforeShellExecution` matcher `git commit` | `PreToolUse` matcher `Bash` / `Shell`，从 `tool_input.command` 判断 |
| 人在终端 `git commit` | `.git/hooks/pre-commit` | 同一份 |

`stop` / `Stop` 的「说完了」不是「做完了」。完成只认全量回执。

多模块工作区里 `adone.toml` 常在子目录，pre-commit 仍写进上层仓库的 `.git/hooks/`
（配了 `core.hooksPath` 就写到那边），脚本会 `cd` 回 `adone.toml` 那一层。
装完看一眼 `adone install` 打印的路径。

<br/><br/>

## 5. 如何在开发中跑相关用例、提交时才全量

`adone.toml` 里的 `[[gate.step]]` **不用改**：全量命令仍是 `mvn test` / `go test ./...`。
开发中不走那条 argv（判据锁会把「换命令」判成放松）。相关用例由适配器另组一条临时命令。

### 两条命令

| 时机 | 命令 | 写 `latest.json`？ |
| --- | --- | --- |
| 改了受监视文件之后（人或 Agent 手跑；`stop` 钩子也会跑） | `adone gate run --changed` | 否，只写 `.adone/partial.json` |
| 宣称完成、交付、`git commit` | `adone gate run` | 是，完成证据只认这份 |
| 多模块 Maven、只想重跑变过的模块 | `adone gate run --affected` | 是，回执写明哪些继承自上一份全量 |
| 随时复核全量回执是否新鲜 | `adone gate check` | 否，约 1 秒 |

```bash
adone gate run --changed   # 只跑与 dirty / git diff 相关的用例
adone gate run             # 全量，写回执
adone gate run --affected  # 只跑变过的模块（要先有一份带单元哈希的全量绿回执）
adone gate check           # 树哈希必须对上 latest.json
adone gate slow            # 最近一轮最慢的用例 / 模块
```

`--changed` 的文件名单：`.adone/dirty` 与 `git status`（含未跟踪）合并。
git 会在项目根和每个 `watch_roots` 各定位一次仓库，所以子目录自带 `.git`
（`aics-bank/aics-api` 这种）也扫得到。路径一律收成相对 `adone.toml` 所在目录：
项目嵌在父仓库里时剥掉 `demo/pet-store-java/` 前缀，否则对不上 `watch_roots`。

名单为空时会说明原因（PATH 里没有 git / 不在仓库里 / 改动都在项目目录外），
不会让「钩子失效」看起来像「代码没改过」。

### 钩子怎么触发（装上才会有）

安装命令和事件名按 IDE 不同，见上一节「按 IDE 接入」。两边跑的是同一套
`adone hook`：`mark-dirty` 记 dirty，`gate-guard` 跑相关用例，`commit-guard` 拦提交。

`mark-dirty` 认 `file_path` / `filePath` / `tool_input.path` 等；stdin 按字节读
（中文 Windows 的 cp936 会把 UTF-8 正文解坏），解不动就从原文正则抽路径。
`gate-guard` 把 dirty 与 `git status` 合并；没有受监视改动不回推；有改动跑 `--changed`，
上一轮已通过且文件哈希没变则跳过。

Cursor 的 `sessionStart` 上也挂了 `mark-dirty`，但没有 `file_path`，不会误写 dirty。

### 相关用例怎么找

第一期是文件名启发式，不做调用图。适配器实现 `related_tests`：

- 改的是测试文件：跑该文件里的用例。
- 改的是实现：同 stem + `Test` / `_test` / `test_`。  
  `PetStore.java` → `PetStoreTest`；`foo.go` → `foo_test.go` 里的 `Test*`；  
  `lib.py` → `test_lib.py` / `lib_test.py`；`store.cpp` → 测到该 stem 的 `Suite.Case`。
- 拼命令：Java `-Dtest=ATest,BTest`，Go `-run`，Python `-k`，C++ `ctest -R`。
- 映射为空：回推「找不到与这些文件相关的用例，写一条再继续」，**不退回全量**。
- 适配器不会找（返回未评估）：同样不空跑冒充绿。

通过后清掉 dirty，避免下一轮问答再跑一遍。找不到或跑失败则留下 dirty，下一轮 `stop` 还会拦。

不需要在 `adone.toml` 里另配增量步骤。也不要在 `afterFileEdit` 里跑测试（每存一次文件就起 JVM）。

### 人怎么用

日常改代码：存盘即可。Agent 回合结束时若改了受监视文件，钩子会跑相关用例。
自己想先看结果：

```bash
adone gate run --changed
```

准备提交或宣称完成：

```bash
adone gate run
adone gate check
git commit
```

人在终端 `git commit` 会撞上 pre-commit；Agent 跑 `git commit` 会先撞上
`commit-guard`（Cursor 的 `beforeShellExecution`，Qoder 的 `PreToolUse`），
过了再走 pre-commit。两条都装，`--no-verify` 也绕不过 Agent 那条。

提交路径默认仍是全量。要让 pre-commit 走范围化全量，在 `adone.toml` 里显式写：

```toml
[gate]
commit_scope = "affected"
```

然后 `adone install --hooks-only --force`（钩子脚本会跑 `gate run --for-commit`）。
Gradle 没有 `-amd`，`--affected` 会被拒绝，不会偷偷少跑。

### 全量跑太久怎么查

先分清是卡住还是真慢。门禁步骤现在边跑边打输出；静默超过 60 秒会打一行心跳。
卡死长得像在跑，是以前最常见的误判。

1. **是不是卡住。** 看有没有心跳、有没有「超时被中断」。每步可配 `timeout_seconds` /
   `stall_seconds`（默认不限时，超时不进判据快照）。超时会把 surefire fork 出的 JVM
   一并杀掉，避免孤儿进程占着端口、下一次再冲突。
2. **是不是端口冲突。** 失败步骤的 note 会写「端口 8080 被占」以及 Spring
   测试上下文缓存这个根因。串行也会撞：前一个 `@SpringBootTest` 没关，socket
   还在它手里。改成 `webEnvironment = RANDOM_PORT`。
3. **慢在哪。** `adone gate slow` 读 surefire XML 的 `time`，按用例和按模块出榜。
   多模块 Spring 十有八九是上下文重复启动，不是用例数。
4. **再谈并发或缩范围。** 固定端口下开 surefire 并行，冲突会变成间歇性变红，
   最后一定被团队关掉。先隔离端口，或用 `--affected` 少跑。

固定端口暂时改不掉时的退路：surefire `${surefire.forkNumber}` 给每个 fork 一段端口；
JUnit 5 `@ResourceLock` 只串行化占端口的那批；容器 / `unshare -n` 做网络命名空间隔离。

**固定端口的测试有可能连上本机已在跑的旧版服务然后通过。** 回执绑的是新代码的树哈希，
测试打的是旧进程——那是真的假绿。

<br/><br/>

## 6. 如何初始化门禁

`adone init` 会按仓库里的标志文件生成步骤。也可以手写 `adone.toml`。

### Go

`go.mod` 在仓库根时，`adone init` 会生成类似：

```toml
[project]
name = "my-service"

[gate]
watch_roots = ["."]
watch_exts = [".go"]
min_tree_files = 1

[[gate.step]]
name = "gofmt"
kind = "fmt"
argv = ["gofmt", "-l", "."]

[[gate.step]]
name = "go build"
argv = ["go", "build", "./..."]

[[gate.step]]
name = "go vet"
argv = ["go", "vet", "./..."]

[[gate.step]]
name = "go test"
kind = "test"
adapter = "go"
argv = ["go", "test", "./...", "-count=1", "-v", "-coverprofile={cover_out}"]
```

`kind = "fmt"`：工具常常永远退出 0，有输出即失败。
`kind = "test"`：用适配器解析用例名和覆盖率，只看退出码会漏掉假绿。

代码在子目录（例如 `backend/go.mod`）时，给步骤加 `cwd = "backend"`，
`watch_roots` 写成 `["backend"]`。

### Java（Maven）

`pom.xml` 里如果声明了 JaCoCo，`adone init` 会把测试步骤写成显式 `prepare-agent`。
**不要**只写 `mvn test jacoco:report`：pom 没把探针绑进生命周期时，Maven 仍会 BUILD SUCCESS，
一份覆盖率报告都没有。

```toml
[project]
name = "aics"

[gate]
watch_roots = ["src"]
watch_exts = [".java"]
min_tree_files = 1

[[gate.step]]
name = "mvn test"
cwd = "."
kind = "test"
adapter = "java"
# timeout_seconds = 1800   # 可选。默认不限时；超时会杀掉进程树
argv = ["mvn", "-B", "-ntp", "jacoco:prepare-agent", "test", "jacoco:report"]
```

多模块时把每个模块的 `src` 写进 `watch_roots`。先跑一次全量拿到带单元哈希的回执，
之后 `adone gate run --affected` 只重跑变过的模块。

要按本机核数并行跑 JUnit 5，把开关写进同一步的 `argv`（判据基线锁的是命令，不是 pom）：

```toml
argv = [
  "mvn", "-B", "-ntp",
  "-Djunit.jupiter.execution.parallel.enabled=true",
  "-Djunit.jupiter.execution.parallel.mode.default=concurrent",
  "-Djunit.jupiter.execution.parallel.mode.classes.default=concurrent",
  "-Djunit.jupiter.execution.parallel.config.strategy=dynamic",
  "-Djunit.jupiter.execution.parallel.config.dynamic.factor=2",
  "jacoco:prepare-agent", "test", "jacoco:report",
]
```

`dynamic` 的线程数 = 本机核数 × `factor`（演示里 factor=2）。Spring 用例不要
`@DirtiesContext` 逐条重启上下文，也不要写死 id=1 / 空列表，否则只能串行。
pom 里用 `systemPropertyVariables` 把这些 `-D` 转进测试 JVM；不要用 Surefire
的 `-Dparallel`（只认 JUnit 4），也不要用 `-DargLine` 塞属性（会盖掉
`jacoco:prepare-agent`）。改完 `argv` 后 `adone policy --accept "理由"`。
演示见 `demo/pet-store-java`。

多模块项目的覆盖率按各模块行数相加；有 `jacoco-aggregate` 时只认聚合报告。
配置里写 `mvn` / `./mvnw` 即可，Windows 上会自动对上 `mvn.cmd` / `mvnw.cmd`。

### C++（CMake）

`adone init` 看见 `CMakeLists.txt` 会写出三步：configure、build、ctest。
同一份 `argv` 在 Windows / macOS / Linux 上都能跑：

- `cmake` / `ctest` 在 Windows 上对上 `cmake.exe` / `ctest.exe`
- `-DCMAKE_BUILD_TYPE=Release` 给 Ninja / Makefiles
- `--config Release` 与 `ctest -C Release` 给 Visual Studio 多配置生成器（单配置生成器会忽略）

```toml
[project]
name = "task-store"
ecosystems = ["cpp"]

[gate]
watch_roots = ["include", "src", "tests"]
watch_exts = [".cpp", ".hpp", ".h"]

[[gate.step]]
name = "cmake configure"
argv = ["cmake", "-S", ".", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"]

[[gate.step]]
name = "cmake build"
argv = ["cmake", "--build", "build", "--config", "Release"]

[[gate.step]]
name = "ctest"
kind = "test"
adapter = "cpp"
argv = ["cmake", "-E", "chdir", "build", "ctest", "--output-on-failure", "-V", "-C", "Release"]
```

适配器认 GoogleTest 的 `[ OK ] Suite.Case`、CTest 的 `Test #n: name Passed`，以及 Catch2 的 passed/failed 行。
覆盖率认 `lcov.info`。MSVC 没有 gcov，不要填 `coverage.threshold`，否则门禁会把「未评估」当成失败。
演示见 `demo/task-store-cpp`（C++17，不引 GoogleTest）。

### 场景门禁（可选）

客服 / Agent 图这类项目可以**另外**加一步 `adapter = "eval"`，用场景金标挡召回漏检、
多块乱合并、该打断没打断。这是 opt-in：Java / Go / Python / Node 的 vibe coding
**不用改**。`adone init` 看见 skill 目录或 LangGraph **不会**自动加这一步，也不会
把 `.md` 加进默认 `watch_exts`。

```toml
[[gate.step]]
name = "skill eval"
kind = "test"
adapter = "eval"
argv = ["python3", "scripts/eval_cs_agent.py"]
```

适配器认 stdout 里的 `PASS <id>` / `FAIL <id>` / `SKIP <id>`（id 可以是 `recall#退货时效`）。
契约用 `scenario =` 绑场景名；只有 `test =` 的条目仍走原来的用例名单。
假绿检测也只在存在 eval 步骤时才把 `adone/eval/*.toml` 算进基线——删场景文件等于删用例。

演示见 `demo/cs-agent-eval`（内存客服，零 LangGraph 依赖）。Java / Go 项目不要抄
它的 `watch_roots`，除非你真的要盯 skill 文本。

生成或改完配置后：

```bash
adone doctor
adone gate run
```

`doctor` 核命令找不找得到；`gate run` 真跑并写出第一份**全量**回执。
日常改动用 `adone gate run --changed`，见第 5 节。不要把全量 `argv` 改成只跑一条——
那是放松判据，要 `policy --accept`。

<br/><br/>

## 7. 如何更新 / 重置基线

基线有两份，都只报**放松**，收紧只提示。确属合理的放宽，必须写理由记账。

| 基线 | 锁什么 | 接受本次快照 |
| --- | --- | --- |
| `.adone/test-baseline.json` | 用例是否消失、跳过是否变多、无断言空壳、覆盖率下限 | `adone integrity --accept-baseline "理由"` |
| `.adone/policy-baseline.json` | 监视范围、步骤 argv、契约条数、豁免名单 | `adone policy --accept "理由"` |

```bash
adone integrity                              # 只看，不改
adone integrity --accept-baseline "拆包期，覆盖率下限暂降到 50"

adone policy                                 # 只看，不改
adone policy --accept "把 go vet 并进 build 步骤，命令因此变了"
```

首次 `gate run` 会在还没有判据基线时自动建一份。已经有基线时，`gate run` **不会**替你重建；
删掉 `policy-baseline.json` 想让锁失效，上一份回执里记着指纹，会被拦住。

复核者不允许跑 `--accept` / `--accept-baseline`。

<br/><br/>

## 8. 如何启用新 Agent 做独立审计

实现者和复核者要分开：换一个会话，最好换一个模型。不要把实现过程贴给复核者。

1. 实现者交付后，开**新会话**，只发这一句：

```
按 independent-check 独立复核这个仓库的交付：<仓库路径>
```

   没装技能时改成：`跑 adone brief，按它说的做，然后跑 adone audit`。

2. 复核者先 `adone brief`（冷启动：判据在哪、现有回执是哪份、不许碰什么），再 `adone audit`。
3. 不信任那份回执时，跑 `adone audit --rerun` 全量重跑再比对。
4. 未通过则把问题清单原样交回实现者。修完由**复核者再核一次**，不接受实现者自证。

```bash
adone brief
adone audit                  # 默认抽 2 条用例当场真跑
adone audit --rerun          # 自己把门禁跑一遍，结果只写进 .adone/audits/
adone audit report --open    # 已有 audit.json 时只出 HTML
```

`audit` 与 `gate check` 用同一套判定，但有三点不同：默认开抽查；不写 `latest.json`、
不推进证据链；口吻是「独立复核通过 / 实现者不能宣称完成」，不替实现者宣布完成。

结论在 `.adone/audit.json` 和 `.adone/audit.html`。页上会写明核到了哪一层
（只读证据 / 抽 N 条真跑 / 全量重跑），不要把最弱的一档读成最强。

<br/><br/>

## 9. 如何生成健康报告，以及怎么读

```bash
adone health                 # 读已有回执，秒级
adone health --open          # 生成后打开
adone health --all           # 先重跑门禁再体检
adone health --only skills   # 只跑某些维度
adone health --skip probes
```

报告是单文件 HTML（`.adone/report.html`），零外链，发给别人也能离线打开。
macOS 用 `open`，Linux 用 `xdg-open`，Windows 用系统关联打开。

六个维度：

| 维度 | 看什么 | 默认 |
| --- | --- | --- |
| 技能沉淀 | frontmatter、断链、引用的代码行号是否失效 | 跑 |
| 测试与覆盖率 | 最新回执：失败、覆盖率、假绿 | 跑 |
| 代码质量 | 权威对权威漂移、未引用符号、重复函数、超大文件 | 跑 |
| 需求台账 | 标了已做但锚点已不存在的失联需求 | 跑 |
| AI 物料 | 关键文档、过期架构图、选摘幻影、写死的数字 | 跑 |
| 业务不变量 | 你自己写的探针 | **不跑**（可能要服务在跑） |

怎么读：

- **总分旁边的「n/6 个维度」比分数本身重要。** `--only skills` 可以拿 100，但只覆盖了 1/6。
  跳过的维度灰显成「未评估」，不参与总分。
- **「这个检查跑不了」必须是未评估，不能默默算通过。**
- 头部的证据强度（自述 / 判据已锁 / 回执链完整）和分数在同一屏，不要只看数字。
- 覆盖率低不扣需求台账的分；扣的是「标了已做、证据没了」。
- 探针：「跑不起来」是警告，「不变量被破坏」才是错误。

<br/><br/>

## 10. Q&A

**Q：`adone` 敲不出来？**  
A：Windows / Linux 都要把 pipx 的 bin 加进 PATH（`~/.local/bin` 或 `%USERPROFILE%\.local\bin`）。
先 `adone --version` 再谈钩子。

<br/>

**Q：需要哪一版 Python？**  
A：3.11+。钩子拿到的 PATH 常常和终端不一样，本机发生过被 conda 的 3.10 拉起、
`import tomllib` 失败。`bin/adone` 会自己找一个够新的解释器：macOS / Linux 去
`~/.local/bin`、`~/.pyenv/shims`；Windows 去 `py.exe` 和
`%LOCALAPPDATA%\Programs\Python`。
装的时候 `pip` 报 `3.10.x not in '>=3.11'` 是同一回事，见第 3 节末尾。

<br/>

**Q：Windows 上 pre-commit / `gate run` 报 `gbk codec can't encode`？**  
A：是工具的锅，不是你的仓库。中文 Windows 上 Python 默认按 GBK 写控制台，
Maven 输出按 UTF-8 解完再 print 就会炸。v1.4.2 起入口会把 stdout 改成 UTF-8；
重渲 `adone install --hooks-only --force` 后钩子里也会带 `PYTHONIOENCODING=utf-8`。
不要手改 `.git/hooks/pre-commit`，下次重渲会盖掉。

<br/>

**Q：同一份配置能在 Windows、macOS、Linux 跑吗？**  
A：能。`adone.toml` 里写 `mvn` / `npm` / `./mvnw` 即可，Windows 上会解析成 `.cmd`
并由 `cmd /c` 拉起（CreateProcess 不能直接跑批处理）。
**钩子不行：** Cursor 的 `hooks.json`、Qoder 的 `settings.json` 都按安装那台机器生成。
各人在本机重渲（见第 4 节「按 IDE 接入」），不要提交对方的 command，也不要提交 `.exe`。

<br/>

**Q：Windows 上手跑 `gate-guard.cmd` 有 `hook.log`，Agent 里却没触发？**  
A：`CreateProcess` 不能直接跑 `.cmd`。升到 v1.3.8 后登记必须是 `.cursor/hooks/gate-guard.exe`。
`cmd /c …cmd` 也不行（整串当文件名）。不要在 `command` 里出现 `.py`（会打开编辑器）。

<br/>

**Q：日志写了「已回推」，对话里没有那条消息？**  
A：钩子已经跑完。Cursor 在 Windows 上经常没收齐 stdout，Execution Log 里变成 `{}`。
看 View → Output → Hooks 里这次 `stop` 的 OUTPUT。问题以 `hook.log` 和 `adone gate check` 为准。

<br/>

**Q：工作区开错一层？**  
A：必须开在放 `adone.toml` 的那一层（或其子目录）。只开子模块时，钩子的工作目录是子模块，
`CURSOR_PROJECT_DIR` 也对不上。

<br/>

**Q：Java 覆盖率读不到，但 `mvn` 是绿的？**  
A：把步骤写成 `mvn -B -ntp jacoco:prepare-agent test jacoco:report`。
只跑 `test jacoco:report` 时，没挂探针也会 BUILD SUCCESS。

<br/>

**Q：`adone detect --write` 把阈值冲掉了？**  
A：新接入一门生态用 `adone detect --merge`。不要用 `--write` 覆盖已有配置。
测试适配器除非加 `--adopt-tests`，否则不改。

<br/>

**Q：问一句设计、没改代码，也被推去跑全量测试？**  
A：那是 1.3.14 之前的设计：把每一轮 `stop` 当成「宣称完成」。现在的配置和用法见第 5 节。
升完要 `adone install --hooks-only --force`，否则项目里还是旧钩子。

<br/>

**Q：怎么把项目里的 adone 拆干净？**  
A：`adone clean`。它拆配置、回执、我们装的钩子和技能、本机 pre-commit。
别人的钩子不动。拆完要重新接入再 `adone init`。

<br/>

**Q：每次敲 adone 都问要不要升级，怎么关掉？**  
A：设 `ADONE_NO_UPDATE_CHECK=1`。钩子、`--json`、管道和 CI 本来就不会问。
也可以直接 `adone upgrade`，不必等提示。

<br/>

**Q：`pipx upgrade actuallydone` 说「已是最新」，GitHub 上明明有新版？**  
A：当初是带 `@v1.3.x` 这样的 tag 装的，pipx 把这串地址记成了升级源，等于钉死在那一版。
改用 `adone upgrade`；或者不带 tag 重装一次：
`pipx install --force git+https://github.com/iamharvey/ActuallyDone.git`。

<br/>

**Q：`git commit` 没触发全量门禁？**  
A：两条路各管一半，缺哪条都是安静地不设防，先 `adone doctor` 看它报哪条。
Agent 跑的 `git commit` 靠 `beforeShellExecution` 的 commit-guard——`hook.log` 里
一条 `commit-guard launched` 都没有，就是登记里没有它（v1.3.14 之前装的），
重跑 `adone install --hooks-only --force`。你自己在终端敲的 `git commit`
Cursor 完全看不见，只有 `.git/hooks/pre-commit` 拦得住；v1.3.19 之前，
`adone.toml` 不在仓库根上时它压根装不上。

<br/>

**Q：升级了 adone，钩子却还是旧的？**  
A：钩子里烧着安装时的绝对路径。`adone upgrade` 之后必须
`adone install --hooks-only --force`，再 `adone doctor`。

<br/>

**Q：删了基线想让检查闭嘴？**  
A：上一份回执记着基线指纹，会被拦。要放宽就 `--accept` / `--accept-baseline` 写理由。

<br/>

**Q：独立复核通过 = 不可能造假？**  
A：不是。复核者和实现者同一台机器、同一套写权限。`--rerun` 只是抬高成本。
要硬证据，把 `adone gate run` 放到 CI，回执留在 CI 侧。

<br/>

**Q：`generic` 项目为什么很多检查是未评估？**  
A：generic 适配器只能跑步骤，列不出用例名。假绿、契约、`--spotcheck` 会显示未评估，
而不是假装通过。

<br/>

**Q：在本仓库里开发时怎么自测？**
A：```bash
cd ActuallyDone
python3 -m unittest
```

MIT，见 [LICENSE](LICENSE)。
