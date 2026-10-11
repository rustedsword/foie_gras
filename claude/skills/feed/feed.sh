#!/usr/bin/env bash
shopt -s globstar nullglob dotglob
here=$(cd "$(dirname "$0")" && pwd)
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
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

sync_lists() {
  local skills=${here%/*} d name f
  for d in "$skills"/feed-*/; do
    name=${d%/}
    name=${name##*/feed-}
    grep -qF "/../feed/feed.sh $name\`" "$d/SKILL.md" 2>/dev/null && [ ! -f ".foie_gras/$name" ] && rm -r "$d"
  done
  for f in .foie_gras/*; do
    name=${f##*/}
    [ "$name" = default ] && continue
    if [[ ! $name =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
      echo "skipped $f: use lowercase letters, digits and dashes" >&2
      continue
    fi
    mkdir -p "$skills/feed-$name"
    sed -e "s|^name: feed$|name: feed-$name|" \
      -e "s|^description: .*|description: Preload the files listed in .foie_gras/$name|" \
      -e "s|\${CLAUDE_SKILL_DIR}/feed.sh|\${CLAUDE_SKILL_DIR}/../feed/feed.sh $name|g" \
      "$here/SKILL.md" > "$skills/feed-$name/SKILL.md"
    echo "/feed-$name"
  done
}

if [ "$1" = --sync ]; then
  sync_lists
  exit
fi

list=${1:-default}
manifest=.foie_gras/$list
[ "$list" = default ] && [ -f .foie_gras ] && manifest=.foie_gras
[ -f "$manifest" ] || { echo "(foie_gras: $manifest not found)"; exit 0; }

while read -r line || [ -n "$line" ]; do
  [[ -z $line || $line == \#* ]] && continue
  expand "$line"
done < "$manifest"
