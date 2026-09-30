#!/usr/bin/env bash
# ============================================================
#  ag — Agent Gateway 安装脚本
#
#  两种用法都支持：
#    1) 从 clone 出来的仓库里跑：   ./install.sh
#    2) 直接管道执行：              curl -fsSL .../install.sh | bash
#
#  装什么：
#    ~/.local/bin/ag              主程序
#    ~/.agents/registry.toml      注册表（已存在则不动，绝不覆盖你的配置）
#    ~/.agents/ag.zsh             zsh 补全 + Ctrl-G
#    ~/.zshrc                     追加一段 source（幂等，重复跑不会重复加）
# ============================================================
set -euo pipefail

RAW="${AG_RAW_BASE:-https://raw.githubusercontent.com/yudch999-bot/agent-gateway/main}"
BIN_DIR="$HOME/.local/bin"
AG_DIR="$HOME/.agents"
ZSHRC="$HOME/.zshrc"
# 检测用「前缀」：容忍标记行后面还跟着说明文字（老版本写的就带说明）
MARK_KEY="# >>> ag — Agent Gateway"
BLOCK_BEGIN="# >>> ag — Agent Gateway >>>"
BLOCK_END="# <<< ag — Agent Gateway <<<"

c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
c_info() { printf '\033[90m·\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_die()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

printf '\n\033[1m ag — Agent Gateway 安装\033[0m\n\n'

# ---------- 1. 检查 Python ----------
PY=""
for cand in python3 python3.13 python3.12 python3.11; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys,tomllib; sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
[ -n "$PY" ] || c_die "需要 Python 3.11+（用到标准库 tomllib），没找到。装一个再来：
    brew install python@3.12     或     pyenv install 3.12"
c_ok "Python: $($PY --version 2>&1)  ($(command -v "$PY"))"

# ---------- 2. 定位源文件（clone 里 or 远程）----------
SRC_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [ -f "$SRC_DIR/ag" ] || SRC_DIR=""
fi
if [ -n "$SRC_DIR" ]; then
  c_info "源文件：${SRC_DIR}（本地仓库）"
else
  c_info "源文件：${RAW}（远程下载）"
  command -v curl >/dev/null 2>&1 || c_die "需要 curl 才能远程安装"
fi

fetch() {  # fetch <相对路径> <目标路径>
  if [ -n "$SRC_DIR" ] && [ -f "$SRC_DIR/$1" ]; then
    cp "$SRC_DIR/$1" "$2"
  else
    curl -fsSL "$RAW/$1" -o "$2" || c_die "下载失败：$RAW/$1"
  fi
}

# ---------- 3. 装主程序 ----------
mkdir -p "$BIN_DIR" "$AG_DIR"
fetch ag "$BIN_DIR/ag.tmp.$$"
chmod +x "$BIN_DIR/ag.tmp.$$"
mv "$BIN_DIR/ag.tmp.$$" "$BIN_DIR/ag"
c_ok "主程序：$BIN_DIR/ag"

# ---------- 4. 装注册表（不覆盖已有的）----------
if [ -f "$AG_DIR/registry.toml" ]; then
  c_info "注册表已存在，保留不动：$AG_DIR/registry.toml"
  c_info "（想看模板长什么样：$AG_DIR/registry.example.toml）"
  fetch registry.example.toml "$AG_DIR/registry.example.toml"
else
  fetch registry.example.toml "$AG_DIR/registry.toml"
  n=$(grep -c '^\[\[agent\]\]' "$AG_DIR/registry.toml" 2>/dev/null || echo "?")
  c_ok "注册表：$AG_DIR/registry.toml（${n} 条示例）"
fi

# ---------- 5. 装 zsh 集成 ----------
fetch ag.zsh "$AG_DIR/ag.zsh"
c_ok "zsh 集成：$AG_DIR/ag.zsh（Tab 补全 + Ctrl-G）"

# ---------- 6. 接进 .zshrc（幂等）----------
BLOCK="$BLOCK_BEGIN
export PATH=\"\$HOME/.local/bin:\$PATH\"
[[ -r \"\$HOME/.agents/ag.zsh\" ]] && source \"\$HOME/.agents/ag.zsh\"
$BLOCK_END"

if [ -f "$ZSHRC" ] && grep -qF "$MARK_KEY" "$ZSHRC"; then
  c_info ".zshrc 里已有 ag 段落，跳过"
else
  if [ -f "$ZSHRC" ]; then
    cp "$ZSHRC" "$ZSHRC.bak-ag-$(date +%Y%m%d-%H%M%S)"
    c_info "已备份 .zshrc"
  fi
  printf '\n%s\n' "$BLOCK" >> "$ZSHRC"
  c_ok "已写入 .zshrc"
fi

# ---------- 7. PATH 提醒 ----------
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) c_warn "$BIN_DIR 不在当前 PATH 上 —— 新开终端就好了（.zshrc 里补了）" ;;
esac

# ---------- 8. 自检 ----------
if "$BIN_DIR/ag" --version >/dev/null 2>&1; then
  c_ok "自检通过：$("$BIN_DIR/ag" --version)"
else
  c_warn "自检没通过，跑一下 $BIN_DIR/ag doctor 看看"
fi

printf '\n\033[1m装好了。\033[0m 新开一个终端，然后：\n\n'
printf '    ag              \033[90m# 打开选择器\033[0m\n'
printf '    ag ls           \033[90m# 看有哪些、哪些没装\033[0m\n'
printf '    ag scan         \033[90m# 扫出你装了但还没登记的 agent\033[0m\n'
printf '    ag add          \033[90m# 加自己的\033[0m\n\n'
printf '  当前终端想立刻生效：  \033[36msource ~/.zshrc\033[0m\n\n'
