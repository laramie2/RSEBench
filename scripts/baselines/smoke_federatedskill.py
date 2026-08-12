#!/usr/bin/env python3
"""FederatedSkill DeepSeek worker/patcher/merger smoke launcher."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.baselines.native_smoke import run_launcher, run_method_python


def online(level: str):
    if level == "transport":
        code = r'''
import json
from pathlib import Path
from rsebench.providers.deepseek import DeepSeekClient, DeepSeekConfig
c = DeepSeekClient(DeepSeekConfig(thinking="disabled", max_tokens=64), Path(".rsebench/smoke-cache"))
r = c.complete([{"role":"user","content":"Return exactly OK."}], role="worker")
print(json.dumps({"model": r.model, "response": r.content.strip()}))
'''
    elif level == "structured":
        code = r'''
import json
from pathlib import Path
from rsebench.providers.deepseek import DeepSeekClient, DeepSeekConfig
c = DeepSeekClient(DeepSeekConfig(thinking="disabled", max_tokens=128), Path(".rsebench/smoke-cache"))
r = c.complete([{"role":"user","content":"Return JSON with fields summary='ok', upsert_files={}, delete_paths=[]."}], response_format={"type":"json_object"}, role="patcher")
payload = json.loads(r.content)
assert set(payload) >= {"summary", "upsert_files", "delete_paths"}
print(json.dumps({"model": r.model, "structured": True, "role": "patcher"}))
'''
    elif level == "tool":
        code = r'''
import asyncio, json, tempfile
from pathlib import Path
from types import SimpleNamespace
from harbor.models.agent.context import AgentContext
from skillfl.skillflow_adapter.deepseek_api import DeepSeekAPIAgent
from rsebench.adapters.harbor_agent import DeepSeekSandboxRunner
class FakeEnvironment:
    def __init__(self): self.commands = []
    async def exec(self, *, command, **kwargs):
        self.commands.append(command)
        return SimpleNamespace(return_code=0, stdout="ok\n", stderr="")
with tempfile.TemporaryDirectory() as root:
    root = Path(root)
    env = FakeEnvironment()
    ctx = AgentContext()
    worker = DeepSeekAPIAgent(logs_dir=root / "worker", model_name="deepseek-v4-flash", max_turns=4)
    asyncio.run(worker.run("Use run_command with argv [python, -c, print('ok')], inspect the result, then finish.", env, ctx))
    assert env.commands
    merger_dir = root / "merger"
    merger_dir.mkdir()
    DeepSeekSandboxRunner()(
        sandbox_dir=merger_dir,
        prompt="Use write_text to create DONE.txt containing merged, then finish.",
        model_name="deepseek-v4-flash",
        max_turns=4,
        wall_clock_sec=30,
        env=None,
    )
    assert (merger_dir / "DONE.txt").is_file()
    print(json.dumps({"model": "deepseek-v4-flash", "worker_commands": len(env.commands), "merger_done": True}))
'''
    else:
        raise RuntimeError(f"online smoke level is not implemented yet: {level}")
    return run_method_python("federatedskill", code)


if __name__ == "__main__":
    raise SystemExit(run_launcher("federatedskill", online))
