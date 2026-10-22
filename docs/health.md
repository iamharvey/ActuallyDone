# 健康报告

[← 回到 README](../README.md)

门禁只回答「这次改动是否全绿」。要看整个项目的状况，跑 `adone health`。

```bash
adone health                 # 读已有回执，秒级
adone health --open          # 生成后打开
adone health --all           # 先重跑门禁再体检
adone health --only skills   # 只跑某些维度
adone health --with-probes   # 加跑自定义探针
adone health --list          # 列出维度与各自成本
adone health --json          # stdout 只有 JSON
```

报告是单文件 HTML（`.adone/report.html`），零外链，发给别人也能离线打开。

| 维度 | 看什么 | 默认 |
| --- | --- | --- |
| 技能沉淀 | frontmatter、断链、引用的代码行号是否失效、SKILL.md 是否过长 | 跑 |
| 测试与覆盖率 | 最新回执：失败、覆盖率、假绿 | 跑 |
| 代码质量 | 权威对权威漂移、未引用符号、重复函数、超大文件 | 跑 |
| 需求台账 | 标了已做但锚点已不存在的失联需求 | 跑 |
| AI 物料 | 关键文档、过期架构图、选摘幻影、写死的数字 | 跑 |
| 业务不变量 | 你自己写的探针 | **不跑**，`--with-probes` 才跑（可能要服务在跑、可能写库） |

怎么读：

- **总分旁边的「n/6 个维度」比分数本身重要。** `--only skills` 可以拿 100，但只覆盖了 1/6。
  没跑的维度灰显成「未评估」，不参与总分。跑不了的检查必须是未评估，不能默默算通过。
- 头部的证据强度（自述 / 判据已锁 / 回执链完整）和分数在同一屏，不要只看数字。
- 覆盖率低不扣需求台账的分；扣的是「标了已做、证据没了」。
- 探针「跑不起来」是警告，「不变量被破坏」才是错误。

需求台账用 `adone requirements init` 从需求源生成骨架，`adone requirements check` 核验证据锚点。

源码：[`actuallydone/health.py`](../actuallydone/health.py)、各维度在 [`actuallydone/dimensions/`](../actuallydone/dimensions/)。
