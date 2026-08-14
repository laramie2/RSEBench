#!/usr/bin/env bash
set -euo pipefail

project_root=$(git rev-parse --show-toplevel)
registry="$project_root/benchmark/registry/methods.yaml"

if [[ -f "$project_root/.env" ]]; then
  set -a
  source "$project_root/.env"
  set +a
fi

methods_root=${RSEBENCH_METHODS_ROOT:-"$project_root/methods/external"}
mkdir -p "$methods_root"

while IFS=$'\t' read -r name repository commit git_lfs; do
  target="$methods_root/$name"
  if [[ -e "$target" && ! -d "$target/.git" ]]; then
    echo "error: existing target is not a Git checkout: $target" >&2
    exit 1
  fi

  if [[ ! -d "$target/.git" ]]; then
    echo "cloning $name"
    git clone --filter=blob:none "$repository" "$target"
  else
    actual_origin=$(git -C "$target" remote get-url origin)
    if [[ "$actual_origin" != "$repository" ]]; then
      echo "error: origin mismatch for $name: $actual_origin" >&2
      exit 1
    fi
  fi

  current_head=$(git -C "$target" rev-parse HEAD 2>/dev/null || true)
  if [[ "$current_head" != "$commit" ]]; then
    if [[ -n "$(git -C "$target" status --porcelain 2>/dev/null)" ]]; then
      echo "error: refusing to change dirty checkout: $target" >&2
      exit 1
    fi
    git -C "$target" fetch --depth 1 origin "$commit"
    git -C "$target" checkout --detach "$commit"
  fi

  if [[ "$git_lfs" == "true" ]]; then
    git -C "$target" lfs pull
  fi

  verified_head=$(git -C "$target" rev-parse HEAD)
  if [[ "$verified_head" != "$commit" ]]; then
    echo "error: commit verification failed for $name" >&2
    exit 1
  fi
  echo "verified $name $verified_head"
done < <(
  python - "$registry" <<'PY'
from pathlib import Path
import sys
import yaml

data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
for name, row in data["methods"].items():
    print(
        name,
        row["repository"],
        row["commit"],
        str(bool(row.get("git_lfs", False))).lower(),
        sep="\t",
    )
PY
)
