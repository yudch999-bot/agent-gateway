#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 docs/demo.cast —— 不需要真终端，也不用录屏。

做法：拿 ag 真正的选择器渲染器跑一遍，把每一帧的输出连同时间戳记下来，
写成 asciinema cast v2 格式。所以录像里的画面和真实运行**逐字节一致**，
不是手搓的假动画。

    python3 docs/make-demo-cast.py

产物：
    docs/demo.cast       asciinema 录像，`asciinema play docs/demo.cast` 播放
"""

import collections
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AG_BIN = os.path.join(ROOT, "ag")
OUT = os.path.join(HERE, "demo.cast")

WIDTH, HEIGHT = 100, 28
PROMPT = "\033[32m➜\033[0m \033[36m~\033[0m $ "

# ---------------------------------------------------------------- 载入 ag

os.environ.setdefault("AG_REGISTRY", os.path.join(ROOT, "registry.example.toml"))

_loader = importlib.machinery.SourceFileLoader("agmod", AG_BIN)
_spec = importlib.util.spec_from_loader("agmod", _loader)
ag = importlib.util.module_from_spec(_spec)
_loader.exec_module(ag)


# ---------------------------------------------------------------- 假终端

class _FakeIn:
    def isatty(self): return True
    def fileno(self): return 0


class _FakeOut(io.StringIO):
    def isatty(self): return True


class _FakeTermios:
    TCSADRAIN = 1
    def tcgetattr(self, fd): return ["ORIG"]
    def tcsetattr(self, fd, when, attrs): pass


class _FakeTty:
    def setraw(self, fd): pass


_keys = collections.deque()
_buf = bytearray()
_stop = threading.Event()


def _read(fd, n=1):
    """阻塞式喂键：队列空了就等主线程投喂，模拟真人敲键的节奏。"""
    global _buf
    while not _buf:
        if _stop.is_set():
            return b""
        if _keys:
            _buf += _keys.popleft()
            continue
        time.sleep(0.005)
    out = bytes(_buf[:n]); del _buf[:n]
    return out


_real_os = ag.os


class _FakeOs:
    def __getattr__(self, k): return getattr(_real_os, k)
    def read(self, fd, n=1): return _read(fd, n)


ag.os = _FakeOs()
ag.termios = _FakeTermios()
ag.tty = _FakeTty()
ag.select = type(sys)("fakeselect")
ag.select.select = lambda *a, **k: ([0], [], [])
_shutil = type(sys)("fakeshutil")
_shutil.get_terminal_size = lambda d=(WIDTH, HEIGHT): os.terminal_size((WIDTH, HEIGHT))
_shutil.which = lambda c: "/usr/bin/" + c
ag.shutil = _shutil

_bufout = _FakeOut()
ag.sys.stdin = _FakeIn()
ag.sys.stdout = _bufout

# 让「启动」只打印那一行，不真的 exec
def _fake_launch(entry, extra):
    print(f"\033[32m▶\033[0m \033[1m{entry.name}\033[0m "
          f"\033[90m({entry.id})\033[0m  \033[2m{' '.join(entry.argv(extra))}\033[0m")
    sys.stdout.flush()
    return 0


ag.cmd_launch = _fake_launch


# ---------------------------------------------------------------- 录制

events = []          # (相对时间, 输出片段)
_last_len = 0


def emit(data, t):
    events.append((round(t, 3), data))


def drain(t):
    """把上一帧之后新产生的输出记下来。"""
    global _last_len
    s = _bufout.getvalue()
    if len(s) > _last_len:
        emit(s[_last_len:], t)
        _last_len = len(s)


ESC, DOWN, ENTER = b"\x1b", b"\x1b[B", b"\r"

# 剧本：(等多久, 投喂什么, 说明)
# 首帧由下面的轮询单独处理，不写在这儿，免得敲完 ag 到出画面之间空一大段。
SCRIPT = [
    (0.85, None,   "让人看清完整列表"),
    (0.40, DOWN,   "↓ 移动光标"),
    (0.38, DOWN,   "↓"),
    (0.38, DOWN,   "↓"),
    (0.55, "设".encode(),  "打中文「设」—— 整表收敛到 1 条"),
    (0.45, "计".encode(),  "「计」"),
    (0.95, None,   "停一下"),
    (0.30, ENTER,  "回车启动"),
    (0.55, None,   "拿到终端，交给 agent"),
]

T_PROMPT = 0.0
T_CMD = 0.55
T_PICKER_START = 1.05
T_TAIL_HOLD = 1.8      # 结尾多停一会儿，转 GIF 时不会戛然而止

emit(PROMPT, T_PROMPT)
emit("ag\r\n", T_CMD)

thread = threading.Thread(target=lambda: ag.main(["ag"]), daemon=True)
thread.start()
t0 = time.time()


def now():
    return T_PICKER_START + (time.time() - t0)


# 首帧一渲染出来就记下来，别让观众干等
while not _bufout.getvalue() and time.time() - t0 < 3.0:
    time.sleep(0.01)
drain(now())

for delay, key, _desc in SCRIPT:
    time.sleep(delay)
    drain(now())
    if key is not None:
        _keys.append(key)

_stop.set()
thread.join(timeout=2)
last = now()
drain(last)

# 补一个空事件把时长撑到结尾，播放器和 GIF 都会停在最后一帧上
emit("", last + T_TAIL_HOLD)

# ---------------------------------------------------------------- 写 cast

header = {
    "version": 2,
    "width": WIDTH,
    "height": HEIGHT,
    "timestamp": int(time.time()),
    "env": {"SHELL": "/bin/zsh", "TERM": "xterm-256color"},
    "title": "ag — Agent Gateway",
}

with open(OUT, "w", encoding="utf-8") as f:
    f.write(json.dumps(header, ensure_ascii=False) + "\n")
    for t, data in events:
        f.write(json.dumps([t, "o", data], ensure_ascii=False) + "\n")

dur = events[-1][0] if events else 0
print(f"写出 {os.path.relpath(OUT, ROOT)}")
print(f"  {len(events)} 个事件，时长 {dur:.1f}s，画布 {WIDTH}x{HEIGHT}")
print(f"\n播放：  asciinema play docs/demo.cast")
print(f"转 GIF： agg docs/demo.cast docs/demo.gif")
