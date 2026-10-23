# 基线配置

[← 回到 README](../README.md)

两份给现成仓库抄的 `adone.toml`，不是能跑起来的项目。目录约定写在文件头，对不上就改 `argv` 和 `watch_roots`，改完要 `adone policy --accept "理由"`。

| 文件 | 生态 |
| --- | --- |
| [java/adone.toml](java/adone.toml) | Maven。格式化、Checkstyle、SpotBugs、敏感信息、单元测试、API 测试、打包、端到端、技能检查 |
| [go/adone.toml](go/adone.toml) | Go。格式化、import、vet、staticcheck、敏感信息、单元测试、API 测试、构建、端到端、技能检查 |

能跑的项目在 [demo/](../demo)。门禁字段说明在 [docs/config.md](../docs/config.md)。

这几步 adone 认得语义，其余步骤只看退出码：

- `kind = "fmt"`：工具经常退出 0，有输出即失败。`gofmt -l`、`goimports -l` 用这个。`spotless:check` 不过时自己退出非 0，不要标成 `fmt`。
- `kind = "test"` 加 `adapter`：解析用例名和覆盖率。只看退出码，整包没跑起来也会被当成通过。
- `invalid_marks`：stdout 里出现这串字，这一步的证据作废。拿来抓「数据库没起来，整批被跳过」。不要填 `Skipped`，正常的单条跳过也会撞上。
- 覆盖率只从 `coverage.source` 那一步读。Java 读 JaCoCo 报告，Go 读该步输出里最后一行 `coverage:`，多包时那不是合计。
- 技能检查是 `adone health --only skills`。有错误才失败，超长这类警告不失败。PATH 上要有 `adone`。
