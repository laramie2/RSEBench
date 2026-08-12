#!/usr/bin/env python3
"""Skills-Coach DeepSeek API smoke launcher."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.baselines.native_smoke import run_launcher, run_method_python


def online(level: str):
    prefix = r'''
import json
from rsebench.adapters.skills_coach import DeepSeekAnthropicCompat, MODEL
c = DeepSeekAnthropicCompat()
'''
    if level == "transport":
        code = prefix + r'''
r = c.messages.create(model="ignored", max_tokens=64, messages=[{"role":"user","content":"Return exactly OK."}])
print(json.dumps({"model": MODEL, "response": r.content[0].text.strip()}))
'''
    elif level == "structured":
        code = prefix + r'''
payload = c.complete_json("Return JSON with ok=true.", max_tokens=64)
assert payload["ok"] is True
print(json.dumps({"model": MODEL, "structured": True}))
'''
    elif level == "tool":
        code = prefix + r'''
tool = {"type":"function","function":{"name":"write_text","description":"Write text.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}}
r = c._client.chat.completions.create(model=MODEL, messages=[{"role":"user","content":"Call write_text with path smoke.txt and content ok."}], tools=[tool], tool_choice={"type":"function","function":{"name":"write_text"}}, max_tokens=128, extra_body={"thinking":{"type":"disabled"}})
call = r.choices[0].message.tool_calls[0]
print(json.dumps({"model": MODEL, "tool": call.function.name, "arguments": json.loads(call.function.arguments)}))
'''
    else:
        raise RuntimeError(f"online smoke level is not implemented yet: {level}")
    return run_method_python("skills_coach", code)


if __name__ == "__main__":
    raise SystemExit(run_launcher("skills_coach", online))
