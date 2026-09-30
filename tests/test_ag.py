"""ag 的假终端测试：不需要真 pty，直接喂按键序列，检查渲染与启动目标。

跑法：
    python3 tests/test_ag.py

夹具用仓库里的 registry.example.toml，所以在任何机器上都能跑，不需要事先装好 agent。
装了全套的可以加 AG_EXPECT_ALL_INSTALLED=1，额外校验每个可执行文件都解析得到。

脚本会自己找 ag 主程序和夹具，顺序：
    ag    ： $AG_BIN → <仓库>/ag → ~/.local/bin/ag
    注册表： $AG_REGISTRY → <仓库>/registry.example.toml → ~/.agents/registry.example.toml
"""
import importlib.machinery, importlib.util, io, json, os, re, shutil, sys, tempfile, time, types

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
    ag.cmd_launch = fake_launch
    try:
        rc = ag.main(ag.sys.argv)
    finally:
        ag.sys.stdout = REAL_OUT
    return buf.getvalue(), got, rc

strip = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
frames_of = lambda out: out.split("\033[H\033[2J")

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
say("=" * 64)
if fail:
    say(f"❌ {len(fail)} 项失败： {fail}")
    sys.exit(1)
shutil.rmtree(_TMPDIR, ignore_errors=True)
say("✅ 全部通过")
