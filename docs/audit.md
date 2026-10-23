# 换一个 Agent 做独立复核

[← 回到 README](../README.md)

实现者自己跑 `gate check`，证明的只是「证据自洽」，而它正是被检者。
复核要换一个会话，最好换一个模型，并且不要把实现过程贴给复核者。

## 步骤

1. 实现者交付后，开**新会话**，只发这一句：

   ```
   按 independent-check 独立复核这个仓库的交付：<仓库路径>
   ```

   没装技能时改成：`跑 adone brief，按它说的做，然后跑 adone audit`。

2. 复核者先 `adone brief`（判据在哪、现有回执是哪份、不许碰什么），再 `adone audit --reviewer <模型名>`。
   回执里的 `runner.model` 与复核者相同则审计不通过；缺任何一边只写进依据。
3. 不信任那份回执时，跑 `adone audit --rerun` 全量重跑再比对。
4. 未通过就把问题清单原样交回实现者。修完由**复核者再核一次**，不接受实现者自证。

```bash
adone brief
adone audit --reviewer <模型名>   # 默认抽 2 条用例当场真跑
adone audit --rerun               # 自己把门禁跑一遍，结果只写进 .adone/audits/
adone audit report --open         # 已有 audit.json 时只出 HTML
```

## 和 `gate check` 的区别

同一套判定，但 `audit` 默认开抽查；不写 `latest.json`、不推进证据链；结论写在 `.adone/audit.json`
和 `audit.html`，口吻是「独立复核通过 / 实现者不能宣称完成」，不替实现者宣布完成。
页上写明核到了哪一层（只读证据 / 抽 N 条真跑 / 全量重跑），不要把最弱的一档读成最强。

## 全绿不证明夹具老实

回执通过只说明契约点名的用例在这棵代码树上跑过。`adone brief` 会要求打开这些用例：调用之后改了主题、发件人、邮箱、状态，或者断言比契约的「要求」弱（两个记录最后同号，证明不了决策前就是双空标题、同邮箱），按未通过写进问题清单。这不进 `audit` 的失败码，门禁该绿还是绿。要在某个项目里真的挡，就在 `adone.toml` 加一步自己的检查。能跑的对照见 [demo/merge-mail](../demo/merge-mail/README.md)。

## 诚实的边界

这套机制提高伪造成本，不是密码学级不可伪造。复核者和实现者在同一台机器、有同一套写权限，
理论上能重算整条回执链。要硬证据，把 `adone gate run` 放到 CI 这种 Agent 无权写入的执行者上，回执留在 CI 侧。

源码：[`actuallydone/audit.py`](../actuallydone/audit.py)、[`actuallydone/spotcheck.py`](../actuallydone/spotcheck.py)。
