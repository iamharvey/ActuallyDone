# 门禁：开发中跑相关用例，提交时全量

[← 回到 README](../README.md)

## 几条命令

| 时机 | 命令 | 写 `latest.json`？ |
| --- | --- | --- |
| 改了受监视文件之后（`stop` 钩子也会跑） | `adone gate run --changed` | 否，只写 `.adone/partial.json` |
| 交给另一个模型之前、交付、`git commit` | `adone gate run` | 是，证据只认这份 |
| 多模块 Maven，只重跑变过的模块 | `adone gate run --affected` | 是，回执写明哪些继承自上一份全量 |
| 随时复核全量回执是否新鲜 | `adone gate check` | 否，约 1 秒 |

```bash
adone gate run --changed   # 只跑与 dirty / git diff 相关的用例
adone gate run             # 全量，写回执
adone gate run --affected  # 只跑变过的模块（要先有一份带单元哈希的全量绿回执）
adone gate check           # 树哈希必须对上 latest.json；通过了是证据，不是完成声明
adone gate check --explain # 附带每一步的判定依据
adone gate slow            # 最近一轮最慢的用例 / 模块
adone gate waive-tests "这次只改注释，没有新行为"   # 人来豁免，实现再变则失效
```

`adone.toml` 里的 `[[gate.step]]` **不用为开发期改**：全量命令仍是 `mvn test` / `go test ./...`。
相关用例由适配器另组一条临时命令；把全量 `argv` 改成只跑一条会被判据锁判成放松。

`gate check` 通过时的那句话是「把回执交给另一个模型」，不是「可以完成了」。
接着换一个模型跑 `adone audit --reviewer <模型名>`，见 [audit.md](audit.md)。

## 回执会挡住什么

- **跑完再改代码**：回执记着受监视树的哈希，改一个字符就过期。
- **实现变了，测试没变**：回执把实现文件和测试文件分开哈希。相对上一份全量回执实现变了而测试没变，
  `gate check` 不通过，提交也被拦。确实没有新行为时由人 `adone gate waive-tests "理由"`。
  扫不到测试文件时标成未评估。只改测试注释会让测试哈希变化从而放行，删用例、掏空断言仍由 `integrity` 抓。
- **整批用例被跳过**：连不上数据库等依赖导致的「绿」不算数。

## 有用例失败，但不是这次改的

全量门禁照样不绿，提交照样被拦，这一步留给人决定。Agent 这边的做法写在 `completion-gate` 技能里：
先用上一份回执的 `tests.failed_names` 或在 `HEAD` 上单跑判归属；确认无关就把本轮的事做完，
不修、不跳过、不删那条用例，交付时单列证据。`stop` 钩子推回时也这么提示。

## `--changed` 怎么找相关用例

文件名单是 `.adone/dirty` 与 `git status`（含未跟踪）合并。git 会在项目根和每个 `watch_roots` 各定位一次仓库，
子目录自带 `.git` 也扫得到。路径一律收成相对 `adone.toml` 所在目录。名单为空时会说明原因
（PATH 里没有 git / 不在仓库里 / 改动都在项目目录外），不会让「钩子失效」看起来像「代码没改过」。

映射是文件名启发式，不做调用图（适配器的 `related_tests`）：

- 改的是测试文件：跑该文件里的用例。
- 改的是实现：同 stem + `Test` / `_test` / `test_`。`PetStore.java` → `PetStoreTest`；
  `foo.go` → `foo_test.go`；`lib.py` → `test_lib.py` / `lib_test.py`；`store.cpp` → 测到该 stem 的 `Suite.Case`。
- 拼命令：Java `-Dtest=ATest,BTest`，Go `-run`，Python `-k`，C++ `ctest -R`。
- 映射为空：回推「找不到与这些文件相关的用例，写一条再继续」，**不退回全量**，也不空跑冒充绿。

通过后清掉 dirty；找不到或跑失败则留下，下一轮 `stop` 还会拦。不要在 `afterFileEdit` 里跑测试（每存一次就起 JVM）。

## 钩子在什么时候跑

- `mark-dirty`：Agent 改文件时记下路径。stdin 按字节读，中文 Windows 的 cp936 解坏时从原文正则抽路径。
- `gate-guard`（`stop`）：没有受监视改动不回推；有改动跑 `--changed`，上一轮已通过且文件哈希没变则跳过。
  问一句设计、没改代码，不会被推去跑测试。
- `commit-guard`：Agent 跑 `git commit` 先过全量门禁；Agent 跑放宽判据的三条命令一律拒绝。
- `.git/hooks/pre-commit`：人在终端 `git commit` 时跑全量。两条都装，`--no-verify` 也绕不过 Agent 那条。

提交默认走全量。要让 pre-commit 走范围化全量，在 `adone.toml` 里写：

```toml
[gate]
commit_scope = "affected"
```

然后 `adone install --hooks-only --force`。Gradle 没有 `-amd`，`--affected` 会被拒绝，不会偷偷少跑。

## 全量跑太久怎么查

1. **是不是卡住。** 门禁步骤边跑边打输出，静默超过 60 秒打一行心跳。每步可配 `timeout_seconds` /
   `stall_seconds`（默认不限时）。超时会把 surefire fork 出的 JVM 一并杀掉。
2. **是不是端口冲突。** 失败步骤的 note 会写「端口 8080 被占」和 Spring 测试上下文缓存这个根因。
   改成 `webEnvironment = RANDOM_PORT`。
3. **慢在哪。** `adone gate slow` 读 surefire XML 的 `time`，按用例和按模块出榜。
   多模块 Spring 十有八九是上下文重复启动，不是用例数。
4. **再谈并发或缩范围。** 固定端口下开并行，冲突会变成间歇性变红。先隔离端口，或用 `--affected` 少跑。
   退路：surefire `${surefire.forkNumber}` 分端口段；JUnit 5 `@ResourceLock`；容器 / `unshare -n` 隔离网络。

**固定端口的测试可能连上本机在跑的旧版服务然后通过。** 回执绑的是新代码，测试打的是旧进程，这是真的假绿。

## 回执里有什么

`.adone/latest.json`，由脚本写，不要手改：

- `tree.hash` / `tree.file_count`：受监视代码树的内容哈希。
- `tree.impl_changed` / `tree.tests_changed`：相对上一份全量回执的变化。
- `tests.passed_names` / `tests.failed_names`：通过与失败的用例名。
- `steps`：每步的命令、退出码、输出尾巴。
- `coverage.percent`：覆盖率。
- `runner.model`：钩子见到模型名时写下，供 `audit --reviewer` 对照。

源码在 [`actuallydone/gate.py`](../actuallydone/gate.py)，回执结构在 [`actuallydone/model.py`](../actuallydone/model.py)。
