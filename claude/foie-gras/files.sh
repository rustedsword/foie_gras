#!/usr/bin/env bash
# Prints the absolute paths of the files a .foie_gras list names, one per line.
shopt -s globstar nullglob dotglob
declare -A seen
out=()
failed=

fail() {
  echo "foie_gras: $1" >&2
  exit 1
}

emit() {
  local f=${1#./}
  [ -n "${seen[$f]}" ] && return
  seen[$f]=1
  out+=("$PWD/$f")
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

list=${1:-default}
[[ $list =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || fail "'$list' is not a list name"
until [ -e .foie_gras ]; do
  [ -e .git ] || [ "$PWD" = / ] && fail "No .foie_gras found"
  cd ..
done
manifest=.foie_gras/$list
[ "$list" = default ] && [ -f .foie_gras ] && manifest=.foie_gras
[ -f "$manifest" ] || fail "$manifest not found"

while read -r line || [ -n "$line" ]; do
  [[ -z $line || $line == \#* ]] && continue
  expand "$line"
done < "$manifest"
[ -z "$failed" ] || exit 1
[ ${#out[@]} -gt 0 ] || fail "$manifest lists no files"
printf '%s\n' "${out[@]}"
