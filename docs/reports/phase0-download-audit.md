# Phase 0 Download and Materialization Audit

Date: 2026-08-12

This report distinguishes four states: `downloaded` means an upstream snapshot is
present; `materialized` means the paper subset was deterministically constructed;
`validated` means generated noise passed hard gates; `experiment-complete` requires
model execution and paired scoring. These states must not be conflated.

## Baseline repositories

All nine registered repositories are present under
`methods/external/`, have the expected origin, and are checked out at the pinned
commit. `scripts/audit_baselines.py` reports `present=True, verified=True` for every
row.

| Local name | Pinned commit | Role |
|---|---|---|
| Trace2Skill | `3d0b52a140f002a512930252b613c49048f7d5ac` | Spreadsheet self-evolution baseline |
| SkillOpt | `47fe269d75d3def79ffd90236261d26d84868ae5` | Multi-domain optimization baseline |
| SkillGrad | `9ecd0a633833a1cf21f6f94d8df42bcffaa66554` | Spreadsheet textual-gradient baseline |
| EvoSkill | `36f6f04952293d7054145550c2b9f0b0411bff1c` | OfficeQA/SealQA evolution baseline |
| Skills-Coach | `77dc5492d85e01cdaf145c0c04bd554d900266e5` | Generated-task skill optimizer |
| CoEvoSkills | `3171de28cc8d3c3bbbec0ef5445e59faca46815b` | SkillsBench paper artifact; runnable code is not released in this snapshot |
| FederatedSkill | `ddefb76a70e58659ba1869162f3d68b8cd6bdb1c` | SkillFlow federated/self-evolution runner |
| SkillsBench | `9a1f4dd5f7659f75707435da3ce854b6e48321d1` | Skill-native diagnostic benchmark |
| SkillFlow | `7b49ff5a7e26cd7706e959bfa0dba4746d18440d` | Skill-native sequential-task harness |

## Dataset snapshots

| Artifact | State | Resolved revision | Raw bytes | Materialized rows |
|---|---:|---|---:|---:|
| SpreadsheetBench Verified-400 | materialized | `ab0b742b0fc95b946f212d80ac7771b5531272e4` | 14,965,252 | 400 |
| DocVQA fixed SkillOpt subset | materialized | `539088ef8a8ada01ac8e2e6d4e372586748a265e` | 1,055,857,210 | 534 |
| DAPO deterministic subset | materialized | `65877096c24ffa7abc4e4fa5edb95cf3413a5674` | 299,367,526 | 1,000 |
| LiveMathematicianBench monthly data | downloaded | `6f53c5ff7227633ea954b2847cd590314d582047` | 3,900,099 | n/a |
| WikiTableQuestions | downloaded | `7d455a5a707b96341ef72aff9428749d443d8aa9` | 461,157,870 | upstream tree |
| MathArena/AIME data | downloaded | `a11194deff8c67a232974a383795e8a2776b4c6f` | 3,962,538 | upstream tree |
| SkillFlow-Task | downloaded | `ecaadb0e25d5d5cfd87bd86d81e77b4abe3a00bc` | 1,667,419,545 | 166 tasks |
| OfficeQA public evaluator code | downloaded | `7b9a3c154ef9fb40215bb67934afc43e6799de16` | 6,221,793 | n/a |
| OfficeQA full questions/corpus | materialized | `763a8366abf2a3605c381d53586d844dc60fa756` | 98,093,279 | 246 |

OfficeQA access was granted and the pinned snapshot is now materialized. The CSV
contains 246 questions and 214 unique `source_files` values; the extracted corpus
contains 1,393 files and occupies 383,187,672 bytes. Multi-document provenance is
material: 125 questions use one source document and 121 use between 2 and 12.
Noise validation therefore preserves every referenced document rather than
reducing each question to a single gold document. The EvoSkill 10-question demo is
retained only as a reproduction fixture and is not reported as formal OfficeQA.

## Frozen split manifests

The group-isolated split generator produced exact counts under `data/splits/`:

| Benchmark | Evolution | Pilot evolve | Pilot eval | Validation | Test | Group key |
|---|---:|---:|---:|---:|---:|---|
| SpreadsheetBench | 200 | 30 | 10 | 20 | 180 | task ID |
| OfficeQA | 50 | 12 | 8 | 24 | 172 | source files |
| DocVQA | 107 | 20 | 10 | 53 | 374 | document ID |
| DAPO | 400 | 30 | 20 | 100 | 500 | normalized problem hash |

Pilot IDs are nested in evolution and no group crosses evolution, validation, or
test. OfficeQA's 246 tasks form 101 source-document connected components. The
regenerated manifest has zero source documents crossing top-level partitions;
the superseded raw-string grouping had 55 such leaks and must not be reused.

## Reproduction commands

```bash
bash scripts/download/baselines.sh
python scripts/download/datasets.py --profile core --resume
python scripts/materialize_splits.py
python scripts/audit_baselines.py
python scripts/audit_datasets.py
python scripts/audit_skill_native.py
```
