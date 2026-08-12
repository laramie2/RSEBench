#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"

python - <<'PY'
import os
from dotenv import load_dotenv
load_dotenv('.env')
if not os.environ.get('DEEPSEEK_API_KEY', '').strip():
    print('blocked_on_credentials: set DEEPSEEK_API_KEY in .env')
    raise SystemExit(2)
print('pilot_b_preflight_ready: see configs/pilot/pilot-b.yaml')
print('No baseline is launched implicitly; native clean reproduction is required first.')
PY
