<p align="center">
  <img src="actuallydone-cover.png" alt="ActuallyDone：别只说完成，拿出证据。">
</p>

# ActuallyDone - adone

当前版本 **v1.7.0**，变更记录见 [CHANGELOG.md](CHANGELOG.md)。Python 3.11+，零第三方依赖。

AI Agent 说「已完成，测试全部通过」时，你没法当场判断真假：它可能贴的是上一轮的日志，
可能跑完测试又改了代码，也可能为了变绿把用例删了、断言去了、覆盖率下限调低了。

`adone` 让「完成」变成**别人能独立复核的证据**，而不是会话里的一句自述：

1. **完成 = 与代码绑死的回执。** `adone gate run` 真跑检查，把代码树哈希、每步退出码、通过的用例名写进回执。
   之后改一个受监视的文件，回执就过期。
2. **尺子也要留档。** 删用例、缩监视范围、调低下限都能让门禁变绿。基线只报放松，放宽必须由人写理由记账。
3. **不自己审自己。** 换一个会话、最好换一个模型跑 `adone audit`，复核者不看实现过程。

它提高的是伪造成本，不是密码学级的不可伪造；要硬证据，把门禁放进 CI。

![ActuallyDone 架构](docs/architecture.png)

## 安装

```bash
pipx install git+https://github.com/iamharvey/ActuallyDone.git
adone --version
```

不要在地址后加 `@v1.x` 这样的 tag，否则以后升不上去。升级用 `adone upgrade`，然后在每个项目里
`adone install --hooks-only --force` 重渲钩子。PATH、pip、免安装、卸载见 [docs/install.md](docs/install.md)。

## 五分钟上手

在项目根目录（放 `go.mod` / `pom.xml` / `package.json` / `pyproject.toml` / `CMakeLists.txt` 的那一层）：

```bash
adone init                         # 探测生态，生成 adone.toml，逐项确认
adone doctor                       # 核路径、命令、钩子
adone gate run                     # 第一次全量门禁，按实测回填覆盖率下限
adone integrity --accept-baseline "建立初始基线"
adone install --with-hooks         # 装技能 + IDE 钩子 + 本机 pre-commit
adone health --open                # 出一页健康报告
```

默认装 Cursor 的钩子；Qoder 或两边都用，见 [docs/ide.md](docs/ide.md)。

## 装好之后，日常是这样

你和 Agent 照常改代码，不用多敲命令：

| 发生了什么 | adone 做什么 |
| --- | --- |
| Agent 改了受监视的文件 | 钩子记下来 |
| Agent 这一轮说完了（`stop`） | 只跑与改动相关的用例，没过就推回给 Agent；没改代码就不打扰 |
| 有人 `git commit` | 先跑全量门禁，不过就拦住 |
| Agent 想自己放宽基线、豁免检查 | 拒绝，这几条只能人在终端敲 |

想自己看结果、或者交付前：

```bash
adone gate run --changed   # 开发中：只跑相关用例
adone gate run             # 全量，写回执
adone gate check           # 1 秒核对回执是否还对得上当前代码
```

`gate check` 通过是「可以交给别人复核」，不是「做完了」。交付时开一个新会话，最好换个模型，只发一句：

```
按 independent-check 独立复核这个仓库的交付：<仓库路径>
```

## 装进项目的技能

`adone install` 把八个技能渲染到 `.cursor/skills/`（Qoder 是 `.qoder/skills/`），按项目配置填好命令和路径。
Agent 在合适的时候自动读它们：

| 技能 | 管什么 |
| --- | --- |
| `completion-gate` | 「完成」只认新鲜的全绿回执；遇到别人留下的失败用例不停工也不去动它；调外部接口要真的发请求 |
| `test-driven-dev` | 先写会失败的用例，再写实现，每步贴真实输出 |
| `test-integrity` | 识别删用例、去断言、跳过、调低下限、事后改数据凑条件这类「把门禁改绿」的手法 |
| `acceptance-contract` | 把需求逐条绑到用例名，门禁逐条核 |
| `independent-check` | 复核者的做法：只报告，不修，不替人记账 |
| `coding-standards` | 本项目的分层、命名、禁用 API |
| `pr-review-checklist` | 评审清单与高频 Bug 模式 |
| `verified-delivery` | 多 Subagent 的六段交付流水线（手动调用） |

模板在 [`actuallydone/templates/skills/`](actuallydone/templates/skills/)。

## 命令一览

| 命令 | 做什么 | 详细 |
| --- | --- | --- |
| `init` / `detect` / `doctor` | 生成配置、增量探测新生态、核对配置 | [docs/config.md](docs/config.md) |
| `gate run` / `check` / `slow` / `waive-tests` | 门禁、回执、慢用例、人工豁免 | [docs/gate.md](docs/gate.md) |
| `integrity` / `policy` | 假绿基线、判据锁 | [docs/baselines.md](docs/baselines.md) |
| `brief` / `audit` | 独立复核 | [docs/audit.md](docs/audit.md) |
| `health` / `requirements` | 健康报告、需求台账 | [docs/health.md](docs/health.md) |
| `install` / `clean` / `upgrade` | 装技能和钩子、拆除、升级 | [docs/install.md](docs/install.md)、[docs/ide.md](docs/ide.md) |

每条命令都有 `--help`。遇到问题先跑 `adone doctor`，再看 [docs/faq.md](docs/faq.md)。

## 项目里会多出什么

```
adone.toml                 # 配置，人写，入库
adone/acceptance/*.toml    # 验收契约，入库
adone/requirements/*.toml  # 需求台账，入库
.adone/                    # 机器写的状态：回执、基线、审计结论、报告
.cursor/skills/            # adone install 渲染的技能
.cursor/hooks.json         # 钩子，按本机路径生成，不入库
.git/hooks/pre-commit      # 本机生成，不入库
```

`.gitignore` 这样写，让两份基线和证据链头入库（**不要写 `.adone/`**，否则后面的 `!` 全部失效且不报错）：

```gitignore
.adone/*
!.adone/test-baseline.json
!.adone/policy-baseline.json
!.adone/chain.json
```

## 演示项目

| 目录 | 演示什么 |
| --- | --- |
| [demo/pet-store-java](demo/pet-store-java/README.md) | Maven + JaCoCo，JUnit 5 按核数并行 |
| [demo/task-store-cpp](demo/task-store-cpp/README.md) | CMake + CTest，不依赖 GoogleTest |
| [demo/cs-agent-eval](demo/cs-agent-eval/README.md) | 内存客服，用场景金标做门禁 |
| [demo/merge-mail](demo/merge-mail/README.md) | 项目自己加一步，挡住调用之后改数据凑条件 |

Java 和 Go 的完整基线配置（不是能跑的项目）在 [examples/](examples/README.md)。

## 开发本仓库

```bash
python3 -m unittest discover -s tests
```

技能改动用 [bench/](bench/README.md) 在固定题目上让 Codex 真跑、比结果，再由人决定是否采纳。

MIT，见 [LICENSE](LICENSE)。
