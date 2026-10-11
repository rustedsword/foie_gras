#!/usr/bin/env bash
shopt -s globstar nullglob dotglob
here=$(cd "$(dirname "$0")" && pwd)
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
declare -A seen

emit() {
  local f=${1#./}
  [ -n "${seen[$f]}" ] && return
  seen[$f]=1
  out+=("@${f// /\\ }")
}

expand() {
  local IFS= p f found=
  for p in $1; do
    if [ -d "$p" ]; then
      for f in "${p%/}"/**; do [ -f "$f" ] && emit "$f" && found=1; done
    elif [ -f "$p" ]; then
      emit "$p" && found=1
    fi
  done
  [ -n "$found" ] || { echo "foie_gras: No files matched '$1' in $manifest" >&2; failed=1; }
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
[ -f "$manifest" ] || { echo "foie_gras: $manifest not found" >&2; exit 1; }

out=()
failed=
while read -r line || [ -n "$line" ]; do
  [[ -z $line || $line == \#* ]] && continue
  expand "$line"
done < "$manifest"
[ -z "$failed" ] || exit 1
[ ${#out[@]} -eq 0 ] || printf '%s\n' "${out[@]}"
