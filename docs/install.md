# 安装与升级

[← 回到 README](../README.md)

需要 Python 3.11+（用到标准库 `tomllib`），零第三方依赖。

## pipx（推荐）

pipx 给 `adone` 单独建一个 venv，自己挑一个够新的解释器，不碰你项目的环境。

```bash
pipx install git+https://github.com/iamharvey/ActuallyDone.git
adone --version
```

**地址后面不要加 `@v1.8.0` 这样的 tag。** pipx 会把这串地址记成以后的升级源，
钉了 tag 就钉死在那一版，之后 `pipx upgrade` 只会说「已是最新」。

没有 pipx 先装一个（Windows 把 `python3` 换成 `py -3`）：

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

## 让 `adone` 敲得出来

pipx 把命令放在 `~/.local/bin`，Windows 上是 `%USERPROFILE%\.local\bin`。
这个目录常常不在 PATH 里，命令敲不出来，钩子也一样找不到它。

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # bash 改 ~/.bashrc
source ~/.zshrc
```

Windows 用 `pipx ensurepath`，然后重开终端。`adone --version` 能打印版本号再往下走。

## 升级：用 `adone upgrade`，不要用 `pipx upgrade`

```bash
adone upgrade --check                 # 只查有没有新版，不动安装
adone upgrade
adone install --hooks-only --force    # 每个装了钩子的项目各跑一次
```

`adone upgrade` 自己去 GitHub 比 Release、tag 和默认分支的版本号，认出你是 pipx / pip / git 工作树再覆盖过去，
所以当初装的时候带没带 tag 都升得上去。它覆盖的是 PATH 上那份 `adone`，不是你当前所在的源码目录。

最后那条 `--hooks-only --force` 不能省：钩子里烧着安装时的绝对路径，换版本或换位置就会失效，
而失效的样子和「门禁通过」在终端里一模一样。Qoder 项目见 [ide.md](ide.md)。

交互式终端里敲 `adone doctor` / `gate` / `install` 时，如果 GitHub 上有新版，会先问一句要不要升。
回车或 `n` 继续，`y` 走 `adone upgrade`。钩子、`--json`、管道、CI 里不问。不想被问设 `ADONE_NO_UPDATE_CHECK=1`。

## 另外两种装法

```bash
# pip：装进当前解释器，和项目依赖共享环境
pip install git+https://github.com/iamharvey/ActuallyDone.git

# vendor：把本仓库拷进项目的 tools/，免安装
python3 tools/ActuallyDone/bin/adone --version
```

pip 报 `requires a different Python: 3.10.x not in '>=3.11'`，是你敲的这个 `pip` 属于某个 3.10 环境
（conda 里很常见），不是机器上没有新 Python。换 `python3.12 -m pip install …`，或者用 pipx。

钩子拿到的 PATH 常常和终端不一样。`bin/adone` 会自己找一个够新的解释器：macOS / Linux 去
`~/.local/bin`、`~/.pyenv/shims`；Windows 去 `py.exe` 和 `%LOCALAPPDATA%\Programs\Python`。

## 拆掉

```bash
adone clean          # 先列出要删的，默认不拆
adone clean --yes    # 不交互
```

拆配置、回执、我们装的钩子和技能、本机 pre-commit。别人写的钩子和不是 adone 渲染的技能不动。
