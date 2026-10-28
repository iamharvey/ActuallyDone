---
name: verified-delivery
description: 防「伪完成」的 Subagent 交付流水线：spec 澄清、implement 实现、test 独立写测、review 评审、verify 全量验证、audit 换个模型独立复核六段，每段带显式验收标准与必须提交的证据。拆分多 Subagent 并行开发、需要保证「自称完成」可验证、或明确调用 verified-delivery 时使用。
disable-model-invocation: true
---

# 可验证交付流水线

核心约束，逐字传给每个实现类 Subagent：

> 不要直接宣称完成，直到你能证明测试是真实运行且通过的（附上测试运行日志），否则视为未完成。

「自称完成」不是完成。段与段之间靠**产物**衔接（契约、文件清单、命令输出），
不靠「上一个 Agent 说它做完了」。

## 六段：spec → implement → test → review → verify → audit

- **spec**：把需求变成一份 `adone/acceptance/<任务>.toml` 验收契约（每条是可观察的行为 +
  一个用例名），写法见 [acceptance-contract](../acceptance-contract/SKILL.md)。产出契约本身，不写代码。
- **implement**：只写实现。**不写自己的测试**（写了也不作数），避免「照着实现写出必然通过的测试」。
- **test**：**独立上下文**，只拿到契约与被改文件清单，**看不到 implement 的推理过程**。
- **review**：评审 diff，重点是不变量与本项目的高频 Bug 模式。
- **verify**：跑门禁，引用回执。
- **audit**：**换一个会话、最好换一个模型**做独立复核，见 [independent-check](../independent-check/SKILL.md)。

## 关键设计：test 段必须盲写

implement 与 test 用两个 Subagent，test 段的提示词里**不放实现思路、不放实现代码的解释**，
只放契约条目、被改文件路径、以及「用例要证明什么业务后果」。同一上下文里先写实现再补测试，
产出的测试往往是实现的镜像——实现漏了的分支，测试也会一起漏。

## Subagent 提示词骨架

直接复制修改。**验收标准一律引用契约条目，不要用自然语言复述**——复述会走样，
而契约条目由 `adone gate verify-contract` 逐条去核。

### implement

```
仓库：当前工作区（pet-store-java）
任务：<一句话说清要实现什么>
验收契约：adone/acceptance/<任务>.toml，逐条必须满足（不要自行增删条目）

必读：.cursor/skills/coding-standards/SKILL.md

约束：
- 只写实现，不写测试文件。测试由独立 Subagent 编写。
- <本项目的不变量清单>

验收标准（不满足即未完成，逐条自查后在回复里勾选）：
- [ ] mvn -B spotless:check 通过
- [ ] mvn -B -ntp test 通过
- [ ] 契约每条 item 的 impl 字段已填上真实的「文件:行号」

产出：改了哪些文件、每个文件干了什么、上述命令的输出。
```

### test

```
仓库：当前工作区（pet-store-java）
被改文件：<路径清单>
验收契约：adone/acceptance/<任务>.toml，每条 item 的 test 字段就是你要写的用例名

必读：.cursor/skills/test-driven-dev/SKILL.md

约束：
- 不要去读实现的设计说明，只按契约里「要求」描述的业务后果写用例。
- 用例名与断言信息写清业务后果。

验收标准：
- [ ] 契约里每条 item 的 test 用例都已写出，函数名一字不差
- [ ] 单跑这些用例的完整输出已贴出
- [ ] 全量测试通过，失败数 0
- [ ] adone integrity 无新增松动

产出：新增/修改的测试文件、上述命令的真实输出（不是转述）。
```

### review

```
仓库：当前工作区（pet-store-java）
评审范围：<文件清单>
必读：.cursor/skills/pr-review-checklist/SKILL.md 及其 references/

约束：
- 只评审本次改动，不评审历史遗留风格。
- known-gaps.md 里的已知缺口不要重复报。
- 阻断项优先，可选项最多三条。

产出：按「阻断 / 建议 / 可选」分档，每条给出文件:行号 + 会发生什么后果。
```

## verify 段：跑门禁，引用回执

自查清单挡不住「贴过期日志」和「跑完再改代码」，所以这一段不逐条自勾，改为跑门禁并引用回执：

```
- [ ] adone gate run      # 全量检查并写回执
- [ ] 回复里写出回执 ID 与树哈希前 12 位（例：20260810-213012 / e3a91c…）
- [ ] adone gate check    # 契约全绿、假绿检测无新增、哈希与当前代码一致
- [ ] review 的阻断项已全部处理
- [ ] 高风险模块按 references/high-risk.md 完成额外验证
```

口径与回执读法见 [completion-gate](../completion-gate/SKILL.md)。**只跑了过滤子集的测试不算数**，门禁跑的是全量。
判定失败归属时把自己的测试单独跑一遍再下结论——多 Agent 并行改同一个包时会看到别人的编译错误。

## audit 段：换个人来查

verify 是实现者自己跑的，证明的是「证据自洽」，不是「没人做手脚」。所以最后开一个新会话（换模型更好），
只给一句 `按 independent-check 独立复核这个仓库的交付：当前工作区（pet-store-java）`，不给实现过程；未通过原样交回问题清单，
修完由复核者再核一次，不接受实现者自证已修好。

## 深入

- 沙箱与合并策略：[references/sandbox.md](references/sandbox.md)
- 高风险模块与端到端验证要求：[references/high-risk.md](references/high-risk.md)
- 效果衡量指标与技能触发准确率抽样：[references/metrics.md](references/metrics.md)
