#!/usr/bin/env bash
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"

limit=5
offline=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) offline=true; shift ;;
    --limit) limit="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

profiles=(spreadsheet officeqa officeqa-demo docvqa math)
for profile in "${profiles[@]}"; do
  args=(--profile "configs/pilot/${profile}.yaml" --limit "$limit")
  if [[ "$offline" == true ]]; then
    args+=(--offline)
  fi
  python -m rsebench.cli generate-noise "${args[@]}"
done

if [[ "$offline" == false ]]; then
  python -m rsebench.cli math-pilot-a --limit "$limit"
fi
