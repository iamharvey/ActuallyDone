# 基线：不让人悄悄把尺子改短

[← 回到 README](../README.md)

「让门禁变绿」有两条路：把代码改对，或者把尺子改短——删用例、去断言、调低覆盖率下限、
缩小监视范围、换测试命令、删验收契约。基线把判据拍成快照，**只报放松**，收紧只提示。
确属合理的放宽，必须由人写理由记账。

| 文件 | 锁什么 | 接受本次快照 |
| --- | --- | --- |
| `.adone/test-baseline.json` | 用例是否消失、跳过是否变多、无断言空壳、覆盖率下限 | `adone integrity --accept-baseline "理由"` |
| `.adone/policy-baseline.json` | 监视范围、步骤 argv、契约条数、豁免名单 | `adone policy --accept "理由"` |
| `.adone/new-tests-waiver.json` | 这一次「实现变了但测试没变」，绑当前实现哈希 | `adone gate waive-tests "理由"` |

```bash
adone integrity                              # 只看，不改
adone integrity --accept-baseline "拆包期，覆盖率下限暂降到 50"

adone policy                                 # 只看，不改
adone policy --accept "把 go vet 并进 build 步骤，命令因此变了"
```

几条规矩：

- 首次 `gate run` 会在还没有判据基线时自动建一份。已有基线时不会替你重建。
- 删掉基线想让检查闭嘴不行：上一份回执记着基线指纹，会被拦住。
- **放宽只能由人在终端里敲。** 装了钩子之后，Agent 在 IDE 里执行这三条会被拒绝；复核者也不许跑。
  直接改这几个 JSON 钩子管不到，但会出现在 diff 里。
- 判据基线、假绿基线、证据链头（`chain.json`）建议入库：它们是证据，不是缓存。

源码：[`actuallydone/integrity.py`](../actuallydone/integrity.py)、[`actuallydone/policy.py`](../actuallydone/policy.py)。
