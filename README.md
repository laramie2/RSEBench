# RSE-Bench

RSE-Bench evaluates whether skill self-evolution remains effective when task context, environment evidence, stored trajectories, or update feedback contain controlled noise. Validation-v1 covers SpreadsheetBench-Verified / SkillOpt, OfficeQA Full / SkillOpt, WebShop / SkillAdaptor, and SkillFlow-Task / SkillFlow. SkillLearnBench remains diagnostic history and is not the fourth active domain.

## Start here

- [Documentation index](docs/README.md)
- [Chinese project onboarding](docs/project-onboarding.md)
- [Project roadmap](docs/project-roadmap.md)
- [Current project status](docs/reports/current/current-project-status.md)
- [N1–N4 collaboration progress](docs/progress/README.md)
- [Validation runbook](docs/operations/validation-runbook.md)

Machine-readable DatasetRelease, MethodRelease, registry, and matrix files are the executable sources of truth. Prose documents explain scope and conclusion boundaries but do not override frozen identities.

## Current validation-v1 scope

| Domain | Benchmark | Method profile | Frozen scale |
|---|---|---|---:|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt | 20/10/30 |
| Document QA | OfficeQA Full | SkillOpt | 12/12/20 |
| Interactive | WebShop | SkillAdaptor | 5/5/20 |
| Longitudinal skill | SkillFlow-Task | SkillFlow | 3 families × 6 ordered tasks |

The four noise stages are independent arms: N1 task context, N2 environment evidence, N3 stored trajectory, and N4 update feedback. Validation-v1 expands to exactly 16 noisy cells and reuses frozen clean evidence.

## Setup

```bash
python -m pip install -e '.[test]'
cp .env.example .env
```

Leave `DEEPSEEK_API_KEY` empty for bootstrap, audit, materialization, dry-run, status, aggregate, and provider-free preflight. Add credentials only immediately before an explicitly approved paid run.

## Provider-free validation

```bash
python -m rsebench.cli validation preflight \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation status \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation aggregate \
  --matrix configs/validation/validation-v1.yaml
```

The current stage interfaces are frozen, but concrete `CELL_RUNNERS` are not implemented. Preflight therefore reports `execution_ready=false`, and `validation run` must fail closed before any provider call.

## Data and baseline bootstrap

```bash
bash scripts/download/baselines.sh
python scripts/download/datasets.py --profile core --resume
python scripts/materialize_splits.py
python scripts/audit_baselines.py
python scripts/audit_datasets.py
```

Large datasets, external checkouts, raw outputs, caches, and credentials are Git-ignored. Earlier generation, Core-1, clean-qualification, SkillLearn, and SkillFlow screening commands are historical reproduction paths; find them through the [experiment history](docs/archive/experiment-history/README.md).
