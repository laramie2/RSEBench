#!/usr/bin/env python3
"""Trace2Skill DeepSeek API smoke launcher."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.baselines.native_smoke import run_launcher, run_method_python


def online(level: str):
    if level == "transport":
        code = r'''
import json
from src.react_agent.models import Message, ModelSettings, OpenAIClient
c = OpenAIClient(model="deepseek-v4-flash", use_cache=False, retry_times=(), timeout=60)
text = c.chat([Message(role="user", content="Return exactly OK.")], ModelSettings(temperature=0, max_tokens=64, extra_body={"thinking":{"type":"disabled"}}))
print(json.dumps({"model": c.model, "response": text.strip()}))
'''
    elif level == "structured":
        code = r'''
import json
from src.react_agent.models import OpenAIClient
c = OpenAIClient(model="deepseek-v4-flash", use_cache=False, retry_times=(), timeout=60)
r = c._client.chat.completions.create(model=c.model, messages=[{"role":"user","content":"Return JSON with ok=true."}], response_format={"type":"json_object"}, max_tokens=64, extra_body={"thinking":{"type":"disabled"}})
payload = json.loads(r.choices[0].message.content)
assert payload["ok"] is True
print(json.dumps({"model": r.model, "structured": True}))
'''
    elif level == "tool":
        code = r'''
import json
from src.react_agent.models import OpenAIClient
c = OpenAIClient(model="deepseek-v4-flash", use_cache=False, retry_times=(), timeout=60)
tool = {"type":"function","function":{"name":"write_text","description":"Write text.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}}
r = c._client.chat.completions.create(model=c.model, messages=[{"role":"user","content":"Call write_text with path smoke.txt and content ok."}], tools=[tool], tool_choice={"type":"function","function":{"name":"write_text"}}, max_tokens=128, extra_body={"thinking":{"type":"disabled"}})
call = r.choices[0].message.tool_calls[0]
print(json.dumps({"model": r.model, "tool": call.function.name, "arguments": json.loads(call.function.arguments)}))
'''
    else:
        raise RuntimeError(f"online smoke level is not implemented yet: {level}")
    return run_method_python("trace2skill", code)


if __name__ == "__main__":
    raise SystemExit(run_launcher("trace2skill", online))
