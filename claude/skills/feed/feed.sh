#!/usr/bin/env bash
shopt -s globstar nullglob dotglob
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
manifest=${FOIE_GRAS:-.foie_gras}
[ -f "$manifest" ] || { echo "(foie_gras: $manifest not found)"; exit 0; }
declare -A seen

emit() {
  local f=${1#./}
  [ -n "${seen[$f]}" ] && return
  seen[$f]=1
  printf '@%s\n' "${f// /\\ }"
}

expand() {
  local IFS= p f
  for p in $1; do
    if [ -d "$p" ]; then
      for f in "${p%/}"/**; do [ -f "$f" ] && emit "$f"; done
    elif [ -f "$p" ]; then
      emit "$p"
    fi
  done
}

while read -r line || [ -n "$line" ]; do
  [[ -z $line || $line == \#* ]] && continue
  expand "$line"
done < "$manifest"
