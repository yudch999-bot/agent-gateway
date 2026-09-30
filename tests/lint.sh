#!/usr/bin/env bash
# 静态检查 —— 专抓「语法检查查不出来、只有真机跑才炸」的那类问题。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$*"; FAIL=1; }

printf '\n\033[1m静态检查\033[0m\n'

# --- 1. $VAR 后面紧跟非 ASCII 字符 ---------------------------------------
# 这是本项目真实踩过的坑：
#   c_info "源文件：$RAW（远程下载）"
# 全角括号紧跟变量名，某些 locale 下 bash 会把多字节字符吞进变量名，
# 运行时报 `RAW?: unbound variable`，而 `bash -n` 完全查不出来。
# 修法一律用 ${RAW} 括起来。
printf '\n1) $VAR 后紧跟非 ASCII（会吞进变量名）\n'
hits=$(python3 - "$REPO" <<'PY'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
pat = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)(?=[^\x00-\x7f])')
n = 0
for f in sorted(root.rglob("*")):
    if f.is_dir() or ".git" in f.parts:
        continue
    if f.suffix not in (".sh", ".zsh") and f.name != "ag.zsh":
        continue
    try:
        text = f.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):      # 注释里举例说明的不算
            continue
        for m in pat.finditer(line):
            print(f"{f.relative_to(root)}:{i}: ${m.group(1)}  ->  {line.strip()}")
            n += 1
sys.exit(1 if n else 0)
PY
) && ok "没有裸变量紧跟多字节字符" || { echo "$hits" | sed 's/^/     /'; bad "有变量需要加花括号"; }

# --- 2. shell 语法 -------------------------------------------------------
printf '\n2) shell 语法\n'
for f in "$REPO"/*.sh "$REPO"/tests/*.sh; do
  [ -f "$f" ] || continue
  if bash -n "$f" 2>/dev/null; then ok "$(basename "$f")  (bash -n)"
  else bad "$(basename "$f") bash 语法错误"; fi
done
# .zsh 得用 zsh 自己校验 —— bash -n 看不懂 ${(f)...} 这类 zsh 语法，过了也不算数
if command -v zsh >/dev/null 2>&1; then
  for f in "$REPO"/*.zsh; do
    [ -f "$f" ] || continue
    if zsh -n "$f" 2>/dev/null; then ok "$(basename "$f")  (zsh -n)"
    else bad "$(basename "$f") zsh 语法错误"; fi
  done
else
  printf '  \033[90m· 没装 zsh，跳过 .zsh 语法校验\033[0m\n'
fi

# --- 3. 目标脚本必须是可执行的 -------------------------------------------
printf '\n3) 可执行位\n'
for f in "$REPO/ag" "$REPO/install.sh" "$REPO/tests/test_install.sh" "$REPO/tests/test_ag.py"; do
  [ -x "$f" ] && ok "$(basename "$f")" || bad "$(basename "$f") 没有可执行位"
done

# --- 4. 别把密钥提交上去 -------------------------------------------------
printf '\n4) 密钥扫描\n'
if grep -rnE 'sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}' \
      --include='*' "$REPO" 2>/dev/null | grep -v '/.git/' | grep -v 'sk-xxx' | grep -q .; then
  grep -rnE 'sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}' \
      --include='*' "$REPO" 2>/dev/null | grep -v '/.git/' | grep -v 'sk-xxx' | sed 's/^/     /'
  bad "疑似真密钥"
else
  ok "没有真密钥（sk-xxx 之类的占位符不算）"
fi

# --- 5. shellcheck（有就跑）---------------------------------------------
printf '\n5) shellcheck\n'
if command -v shellcheck >/dev/null 2>&1; then
  # 只查 bash 脚本：shellcheck 的 zsh 支持不完整，ag.zsh 查了都是误报
  if shellcheck -S warning "$REPO"/*.sh "$REPO"/tests/*.sh; then
    ok "shellcheck 通过"
  else
    bad "shellcheck 有告警"
  fi
else
  printf '  \033[90m· 没装 shellcheck，跳过\033[0m\n'
fi

printf '\n'
if [ "$FAIL" = "0" ]; then
  printf '\033[32m✅ 静态检查全部通过\033[0m\n\n'; exit 0
else
  printf '\033[31m❌ 静态检查有失败项\033[0m\n\n'; exit 1
fi
