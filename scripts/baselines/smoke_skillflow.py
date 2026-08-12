#!/usr/bin/env python3
"""SkillFlow DeepSeek API/Harbor smoke launcher."""

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
c = DeepSeekClient(DeepSeekConfig(thinking="disabled", max_tokens=64), Path(".rsebench/smoke-cache"))
r = c.complete([{"role":"user","content":"Return JSON with ok=true."}], response_format={"type":"json_object"}, role="patcher")
payload = json.loads(r.content)
assert payload["ok"] is True
print(json.dumps({"model": r.model, "structured": True}))
'''
    elif level == "tool":
        code = r'''
import asyncio, json, tempfile
from pathlib import Path
from types import SimpleNamespace
from harbor.models.agent.context import AgentContext
from libs.harbor_noinstall_agents.deepseek_api import DeepSeekAPIAgent
class FakeEnvironment:
    def __init__(self): self.commands = []
    async def exec(self, *, command, **kwargs):
        self.commands.append(command)
        return SimpleNamespace(return_code=0, stdout="ok\n", stderr="")
with tempfile.TemporaryDirectory() as root:
    env = FakeEnvironment()
    ctx = AgentContext()
    agent = DeepSeekAPIAgent(logs_dir=Path(root), model_name="deepseek-v4-flash", max_turns=4)
    asyncio.run(agent.run("Use run_command with argv [python, -c, print('ok')], inspect its result, then finish.", env, ctx))
    assert env.commands
    assert Path(root, "trajectory.json").is_file()
    print(json.dumps({"model": "deepseek-v4-flash", "tool": "run_command", "commands": len(env.commands), "tokens": {"input": ctx.n_input_tokens, "output": ctx.n_output_tokens}}))
'''
    else:
        raise RuntimeError(f"online smoke level is not implemented yet: {level}")
    return run_method_python("skillflow", code)


if __name__ == "__main__":
    raise SystemExit(run_launcher("skillflow", online))
