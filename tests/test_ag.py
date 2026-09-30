"""ag 的假终端测试：不需要真 pty，直接喂按键序列，检查渲染与启动目标。

跑法：
    python3 tests/test_ag.py

夹具用仓库里的 registry.example.toml，所以在任何机器上都能跑，不需要事先装好 agent。
装了全套的可以加 AG_EXPECT_ALL_INSTALLED=1，额外校验每个可执行文件都解析得到。

脚本会自己找 ag 主程序和夹具，顺序：
    ag    ： $AG_BIN → <仓库>/ag → ~/.local/bin/ag
    注册表： $AG_REGISTRY → <仓库>/registry.example.toml → ~/.agents/registry.example.toml
"""
import importlib.machinery, importlib.util, io, json, os, re, shlex, shutil, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOME = os.path.expanduser("~")


def _first(*cands):
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


AG_BIN = _first(os.environ.get("AG_BIN"),
                os.path.join(ROOT, "ag"),
                os.path.join(HOME, ".local/bin/ag"))
if not AG_BIN:
    sys.exit("找不到 ag 主程序。设 AG_BIN=/path/to/ag 或先跑 install.sh")

FIXTURE_SRC = _first(os.environ.get("AG_REGISTRY"),
                 os.path.join(ROOT, "registry.example.toml"),
                 os.path.join(HOME, ".agents/registry.example.toml"),
                 os.path.join(HOME, ".agents/registry.toml"))
if not FIXTURE_SRC:
    sys.exit("找不到夹具注册表。设 AG_REGISTRY=/path/to/registry.toml")

REAL_OUT = sys.stdout
def say(*a, **k):
    print(*a, file=REAL_OUT, **k)

# 夹具复制一份到临时目录再指过去：
# usage.jsonl / pins.json 是跟注册表同级的，这样测试写的状态全在临时目录里，
# 不会往仓库里拉屎，也不会踩到用户真实的 ~/.agents/registry.toml
_TMPDIR = tempfile.mkdtemp(prefix="ag-test-")
_FIXTURE = os.path.join(_TMPDIR, "registry.toml")
shutil.copyfile(FIXTURE_SRC, _FIXTURE)

# 注册表必须在 import ag 之前设好（REGISTRY 是导入期读的）
os.environ["AG_REGISTRY"] = _FIXTURE

loader = importlib.machinery.SourceFileLoader("agmod", AG_BIN)
spec = importlib.util.spec_from_loader("agmod", loader)
ag = importlib.util.module_from_spec(spec)
loader.exec_module(ag)

# ag 导入时 stdout 不是 tty，颜色会被自动关掉。渲染相关的断言要靠反显（\033[7m）
# 定位高亮行，所以这里强制打开 —— 别处用 strip() 之后不受影响。
ag.C = dict(r="\033[0m", b="\033[1m", dim="\033[2m", red="\033[31m",
            grn="\033[32m", yel="\033[33m", blu="\033[34m", mag="\033[35m",
            cyn="\033[36m", gry="\033[90m", inv="\033[7m")

say(f"  ag   : {AG_BIN}")
say(f"  注册表: {FIXTURE_SRC}  (测试用副本: {_TMPDIR})")
say()

# ---------------------------------------------------------------- 假终端
class FakeIn:
    def isatty(self): return True
    def fileno(self): return 0

class FakeOut(io.StringIO):
    def isatty(self): return True

class FakeTermios:
    TCSADRAIN = 1
    restored = False
    def tcgetattr(self, fd): return ["ORIG"]
    def tcsetattr(self, fd, when, attrs):
        assert attrs == ["ORIG"], "退出时必须还原原始终端设置"
        FakeTermios.restored = True

class FakeTty:
    def setraw(self, fd): pass

keys, _buf = [], bytearray()

def fake_read(fd, n=1):
    """模拟真终端：一次只吐 1 个字节。"""
    global _buf
    if not _buf:
        if not keys:
            return b""          # EOF
        _buf += keys.pop(0)
    out = bytes(_buf[:n]); del _buf[:n]
    return out

_real_os = ag.os
class FakeOs:
    def __getattr__(self, k): return getattr(_real_os, k)
    def read(self, fd, n=1): return fake_read(fd, n)

ag.os = FakeOs()
ag.termios = FakeTermios()
ag.tty = FakeTty()
_real_select, _real_shutil = ag.select, ag.shutil
_real_subprocess = ag.subprocess
_real_launch_many = ag.launch_many      # run() 会把它换成桩，先留个真身
ag.select = types.SimpleNamespace(select=lambda *a, **k: ([0], [], []))
ag.shutil = types.SimpleNamespace(
    get_terminal_size=lambda d=(100, 24): os.terminal_size((110, 30)),
    which=lambda c: "/usr/bin/" + c)

ESC, UP, DOWN, BS, ENTER = b"\x1b", b"\x1b[A", b"\x1b[B", b"\x7f", b"\r"

def run(seq, argv=None):
    """跑一次 main()，返回 (渲染输出, 启动了谁, rc)。"""
    global keys, _buf
    keys, _buf = list(seq), bytearray()
    FakeTermios.restored = False
    buf = FakeOut()
    got = {}
    ag.sys.stdin, ag.sys.stdout = FakeIn(), buf
    ag.sys.argv = argv or ["ag"]
    def fake_launch(e, extra, resume=False):
        got["launched"] = (e.id, extra)
        got["resume"] = resume
        return 0

    def fake_many(entries, layout="windows", resume=False, session=None):
        got["many"] = [e.id for e in entries]
        got["many_layout"] = layout
        got["many_resume"] = resume
        return 0
    ag.cmd_launch = fake_launch
    ag.launch_many = fake_many
    try:
        rc = ag.main(ag.sys.argv)
    finally:
        ag.sys.stdout = REAL_OUT
    return buf.getvalue(), got, rc

strip = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
frames_of = lambda out: out.split("\033[H\033[2J")
def last_frame(out):
    """很多断言只该看最后一帧 —— strip(out) 会把历史帧也算进来。"""
    return strip(frames_of(out)[-1])

fail = []
def check(name, cond, extra=""):
    say(f"  {'✓' if cond else '✗'} {name}" + (f"   [{extra}]" if (extra and not cond) else ""))
    if not cond: fail.append(name)

say("=" * 64)
say("1) 输入过滤 · 方向键 · 退格 · Esc 取消")
out, got, rc = run([b"c", b"e", DOWN, UP, BS, ESC])
fr = frames_of(out)
check("每按一键重绘一帧（6 帧）", len(fr) - 1 == 6, f"实际 {len(fr)-1}")
check("退出时还原终端设置", FakeTermios.restored)
check("Esc 不启动任何 agent", "launched" not in got)
check("退出备用屏幕", "\033[?1049l" in out)
check("进入备用屏幕 + 隐藏光标", "\033[?1049h" in out and "\033[?25l" in out)
say("  ── 输完 'ce' 那一帧 ──")
for l in [x for x in strip(fr[-3]).splitlines() if x.strip()]:
    say("   │", l)

say()
say("2) 输入完整 id 后回车")
out, got, _ = run([b"o", b"t", b"-", b"c", b"e", b"o", ENTER])
check("回车启动 ot-ceo", got.get("launched", ("",))[0] == "ot-ceo", str(got))
check("渲染里出现 ot-ceo", "ot-ceo" in strip(out))

say()
say("3) 方向键导航")
reg = ag.load_registry()
out, got, _ = run([DOWN, DOWN, DOWN, ENTER])
check("下移 3 格后回车 → 第 4 项", got.get("launched", ("",))[0] == reg[3].id,
      f"{got.get('launched')} vs {reg[3].id}")
out, got, _ = run([b"\x1b[6~", ENTER])          # PgDn
check("PgDn 翻页不崩", "launched" in got, str(got))
out, got, _ = run([b"\x1b[B"] * 200 + [ENTER])  # 越界
check("一直按到底不越界", got.get("launched", ("",))[0] == reg[-1].id,
      str(got.get("launched")))

say()
say("4) 模糊筛选与排序")
for q, want in [("cc", "cc"), ("kimi", "kimi"), ("deepseek", "d"), ("goose", "goose"),
                ("mcode", "mcode"), ("claude", "cc"), ("openclaw", "ot")]:
    hits = [e.id for e, _ in ag.fuzzy(reg, q)]
    check(f"'{q}' 首选 {want}", bool(hits) and hits[0] == want, str(hits[:4]))
say("   多关键词 'openclaw 设计' ->", [e.id for e, _ in ag.fuzzy(reg, "openclaw 设计")])
say("   中文搜索 '文案写手'      ->", [e.id for e, _ in ag.fuzzy(reg, "文案写手")])
say("   标签搜索 'wrapper'       ->", [e.id for e, _ in ag.fuzzy(reg, "wrapper")])
check("中文可搜", ag.fuzzy(reg, "文案写手") and ag.fuzzy(reg, "文案写手")[0][0].id == "ot-dev")
check("标签可搜", len(ag.fuzzy(reg, "wrapper")) == 2)

say()
say("5) 别名解析")
for a, want in [("opencode", "oc"), ("codewhale", "cw"), ("jcode", "j"),
                ("claude", "cc"), ("hermes", "h"), ("openclaw", "ot")]:
    e = ag.find_entry(reg, a)
    check(f"ag {a} → {want}", bool(e) and e.id == want, str(e and e.id))

say()
say("6) TOML 往返 · 特殊字符转义")
e = ag.Entry(dict(id="zz-test", name='测试 "Agent"', cmd="echo",
                  args=["a b", "c"], desc='带"引号"和\\反斜杠',
                  tags=["x", "y"], alias=["zz"], env={"K": "V v"},
                  cwd="~/tmp", install="echo hi"))
blk = ag.render_toml(e)
say("  ── 生成的 TOML ──")
for l in blk.splitlines(): say("   │", l)
open("/tmp/zz.toml", "w").write("[[agent]]\n" + blk)
back = ag.load_registry("/tmp/zz.toml")[0]
check("往返无损", (back.id, back.name, back.args, back.desc, back.tags,
                   back.alias, back.env, back.cwd, back.install) ==
                  (e.id, e.name, e.args, e.desc, e.tags, e.alias,
                   e.env, e.cwd, e.install))

say()
say("7) ag rm —— 单条 / 多条 / 保留注释 / 报错")
ag.shutil = _real_shutil          # rm 要真 shutil（备份用 copy2），别再喂假的
import tempfile
FIXTURE = """# 顶部注释，不能被删

# ---------- A 组 ----------
[[agent]]
id = "aa"
name = "甲"
cmd = "echo"
desc = "第一个"
alias = ["a1"]
tags = ["grp"]

# ---------- B 组 ----------
[[agent]]
id = "bb"
name = "乙"
cmd = "echo"
desc = "第二个"

# ---------- C 组 ----------
[[agent]]
id = "cc"
name = "丙"
cmd = "echo"
desc = "第三个"

# 文件结尾注释
"""

def rm_case(args, label):
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False,
                                     encoding="utf-8") as f:
        f.write(FIXTURE)
        path = f.name
    saved_reg, saved_out, saved_err = ag.REGISTRY, ag.sys.stdout, ag.sys.stderr
    ag.REGISTRY, ag.sys.stdout, ag.sys.stderr = path, io.StringIO(), io.StringIO()
    try:
        rc = ag.main(["ag", "rm", *args])
    finally:
        ag.REGISTRY, ag.sys.stdout, ag.sys.stderr = saved_reg, saved_out, saved_err
    text = open(path, encoding="utf-8").read()
    return rc, text, path

rc, text, p1 = rm_case(["aa"], "单条")
ids = [x.id for x in ag.load_registry(p1)]
check("单条删除成功", rc == 0 and ids == ["bb", "cc"], str(ids))
check("保留了别的块的小标题", "# ---------- B 组 ----------" in text and
                              "# ---------- C 组 ----------" in text)
check("保留了顶部和结尾注释", "顶部注释" in text and "文件结尾注释" in text)

rc, text, p2 = rm_case(["aa", "cc"], "多条")
ids = [x.id for x in ag.load_registry(p2)]
check("一次删多条", rc == 0 and ids == ["bb"], str(ids))
check("多条删除后注释仍在", "# ---------- B 组 ----------" in text)

rc, text, p3 = rm_case(["a1"], "用别名删")
ids = [x.id for x in ag.load_registry(p3)]
check("别名也能删", rc == 0 and ids == ["bb", "cc"], str(ids))

rc, text, p4 = rm_case(["aa", "nope"], "有找不到的")
ids = [x.id for x in ag.load_registry(p4)]
check("有一个找不到就整体不删", rc != 0 and ids == ["aa", "bb", "cc"], str(ids))

for f in (p1, p2, p3, p4):
    os.unlink(f)

say()
say("8) 注册表完整性")
reg = ag.load_registry()
ids = [x.id for x in reg]
check("id 无重复", len(ids) == len(set(ids)))
check("都有 cmd", all(x.cmd for x in reg))
check("18 个主 agent 都在", all(k in ids for k in
      ["d", "cc", "codex", "gemini", "grok", "oc", "ot", "h", "pi", "omp",
       "pa", "j", "kimi", "goose", "omx", "omc", "mcode", "cw"]))
check("openclaw 8 个专职 session 都在", all(f"ot-{k}" in ids for k in
      ["ceo", "product", "dev", "design", "marketing", "data", "ops", "finance"]))
miss = [x.id for x in reg if not x.resolved()]
if os.environ.get("AG_EXPECT_ALL_INSTALLED"):
    check("全部可执行文件都能解析到", not miss, str(miss))
else:
    say(f"  · 未安装 {len(miss)}/{len(reg)} 个（没装的环境属正常）"
        f"{'：' + ', '.join(miss[:6]) + ' …' if miss else ''}")
    check("解析逻辑不抛异常", all(x.resolved() is None or os.path.exists(x.resolved())
                                  for x in reg))

# 续聊命令不能有重复参数 —— args 里已经有的就别在 resume 里再写一遍。
# 这个检查是因为 ht 真踩过：hermes --tui --tui --continue
dupes = []
for x in reg:
    if not x.can_resume:
        continue
    argv = x.resume_argv()
    seen, dup = set(), set()
    for a in argv[2:]:
        (dup if a in seen else seen).add(a)
    if dup:
        dupes.append(f"{x.id}: {' '.join(argv)} (重复 {sorted(dup)})")
check("续聊命令没有重复参数", not dupes, "; ".join(dupes))
say(f"  · 可续聊的 agent: {sum(1 for x in reg if x.can_resume)}/{len(reg)}")

say()
say("9) frecency 使用频率评分")
NOW = 1_800_000_000.0
u = {"hot": [NOW - 3600, NOW - 7200, NOW - 10800],     # 今天用了 3 次
     "warm": [NOW - 86400 * 3],                        # 3 天前 1 次
     "cold": [NOW - 86400 * 60],                       # 60 天前 1 次
     "ancient": [NOW - 86400 * 400]}                   # 一年多前
fr = ag.frecency(u, now=NOW)
say("  分数：" + "  ".join(f"{k}={v:.3f}" for k, v in sorted(fr.items(), key=lambda t: -t[1])))
check("今天用 3 次的 > 3 天前用 1 次的", fr["hot"] > fr["warm"])
check("3 天前的 > 60 天前的", fr["warm"] > fr["cold"])
check("60 天前的 > 400 天前的", fr["cold"] > fr["ancient"])
check("半衰期算得对（14 天整应衰减到一半）",
      abs(ag.frecency({"x": [NOW - 86400 * 14]}, now=NOW)["x"] - 0.5) < 1e-9)
check("一次没用过的没有分", "nobody" not in fr)

say()
say("10) 排序：置顶 > 常用 > 注册表顺序")
small = [ag.Entry(dict(id=i, cmd="echo")) for i in ["a1", "b2", "c3", "d4"]]
# a1 常用但没置顶；c3 置顶但没用过
hits = [(e, 0) for e in small]
u2 = {"a1": [NOW - 100] * 5, "b2": [NOW - 100]}
ordered = [e.id for e, _ in ag.order_hits(hits, u2, ["c3"], query="", entries=small)]
say("  空查询顺序：" + " > ".join(ordered))
check("置顶的排第一", ordered[0] == "c3")
check("其余的按常用程度排", ordered[1] == "a1" and ordered[2] == "b2")
check("没用过的垫底", ordered[3] == "d4")

# 一打字就该按命中质量排，置顶不能压过精确命中
hits2 = ag.fuzzy(small, "d4")
ordered2 = [e.id for e, _ in ag.order_hits(hits2, u2, ["c3"], query="d4", entries=small)]
check("有查询时精确命中优先于置顶", ordered2[0] == "d4", str(ordered2))

say()
say("11) 续聊：Ctrl-R")
reg_now = ag.load_registry()
say(f"  · 注册表里 {sum(1 for e in reg_now if e.can_resume)} 条支持续聊")
out, got, _ = run([b""])                     # Ctrl-R，光标在第 1 项
first = ag.order_hits(ag.fuzzy([e for e in reg_now if not e.hidden], ""),
                      ag.load_usage(), ag.load_pins(), query="", entries=reg_now)[0][0]
if first.can_resume:
    check("Ctrl-R 走续聊", got.get("resume") is True, str(got))
else:
    check("Ctrl-R 对不支持续聊的给提示", "resume" not in got, str(got))

# 明确挑一个支持续聊的
res_entry = next(e for e in reg_now if e.can_resume and not e.hidden)
out, got, _ = run([res_entry.id.encode(), ENTER])
check(f"回车是普通启动（{res_entry.id}）", got.get("resume") is False, str(got))
out, got, _ = run([res_entry.id.encode(), b"\x12"])   # Ctrl-R
check(f"Ctrl-R 是续聊（{res_entry.id}）", got.get("resume") is True, str(got))
check("续聊时启动的还是同一个 agent",
      got.get("launched", ("",))[0] == res_entry.id, str(got.get("launched")))

say()
say("12) 置顶：Ctrl-T + pins.json")
pins_path = os.path.join(ag.STATE_DIR, "pins.json")
if os.path.exists(pins_path):
    os.unlink(pins_path)
out, got, _ = run([b"", ESC])                # Ctrl-T 然后退出
pins_now = ag.load_pins()
check("Ctrl-T 写进了 pins.json", len(pins_now) == 1, str(pins_now))
check("置顶项出现在列表里", "★" in strip(out))
out, got, _ = run([b"", ESC])                # 再来一次 = 取消
check("再按一次取消置顶", ag.load_pins() == [], str(ag.load_pins()))

say()
say("13) 帮助面板：?")
out, got, _ = run([b"?", ESC])
txt = strip(out)
check("? 打开帮助面板", "按键" in txt and "Ctrl-R" in txt, txt[-200:])
check("帮助里说明了排序规则", "半衰期" in txt)
check("帮助面板里不会误启动", "launched" not in got)

say()
say("14) 子命令：pin / unpin / last / stats")
def runcmd_err(args):
    """跟 runcmd 一样，但把 stderr 也返回 —— 用于检查提示信息。"""
    buf, err = io.StringIO(), io.StringIO()
    saved = ag.sys.stdout, ag.sys.stderr, ag.sys.argv
    ag.sys.stdout, ag.sys.stderr = buf, err
    ag.sys.argv = ["ag", *args]
    try:
        rc = ag.main(ag.sys.argv)
    finally:
        ag.sys.stdout, ag.sys.stderr, ag.sys.argv = saved
    return rc, buf.getvalue(), err.getvalue()


def runcmd(args, expect_rc=None):
    buf, err = io.StringIO(), io.StringIO()
    saved = ag.sys.stdout, ag.sys.stderr, ag.sys.argv
    ag.sys.stdout, ag.sys.stderr = buf, err
    ag.sys.argv = ["ag", *args]
    try:
        rc = ag.main(ag.sys.argv)
    finally:
        ag.sys.stdout, ag.sys.stderr = saved[0], saved[1]
        ag.sys.argv = saved[2]
    return rc, buf.getvalue()

rc, o = runcmd(["pin", "cc", "oc"])
check("ag pin 两条", rc == 0 and set(ag.load_pins()) == {"cc", "oc"}, str(ag.load_pins()))
rc, o = runcmd(["pin", "nope"])
check("ag pin 不存在的会跳过而不是崩", rc == 0)
rc, o = runcmd(["pin"])
check("ag pin 无参数 = 列出", "★" in o and "cc" in o)
rc, o = runcmd(["unpin", "oc"])
check("ag unpin", rc == 0 and ag.load_pins() == ["cc"], str(ag.load_pins()))

# 造一条使用记录，验证 ag last 认得出来
with open(ag.USAGE, "a", encoding="utf-8") as f:
    for eid in ("cc", "goose"):
        f.write(json.dumps({"t": int(time.time()), "id": eid,
                            "cwd": "/tmp", "resumed": False}) + "\n")
rc, o = runcmd(["last"])
check("ag last 认最后一条记录（不是时间戳最大的）",
      "goose" in o, o.strip()[:100])

rc, o = runcmd(["stats"])
check("ag stats 出表格", rc == 0 and "使用统计" in o and "goose" in o)
rc, o = runcmd(["stats", "--history"])
check("ag stats --history 出时间线", rc == 0 and "最近的启动" in o)

say()
say("15) 批量升级：命令提取与执行")
say("  · 包名提取")
for cmd, want in [("npm i -g @scope/pkg@latest", "@scope/pkg"),
                  ("npm install -g oh-my-codex", "oh-my-codex"),
                  ("npm i -g openclaw@latest", "openclaw"),
                  ("curl -fsSL https://x.sh | bash", None),
                  ("echo npm i -g plain", "plain")]:
    got_pkg = ag.npm_package(cmd)
    check(f"npm_package({cmd[:34]}…) → {want}", got_pkg == want, str(got_pkg))
check("brew_package 提取", ag.brew_package("brew install can1357/tap/omp") == "can1357/tap/omp",
      str(ag.brew_package("brew install can1357/tap/omp")))
check("brew_package 对 curl 返回 None", ag.brew_package("curl x | sh") is None)

say("  · update 缺省回退到 install")
e_fb = ag.Entry(dict(id="fb", cmd="echo", install="echo from-install"))
e_up = ag.Entry(dict(id="up", cmd="echo", install="echo from-install", update="echo from-update"))
check("没写 update 就用 install", ag.update_command(e_fb) == "echo from-install")
check("写了 update 就用 update", ag.update_command(e_up) == "echo from-update")

say("  · 真的执行（沙箱注册表，全是 echo，不动真实环境）")
UPD_DIR = tempfile.mkdtemp(prefix="ag-upd-")
UPD_REG = os.path.join(UPD_DIR, "registry.toml")
with open(UPD_REG, "w", encoding="utf-8") as f:
    f.write('''
[[agent]]
id = "g1"
name = "成功的"
cmd = "echo"
update = "echo UPDATED-g1"

[[agent]]
id = "g2"
name = "靠 install 回退"
cmd = "echo"
install = "echo UPDATED-g2"

[[agent]]
id = "b1"
name = "会失败的"
cmd = "echo"
update = "exit 3"

[[agent]]
id = "nocmd"
name = "没有升级命令"
cmd = "echo"
''')

saved_reg = ag.REGISTRY
ag.REGISTRY = UPD_REG
try:
    rc, o = runcmd(["update", "--dry-run"])
    check("--dry-run 只列不跑", rc == 0 and "UPDATED-g1" in o and "没真跑" in o)
    check("--dry-run 不碰没有升级命令的条目", "nocmd" not in o)

    rc, o = runcmd(["update", "g1"])
    check("指定 id 能升级", rc == 0 and "UPDATED-g1" in o)
    check("没有升级命令的会报错", runcmd(["update", "nocmd"])[0] != 0)

    rc, o = runcmd(["update", "--all"])
    check("--all 跑全部，失败的让退出码非 0", rc == 1, str(rc))
    check("成功的都跑了", "UPDATED-g1" in o and "UPDATED-g2" in o)
    check("失败的有单独汇报", "失败 1 条" in o and "b1" in o)

    # 非交互且没给 --all 时必须拦住，否则脚本里一句 ag update 就把全机器刷了
    saved_stdin = ag.sys.stdin
    ag.sys.stdin = io.StringIO()      # 没有 isatty
    try:
        rc, o = runcmd(["update"])
    finally:
        ag.sys.stdin = saved_stdin
    check("非交互不给 --all 就拒绝执行", rc != 0, str(rc))

    # outdated 的包名映射：拿假数据走一遍分支，不真跑 npm
    rc, o = runcmd(["outdated", "--json"])
    check("outdated --json 输出合法 JSON", rc == 0 and json.loads(o) is not None)
finally:
    ag.REGISTRY = saved_reg
    shutil.rmtree(UPD_DIR, ignore_errors=True)

say()
say("16) 会话搜索与交接")
SESS_DIR = tempfile.mkdtemp(prefix="ag-sess-")

def w(rel, lines):
    full = os.path.join(SESS_DIR, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        for l in lines:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    return full

# 三种真实格式的迷你复刻
CLAUDE = [
    {"type": "queue-operation", "timestamp": "2026-09-01T10:00:00Z",
     "content": "🚀 ~ % npm test │ ◇ Phase: running"},
    {"type": "user", "cwd": "/Users/me/proj-a", "timestamp": "2026-09-01T10:00:05Z",
     "message": {"role": "user",
                 "content": [{"type": "text", "text": "<system-reminder>ignored</system-reminder>"}]}},
    {"type": "user", "cwd": "/Users/me/proj-a", "timestamp": "2026-09-01T10:00:09Z",
     "message": {"role": "user",
                 "content": [{"type": "text", "text": "帮我修复登录页的样式问题"}]}},
    {"type": "assistant", "timestamp": "2026-09-01T10:00:20Z",
     "message": {"role": "assistant",
                 "content": [{"type": "text", "text": "先看一下 LoginPage 组件的样式定义"}]}},
]
CODEX = [
    {"type": "session_meta", "payload": {"cwd": "/Users/me/proj-b",
                                         "session_id": "abc"},
     "timestamp": "2026-09-02T11:00:00Z"},
    {"type": "response_item", "payload": {"role": "user",
                                          "content": [{"type": "text", "text": "给这个接口加上重试"}]}},
    {"type": "response_item", "payload": {"role": "assistant",
                                          "content": [{"type": "text", "text": "用指数退避实现"}]}},
]
JCODE = [{"id": "session_x", "title": None, "working_dir": "/Users/me/proj-c",
          "created_at": "2026-09-03T12:00:00Z",
          "messages": [
              {"role": "user", "content": [{"type": "text", "text": "数据库迁移脚本写一下"}]},
              {"role": "assistant", "content": [{"type": "text", "text": "用 alembic 生成"}]},
          ]}]

w("cc/s1.jsonl", CLAUDE)
w("cc/subagents/s2.jsonl", CLAUDE)          # 子会话，应被过滤
w("codex/s3.jsonl", CODEX)
w("j/s4.json", JCODE)

REG2 = os.path.join(SESS_DIR, "registry.toml")
with open(REG2, "w", encoding="utf-8") as fh:
    fh.write(f'''
[[agent]]
id = "cc"
name = "Claude Code"
cmd = "echo"
resume = ["--resume"]
sessions = "{SESS_DIR}/cc"

[[agent]]
id = "codex"
name = "Codex"
cmd = "echo"
resume = ["resume"]
sessions = "{SESS_DIR}/codex"

[[agent]]
id = "j"
name = "JCode"
cmd = "echo"
sessions = "{SESS_DIR}/j"
''')

saved_reg = ag.REGISTRY
ag.REGISTRY = REG2
try:
    ents = ag.load_registry()

    say("  · session_files 会过滤子会话")
    cc = ag.find_entry(ents, "cc")
    files = ag.session_files(cc)
    check("子会话被排除", len(files) == 1 and "subagents" not in files[0], str(files))

    say("  · 三种格式都能提取 cwd / 标题")
    m1 = ag.session_meta(os.path.join(SESS_DIR, "cc/s1.jsonl"))
    check("claude: cwd", m1["cwd"] == "/Users/me/proj-a", str(m1))
    check("claude: 取到用户说的话（跳过 system-reminder 和终端回显）",
          m1["title"] == "帮我修复登录页的样式问题", repr(m1["title"]))
    m2 = ag.session_meta(os.path.join(SESS_DIR, "codex/s3.jsonl"))
    check("codex: cwd 在 payload 里也能拿到", m2["cwd"] == "/Users/me/proj-b", str(m2))
    check("codex: 标题", m2["title"] == "给这个接口加上重试", repr(m2["title"]))
    m3 = ag.session_meta(os.path.join(SESS_DIR, "j/s4.json"))
    check("jcode: 读 working_dir", m3["cwd"] == "/Users/me/proj-c", str(m3))
    check("jcode: 从 messages 里挖出用户消息",
          m3["title"] == "数据库迁移脚本写一下", repr(m3["title"]))

    say("  · _prose 挡得住噪音")
    for bad in ["<task-notification>x</task-notification>", "🚀 ~ % openclaw update │ ◇",
                "│ col1 │ col2 │", "```python", "$ ls -la"]:
        check(f"拒绝 {bad[:24]!r}", ag._prose(bad) is None, repr(ag._prose(bad)))
    check("放行正常中文", ag._prose("帮我修复登录页的样式问题") is not None)
    check("过短的拒绝", ag._prose("ok") is None)

    say("  · session_tail 合并连续同角色")
    tail = ag.session_tail(os.path.join(SESS_DIR, "cc/s1.jsonl"))
    roles = [r for r, _ in tail]
    check("角色交替，无连续重复", all(roles[i] != roles[i + 1] for i in range(len(roles) - 1)),
          str(roles))
    check("抓到内容", any("登录页" in t for _, t in tail), str(tail))

    say("  · ag search")
    rc, o = runcmd(["search", "登录页"])
    check("搜得到", rc == 0 and "命中" in o, o[:200])
    check("显示了 cwd", "proj-a" in o, o[:300])
    rc, o = runcmd(["search", "绝对不存在的词zzz"])
    check("搜不到时明确说没搜到", rc == 0 and "没搜到" in o, o[:200])
    rc, o = runcmd(["search"])
    check("不给关键词会报用法", rc != 0)

    say("  · ag handoff")
    rc, o = runcmd(["handoff", "cc", "--print"])
    check("生成交接 prompt", rc == 0 and "交接" in o and "Claude Code" in o, o[:200])
    check("带上了工作目录", "proj-a" in o)
    check("带上了对话内容", "登录页" in o)
    check("明确要求接着做、别复述", "不要复述" in o)
    rc, o = runcmd(["handoff", "codex", "--print"])
    check("从 codex 也能交接", rc == 0 and "重试" in o, o[:200])
    rc, o = runcmd(["handoff", "nosuch", "--print"])
    check("不存在的 agent 报错", rc != 0)

    # 没登记 sessions 的 agent 要给出明确提示，而不是静默失败
    with open(REG2, "a", encoding="utf-8") as fh:
        fh.write('''
[[agent]]
id = "nosess"
name = "没登记会话目录"
cmd = "echo"
''')
    ents2 = ag.load_registry()
    ag.REGISTRY = REG2
    rc, o = runcmd(["handoff", "nosess", "--print"])
    check("没登记 sessions 时明确报错", rc != 0, o[:120])

    say("  · 最近的会话没内容时，自动往前找")
    # 造一个「更新时间最新、但里面只有系统噪音」的会话
    import time as _t
    empty = w("cc/s9.jsonl", [
        {"type": "user", "cwd": "/Users/me/proj-a", "timestamp": "2026-09-09T10:00:00Z",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "# AGENTS.md instructions\n\n<INSTRUCTIONS>\n"
                                       "每次开始任何任务前先读取记忆库</INSTRUCTIONS>"}]}},
    ])
    os.utime(empty, (_t.time() + 100, _t.time() + 100))   # 保证它是最新的
    rc, o, e = runcmd_err(["handoff", "cc", "--print"])
    check("跳过了没内容的会话（提示走 stderr，stdout 保持干净）",
          rc == 0 and "跳过" in e, repr(e))
    check("stdout 里只有 prompt 本身", "跳过" not in o, o[:120])
    check("拿到的是有对话的那个", "登录页" in o, o[:300])
finally:
    ag.REGISTRY = saved_reg
    shutil.rmtree(SESS_DIR, ignore_errors=True)

say()
say("17) 一次开多个（Tab 多选 + tmux）")
TAB = b"\t"

say("  · Tab 多选，Enter 一次全开")
out, got, _ = run([TAB, TAB, ENTER])
check("选了 2 个就交给 launch_many", "many" in got and len(got["many"]) == 2,
      str(got.get("many")))
out, got, _ = run([TAB, ENTER])
check("只勾 1 个时走单开", "launched" in got and "many" not in got, str(got))
check("勾选后光标会往下走（方便连勾）",
      strip(out).count("▣") >= 1, strip(out)[-300:])

say("  · 再按一次 Tab 取消选中")
# Tab 勾上第 1 个（光标自动下移）-> ↑ 回到第 1 个 -> Tab 取消 -> Enter
out, got, _ = run([TAB, b"\x1b[A", TAB, ENTER])
check("同一个再勾一次是取消，于是走单开", "launched" in got and "many" not in got,
      str(got))

say("  · build_tmux_plan")
reg_t = ag.load_registry()
three = [ag.find_entry(reg_t, i) for i in ("cc", "oc", "goose")]
plan = ag.build_tmux_plan(three, "ag", "windows", resume=False, fresh=True)
check("默认布局是宫格（不是窗口）",
      ag.build_tmux_plan(three, "ag")[0][0][1] == "new-session" and
      ag.build_tmux_plan(three, "ag")[1][0][1] == "split-window",
      str([p[0][1] for p in ag.build_tmux_plan(three, "ag")]))
check("窗口模式：第一个 new-session，其余 new-window",
      plan[0][0][1] == "new-session" and plan[1][0][1] == "new-window"
      and plan[2][0][1] == "new-window", str([p[0][1] for p in plan]))
check("窗口名用了短名", [p[0][p[0].index("-n") + 1] for p in plan] == ["cc", "oc", "goose"])
check("每条都带 -c 工作目录", all("-c" in p[0] for p in plan))
check("命令是整条一个参数（过 shell，带空格也不散）",
      plan[0][0][-1] == "claude", plan[0][0][-1])

plan2 = ag.build_tmux_plan(three, "ag", "grid", resume=False, fresh=True)
check("宫格：用 split-window",
      plan2[1][0][1] == "split-window" and plan2[2][0][1] == "split-window",
      str([p[0][1] for p in plan2]))
check("宫格最后会 tiled 排一下",
      any(p[0][1:3] == ["select-layout", "-t"] and "tiled" in p[0] for p in plan2),
      str([p[0][1:3] for p in plan2]))
check("--panes 是 grid 的老写法，行为一致",
      [p[0][1] for p in ag.build_tmux_plan(three, "ag", "panes")] ==
      [p[0][1] for p in plan2])

plan3 = ag.build_tmux_plan([ag.find_entry(reg_t, "cc")], "ag",
                           "windows", resume=True, fresh=False)
check("续聊模式带上 resume 参数", plan3[0][0][-1] == "claude --resume",
      plan3[0][0][-1])
check("会话已存在时用 new-window", plan3[0][0][1] == "new-window", plan3[0][0][1])

sp_entry = ag.Entry(dict(id="sp", cmd="echo", args=["a b", "c d"]))
sp_plan = ag.build_tmux_plan([sp_entry], "ag")[0][0][-1]
check("带空格的参数被正确引用", sp_plan == "echo 'a b' 'c d'", sp_plan)
check("引用后能还原", shlex.split(sp_plan) == ["echo", "a b", "c d"])

say("  · cmd_team")
rc, o = runcmd(["team", "--dry-run", "cc", "oc"])
check("--dry-run 不真跑", rc == 0 and "没真跑" in o, o[:160])
check("dry-run 里能看到两个短名", "cc" in o and "oc" in o)
check("dry-run 里能看到真命令", "claude" in o and "opencode" in o)
rc, o = runcmd(["team", "--dry-run", "cc", "oc"])
check("默认就是宫格", "宫格" in o, o[:100])
rc, o = runcmd(["team", "--dry-run", "--plan" if False else "--windows", "cc", "oc"])
check("--windows 走老路", "窗口" in o and "宫格" not in o, o[:120])
rc, o = runcmd(["team", "nosuch"])
check("不存在的 id 报错", rc != 0)

say("  · tmux 一条都没跑成时不能谎报成功")
class _FailProc:
    """假的 subprocess 模块：tmux 一律失败。"""
    DEVNULL = -3
    class SubprocessError(Exception): pass
    @staticmethod
    def run(*a, **k):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")
ag.shutil = types.SimpleNamespace(
    which=lambda c: "/usr/local/bin/" + c if c == "tmux" else None,
    get_terminal_size=lambda d=(100, 24): os.terminal_size((100, 28)))
ag.subprocess = _FailProc
try:
    ag.launch_many = _real_launch_many      # 这条要测真实现，不能用桩
    rc, o = runcmd(["team", "cc", "oc"])
    check("全失败时返回非 0", rc != 0, str(rc))
    check("全失败时不说「✓」", "✓" not in o.split("tmux 一条")[0], o[:200])
    check("全失败时给出排查提示", "tmux new -s test" in o, o[:300])

    say("  · tmux 报的错要透出来，不能吞掉")
    class _FailProcErr(_FailProc):
        @staticmethod
        def run(*a, **k):
            return types.SimpleNamespace(
                returncode=1, stdout="",
                stderr="create window failed: fork failed: Operation not permitted")
    ag.subprocess = _FailProcErr
    ag.launch_many = _real_launch_many
    rc, o = runcmd(["team", "cc", "oc"])
    check("把 tmux 的 stderr 打出来了", "fork failed" in o, o[:300])
    check("认出是权限问题而不是 tmux 坏了",
          "权限" in o or "沙箱" in o, o[:300])
finally:
    ag.shutil = _real_shutil
    ag.subprocess = _real_subprocess
    ag.launch_many = _real_launch_many

say()
say("18) ag ps / ag kill（假 tmux）")

class FakeTmux:
    """一个能记事的假 tmux：列表可读，kill 会真的从列表里删掉。"""
    DEVNULL = -3
    class SubprocessError(Exception): pass

    def __init__(self):
        self.sessions = {"ag": 3, "work": 1}
        self.windows = [
            ["ag", "0", "cc", "0", "claude", "0", "1800000000", "@1"],
            ["ag", "1", "oc", "1", "opencode", "0", "1800000100", "@2"],
            ["ag", "2", "goose", "0", "goose", "0", "1800000200", "@3"],
            ["work", "0", "vim", "1", "vim", "0", "1800000300", "@4"],
        ]
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        cmd = argv[1] if len(argv) > 1 else ""
        if cmd == "list-sessions":
            body = "".join(f"{n}\t{c}\t1800000000\t0\n"
                           for n, c in self.sessions.items())
            return types.SimpleNamespace(returncode=0, stdout=body, stderr="")
        if cmd == "list-windows":
            tgt = argv[argv.index("-t") + 1] if "-t" in argv else None
            rows = [w for w in self.windows if tgt is None or w[0] == tgt]
            return types.SimpleNamespace(
                returncode=0 if rows else 1,
                stdout="".join("\t".join(w) + "\n" for w in rows), stderr="")
        if cmd == "kill-window":
            t = argv[argv.index("-t") + 1]
            sess, _, idx = t.rpartition(":")
            before = len(self.windows)
            self.windows = [w for w in self.windows
                            if not (w[0] == sess and w[1] == idx)]
            if len(self.windows) == before:
                return types.SimpleNamespace(returncode=1, stdout="",
                                             stderr="can't find window")
            if not any(w[0] == sess for w in self.windows):
                self.sessions.pop(sess, None)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd == "kill-session":
            t = argv[argv.index("-t") + 1]
            if t not in self.sessions:
                return types.SimpleNamespace(returncode=1, stdout="",
                                             stderr="can't find session")
            self.sessions.pop(t)
            self.windows = [w for w in self.windows if w[0] != t]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

fake = FakeTmux()
saved_shutil, saved_sub = ag.shutil, ag.subprocess
saved_tmux_env = os.environ.pop("TMUX", None)
ag.shutil = types.SimpleNamespace(
    which=lambda c: "/usr/local/bin/tmux" if c == "tmux" else None,
    get_terminal_size=lambda d=(100, 24): os.terminal_size((100, 28)))
ag.subprocess = fake
try:
    rc, o = runcmd(["ps"])
    check("ag ps 列出正在跑的", rc == 0 and "cc" in o and "goose" in o, o[:200])
    check("ag ps 认得出不认识的窗口", "vim" in o, o[:300])
    check("不在 tmux 里时不乱标「你在这」", "你在这" not in o, o[:300])

    rc, o = runcmd(["kill", "cc"])
    check("关掉单个窗口", rc == 0 and "关掉 1 个" in o, o[:150])
    check("cc 真的从列表里没了",
          not any(w[2] == "cc" for w in fake.windows), str(fake.windows))
    check("别的窗口没被误伤", any(w[2] == "oc" for w in fake.windows))

    rc, o = runcmd(["kill", "nosuch"])
    check("关不存在的会报错并提示 ag ps", rc != 0 and "ag ps" in o, o[:200])

    rc, o = runcmd(["kill", "oc", "goose"])
    check("一次关多个", rc == 0 and "关掉 2 个" in o, o[:150])
    check("窗口关光了会话自己也收了", "ag" not in fake.sessions, str(fake.sessions))
    check("跟用户说了会话收了", "自己也收了" in o, o[:200])

    fake.sessions.update({"ag": 2, "work": 1})
    fake.windows += [["ag", "0", "cc", "0", "claude", "0", "1800000000", "@9"],
                     ["ag", "1", "oc", "0", "opencode", "0", "1800000001", "@10"],
                     ["work", "0", "vim", "1", "vim", "0", "1800000002", "@11"]]
    rc, o = runcmd(["kill", "--all", "--session=work", "--force"])
    check("--all 关掉指定会话", rc == 0 and "work" not in fake.sessions, str(fake.sessions))
    check("--all 没误伤别的会话", "ag" in fake.sessions, str(fake.sessions))

    rc, o, e = runcmd_err(["kill", "--all", "--session=nosuch", "--force"])
    check("--all 指定不存在的会话时明确报错",
          rc != 0 and "没有叫" in e, (o + e)[:200])

    fake.sessions.clear(); fake.windows = []
    rc, o, e = runcmd_err(["kill", "cc", "--session=nosuch"])
    check("一条会话都没有时点名也要明确报错",
          rc != 0 and "不存在" in e, (o + e)[:200])
    fake.sessions["ag"] = 1
    fake.windows = [["ag", "0", "cc", "0", "claude", "0", "1800000000", "@1"]]

    # 全没了的时候要友好，不能崩
    fake.sessions.clear(); fake.windows = []
    rc, o = runcmd(["ps"])
    check("一个会话都没有时 ps 不崩", rc == 0 and "没有 tmux 会话" in o, o[:150])
    rc, o = runcmd(["kill", "cc"])
    check("一个会话都没有时 kill 不崩", rc == 0 and "没什么可关" in o, o[:150])
finally:
    ag.shutil, ag.subprocess = saved_shutil, saved_sub
    if saved_tmux_env is not None:
        os.environ["TMUX"] = saved_tmux_env

say()
say("19) 分组显示与 @ 过滤")

say("  · group 字段")
ge = ag.Entry(dict(id="x", cmd="echo", group="我的组", desc="d"))
check("group 读得出来", ge.group == "我的组")
check("不填 group 时是空串", ag.Entry(dict(id="y", cmd="echo")).group == "")
blk = ag.render_toml(ge)
check("render_toml 写出 group", 'group = "我的组"' in blk, blk)
open("/tmp/gg.toml", "w").write("[[agent]]\n" + blk)
check("往返无损", ag.load_registry("/tmp/gg.toml")[0].group == "我的组")

say("  · parse_query")
for q, want in [("@openclaw", ("openclaw", "")),
                ("@openclaw ceo", ("openclaw", "ceo")),
                ("@Hermes", ("hermes", "")),
                ("ceo", (None, "ceo")),
                ("", (None, "")),
                ("@", ("", "")),
                ("@a b c", ("a", "b c"))]:
    got = ag.parse_query(q)
    check(f"{q!r} → {want}", got == want, str(got))

say("  · grouped 排序")
def mk(i, g, c="echo"):
    return ag.Entry(dict(id=i, cmd=c, group=g))
items = [mk("a1", "甲"), mk("a2", "甲"), mk("b1", "乙"), mk("z9", "")]
NOW2 = 1_800_000_000.0
g1 = ag.grouped(items, {"a2": [NOW2 - 60]}, [], entries=items)
check("组名都在", [g for g, _ in g1] == ["甲", "乙", "其它"], str([g for g, _ in g1]))
check("其它永远垫底", g1[-1][0] == "其它")
check("用过的组浮到前面（甲里有 a2 常用）", g1[0][0] == "甲", str(g1[0][0]))
check("组内用过的排前面", [e.id for e in g1[0][1]] == ["a2", "a1"],
      str([e.id for e in g1[0][1]]))

g2 = ag.grouped(items, {}, ["b1"], entries=items)
check("有置顶的组排最前", g2[0][0] == "乙", str([g for g, _ in g2]))
check("置顶的组内也排第一", g2[0][1][0].id == "b1")

g3 = ag.grouped(items, {}, [], entries=items)
check("都没有记录时按注册表顺序", [g for g, _ in g3] == ["甲", "乙", "其它"],
      str([g for g, _ in g3]))
check("组内也按注册表顺序", [e.id for e in g3[0][1]] == ["a1", "a2"])

say("  · 选择器：空查询按组显示，一打字就平铺")
out, got, _ = run([ESC])
txt = last_frame(out)
check("空查询有组标题", "原厂 CLI" in txt, txt[:300])
check("组标题带横线分隔", "─" in txt.split("原厂 CLI")[1][:6], repr(txt.split("原厂 CLI")[1][:10]))
# 别写成「某几个组标题都得在」—— 那取决于终端高度，太脆。
# 真正要保证的是排版规矩：窗口最后一行不能是个孤零零的组标题。
# 纯分隔线（整行都是 ─）不算内容，先滤掉，再掐头去尾
body = [l for l in txt.splitlines()
        if l.strip() and set(l.strip()) != {"─"}]
body = body[2:-2]                      # 去掉头部两行和底部两行
if body:
    check("窗口末尾不是孤立的组标题（上面没内容）",
          "─" not in body[-1] or "●" in body[-1], repr(body[-1][:70]))
    check("开头也不是孤立条目（组标题被滚掉了）",
          "●" not in body[0] or "─" in body[0], repr(body[0][:70]))
out, got, _ = run([b"c", b"c", ESC])
check("打了关键词就不显示组标题", "原厂 CLI" not in last_frame(out), last_frame(out)[:300])

say("  · 选择器：@ 过滤")
out, got, _ = run([b"@", b"h", b"e", b"r", ESC])
txt = last_frame(out)
check("@her 只剩 Hermes 组", "Hermes" in txt and "原厂 CLI" not in txt, txt[:300])
check("@ 过滤时计数正确", "3/29" in txt, txt[:200])
out, got, _ = run([b"@", b"n", b"o", b"s", b"u", b"c", b"h", ESC])
check("不存在的组给空态而不是崩", "没有匹配" in strip(out), strip(out)[:300])

out, got, _ = run([b"@", b"o", b"p", b"e", b"n", b"c", b"l", b"a", b"w",
                   b" ", b"c", b"e", b"o", ENTER])
check("@组 + 关键词能定位到具体条目", got.get("launched", ("",))[0] == "ot-ceo",
      str(got.get("launched")))

say("  · 跨组多选")
out, got, _ = run([TAB, b"\x1b[B", b"\x1b[B", b"\x1b[B", b"\x1b[B", b"\x1b[B",
                   b"\x1b[B", b"\x1b[B", b"\x1b[B", TAB, ENTER])
ids_picked = got.get("many", [])
check("能跨组选两个", len(ids_picked) == 2, str(ids_picked))

say("  · 导航：上下键必须严格按屏幕顺序走")
# 这个 bug 真发生过：cursor 索引的是「命中顺序」，屏幕画的是「分组顺序」，
# 两边分叉之后高亮和窗口各走各的，按上下键看起来就是在乱跳。
reg_n = [e for e in ag.load_registry() if not e.hidden]
hits_n = ag.order_hits(ag.fuzzy(reg_n, ""), ag.load_usage(), ag.load_pins(),
                       query="", entries=reg_n)
EXPECT = [e.id for _, es in ag.grouped([e for e, _ in hits_n], ag.load_usage(),
                                       ag.load_pins(), entries=reg_n) for e in es]

def press(key, times, prefix=()):
    """连按同一个键，返回每步的高亮项和当时屏幕上的可见项。"""
    keys, steps = list(prefix), []
    for _ in range(times):
        keys.append(key)
        lines = frames_of(run(list(keys) + [ESC])[0])[-1].split("\r\n")
        hl = next((strip(l).split()[1] for l in lines
                   if l.startswith("\033[7m")), None)
        vis = {strip(l).split()[1] for l in lines
               if strip(l).strip().startswith(("●", "○", "★", "▣"))}
        steps.append((hl, vis))
    return steps

down = press(b"\x1b[B", len(EXPECT) + 6)
down_ids = [h for h, _ in down]
want_down = EXPECT[1:] + [EXPECT[-1]] * 7
check("↓ 的路径 == 屏幕顺序（一条不差）", down_ids == want_down,
      next((f"第{i+1}步 {a}≠{b}" for i, (a, b) in enumerate(zip(down_ids, want_down))
            if a != b), f"长度 {len(down_ids)} vs {len(want_down)}"))
check("↓ 到底后不越界（停在最后一条）", down_ids[-1] == EXPECT[-1], str(down_ids[-1]))
bad_vis = [f"第{i+1}步 {h}" for i, (h, vis) in enumerate(down) if h and h not in vis]
check("一路 ↓ 高亮从没跑出可视区", not bad_vis, ", ".join(bad_vis))

up = press(b"\x1b[A", len(EXPECT) + 6,
           prefix=[b"\x1b[B"] * (len(EXPECT) + 6))
up_ids = [h for h, _ in up]
idx = [EXPECT.index(x) for x in up_ids if x]
check("↑ 最终回到第一条", up_ids[-1] == EXPECT[0], str(up_ids[-1]))
check("↑ 是单调往回走", idx == sorted(idx, reverse=True), str(idx[:12]))
bad_vis2 = [f"第{i+1}步 {h}" for i, (h, vis) in enumerate(up) if h and h not in vis]
check("一路 ↑ 高亮也没跑出可视区", not bad_vis2, ", ".join(bad_vis2))

say("  · 打字后光标回第一条")
f = frames_of(run([b"\x1b[B", b"\x1b[B", b"\x1b[B", b"c", b"c", ESC])[0])[-1]
got_c = next((strip(l).split()[1] for l in f.split("\r\n")
              if l.startswith("\033[7m")), None)
check("打了关键词后高亮在首条", got_c == "cc", str(got_c))

say("  · 注册表分组完整性")
reg_g = ag.load_registry()
groups_seen = {}
for e in reg_g:
    groups_seen.setdefault(e.group or ag.OTHER_GROUP, []).append(e.id)
say("  · " + " | ".join(f"{g}: {len(v)}" for g, v in groups_seen.items()))
check("示例注册表每条都有 group", all(e.group for e in reg_g),
      str([e.id for e in reg_g if not e.group]))
check("分组数在合理范围（2~8 组）", 2 <= len(groups_seen) <= 8, str(len(groups_seen)))
check("没有空组", all(v for v in groups_seen.values()))

say()
say("20) 宫格布局")
say("  · auto_grid 的形状")
for n, want in [(1, (1, 1)), (2, (2, 1)), (3, (3, 1)), (4, (2, 2)),
                (5, (3, 2)), (6, (3, 2)), (7, (4, 2)), (8, (4, 2)),
                (9, (3, 3)), (12, (4, 3)), (16, (4, 4))]:
    got_g = ag.auto_grid(n)
    check(f"{n} 个 → {want[0]}×{want[1]}", got_g == want, str(got_g))
bad_tall = [n for n in range(1, 25) if ag.auto_grid(n)[1] > ag.auto_grid(n)[0]]
check("永远不给「竖着比横着长」的形状", not bad_tall, str(bad_tall))
check("格子数永远够（不会装不下）",
      all(ag.auto_grid(n)[0] * ag.auto_grid(n)[1] >= n for n in range(1, 40)))
check("2 个是左右并排（不是上下叠）", ag.auto_grid(2) == (2, 1))
check("--cols 能强制列数", ag.auto_grid(7, cols=7) == (7, 1), str(ag.auto_grid(7, cols=7)))

say("  · parse_grid")
for spec, want in [("3x2", (3, 2)), ("3X2", (3, 2)), ("2*2", (2, 2)),
                   ("2×2", (2, 2)), (" 3 x 2 ", (3, 2)),
                   ("3x", None), ("x2", None), ("0x2", None), ("abc", None)]:
    check(f"{spec!r} → {want}", ag.parse_grid(spec) == want, str(ag.parse_grid(spec)))

say("  · 宫格的 tmux 命令")
reg_g2 = ag.load_registry()
four = [ag.find_entry(reg_g2, i) for i in ("cc", "oc", "goose", "codex")]
pl = ag.build_tmux_plan(four, "ag", "grid", grid=(2, 2))
kinds = [p[0][1] for p in pl if p[1] is not None]
check("第一格 new-session，其余 split-window", kinds[0] == "new-session"
      and all(k == "split-window" for k in kinds[1:]), str(kinds))
check("2×2 里是 1 次横切 + 2 次竖切",
      sum(1 for p in pl if "-h" in p[0]) == 1 and
      sum(1 for p in pl if "-v" in p[0]) == 2,
      str([p[0] for p in pl]))
check("每个 pane 都用 -P -F 把 id 打回来",
      all("-P" in p[0] and "#{pane_id}" in p[0] for p in pl if p[1] is not None))
targets = [p[2] for p in pl if p[1] is not None]
check("分割目标指向「前面捕获到的 pane」（@k 形式）",
      targets[0] is None and all(t.startswith("@") for t in targets[1:]),
      str(targets))
check("先 tiled 排一下再设边框",
      [p[0][1] for p in pl if p[1] is None].count("select-layout") == 1 and
      any("pane-border-status" in p[0] for p in pl))
check("3×2 会切成 2 横 + 3 竖",
      sum(1 for p in ag.build_tmux_plan(
          four + [ag.find_entry(reg_g2, "kimi"), ag.find_entry(reg_g2, "gemini")],
          "ag", "grid", grid=(3, 2)) if "-h" in p[0]) == 2)

pl_w = ag.build_tmux_plan(four, "ag", "windows")
check("--windows 仍然是 new-window 那套",
      pl_w[0][0][1] == "new-session" and pl_w[1][0][1] == "new-window",
      str([p[0][1] for p in pl_w]))
check("窗口模式不带 -P", all("-P" not in p[0] for p in pl_w))

say("  · 格子太小要提醒")
saved_sh, saved_sub = ag.shutil, ag.subprocess
class OkProc:
    DEVNULL = -3
    class SubprocessError(Exception): pass
    calls = []
    @classmethod
    def run(cls, argv, **kw):
        cls.calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="%9", stderr="")
ag.shutil = types.SimpleNamespace(
    which=lambda c: "/usr/local/bin/tmux",
    get_terminal_size=lambda d=(100, 30): os.terminal_size((80, 24)))
ag.subprocess = OkProc
ag.launch_many = _real_launch_many
# 假装在 tmux 里 —— 否则真实分支会去 os.execvp 真 tmux
saved_tmux2 = os.environ.get("TMUX")
os.environ["TMUX"] = "/tmp/fake,1,0"
try:
    buf = io.StringIO()
    saved_out = ag.sys.stdout
    ag.sys.stdout = buf
    try:
        ag.launch_many(four, layout="grid", session="zz")
    finally:
        ag.sys.stdout = saved_out
    check("小终端里会提醒格子挤", "可能挤" in buf.getvalue(), buf.getvalue()[:200])
    check("提醒里给了 --windows 的出路", "--windows" in buf.getvalue())
finally:
    ag.shutil, ag.subprocess = saved_sh, saved_sub
    if saved_tmux2 is None:
        os.environ.pop("TMUX", None)
    else:
        os.environ["TMUX"] = saved_tmux2

say()
say("=" * 64)
if fail:
    say(f"❌ {len(fail)} 项失败： {fail}")
    sys.exit(1)
shutil.rmtree(_TMPDIR, ignore_errors=True)
say("✅ 全部通过")
