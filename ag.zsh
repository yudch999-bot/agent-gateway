# shellcheck shell=zsh
# （shellcheck 对 zsh 支持不完整，本文件不纳入 CI 的 shellcheck 检查，
#   只做 zsh -n 语法校验；见 tests/lint.sh）
# ============================================================
#  ag — Agent Gateway 的 zsh 集成
#  由 ~/.zshrc 里的一行 source 引入
#    · Tab 补全：agent 短名 + 子命令
#    · 快捷键：Ctrl-G 随时弹出选择器
#  不想要快捷键就设  AG_NO_KEYBIND=1
# ============================================================

# 从注册表里按区块抽 id 和 alias（纯 awk/sed，Tab 时无延迟）。
# 分区块是为了不让 [[team]] 的组合名混进 agent 短名里。
_ag_section_ids() {
  local reg="${AG_REGISTRY:-$HOME/.agents/registry.toml}" want="$1"
  [[ -r $reg ]] || return
  awk -v want="$want" '
    /^[[:space:]]*\[\[agent\]\]/ { sec = "agent"; next }
    /^[[:space:]]*\[\[team\]\]/  { sec = "team";  next }
    /^[[:space:]]*\[\[/          { sec = "" }
    sec == want && /^[[:space:]]*(id|alias)[[:space:]]*=/ { print }
  ' "$reg" 2>/dev/null \
    | sed -E 's/.*=[[:space:]]*//; s/^\[//; s/\][[:space:]]*$//; s/["'"'"']//g; s/,[[:space:]]*/ /g' \
    | tr ' ' '\n' | grep -v '^$'
}

# 从注册表里抽 agent 的 id 和 alias
_ag_ids() {
  _ag_section_ids agent
}

_ag_team_ids() {
  _ag_section_ids team
}

_ag() {
  local -a ids teams trefs
  ids=(${(f)"$(_ag_ids)"})
  teams=(${(f)"$(_ag_team_ids)"})
  local t
  for t in $teams; do trefs+=("@$t"); done
  if (( CURRENT == 2 )); then
    compadd -X '子命令' -- ls add rm edit scan doctor install which path teams team help
    (( ${#ids} )) && compadd -X 'agent（也可直接敲关键词再 Tab）' -- $ids
  else
    case ${words[2]} in
      team)
        if (( CURRENT == 3 )); then
          (( ${#trefs} )) && compadd -X '组合（@名字）' -- $trefs
          (( ${#ids} )) && compadd -X 'agent' -- $ids
        fi ;;
      rm|which|install) (( ${#ids} )) && compadd -X 'agent' -- $ids ;;
      edit|ls|scan|doctor|path) _files ;;
      *) _files ;;
    esac
  fi
}
compdef _ag ag 2>/dev/null

# ---- Ctrl-G：命令行上随时召唤选择器 ----
if [[ -o interactive && -z $AG_NO_KEYBIND ]]; then
  ag-launch-widget() {
    zle -I                 # 先把当前提示行收起来，别和全屏选择器打架
    ag
    zle reset-prompt
  }
  zle -N ag-launch-widget 2>/dev/null
  bindkey '^G' ag-launch-widget 2>/dev/null
fi
