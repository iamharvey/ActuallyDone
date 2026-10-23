# merge-mail

一个小范例：规则是真的，测试也可以绿得不老实。这里演示怎么在通用门禁旁边加一步，以及怎么把两种结果都跑出来看。

规则在 `merge_mail.py`：两封信都是空标题、邮箱又相同，才并到同一个单号。`ingest` 只读调用那一刻已经写好的字段。

## 门禁原来挡住什么

`adone gate run` 的第一步是 `unittest`。它只证明 `tests/` 里点了名的用例通过了。验收契约写在 `adone/acceptance/merge-mail.toml`：正例一条、反例一条，`要求` 写的是能证明的那句话，不是「最后两个单号相同」。

这一步挡不住两件事：

- 有人在调用 `ingest` 之后把邮箱改成一样，再断言同号。断言是绿的，决策前的邮箱并不是那样。
- 有人把 `decide` 改成 `return True`。只写正例的测试照样绿。

`adone integrity` 不扫 SQL，也不把 `return` 常量当成失败。误报太多，写进通用门禁会被豁免掉。

## 这一步是项目自己加的

`adone.toml` 里第二步跑 `scripts/check_honest.py`，只扫 `tests/`：

- 自己用诚实输入调用 `ingest`。同邮箱必须合并，不同邮箱不得合并。判定写成恒真，会在反例上失败。
- 读测试源码。调用之后如果还有对主题、发件人、邮箱、状态的赋值、`UPDATE` 或 `$set`，这一步失败。

反面教材放在 `examples/cheat_after_call.py`，不在 `tests/` 里，所以第一步发现不到它。

## 自己验证

在本目录：

```bash
cd demo/merge-mail

python3 -m unittest discover -s tests -v
python3 scripts/check_honest.py
python3 examples/cheat_after_call.py
python3 scripts/check_honest.py --scan examples
```

前两条应该通过。第三条会打印「断言过了」：造数脚本自己是绿的。第四条应该失败，并且看到「调用之后改了规则要读的字段」。

装了 adone 之后，在本目录跑 `adone gate run`。两步都过，回执才是绿的。第一次 `adone gate check` 会要求建假绿基线，由人在终端执行 `adone integrity --accept-baseline "建立初始基线"`，再跑 `adone gate check`。

把 `decide` 改成 `return True`，或者把反面教材挪进 `tests/`，第二步会红，第一步的 unittest 仍可能是绿的。
