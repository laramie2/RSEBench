# RSE-Bench

RSE-Bench constructs paired clean/noisy tasks for evaluating robust skill self-evolution. The current implementation phase covers pinned baseline/data acquisition and small pilot experiments. Pilot model calls are locked to `deepseek-v4-flash`.

## Setup

```bash
python -m pip install -e '.[test]'
cp .env.example .env
```

Leave `DEEPSEEK_API_KEY` empty for download, materialization, rule-based noise generation, and offline validation. Add a valid key only before model-backed noise generation or pilot execution.

The full approved design is in `docs/superpowers/specs/2026-08-11-robust-skill-evolution-benchmark-design.md`.
