# 诚实的边界

这套机制**提高伪造成本，不是密码学级不可伪造**。Agent 有写文件权限，理论上能重算整条回执链
并同步改掉基线。缓解是回执由脚本写、带自哈希与链、内容含树哈希与命令输出，
任何人可以用 `{{ADONE}} gate check --explain` 独立复核，交付前还可以
`{{ADONE}} gate check --spotcheck` 抽两条用例当场真跑、由第二个模型 `{{ADONE}} audit --rerun` 全量重跑。
要做到真正不可伪造，需要一个 Agent 无权写入的执行者（CI），路径写在
[verified-delivery/references/sandbox.md](../../verified-delivery/references/sandbox.md)。
