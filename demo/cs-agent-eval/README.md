# cs-agent-eval

ActuallyDone 的**可选场景门禁**演示：内存里的召回 / 多块合并 / HITL 打断，
**不引入 LangGraph 或任何模型**。语义对应客服图，评测是读金标、打印 `PASS` / `FAIL`。

Java / Go / Python / Node 的 vibe coding **不要抄**这份 `watch_roots`。
只有当你真的要盯 skill 文本和 eval 金标时，才把 `.md` / `adone/eval` 加进受监视树。
`adone init` 也不会因为仓库里有 skill 或图就自动加 eval 步骤。

## 自己跑

需要 Python 3.11+。

```bash
cd demo/cs-agent-eval
python3 scripts/eval_cs_agent.py
```

金标在 `adone/eval/*.toml`：召回必中 / 禁中、冲突块取谁、高额退款必须打断、查物流禁止打断。

## 用 adone 复核

在本目录（不要在 ActuallyDone 仓库根）：

```bash
adone gate run
adone gate check
adone integrity
adone policy
```

门禁步骤是手写的 `adapter = "eval"`。契约用 `scenario =` 绑场景名，不走 `test =`。
`.adone/` 入库判据基线、假绿基线和证据链。回执和 `latest.json` 不入库：每人跑一次门禁都会改写它们。
