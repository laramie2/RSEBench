#!/usr/bin/env python3
"""EvoSkill DeepSeek API smoke launcher."""

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
c = DeepSeekClient(DeepSeekConfig(thinking="disabled", max_tokens=64), Path(".evoskill/smoke-cache"))
r = c.complete([{"role":"user","content":"Return exactly OK."}], role="executor")
print(json.dumps({"model": r.model, "response": r.content.strip(), "usage": r.usage}))
'''
    elif level == "structured":
        code = r'''
import json
from pathlib import Path
from rsebench.providers.deepseek import DeepSeekClient, DeepSeekConfig
c = DeepSeekClient(DeepSeekConfig(thinking="disabled", max_tokens=64), Path(".evoskill/smoke-cache"))
r = c.complete([{"role":"user","content":"Return JSON with ok=true."}], response_format={"type":"json_object"}, role="evaluator")
payload = json.loads(r.content)
assert payload["ok"] is True
print(json.dumps({"model": r.model, "structured": True}))
'''
    elif level == "tool":
        code = r'''
import asyncio, json, tempfile
from pathlib import Path
from pydantic import BaseModel
from src.harness import Agent, build_options, set_sdk
class Answer(BaseModel):
    final_answer: str
with tempfile.TemporaryDirectory() as root:
    set_sdk("deepseek_api")
    options = build_options(system="Follow the request and return JSON.", schema=Answer.model_json_schema(), tools=["Read", "Write"], project_root=root, model="deepseek-v4-flash")
    trace = asyncio.run(Agent(options, Answer, max_retries=1).run("Use write_text to create smoke.txt containing ok, then answer done."))
    assert Path(root, "smoke.txt").read_text() == "ok"
    assert trace.output is not None
    print(json.dumps({"model": trace.model, "tool": "write_text", "answer": trace.output.final_answer, "turns": trace.num_turns}))
'''
    else:
        raise RuntimeError(f"online smoke level is not implemented yet: {level}")
    return run_method_python("evoskill", code)


if __name__ == "__main__":
    raise SystemExit(run_launcher("evoskill", online))
