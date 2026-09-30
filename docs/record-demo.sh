#!/usr/bin/env bash
# ============================================================
#  用真终端录一段演示，转成 README 用的 GIF
#
#  跟 docs/make-demo-cast.py 的区别：
#    · make-demo-cast.py  不需要终端，拿真实渲染器生成录像，
#                         画面和真跑逐字节一致，但按键是脚本喂的
#    · 本脚本             开一个真 asciinema 会话，你亲手敲，
#                         适合录进自己的真实环境和真实 agent
#
#  用法：  bash docs/record-demo.sh
# ============================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAST="$REPO/docs/demo-real.cast"
GIF="$REPO/docs/demo-real.gif"

c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_die()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 1. 检查工具 ----------
if ! command -v asciinema >/dev/null 2>&1; then
  c_die "没装 asciinema。任选一种：
    brew install asciinema
    pipx install asciinema
    pip install --user asciinema"
fi
c_ok "asciinema $(asciinema --version 2>&1 | awk '{print $2}')"

# ---------- 2. 录 ----------
cat <<'TIP'

  接下来会开一个录制会话。建议照这个剧本敲，大约 10 秒：

      ag              ← 打开选择器
      ↓ ↓ ↓           ← 上下移动让人看到光标在动
      设计            ← 打中文，直接筛到 ot-design
      Enter           ← 启动
      exit            ← 退出那个 agent，回到 shell
      exit            ← 结束录制

  录的时候记住：
    · 别打字太快，留点停顿给人看清
    · 打错了就继续，别停 —— 真实感更好
    · 想中途放弃：Ctrl-D 或 exit

TIP
read -r -p "  按回车开始录制… " _

asciinema rec "$CAST" \
  --cols 100 --rows 28 \
  --title "ag — Agent Gateway" \
  --idle-time-limit 2 \
  --command "zsh -f" \
  || c_die "录制失败"

c_ok "录像：$CAST"

# ---------- 3. 转 GIF ----------
if command -v agg >/dev/null 2>&1; then
  agg --font-size 15 --theme monokai --cols 100 --rows 28 \
      --speed 1.0 --last-frame-duration 2 "$CAST" "$GIF"
  c_ok "GIF：$GIF  ($(du -h "$GIF" | cut -f1))"
else
  c_warn "没装 agg，跳过转 GIF。装法：
      brew install agg
      # 或直接下静态二进制：
      # https://github.com/asciinema/agg/releases"
  printf '\n  手动转： agg --theme monokai %s %s\n\n' "$CAST" "$GIF"
fi

cat <<EOF

  预览：  asciinema play $CAST
  上传：  asciinema upload $CAST     （会给你一个 asciinema.org 链接，可嵌 README）

  想直接用「不需要终端」的生成方式（CI 友好、可复现）：
      python3 docs/make-demo-cast.py

EOF
