"""ag 的假终端测试：不需要真 pty，直接喂按键序列，检查渲染与启动目标。

跑法：
    python3 tests/test_ag.py

夹具用仓库里的 registry.example.toml，所以在任何机器上都能跑，不需要事先装好 agent。
装了全套的可以加 AG_EXPECT_ALL_INSTALLED=1，额外校验每个可执行文件都解析得到。

脚本会自己找 ag 主程序和夹具，顺序：
    ag    ： $AG_BIN → <仓库>/ag → ~/.local/bin/ag
    注册表： $AG_REGISTRY → <仓库>/registry.example.toml → ~/.agents/registry.example.toml
"""
import importlib.machinery, importlib.util, io, os, re, sys, types

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

FIXTURE = _first(os.environ.get("AG_REGISTRY"),
                 os.path.join(ROOT, "registry.example.toml"),
                 os.path.join(HOME, ".agents/registry.example.toml"),
                 os.path.join(HOME, ".agents/registry.toml"))
if not FIXTURE:
    sys.exit("找不到夹具注册表。设 AG_REGISTRY=/path/to/registry.toml")

REAL_OUT = sys.stdout
def say(*a, **k):
    print(*a, file=REAL_OUT, **k)

# 注册表必须在 import ag 之前设好（REGISTRY 是导入期读的）
os.environ["AG_REGISTRY"] = FIXTURE

loader = importlib.machinery.SourceFileLoader("agmod", AG_BIN)
spec = importlib.util.spec_from_loader("agmod", loader)
ag = importlib.util.module_from_spec(spec)
loader.exec_module(ag)

say(f"  ag   : {AG_BIN}")
say(f"  注册表: {FIXTURE}")
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
    ag.cmd_launch = lambda e, extra: (got.setdefault("launched", (e.id, extra)), 0)[1]
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
say("7) 注册表完整性")
ag.shutil = _real_shutil          # 用真的 which()，别被假终端骗了
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

say()
say("=" * 64)
if fail:
    say(f"❌ {len(fail)} 项失败： {fail}")
    sys.exit(1)
say("✅ 全部通过")
