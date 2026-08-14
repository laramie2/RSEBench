#!/usr/bin/env python3
"""SkillOpt DeepSeek API smoke launcher."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.baselines.native_smoke import run_launcher, run_method_python


def online(level: str):
    if level == "transport":
        code = r'''
import json
from skillopt.model import openai_compatible_backend as b
text, usage = b.chat_target("Return exactly OK.", "Connectivity check.", max_completion_tokens=64, retries=1, stage="transport", timeout=60)
print(json.dumps({"model": b.TARGET_CONFIG.deployment, "response": text.strip(), "usage": usage}))
'''
    elif level == "structured":
        code = r'''
import json
from skillopt.model import openai_compatible_backend as b
r = b._get_client("target").chat.completions.create(model=b.TARGET_CONFIG.deployment, messages=[{"role":"user","content":"Return JSON with ok=true."}], response_format={"type":"json_object"}, max_tokens=64, extra_body={"thinking":{"type":"disabled"}})
payload = json.loads(r.choices[0].message.content)
assert payload["ok"] is True
print(json.dumps({"model": r.model, "structured": True}))
'''
    elif level == "tool":
        code = r'''
import json
from skillopt.model import openai_compatible_backend as b
tool = {"type":"function","function":{"name":"write_text","description":"Write text.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}}
message, usage = b.chat_target_messages([{"role":"user","content":"Call write_text with path smoke.txt and content ok."}], max_completion_tokens=128, retries=1, stage="tool", tools=[tool], tool_choice={"type":"function","function":{"name":"write_text"}}, return_message=True, timeout=60)
call = message.tool_calls[0]
print(json.dumps({"model": b.TARGET_CONFIG.deployment, "tool": call.function.name, "arguments": json.loads(call.function.arguments), "usage": usage}))
'''
    else:
        raise RuntimeError(f"online smoke level is not implemented yet: {level}")
    return run_method_python("skillopt", code)


if __name__ == "__main__":
    raise SystemExit(run_launcher("skillopt", online))
