#!/usr/bin/env bash
# install.sh 的回归测试 —— 全程在临时 HOME 里跑，不碰真环境。
#
# 覆盖两个真机才暴露的坑：
#   1. 变量后紧跟全角字符 → bash 把多字节字符吞进变量名 → unbound variable
#      （LC_ALL=C 时最容易触发）
#   2. .zshrc 幂等检测用精确整行匹配 → 匹配不上 → 重复追加
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; FAIL=1; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

BEGIN_KEY='# >>> ag — Agent Gateway'
OLD_STYLE_BLOCK='# >>> ag — Agent Gateway （统一启动/切换所有 AI coding agent）>>>
# 用 ag 打开选择器
export PATH="$HOME/.local/bin:$PATH"
[[ -r "$HOME/.agents/ag.zsh" ]] && source "$HOME/.agents/ag.zsh"
# <<< ag — Agent Gateway <<<'

new_home() {
  local d; d="$(mktemp -d)"
  echo "$d"
}

run_install() {  # run_install <home> [额外 env...]
  local h="$1"; shift
  env HOME="$h" "$@" bash "$REPO/install.sh" 2>&1
}

# ---------------------------------------------------------------- 测试 1
head_ "1) 全新 HOME 安装（含 LC_ALL=C —— 复现全角字符那个坑）"
H1="$(new_home)"
out="$(run_install "$H1" LC_ALL=C LANG=C)"
if echo "$out" | grep -q 'unbound variable'; then
  bad "LC_ALL=C 下报 unbound variable：$(echo "$out" | grep 'unbound variable')"
else
  ok "LC_ALL=C 下没有 unbound variable"
fi
[ -x "$H1/.local/bin/ag" ]      && ok "主程序已装"     || bad "主程序没装"
[ -f "$H1/.agents/registry.toml" ] && ok "注册表已生成" || bad "注册表没生成"
[ -f "$H1/.agents/ag.zsh" ]     && ok "zsh 集成已装"   || bad "zsh 集成没装"
n=$(grep -c "^$BEGIN_KEY" "$H1/.zshrc" 2>/dev/null || echo 0)
[ "$n" = "1" ] && ok ".zshrc 写入 1 段" || bad ".zshrc 段落数 = ${n}（应为 1）"

# ---------------------------------------------------------------- 测试 2
head_ "2) 重复安装应幂等（连跑三次，.zshrc 不能变长）"
before_lines=$(wc -l < "$H1/.zshrc")
bk_before=$(ls "$H1"/.zshrc.bak-ag-* 2>/dev/null | wc -l | tr -d ' ')
for i in 1 2 3; do run_install "$H1" >/dev/null; done
after_lines=$(wc -l < "$H1/.zshrc")
bk_after=$(ls "$H1"/.zshrc.bak-ag-* 2>/dev/null | wc -l | tr -d ' ')
n=$(grep -c "^${BEGIN_KEY}" "$H1/.zshrc")
[ "$before_lines" = "$after_lines" ] && ok ".zshrc 行数不变（${before_lines}）" \
                                     || bad ".zshrc 行数 $before_lines → $after_lines"
[ "$n" = "1" ] && ok "段落数仍是 1" || bad "段落数变成 $n"
# 跳过写入就不该备份，所以只要求「不再新增」
[ "$bk_before" = "$bk_after" ] && ok "没有新增备份（${bk_after} 份）" \
                               || bad "备份从 $bk_before 涨到 $bk_after"

# ---------------------------------------------------------------- 测试 3
head_ "3) 老式标记行（带中文说明）必须被识别为「已存在」"
H2="$(new_home)"
printf '%s\n' "$OLD_STYLE_BLOCK" > "$H2/.zshrc"
before_lines=$(wc -l < "$H2/.zshrc")
out="$(run_install "$H2")"
after_lines=$(wc -l < "$H2/.zshrc")
if echo "$out" | grep -q '已有 ag 段落'; then
  ok "识别为已存在，跳过写入"
else
  bad "没识别出老式标记行，又追加了一段"
fi
[ "$before_lines" = "$after_lines" ] && ok ".zshrc 未被改动" \
                                     || bad ".zshrc 被改了：$before_lines → $after_lines"

# ---------------------------------------------------------------- 测试 4
head_ "4) 已存在的注册表绝不能被覆盖"
H3="$(new_home)"
mkdir -p "$H3/.agents"
echo '[[agent]]
id = "mine"
cmd = "echo"
desc = "我自己的"' > "$H3/.agents/registry.toml"
run_install "$H3" >/dev/null
if grep -q '"mine"' "$H3/.agents/registry.toml"; then
  ok "用户注册表原样保留"
else
  bad "用户的注册表被覆盖了！"
fi
[ -f "$H3/.agents/registry.example.toml" ] && ok "同时给出了模板副本" \
                                           || bad "没有附带模板"

# ---------------------------------------------------------------- 测试 5
head_ "5) 装完能跑"
H4="$(new_home)"
run_install "$H4" >/dev/null
if out="$(env HOME="$H4" "$H4/.local/bin/ag" ls 2>&1)"; then
  echo "$out" | grep -q 'Agent Gateway' && ok "ag ls 正常输出" || bad "ag ls 输出异常"
else
  bad "ag ls 跑不起来：$out"
fi
if env HOME="$H4" "$H4/.local/bin/ag" --version >/dev/null 2>&1; then
  ok "ag --version 正常"
else
  bad "ag --version 失败"
fi

for h in "$H1" "$H2" "$H3" "$H4"; do rm -rf "$h"; done

printf '\n'
if [ "$FAIL" = "0" ]; then
  printf '\033[32m✅ install.sh 全部通过\033[0m\n'; exit 0
else
  printf '\033[31m❌ install.sh 有失败项\033[0m\n'; exit 1
fi
