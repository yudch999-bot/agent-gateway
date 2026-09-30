# ag — Agent Gateway

[![test](https://github.com/yudch999-bot/agent-gateway/actions/workflows/test.yml/badge.svg)](https://github.com/yudch999-bot/agent-gateway/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**One command to launch and switch between all your AI coding agents.**

Claude Code, Codex, Gemini, Grok, OpenCode, OpenClaw, Hermes, Pi, Goose, Kimi…
Stop memorizing a dozen different launch commands and a dozen shell aliases.
Put them all behind one fuzzy picker, and add your own by editing one line.

它管三层：

| 层 | 命令 | 解决什么 |
|---|---|---|
| **开哪个** | `ag` / `ag cc` | 十几套启动方式记不住 |
| **同时开几个** | `ag` 里 Tab 多选 / `ag team` | 一个不够用，还得手动开窗口 |
| **接着哪个干** | `ag last` / `ag resume` / `Ctrl-R` | 每次都要重新交代上下文 |
| **翻旧账 / 搬家** | `ag search` / `ag handoff` | 1.8G 会话历史躺着睡觉 |
| 顺带 | `ag outdated` / `ag update` / `ag stats` / `ag pin` | 批量运维、看习惯 |

![demo](docs/demo.gif)

```bash
ag            # 模糊选择器：打字即筛选，回车启动
ag cc         # 直接进 Claude Code
ag ot-design  # 直接进 OpenClaw 的 design 会话
ag cc --resume   # 参数原样透传
```

上面这段录像是**用真实的渲染器生成的**（不是手搓的假动画），
所以画面和真跑逐字节一致 —— 见 [`docs/make-demo-cast.py`](docs/make-demo-cast.py)。

> 📖 想一次看全？**[完整使用指南 →](docs/使用指南.md)**（命令全表、选择器按键、
> 注册表字段、加自定义 agent、排障、FAQ）

---

## 装的东西太多，各有各的启动方式

本机装了 18 个 AI coding agent，启动方式全不一样：

- 有的命令名就是启动指令（`codex`、`gemini`、`goose`）
- 有的靠 shell 别名（`cc`→`claude`、`oc`→`opencode`、`d`→`dsh-tui`）
- 多会话的还得敲一长串（`openclaw tui --session agent:design:main`）
- 想加一个新的，就得改 `.zshrc`、重开 shell、再记住一个别名

`ag` 把这些收在一处：

| 原来的麻烦 | 现在 |
|---|---|
| N 套启动方式要分别记 | `ag` 一个命令，选就行 |
| 长命令记不住 | `ag ot-design` |
| 加新 agent 要动 `.zshrc` | `ag add`，存完立刻生效 |
| 装了但忘了叫什么 | `ag scan` 扫出来 |
| 不知道哪个还能跑 | `ag doctor` 体检 |

**原有的 shell 别名一个都不用删**，`ag` 是加在上面的一层。

---

## 安装

一条命令（会装到 `~/.local/bin/ag`，并在 `~/.zshrc` 追加一段 source）：

```bash
curl -fsSL https://raw.githubusercontent.com/yudch999-bot/agent-gateway/main/install.sh | bash
```

或者手动：

```bash
git clone https://github.com/yudch999-bot/agent-gateway.git
cd agent-gateway
./install.sh
```

**依赖**：Python 3.11+（用了标准库 `tomllib`）、zsh（可选，只为补全）。
除此之外**零第三方依赖**，不用 pip install 任何东西。

装完开个新终端，敲 `ag` 试试。

---

## 用法

### 启动

| 命令 | 作用 |
|---|---|
| `ag` | 打开模糊选择器 |
| `ag <id>` | 精确启动，例 `ag cc` |
| `ag <id> [参数...]` | 参数透传给 agent，例 `ag cc --resume` |
| `ag <关键词>` | 没精确匹配时，打开预填关键词的选择器 |
| **`ag last`** | **接着上次那个 agent、上次那个会话继续** |
| `ag last --new` | 同上，但开新会话 |
| **`ag resume [id]`** | **续聊。不带 id 会列出支持续聊的** |
| **`ag team`** | **多选，一次全开，各占一个 tmux 窗口** |
| `ag team cc oc goose` | 直接点名几个 |
| `ag team --panes cc oc` | 用分屏（同屏都能看见） |
| `ag attach` | 回到之前的 tmux 会话 |
| **`ag ps`** | **看现在有哪些 agent 在跑** |
| **`ag kill [id...]`** | **关掉指定的窗口**（不带参数会列出让你挑） |
| `ag kill --all` | 关掉整个 tmux 会话 |

### 选择器

```
  ag Agent Gateway  1/29 · 选一个 agent · 输入即筛选
  ❯ 设
  ────────────────────────────────────────────────────────────
  ● ot-design     OpenClaw · design 视觉设计师     视觉设计师
  ────────────────────────────────────────────────────────────
  openclaw tui --session agent:design:main  tags: openclaw,team
  ↑↓ 移动 · Enter 启动 · Ctrl-R 续聊 · Ctrl-T 置顶 · Ctrl-O 配置 · ? 帮助 · Esc 退出
```

| 按键 | 作用 |
|---|---|
| 直接打字 | 追加筛选词（**支持中文**） |
| **`Tab`** | **多选 —— 勾几个，Enter 一次全开** |
| `↑` `↓` / `Ctrl-P` `Ctrl-N` | 移动 |
| `PgUp` `PgDn` / `Home` `End` | 翻页 / 跳首尾 |
| `Backspace` / `Ctrl-U` | 删一字 / 清空 |
| `Enter` | 启动（新会话） |
| **`Ctrl-R`** | **续聊 —— 接上次的会话**（需要注册表里有 `resume`） |
| `Ctrl-T` | 置顶 / 取消置顶（★ 标记，会排在前面） |
| `Ctrl-O` | 打开该 agent 的配置目录 |
| `?` | 帮助面板 |
| `Esc` / `Ctrl-C` | 退出 |

**排序会学习你的习惯**：空查询时按 *置顶 > 常用程度 > 注册表顺序* 排。
常用程度 = 用过的次数按 **14 天半衰期** 衰减 —— 常用来的一直在前面，
偶尔翻出来的老古董会自然沉下去。一打字就切回按命中质量排。

搜索范围：**短名、显示名、说明、标签、别名**，中英文都行。

```
ag 设计        →  ot-design
ag 文案写手     →  ot-dev
ag wrapper     →  omc / omx
ag deepseek    →  d
```

排序：精确短名 > 短名前缀 > 短名含 > 显示名前缀 > 别名前缀 > 主字段含 > 仅在标签/说明中命中（沉底）。

行首 **绿点 `●` = 能找到可执行文件，红圈 `○` = 没装**，选中缺失项时底部会显示安装命令。

### 管理

| 命令 | 作用 |
|---|---|
| `ag ls` | 列出全部（`--all` 含隐藏项，`--json` 机器可读） |
| `ag add` | 向导式添加 |
| `ag rm <id>` | 删除（保留注释，自动备份） |
| `ag edit` | 用 `$EDITOR` 打开注册表 |
| `ag scan` | 扫描 `PATH`，找出装了但没登记的 |
| `ag doctor` | 体检：逐条解析真实路径 |
| `ag install <id>` | 按登记的 `install` 命令安装 |
| `ag install --missing` | 一键补装所有缺失的 |
| **`ag outdated`** | **看哪些有新版本**（npm / brew 能查的都查） |
| **`ag update [id...]`** | **批量升级**，不带 id 会先列出命令再确认 |
| `ag update --all` | 全部升级，不问 |
| `ag update --dry-run` | 只看会执行什么，不真跑 |
| `ag which <id>` | 看实际会执行什么、在哪 |
| `ag pin [id...]` | 置顶（不带参数列出当前置顶） |
| `ag unpin <id...>` | 取消置顶 |
| `ag stats` | 使用统计（含 frecency 柱状图） |
| `ag stats --history` | 最近启动的时间线 |
| **`ag search <关键词>`** | **在历史会话里搜**（1.8G 的记录不再躺着睡觉） |
| **`ag handoff [id]`** | **把最近一次会话整理成交接 prompt，复制到剪贴板** |
| `ag path` | 打印注册表路径 |

---

## 一次开好几个

一个 agent 不够用的时候：让它跟另一个互相 review、一个写一个查、
或者干脆几个模型同时上。

```bash
ag team                 # 多选器：Tab 勾几个，Enter 一次全开
ag team cc oc goose     # 或者直接点名
ag team -r cc codex     # 都续聊上次的会话
ag team --panes cc oc   # 用分屏，同屏都能看见
```

其实**普通的 `ag` 也支持**：Tab 勾上几个再 Enter 就行。

```
  ag Agent Gateway  已选 3：cc,oc,goose · 输入即筛选
  ❯
  ────────────────────────────────────────────────────────
  ▣ cc            Claude Code            Anthropic 官方 CLI
  ▣ oc            OpenCode               开源终端编码 agent
  ▣ goose         Goose                  Block/aaif 开源 agent
  ────────────────────────────────────────────────────────
  ↑↓ 移动 · Enter 一次全开（各占一个窗口） · ...
```

### 它们跑在哪儿

默认走 **tmux**，一人一个窗口：

- **本来就在 tmux 里** → 直接往你当前会话加窗口，人不用动
- **不在 tmux 里** → 建一个叫 `ag` 的会话然后 attach 进去

第二种更常用。好处是**关掉终端它们也还活着**：

```bash
Ctrl-B d        # 脱离，回到普通 shell，agent 继续跑
ag attach       # 随时回来
```

没装 tmux 也不会死：macOS 会退化成开几个 Terminal 窗口，其它平台把命令打出来。

### 收尾

```bash
ag ps              # 现在跑着什么
ag kill            # 列出让你挑（回车取消）
ag kill cc oc      # 关掉指定的
ag kill --all      # 关掉整个会话
```

```
  正在跑的 agent  3 个 · 1 个 tmux 会话

  ● ag:0  cc       Claude Code             4 分钟前
  ● ag:1  oc       OpenCode                1 分钟前  ← 你在这
  ● ag:2  goose    Goose                   3 分钟前
```

不认识的窗口也会列出来（比如你自己开的 vim），不会假装没看见。
`ag kill` 不带参数时**回车就是取消**；要关的如果正是你待着的窗口会先问一次；
窗口关光了 tmux 会话自己结束，`ag` 会告诉你一声。

> 想看会执行什么：`ag team --dry-run cc oc`

---

## 接着上次干

启动器只解决了「开哪个」。真正每天在用的痛点是**「接着上次那个活干」**。

```bash
ag last          # 上次用的哪个 agent、上次那个会话 → 直接续上
ag resume cc     # 指定续聊 Claude Code
ag resume        # 不知道续哪个？列出所有支持续聊的
```

或者在选择器里选中一项按 **`Ctrl-R`**。

各家 agent 的续聊方式完全不一样，`ag` 不自己解析会话文件（格式私有、还会变），
而是**把命令转过去，让各家自己的会话选择器干活**：

| 短名 | 续聊时执行 |
|---|---|
| `cc` | `claude --resume` |
| `codex` | `codex resume` |
| `grok` | `grok --resume` |
| `oc` | `opencode --continue` |
| `kimi` | `kimi --session` |
| `goose` | `goose session --resume` |
| `d` | `dsh-tui --resume` |

在注册表里一行就能给任何 agent 加上：

```toml
resume = ["--resume"]     # 选项式，如 claude / grok
resume = ["resume"]       # 子命令式，如 codex / omx
resume = ["session", "--resume"]   # 更长的，如 goose
```

示例注册表里 **29 条有 15 条**已经填好了（都实测过 `--help`，不是猜的）。
没填的按 `Ctrl-R` 会明确提示你去加，而不是默默开个新会话。

`ag stats` 能看你到底在用哪些：

```
  使用统计   共 137 次启动 · 续聊 41 次 · 用过 6 个 agent

  ★ cc         62 次 ·   2 小时前  ▇▇▇▇▇▇▇▇▇▇▇▇ Claude Code
    oc         38 次 ·      昨天  ▇▇▇▇▇▇▇ OpenCode
    goose      21 次 ·    3 天前  ▇▇▇▇ Goose
    kimi        9 次 ·   2 周前  ▇▇ Kimi Code
```

---

## 翻历史

装了十几个 agent，历史会话散在十几个私有格式的目录里，加起来 1.8G。
`ag` 把它们变成能用的东西。

### 搜

```bash
ag search 登录页           # 我记得上周让某个 agent 改过，但忘了是哪个
```

```
  搜索 4 个 agent 的历史会话：'公众号'
    cc           40 /51 个会话命中
    codex        77 /84 个会话命中
    j            32 /91 个会话命中

  命中 149 个会话，显示最近 8 个：

  cc             10 小时前  ~/projects/foo
            OpenClaw 升级在 validating 阶段被拒，triage 也没跑起来…
            ~/.claude/projects/-Users-yudengcheng/23451c59-….jsonl
```

`ag search` 走 ripgrep，扫完 4 个 agent 约 **1.8 秒**。找到之后 `ag resume <id>`
就能接着聊。

### 交接

```bash
ag handoff          # 从最近用过的 agent 交接
ag handoff cc       # 指定从 Claude Code 交接
```

它会读那个 agent **最近一次会话**的最后 8 轮对话，加上工作目录，
生成一段 prompt 塞进剪贴板。你切到另一个 agent 粘一下就行。

场景：在 Claude Code 里聊到一半发现 Codex 更合适，不用把那堆上下文重新讲一遍。

> 加 `--print` 直接打出来（没装剪贴板工具时用）。

### 怎么做到的

**不给每家写解析器。** 各家会话格式完全不同（claude 是
`<编码路径>/<uuid>.jsonl`，codex 是 `YYYY/MM/DD/rollout-*.jsonl`，
jcode 干脆是整份塞一个 `.json` 里），私有、还会变。所以 `ag` 只做两件事：

1. 注册表里用 `sessions` 字段记「去哪找」
2. 用一个**宽容的通用提取器**挖 `cwd` / 标题 / 对话：按 key 名递归找
   `text` / `content` / `message` / `messages` / `payload`，
   再用一组启发式（长度、符号占比、XML 标签、shell 回显）把噪音挡掉

认得出就显示，认不出就少显示一点，**绝不因为某家改了格式就整个崩掉**。

想给自己的 agent 加上：

```toml
sessions = "~/.youragent/sessions"
```

示例注册表里已填好 4 个（`cc` `codex` `gemini` `j`），都是实测确认过目录里
确实是会话记录的 —— 像 `~/.grok/memtrace`、`~/.codewhale/telemetry`
那些是调试数据，看着像但不是，就没收。

---

## 加自己的 agent

### 向导

```bash
ag add
```

### 一行

```bash
ag add --id myagent --cmd myagent --name "My Agent" \
        --desc "干什么的" --tags "自研,内部" --alias ma
```

### 直接改注册表

`ag edit`，追加一块，**保存即生效，不用重开 shell**：

```toml
[[agent]]
id = "myagent"                # 必填，唯一短名，就是 `ag myagent` 敲的那个
name = "My Agent"             # 显示名
cmd = "myagent"               # 必填，可执行文件名或绝对路径
args = ["--flag", "value"]    # 固定参数，每次启动都带
desc = "一句话说明"
tags = ["自研", "内部"]        # 标签，可被搜索
alias = ["ma", "mine"]        # 额外别名
env = { API_KEY = "sk-xxx" }  # 启动时注入的环境变量
cwd = "~/work"                # 启动目录，支持 ~
install = "npm i -g myagent"  # 给 `ag install` 用
update = "npm i -g myagent@latest"   # 给 `ag update` 用（不给就退回 install）
resume = ["--resume"]         # 续聊参数，给 `ag resume` / Ctrl-R 用
hidden = false                # true 则不进选择器
```

它本质就是个**带参数的启动器**，非 AI 的命令也能收：

```bash
ag add --id k9s --cmd k9s --desc "K8s 面板"
ag add --id gp --cmd git --args "pull --rebase" --desc "拉取变基"
```

---

## 进阶

### 用另一份注册表

```bash
export AG_REGISTRY=~/proj/agents.toml
ag ls
```

`ag` 本体、补全、备份目录都会跟着走。适合给单个项目配一套入口。

### Ctrl-G 快捷键

`ag.zsh` 会绑定 `Ctrl-G`，在任意命令行提示符下直接召唤选择器。不想要：

```zsh
export AG_NO_KEYBIND=1
```

### 和 cc-switch 的分工

不冲突，建议并用：

| | 管什么 |
|---|---|
| **cc-switch** 等 provider 切换器 | 同一个 agent 换**供应商 / 模型 / API Key** |
| **ag** | 换**哪个 agent**，以及怎么启动它 |

`ag` 负责把进程拉起来，拉起来之后走哪家 API 仍然归切换器管。

---

## 开发

主程序是单文件 `ag`（Python 标准库，无第三方依赖）。改完跑全套：

```bash
bash tests/lint.sh            # 静态检查
python3 tests/test_ag.py      # 主程序回归测试
bash tests/test_install.sh    # 安装脚本回归测试（临时 HOME，不碰真环境）
```

| 测试 | 覆盖什么 |
|---|---|
| `tests/lint.sh` | `$VAR` 后紧跟多字节字符、shell 语法、可执行位、密钥扫描、shellcheck |
| `tests/test_ag.py` | 假终端驱动选择器（**不需要真 pty**）：渲染帧、终端还原、按键导航、中英文与标签搜索排序、别名解析、TOML 特殊字符往返、注册表完整性 |
| `tests/test_install.sh` | 全新 HOME 安装、重复安装幂等、老式标记行识别、已有注册表不被覆盖 |

本机装齐了全套 agent 的，可以加 `AG_EXPECT_ALL_INSTALLED=1` 让它额外校验每个可执行文件都解析得到。

### 为什么有 `lint.sh` 第 1 项

这个项目真踩过：`"源文件：$RAW（远程下载）"` 里 `$RAW` 后面紧跟全角括号 `（`，
某些 locale 下 bash 会把多字节字符吞进变量名，运行时报 `RAW?: unbound variable`，
而 **`bash -n` 完全查不出来**。修法一律写成 `${RAW}`。lint 第 1 项就是抓这个。

### 重新生成 README 里的演示

有两种方式：

```bash
python3 docs/make-demo-cast.py    # 不需要终端，可复现，CI 友好
bash docs/record-demo.sh          # 开真 asciinema 会话，你亲手敲
```

第一种拿 `ag` 真正的渲染器跑一遍，把每帧输出连时间戳录成
[asciinema cast](https://docs.asciinema.org/manual/asciicast/v2/)，
所以**画面和真实运行逐字节一致**，而且不需要 pty、不需要人操作。
第二种适合录进自己的真实环境。

两种都产出 `.cast`，再转 GIF：

```bash
agg --font-size 15 --theme monokai docs/demo.cast docs/demo.gif
```

---

## 文件

```
ag                       主程序（Python 标准库，零依赖）
registry.example.toml    注册表模板，install.sh 会复制成 ~/.agents/registry.toml
ag.zsh                   zsh 补全 + Ctrl-G 快捷键
install.sh               安装脚本（幂等，支持 curl | bash）
docs/使用指南.md          完整使用手册
docs/demo.cast           演示录像（asciinema 格式）
docs/demo.gif            README 里那张图
docs/make-demo-cast.py   从真实渲染器生成录像
docs/record-demo.sh      开真终端录一段
tests/lint.sh            静态检查
tests/test_ag.py         主程序回归测试
tests/test_install.sh    安装脚本回归测试
```

运行时目录：

```
~/.local/bin/ag                主程序
~/.agents/registry.toml        你的注册表
~/.agents/ag.zsh               zsh 集成
~/.agents/backups/             注册表自动备份（保留最近 20 份）
~/.agents/usage.jsonl          使用记录（frecency 用，追加写）
~/.agents/pins.json            置顶的短名
```

后面两个是**状态**不是**配置**，跟注册表同级：换了 `AG_REGISTRY` 它们跟着走。
`usage.jsonl` 一行一条记录，删掉不影响使用，只是排序会退回注册表顺序。

---

## FAQ

**改了注册表要重启 shell 吗？**
不用。`ag` 每次运行重读注册表。只有改 `.zshrc` 才需要 `source ~/.zshrc`。

**启动报「找不到可执行文件」？**
那条的 `cmd` 不在 `PATH` 上。`cmd` 可以直接写绝对路径，或把它的 bin 目录加进 `PATH`。先 `ag doctor` 看哪条断了。

**短名和子命令重名了？**
子命令优先。登记一个短名叫 `ls` 的 agent，`ag ls` 会走子命令而不是启动它。换个短名。

**想同时跑好几个 agent？**
每个 `ag <id>` 是独立进程，开几个终端窗口即可。要多窗格同屏用 tmux，每个 pane 里 `ag <id>`。

---

## License

MIT
