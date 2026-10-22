# 写 `adone.toml`：按生态配置门禁

[← 回到 README](../README.md)

`adone init` 按仓库里的标志文件（`go.mod` / `pom.xml` / `CMakeLists.txt` …）生成步骤，探测所得的项都标着「请确认」。
覆盖率下限留空，等第一次 `adone gate run` 拿实测值回填。改完配置跑 `adone doctor` 核命令，再 `adone gate run`。

新接入一门生态用 `adone detect --merge`（追加步骤、不碰阈值）。不要用 `--write`，它会整份覆盖已有配置。

两个关键字段：

- `kind = "fmt"`：格式化工具常常永远退出 0，有输出即失败。
- `kind = "test"` + `adapter`：用适配器解析用例名和覆盖率，只看退出码会漏掉假绿。

完整的样例在三个 demo 里：[pet-store-java](../demo/pet-store-java/adone.toml)、
[task-store-cpp](../demo/task-store-cpp/adone.toml)、[cs-agent-eval](../demo/cs-agent-eval/adone.toml)。
生态适配器的源码在 [`actuallydone/adapters/`](../actuallydone/adapters/)。

## Go

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

代码在子目录（例如 `backend/go.mod`）时，给步骤加 `cwd = "backend"`，`watch_roots` 写成 `["backend"]`。

## Java（Maven）

```toml
[[gate.step]]
name = "mvn test"
kind = "test"
adapter = "java"
# timeout_seconds = 1800   # 可选。默认不限时；超时会杀掉进程树
argv = ["mvn", "-B", "-ntp", "jacoco:prepare-agent", "test", "jacoco:report"]
```

- **不要只写 `mvn test jacoco:report`**：pom 没把探针绑进生命周期时，Maven 仍会 BUILD SUCCESS，一份覆盖率报告都没有。
- 多模块时把每个模块的 `src` 写进 `watch_roots`。覆盖率按各模块行数相加；有 `jacoco-aggregate` 时只认聚合报告。
- 写 `mvn` / `./mvnw` 即可，Windows 上会自动对上 `mvn.cmd` / `mvnw.cmd`。
- 按本机核数并行跑 JUnit 5，把 `-Djunit.jupiter.execution.parallel.*` 开关写进同一步的 `argv`
  （判据锁锁的是命令，不是 pom），改完 `adone policy --accept "理由"`。
  不要用 Surefire 的 `-Dparallel`（只认 JUnit 4），也不要用 `-DargLine` 塞属性（会盖掉 `jacoco:prepare-agent`）。
  完整写法见 [demo/pet-store-java/README.md](../demo/pet-store-java/README.md)。

## C++（CMake）

```toml
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

同一份 `argv` 在三个平台都能跑：`-DCMAKE_BUILD_TYPE` 给 Ninja / Makefiles，`--config` 与 `-C` 给 Visual Studio。
适配器认 GoogleTest、CTest 和 Catch2 的输出；覆盖率认 `lcov.info`。
MSVC 没有 gcov，不要填 `coverage.threshold`，否则门禁会把「未评估」当成失败。

## 场景门禁（可选）

客服 / Agent 图这类项目可以**另外**加一步 `adapter = "eval"`，用场景金标挡召回漏检、多块乱合并、该打断没打断。
这是 opt-in，普通 Java / Go / Python / Node 项目不用加，`adone init` 也不会自动加。

```toml
[[gate.step]]
name = "skill eval"
kind = "test"
adapter = "eval"
argv = ["python3", "scripts/eval_cs_agent.py"]
```

适配器认 stdout 里的 `PASS <id>` / `FAIL <id>` / `SKIP <id>`（id 可以是 `recall#退货时效`）。
契约用 `scenario =` 绑场景名。存在 eval 步骤时，`adone/eval/*.toml` 也算进假绿基线，删场景文件等于删用例。
演示见 [demo/cs-agent-eval](../demo/cs-agent-eval/README.md)。

## 源码编码

```toml
[project]
source_encoding = "gbk"    # utf-8 / gbk / auto
```

UTF-8 永远先试，这一项决定解不动时退到哪，逐个文件判断，迁移期两种编码混放也没问题。
它只影响读文本的检查，回执的树哈希按字节算。GBK 项目上这项不能省：GBK 尾字节含 ASCII，
硬按 UTF-8 读会凭空多出 `{`，扫测试方法时切错函数体，「相关用例」就会少认几条。
