# RSE-Bench

RSE-Bench evaluates whether skill self-evolution remains effective when task context, environment evidence, stored trajectories, or update feedback contain controlled noise. The active Core-1 scope covers SpreadsheetBench-Verified, OfficeQA Full, WebShop, and SkillLearnBench.

## Collaborator roadmap

Start with the [Chinese project roadmap](docs/project-roadmap.md) for the active benchmarks, baseline methods, N1–N4 noise matrix, experiment gates, current limitations, and pending work. Machine-readable registries and executable configs remain the source of truth.

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
  --profile configs/pilot/officeqa.yaml --limit 10 --offline
python -m rsebench.cli generate-noise \
  --profile configs/pilot/docvqa.yaml --limit 10 --offline
```

`configs/pilot/officeqa-demo.yaml` remains available only as a small reproduction
fixture; formal validation uses all 246 OfficeQA rows and the downloaded corpus.

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
