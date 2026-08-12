# RSE-Bench

RSE-Bench constructs paired clean/noisy tasks for evaluating robust skill self-evolution. The current implementation phase covers pinned baseline/data acquisition and small pilot experiments. Pilot model calls are locked to `deepseek-v4-flash`.

## Setup

```bash
python -m pip install -e '.[test]'
cp .env.example .env
```

Leave `DEEPSEEK_API_KEY` empty for download, materialization, rule-based noise generation, and offline validation. Add a valid key only before model-backed noise generation or pilot execution.

The full approved design is in `docs/superpowers/specs/2026-08-11-robust-skill-evolution-benchmark-design.md`.

## Reproduce downloads and audits

```bash
bash scripts/download/baselines.sh
python scripts/download/datasets.py --profile core --resume
python scripts/materialize_splits.py
python scripts/audit_baselines.py
python scripts/audit_datasets.py
python scripts/audit_skill_native.py
```

Large assets are stored under the central project `data/` and
`methods/external/` directories and are not committed.

## Run noise-generation validation

The offline smoke validates generation and label-preservation gates; it does not
claim that noise reduces model accuracy.

```bash
bash scripts/run/pilot_a.sh --offline --limit 5

python -m rsebench.cli generate-noise \
  --profile configs/pilot/spreadsheet.yaml --limit 10 --offline
python -m rsebench.cli generate-noise \
  --profile configs/pilot/officeqa-demo.yaml --limit 10 --offline
python -m rsebench.cli generate-noise \
  --profile configs/pilot/docvqa.yaml --limit 10 --offline
```

After adding a valid DeepSeek key to `.env`, run the small paired effectiveness
experiment:

```bash
python -m rsebench.cli provider-check \
  --config configs/pilot/deepseek-v4-flash.yaml
python -m rsebench.cli math-pilot-a --limit 5
```

See `docs/reports/phase0-download-audit.md`,
`docs/reports/baseline-benchmark-audit.md`, and
`docs/reports/pilot-readiness.md` for exact states, limitations, and next gates.
