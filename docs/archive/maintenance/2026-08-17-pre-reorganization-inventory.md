# Pre-reorganization inventory

> Captured: 2026-08-17 UTC
>
> Purpose: preserve the exact repository, release, evidence, and cleanup boundary before documentation and experiment-history reorganization.

## Git state

- Primary worktree: `/home/nvidia/yutao/lzt/self-evolution-robustness`
- Primary branch and HEAD: `main` at `bf8e1b611f269f3aaaea7a41a8e44dd87fa3cc11`
- User-owned untracked file: `docs/project-onboarding.md`
- `feature/rsebench-pilot` at `6fb608c14fb601cdf1c8a34421b6f114110740f6` is an ancestor of `main`.
- `fix/clean-qualification-baselines` at `3795c23f735d81ad10401a79e65626eaa7cf776a` is an ancestor of `main`.
- The primary branch was 62 commits ahead of the locally recorded `origin/main` at capture time. This inventory does not push or rewrite remote state.

Registered linked worktrees before cleanup:

| Worktree | Branch | HEAD | Dirty state |
|---|---|---|---|
| `.worktrees/rsebench-pilot` | `feature/rsebench-pilot` | `6fb608c` | tracked tree clean; ignored historical outputs present |
| `.worktrees/clean-qualification-fixes` | `fix/clean-qualification-baselines` | `3795c23` | one untracked execution plan |

## Frozen validation identities

The matrix embedded content hash remains:

```text
07e72a189af40c4436bf7f005a2eae2dd8b9790b54e5c20229bdc637182bf932
```

File SHA-256 values captured before reorganization:

```text
524c8a16cb6571bbd78493a63c9f8465458a95b11d7aa8040b6af14ebd215d33  configs/validation/validation-v1.yaml
e09a876f88d4663c60eb0fdebe83ed32fc182761fc562cac6de5915e1c6b37e7  benchmark/datasets/spreadsheet/spreadsheetbench_verified/releases/validation-v1/manifest.json
e52b1b84c5c534ee7d3e6e8e88807f1f95dc6f45286e220a549e978caff7c39e  benchmark/datasets/document/officeqa_full/releases/validation-v1/manifest.json
09c71b8063e4713d62085648df53959104acb6e2dee057b2f8f14009f72db4a6  benchmark/datasets/interactive/webshop/releases/validation-v1/manifest.json
aa4c7d400a33cf3f440a724c1f0dd5c3924c31409c2cabdb94dfb12582ed11d8  benchmark/datasets/skill/skillflow_tasks/releases/validation-v1/manifest.json
```

Embedded DatasetRelease identities:

| DatasetRelease | Content hash |
|---|---|
| `spreadsheetbench-verified-validation-v1` | `25c9d28c45a470add27b093d59c98e849fad5c6b82113110db531485a5e26632` |
| `officeqa-full-validation-v1` | `a87c3f436ad2ac7d4a0618bb1464a5560515944021c79b78192268cc382b63dd` |
| `webshop-validation-v1` | `c2678c6482d7cc3f43662ec34fe7fa562ab8a0a2af0ca02ec9a2487c0f11930d` |
| `skillflow-tasks-validation-v1` | `028f696980f7f0170da67a8c2969bab6addf14c3c2b6f739b4b47b0b04463c5d` |

Active MethodRelease identities:

| MethodRelease | Baseline fingerprint | Content hash |
|---|---|---|
| `skillopt-spreadsheet-validation-v1` | `b209b2686c902166e31062e6473075f5a87d1058759d81ce66f6864efafcc3a3` | `4e33580c96e2dac23f7d2f360c0312c1d2672522b834415fb856d4076a408e12` |
| `skillopt-officeqa-validation-v1` | `bbf775793ff2cc1e9f22b2c530a82957ba87d05749a50f6f53657c01549d9033` | `261c2dc38206efc173227ce8285240f3179b42ee2d977b60b559cd3d2365f4d1` |
| `skilladaptor-webshop-validation-v1` | `ebcfa0ccc76c5589bd95da3e7ae21a4065dd5e060f9abc207954e4cd750ef014` | `f8d55b9943a0a91f6cb084395839ac13aabe6165f289aadc79535eba8c04eaca` |
| `skillflow-validation-v1` | `e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875` | `e97deb7babd9016831d73a0ca2ca6a984996dab0c82687e173d13a887dcbfff8` |

The retained diagnostic release is `skilllearn-self-feedback-diagnostic-v1`, status `validated_inactive`, content hash `f2db4daed9813821e43cec604b5eace619e9a99b5cf360563ef5b2a2f909a6b0`.

## Frozen path dependencies

The following project paths are referenced by DatasetRelease or MethodRelease files and must not move in this reorganization:

```text
benchmark/validation/clean_qualification_v2/spreadsheetbench_verified.json
benchmark/validation/clean_qualification_v2/officeqa_full.json
benchmark/validation/clean_qualification_v2/webshop.json
benchmark/validation/skillflow_clean_qualification_v1/noise_validation_selection.json
benchmark/validation/skillflow_clean_qualification_v1/second_family_candidates_batch2.json
```

The SkillFlow selection manifest also records these evidence roots, which remain at their original paths:

```text
outputs/runs/skillflow-clean-qualification-v1-20260816-v4/attempts/screen-batch-a-r1-final-20260816/families/HWPX-Document-Automation/r1
outputs/runs/skillflow-hwpx-candidate-v1-20260816/attempts/confirm-r2
outputs/runs/skillflow-hwpx-candidate-v1-20260816/attempts/confirm-r3
outputs/runs/skillflow-hwpx-candidate-v1-20260816/attempts/confirm-r1-retry-after-disk-recovery
```

## Documentation counts

Counts include the newly approved reorganization spec and plan:

| Class | Count |
|---|---:|
| All files below `docs/` | 54 |
| Reports | 18 |
| Implementation plans | 18 |
| Design specs | 14 |

`docs/` occupied approximately 944 KB before the reorganization.

## Local storage counts

| Path | Size before cleanup | Policy |
|---|---:|---|
| `outputs/` | 1.4 GB | preserve paid/frozen evidence; index by phase |
| `data/` | 5.1 GB | retain active and candidate raw data in this pass |
| `methods/external/` | 6.8 GB | retain Git sources in this pass |
| `.worktrees/` | 168 MB | remove only after complete evidence recovery |
| `.venv/` | 364 MB | retain |
| `pytest-of-nvidia/` | 14 MB | approved rebuildable cleanup |

The Python editable install initially resolved `rsebench` from `.worktrees/rsebench-pilot/src`. Before implementation, it was reinstalled from the primary worktree and the full pytest baseline completed with exit code 0. This environment correction does not change tracked source.

## Worktree-only documents

The clean-qualification worktree contains one untracked document:

```text
.worktrees/clean-qualification-fixes/docs/superpowers/plans/2026-08-14-officeqa-webshop-clean-v2-execution.md
```

It must be copied byte-for-byte into `docs/archive/implementation-plans/` before that worktree is removed.

## Worktree-only experiment evidence

The pilot worktree contains approximately 117 MB of ignored output evidence. It includes more than the six paths cited by current reports:

- baseline compatibility smoke results for SkillOpt, SkillGrad, Trace2Skill, EvoSkill, Skills-Coach, SkillFlow, and FederatedSkill;
- clean-qualification-v1 results for Spreadsheet, OfficeQA, WebShop, and SkillLearn;
- expanded-N1 aggregate and paired runs;
- multiple Core-1 Spreadsheet, OfficeQA, WebShop, and SkillLearn structural/runtime smoke runs;
- report-cited expanded N1 and Core-1 result files missing from the primary `outputs/runs/` tree.

Therefore the complete `.worktrees/rsebench-pilot/outputs/` tree is classified as `historical-evidence` and must be copied into a checksum-verified local archive before worktree removal. The six report-cited run roots are additionally restored under their original `outputs/runs/` locators.

## Approved cleanup scope

- Reorganize and update tracked documentation.
- Build a phase-based historical experiment registry.
- Add the N1–N4 progress dashboard and four member-owned progress files.
- Recover complete worktree-only output evidence and the untracked execution plan.
- Remove repository-local Python/test caches and empty stale preflight output.
- Remove the two merged linked worktrees after recovery verification.
- Retain both historical branch refs.

## Explicitly excluded cleanup scope

- No compression or deletion of paid-run raw evidence.
- No deletion of candidate baseline Git repositories.
- No deletion of candidate benchmark raw data.
- No deletion of active benchmark materializations.
- No movement of release-referenced manifests or SkillFlow evidence roots.
- No modification of validation-v1 matrix, release identities, operators, provider settings, seeds, or runtime budgets.
