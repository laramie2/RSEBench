#!/usr/bin/env python3
"""SkillGrad DeepSeek API smoke launcher."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.baselines.native_smoke import run_launcher, run_method_python


def online(level: str):
    common = r'''
import asyncio, json
from runners.model_dispatch import get_client_for_model
async def main():
    c = get_client_for_model("deepseek-v4-flash")
'''
    if level == "transport":
        body = r'''
    r = await c.chat.completions.create(model="deepseek-v4-flash", messages=[{"role":"user","content":"Return exactly OK."}], max_tokens=64, extra_body={"thinking":{"type":"disabled"}})
    print(json.dumps({"model": r.model, "response": (r.choices[0].message.content or "").strip()}))
'''
    elif level == "structured":
        body = r'''
    r = await c.chat.completions.create(model="deepseek-v4-flash", messages=[{"role":"user","content":"Return JSON with ok=true."}], response_format={"type":"json_object"}, max_tokens=64, extra_body={"thinking":{"type":"disabled"}})
    payload = json.loads(r.choices[0].message.content)
    assert payload["ok"] is True
    print(json.dumps({"model": r.model, "structured": True}))
'''
    elif level == "tool":
        body = r'''
    tool = {"type":"function","function":{"name":"write_text","description":"Write text.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}}
    r = await c.chat.completions.create(model="deepseek-v4-flash", messages=[{"role":"user","content":"Call write_text with path smoke.txt and content ok."}], tools=[tool], tool_choice={"type":"function","function":{"name":"write_text"}}, max_tokens=128, extra_body={"thinking":{"type":"disabled"}})
    call = r.choices[0].message.tool_calls[0]
    print(json.dumps({"model": r.model, "tool": call.function.name, "arguments": json.loads(call.function.arguments)}))
'''
    else:
        raise RuntimeError(f"online smoke level is not implemented yet: {level}")
    return run_method_python("skillgrad", common + body + "\nasyncio.run(main())\n")


if __name__ == "__main__":
    raise SystemExit(run_launcher("skillgrad", online))
