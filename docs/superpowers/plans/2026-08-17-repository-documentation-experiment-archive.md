# Repository Documentation and Experiment Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize RSEBench documentation and experiment history, add four independent N1–N4 progress-reporting pages, recover unique historical evidence, and remove only approved rebuildable local artifacts without changing validation-v1 identity.

**Architecture:** Current operational documentation moves into stable role-based directories, while superseded designs, plans, status snapshots, and experiment reports move into a dated archive. Historical experiments receive a phase registry that points to canonical manifests, reports, outputs, token records, and preservation classes; release-referenced paths remain in place. Destructive cleanup is limited to explicit cache targets and two merged worktrees after unique evidence has been copied and hash-verified.

**Tech Stack:** Markdown, YAML, Git, Bash, `rg`, `sha256sum`, RSEBench Python CLI, pytest, Ruff.

## Global Constraints

- Do not change any DatasetRelease content hash, MethodRelease identity, operator ID, matrix cell identity, provider setting, runtime budget, or frozen task ID.
- Preserve `configs/validation/validation-v1.yaml` content hash `07e72a189af40c4436bf7f005a2eae2dd8b9790b54e5c20229bdc637182bf932`.
- Preserve DatasetRelease content hashes: Spreadsheet `25c9d28c45a470add27b093d59c98e849fad5c6b82113110db531485a5e26632`, OfficeQA `a87c3f436ad2ac7d4a0618bb1464a5560515944021c79b78192268cc382b63dd`, WebShop `c2678c6482d7cc3f43662ec34fe7fa562ab8a0a2af0ca02ec9a2487c0f11930d`, SkillFlow `028f696980f7f0170da67a8c2969bab6addf14c3c2b6f739b4b47b0b04463c5d`.
- Keep `benchmark/validation/clean_qualification_v2/`, `benchmark/validation/skillflow_clean_qualification_v1/`, and every tracked `evidence_root` at their current paths.
- Treat `docs/project-onboarding.md` and `.worktrees/clean-qualification-fixes/docs/superpowers/plans/2026-08-14-officeqa-webshop-clean-v2-execution.md` as user-owned untracked documents until explicitly copied and reviewed.
- Do not compress or delete paid-run raw evidence, candidate baseline Git repositories, candidate benchmark raw data, or active benchmark materializations.
- Use `git mv` for tracked documentation moves and update all relative Markdown links in the same commit.
- Use `git worktree remove --force` only after the worktree's unique untracked files and output evidence have been copied and checksum-verified.
- Keep progress page filenames stable; real member names change only the `Owner` field.
- All timestamps written to experiment and progress records use UTC.
- Run provider-free checks only; no command in this plan may make a model call.

---

### Task 1: Capture the pre-reorganization identity and evidence inventory

**Files:**
- Create: `docs/archive/maintenance/2026-08-17-pre-reorganization-inventory.md`
- Read: `configs/validation/validation-v1.yaml`
- Read: `benchmark/datasets/*/*/releases/validation-v1/manifest.json`
- Read: `methods/validated/*/releases/*.json`

**Interfaces:**
- Consumes: current Git state, validation-v1 manifests, worktree registrations, tracked output locators.
- Produces: a human-readable inventory used as the before-state for Tasks 2, 8, and 9.

- [ ] **Step 1: Record the exact dirty state without staging the onboarding file**

Run:

```bash
git status --short
git worktree list --porcelain
git branch -vv
```

Expected: `docs/project-onboarding.md` is untracked; `main` contains spec commit `698c9c0`; both historical branches are ancestors of `main`.

- [ ] **Step 2: Verify both historical branches are merged**

Run:

```bash
git merge-base --is-ancestor feature/rsebench-pilot main
git merge-base --is-ancestor fix/clean-qualification-baselines main
```

Expected: both commands exit `0`.

- [ ] **Step 3: Capture frozen identities**

Run:

```bash
sha256sum configs/validation/validation-v1.yaml \
  benchmark/datasets/spreadsheet/spreadsheetbench_verified/releases/validation-v1/manifest.json \
  benchmark/datasets/document/officeqa_full/releases/validation-v1/manifest.json \
  benchmark/datasets/interactive/webshop/releases/validation-v1/manifest.json \
  benchmark/datasets/skill/skillflow_tasks/releases/validation-v1/manifest.json
rg -n '"content_hash"|"release_id"' benchmark/datasets/*/*/releases/validation-v1/manifest.json
```

Expected: the embedded DatasetRelease content hashes equal the four values in Global Constraints. Record the file SHA-256 values in the inventory; file SHA-256 and embedded content hash are intentionally different concepts.

- [ ] **Step 4: Record referenced paths that cannot move**

Run:

```bash
rg -n 'benchmark/validation/|outputs/runs/' \
  benchmark/datasets methods/validated configs/validation releases
```

Expected: the output includes clean-qualification-v2, SkillFlow selection manifests, and four SkillFlow evidence roots. Paste the exact path list into the inventory under `Frozen path dependencies`.

- [ ] **Step 5: Record size and uniqueness evidence**

Run:

```bash
du -sh docs outputs data methods/external .worktrees .venv pytest-of-nvidia
git -C .worktrees/clean-qualification-fixes status --short
git -C .worktrees/rsebench-pilot status --short
find .worktrees/rsebench-pilot/outputs/runs -maxdepth 4 -type f \
  \( -name aggregate.json -o -name result.json \) -print | sort
```

Expected: the clean-qualification worktree contains only its untracked execution plan; the pilot worktree contains the historical aggregate/results identified in the design.

- [ ] **Step 6: Write the inventory with fixed sections**

Create the parent directory, then use `apply_patch` to create the inventory with these headings and the exact command outputs collected above:

```bash
mkdir -p docs/archive/maintenance
```

```markdown
# Pre-reorganization inventory

## Git state
## Frozen validation identities
## Frozen path dependencies
## Documentation counts
## Local storage counts
## Worktree-only documents
## Worktree-only experiment evidence
## Approved cleanup scope
## Explicitly excluded cleanup scope
```

The approved scope is documentation moves, experiment indexing, progress pages, repository-local caches, and the two merged worktrees after evidence recovery. The excluded scope is paid evidence, candidate Git sources, candidate raw data, active materializations, and frozen locators.

- [ ] **Step 7: Verify and commit the inventory only**

Run:

```bash
git add docs/archive/maintenance/2026-08-17-pre-reorganization-inventory.md
git diff --cached --check
git commit -m "docs: inventory repository before archive reorganization"
```

Expected: one inventory file committed; `docs/project-onboarding.md` remains untracked.

---

### Task 2: Recover unique worktree documents and historical results

**Files:**
- Create: `docs/archive/implementation-plans/2026-08-14-officeqa-webshop-clean-v2-execution.md`
- Create locally: `outputs/runs/n1-expanded-20260813/`
- Create locally: `outputs/runs/core1-spreadsheet-n3-expanded/`
- Create locally: `outputs/runs/core1-spreadsheet-n3-applicable-confirm/`
- Create locally: `outputs/runs/core1-officeqa-n4-expanded/`
- Create locally: `outputs/runs/core1-screen-smoke-webshop-n1-structural/`
- Create locally: `outputs/runs/core1-screen-smoke-skilllearn-n3-fixed2/`
- Create locally: `outputs/archive/worktree-rsebench-pilot-20260817/`
- Create locally: `outputs/archive/2026-08-17-worktree-recovery/SHA256SUMS`

**Interfaces:**
- Consumes: untracked worktree plan and the complete worktree-only output tree identified in Task 1.
- Produces: a complete historical archive plus canonical main-worktree copies that satisfy existing report locators and permit safe worktree removal.

- [ ] **Step 1: Confirm every destination is absent**

Run:

```bash
for path in \
  outputs/archive/worktree-rsebench-pilot-20260817 \
  outputs/runs/n1-expanded-20260813 \
  outputs/runs/core1-spreadsheet-n3-expanded \
  outputs/runs/core1-spreadsheet-n3-applicable-confirm \
  outputs/runs/core1-officeqa-n4-expanded \
  outputs/runs/core1-screen-smoke-webshop-n1-structural \
  outputs/runs/core1-screen-smoke-skilllearn-n3-fixed2; do
  test ! -e "$path" || { echo "destination exists: $path"; exit 1; }
done
```

Expected: exit `0`. If any destination exists, compare it byte-for-byte and stop this task rather than overwrite it.

- [ ] **Step 2: Copy the unique execution plan**

Run:

```bash
mkdir -p docs/archive/implementation-plans
cp -a \
  .worktrees/clean-qualification-fixes/docs/superpowers/plans/2026-08-14-officeqa-webshop-clean-v2-execution.md \
  docs/archive/implementation-plans/2026-08-14-officeqa-webshop-clean-v2-execution.md
cmp \
  .worktrees/clean-qualification-fixes/docs/superpowers/plans/2026-08-14-officeqa-webshop-clean-v2-execution.md \
  docs/archive/implementation-plans/2026-08-14-officeqa-webshop-clean-v2-execution.md
```

Expected: `cmp` exits `0`.

- [ ] **Step 3: Copy the complete pilot output tree, then restore six report locators**

Run:

```bash
mkdir -p outputs/archive
cp -a .worktrees/rsebench-pilot/outputs outputs/archive/worktree-rsebench-pilot-20260817
cp -a outputs/archive/worktree-rsebench-pilot-20260817/runs/n1-expanded-20260813 outputs/runs/
cp -a outputs/archive/worktree-rsebench-pilot-20260817/runs/core1-spreadsheet-n3-expanded outputs/runs/
cp -a outputs/archive/worktree-rsebench-pilot-20260817/runs/core1-spreadsheet-n3-applicable-confirm outputs/runs/
cp -a outputs/archive/worktree-rsebench-pilot-20260817/runs/core1-officeqa-n4-expanded outputs/runs/
cp -a outputs/archive/worktree-rsebench-pilot-20260817/runs/core1-screen-smoke-webshop-n1-structural outputs/runs/
cp -a outputs/archive/worktree-rsebench-pilot-20260817/runs/core1-screen-smoke-skilllearn-n3-fixed2 outputs/runs/
```

Expected: the complete 117 MB historical output tree is archived and every report locator is restored without overwriting an existing destination.

- [ ] **Step 4: Hash-verify source and destination trees**

Run from the repository root:

```bash
mkdir -p outputs/archive/2026-08-17-worktree-recovery
find .worktrees/rsebench-pilot/outputs -type f -print0 | sort -z | xargs -0 sha256sum \
  > outputs/archive/2026-08-17-worktree-recovery/source.sha256
find outputs/archive/worktree-rsebench-pilot-20260817 -type f -print0 | sort -z | xargs -0 sha256sum \
  > outputs/archive/2026-08-17-worktree-recovery/destination.sha256
sed 's#\.worktrees/rsebench-pilot/##' \
  outputs/archive/2026-08-17-worktree-recovery/source.sha256 \
  > outputs/archive/2026-08-17-worktree-recovery/source.normalized.sha256
sed 's#outputs/archive/worktree-rsebench-pilot-20260817/#outputs/#' \
  outputs/archive/2026-08-17-worktree-recovery/destination.sha256 \
  > outputs/archive/2026-08-17-worktree-recovery/destination.normalized.sha256
cmp \
  outputs/archive/2026-08-17-worktree-recovery/source.normalized.sha256 \
  outputs/archive/2026-08-17-worktree-recovery/destination.normalized.sha256
cp outputs/archive/2026-08-17-worktree-recovery/destination.normalized.sha256 \
  outputs/archive/2026-08-17-worktree-recovery/SHA256SUMS
```

Expected: `cmp` exits `0`. The checksum ledger remains local and ignored with `outputs/`.

- [ ] **Step 5: Confirm formerly missing report paths now resolve**

Run:

```bash
test -f outputs/runs/n1-expanded-20260813/aggregate.json
test -f outputs/runs/core1-spreadsheet-n3-expanded/20260813T103149516404Z-skillopt/result.json
test -f outputs/runs/core1-spreadsheet-n3-applicable-confirm/20260813T104512125192Z-skillopt/result.json
test -f outputs/runs/core1-officeqa-n4-expanded/20260813T102616526997Z-skillopt/result.json
test -f outputs/runs/core1-screen-smoke-webshop-n1-structural/runs/interactive--webshop--N1/20260813T101255959755Z-skilladaptor/result.json
test -f outputs/runs/core1-screen-smoke-skilllearn-n3-fixed2/runs/skill_learning--skilllearnbench--N3/20260813T085057778905Z-skilllearn_self_feedback/result.json
```

Expected: every command exits `0`.

- [ ] **Step 6: Commit only the recovered historical plan**

Run:

```bash
git add docs/archive/implementation-plans/2026-08-14-officeqa-webshop-clean-v2-execution.md
git diff --cached --check
git commit -m "docs: recover clean qualification execution plan"
```

Expected: the local output copies remain ignored; the recovered plan is tracked.

---

### Task 3: Create current documentation navigation and four-member progress pages

**Files:**
- Create: `docs/README.md`
- Create: `docs/progress/README.md`
- Create: `docs/progress/templates/stage-progress-template.md`
- Create: `docs/progress/n1-task-context.md`
- Create: `docs/progress/n2-environment-evidence.md`
- Create: `docs/progress/n3-stored-trajectory.md`
- Create: `docs/progress/n4-update-feedback.md`
- Create: `docs/progress/archive/.gitkeep`

**Interfaces:**
- Consumes: validation-v1 matrix operator IDs and current `execution_ready=false` state.
- Produces: stable collaboration paths used by onboarding, roadmap, and future milestone snapshots.

- [ ] **Step 1: Create the documentation index**

Create the progress directories, then use `apply_patch` to create `docs/README.md` with these sections and links:

```bash
mkdir -p docs/progress/templates docs/progress/archive
```

```markdown
# RSEBench 文档索引

## 新协作者入口
- [项目入门](project-onboarding.md)
- [项目路线图](project-roadmap.md)
- [N1–N4 协作进度](progress/README.md)

## 当前架构与协议
- [Validation-v1 架构](architecture/validation-v1-architecture.md)
- [仓库布局](architecture/repository-layout.md)
- [数据与方法 release](protocols/dataset-and-method-release.md)
- [Noise stage 接口](protocols/noise-stage-interface.md)
- [Token、时间与结果合同](protocols/token-timing-and-result-contract.md)

## 运行与状态
- [Validation runbook](operations/validation-runbook.md)
- [协作者工作流](operations/collaborator-workflow.md)
- [当前项目状态](reports/current/current-project-status.md)
- [Validation-v1 冻结报告](reports/current/2026-08-17-validation-v1-freeze.md)

## 历史资料
- [文档归档说明](archive/README.md)
- [历史实验时间线](archive/experiment-history/README.md)
```

- [ ] **Step 2: Create the shared stage template**

Create `docs/progress/templates/stage-progress-template.md` with these exact headings:

```markdown
# Stage progress template

## Ownership and status
- Owner:
- Status:
- Last updated (UTC):
- Branch:
- Latest commit:

## Boundary and protected fields
## Four-benchmark progress
## Completed this cycle
## Current blockers
## Next three actions
## Decisions and coordination requests
## Provider, token, timing, and result records
## Handoff notes
```

The template is instructional; blank values are allowed only in this template, never in the four active stage pages.

- [ ] **Step 3: Create the exact N1 page**

Create `docs/progress/n1-task-context.md` with owner `member-1`, status `implementing`, last update `2026-08-17`, branch `not-assigned`, latest commit `7d95b87`, boundary `before the first action`, and protected fields `objective, gold, artifact, environment, verifier`. Use this table:

```markdown
| Benchmark | Operator | Unit tests | Protected-field audit | Preflight | Runner | Paid run | Result |
|---|---|---|---|---|---|---|---|
| Spreadsheet | `spreadsheet_n1_erroneous_handover` | interface tests pass | pending | structural pass | not registered | not started | none |
| OfficeQA | `officeqa_n1_one_axis_derivation` | interface tests pass | pending | structural pass | not registered | not started | none |
| WebShop | `webshop_n1_near_match_session` | interface tests pass | pending | structural pass | not registered | not started | none |
| SkillFlow | `skillflow_n1_unverified_prior_skill` | interface tests pass | pending | structural pass | not registered | not started | none |
```

Record completed work as the shared plugin interface and matrix IDs; blocker as missing benchmark-specific operators and `CELL_RUNNERS`; next actions as implement Spreadsheet, add protected-field audit, then register one provider-free runner. Record provider calls `0`, tokens `0`, and no paid result.

- [ ] **Step 4: Create the exact N2 page**

Create `docs/progress/n2-environment-evidence.md` with owner `member-2`, status `implementing`, last update `2026-08-17`, branch `not-assigned`, latest commit `7d95b87`, boundary `during execution`, and protected fields `gold reachability, original resource, official environment, verifier`. Use operator IDs:

```text
spreadsheet_n2_unlabeled_stale_sheet
officeqa_n2_conflicting_period_source
webshop_n2_promote_near_match
skillflow_n2_stale_same_family_artifact
```

Use the same seven gate values as N1. Record the blocker as missing immutable clean/noisy artifact materialization and runner registration; next actions are Spreadsheet materialization, artifact hash audit, and one provider-free runner.

- [ ] **Step 5: Create the exact N3 page**

Create `docs/progress/n3-stored-trajectory.md` with owner `member-3`, status `implementing`, last update `2026-08-17`, branch `not-assigned`, latest commit `7d95b87`, boundary `after rollout and reward, before reflection`, and protected fields `scalar reward, success, environment state, final result`. Use operator IDs:

```text
spreadsheet_n3_omit_workbook_edit
officeqa_n3_omit_oracle_source
webshop_n3_omit_constraint_event
skillflow_n3_omit_skill_use_event
```

Use `interface tests pass`, `pending`, `structural pass`, `not registered`, `not started`, and `none` for the six status columns. Record the blocker as missing method-specific selector/operator adapters; next actions are define replay-pack schema use, implement SkillOpt hook, and verify reward/result preservation.

- [ ] **Step 6: Create the exact N4 page**

Create `docs/progress/n4-update-feedback.md` with owner `member-4`, status `implementing`, last update `2026-08-17`, branch `not-assigned`, latest commit `7d95b87`, boundary `after feedback, before skill revision`, and protected fields `trajectory, scalar reward, official score, true environment state`. Use operator IDs:

```text
spreadsheet_n4_replace_blamed_range
officeqa_n4_replace_failure_axis
webshop_n4_replace_fault_step
skillflow_n4_replace_patch_attribution
```

Use the same gate values as N3. Record the blocker as missing feedback-boundary adapters; next actions are map four method hooks, implement SkillOpt attribution replacement, and verify trajectory/reward identity.

- [ ] **Step 7: Create the coordinator dashboard**

Create `docs/progress/README.md` with:

- one row for N1–N4, each status `implementing`, owner `member-1` through `member-4`, and link to its page;
- current shared milestone `register one provider-free runner for every stage`;
- shared blocker `CELL_RUNNERS are interface-only; execution_ready=false`;
- communication rules: update on state change, blocker, paid-run start, result completion, and at least once per active workday;
- snapshot rule `docs/progress/archive/YYYY-MM-DD-<milestone>/`;
- statement that machine-readable matrix/run status remains the executable source of truth.

- [ ] **Step 8: Verify and commit progress documentation**

Run:

```bash
rg -n '^## Ownership and status|^## Four-benchmark progress|^## Current blockers|^## Handoff notes' docs/progress/n*.md
rg -n 'spreadsheet_|officeqa_|webshop_|skillflow_' docs/progress/n*.md
git add docs/README.md docs/progress
git diff --cached --check
git commit -m "docs: add four-stage collaboration progress reports"
```

Expected: every active stage page has all four operator families and all required headings.

---

### Task 4: Update project entry points and current status

**Files:**
- Modify: `README.md`
- Modify and track: `docs/project-onboarding.md`
- Modify: `docs/project-roadmap.md`
- Modify: `benchmark/core1/README.md`
- Create: `docs/reports/current/current-project-status.md`

**Interfaces:**
- Consumes: validation-v1 freeze report, matrix, DatasetRelease/MethodRelease registries, progress dashboard.
- Produces: consistent collaborator-facing current-state entry points.

- [ ] **Step 1: Replace stale root README scope**

Update the first section so it states exactly:

```markdown
RSE-Bench evaluates whether skill self-evolution remains effective when task
context, environment evidence, stored trajectories, or update feedback contain
controlled noise. Validation-v1 covers SpreadsheetBench-Verified / SkillOpt,
OfficeQA Full / SkillOpt, WebShop / SkillAdaptor, and SkillFlow-Task / SkillFlow.
SkillLearnBench remains diagnostic history and is not the fourth active domain.
```

Replace the old pilot-first navigation with links to `docs/README.md`, onboarding, roadmap, current status, validation runbook, and progress dashboard. Keep setup commands. Mark old generation/pilot commands as historical and link to the experiment archive instead of presenting them as the current workflow.

- [ ] **Step 2: Update onboarding to the frozen state**

Preserve its research explanation and N1–N4 definitions, but replace Milestones 2–3 and current progress with these facts:

```text
M2 completed: four DatasetReleases and four MethodRelease profiles are frozen for validation-v1.
M3 current: four members implement N1–N4 operators and register CELL_RUNNERS.
Current execution boundary: structural preflight passes, execution_ready=false, provider calls remain zero.
```

Add the frozen scales `20/10/30`, `12/12/20`, `5/5/20`, and `3 families × 6 ordered tasks`. Add links to `docs/progress/README.md`, current status, freeze report, architecture, runbook, and archive. Keep the efficacy caveat: Spreadsheet and WebShop have selected positive clean controls, OfficeQA is a complete-update score tie, and SkillFlow has one local positive family plus two execution/update ties.

- [ ] **Step 3: Make the roadmap internally consistent**

Change every statement that calls M2 current to M3 current. Replace the superseded two-family SkillFlow gate with the approved mechanism-validation boundary. Keep the warning that validation-v1 is not a four-domain stable efficacy claim. In the pending-work checklist, make these the first four gates:

```markdown
- [ ] Implement benchmark-specific operators under each stage `operators/` directory.
- [ ] Add protected-field and applicability audits for all 16 cells.
- [ ] Register concrete `CELL_RUNNERS` and make structural preflight report `execution_ready=true` only when all required adapters exist.
- [ ] Run bounded per-stage validation before starting the complete 4×4 matrix.
```

Replace links to moved current/archive documents using their new paths.

- [ ] **Step 4: Mark Core-1 README as historical**

Add this warning directly below the title:

```markdown
> **Legacy diagnostic slice.** This directory preserves the earlier Core-1
> operator pilot whose fourth row was SkillLearnBench. The active validation-v1
> matrix uses SkillFlow-Task as the fourth domain and is defined by
> `configs/validation/validation-v1.yaml`. Do not start new formal runs from this
> README.
```

Keep old reproduction commands for historical replay and link to the current runbook.

- [ ] **Step 5: Create concise current project status**

Create the current-report directory and `docs/reports/current/current-project-status.md` with:

```bash
mkdir -p docs/reports/current
```

- date `2026-08-17 UTC`;
- the four DatasetRelease IDs and scales;
- the four active MethodRelease profile IDs;
- clean evidence boundary for each domain;
- `16 structural cells ready`, `139 artifact locators validated`, `execution_ready=false`, `provider calls=0`;
- completed infrastructure: releases, patch replay, isolated attempts, scheduler, CLI, timing/token contracts;
- current blockers: four concrete stage runner families;
- next gate: one provider-free executable cell per stage, then bounded paid validation;
- links to matrix, freeze report, progress dashboard, roadmap, and historical registry.

- [ ] **Step 6: Check stale-scope language**

Run:

```bash
rg -n '当前阶段.*M2|SkillLearnBench.*第四|fourth.*SkillLearn|SkillLearnBench is.*four' \
  README.md docs/project-onboarding.md docs/project-roadmap.md benchmark/core1/README.md \
  docs/reports/current/current-project-status.md
```

Expected: no unqualified statement identifies M2 or SkillLearn as current. The only SkillLearn hits explicitly say diagnostic or legacy.

- [ ] **Step 7: Commit entry-point updates**

Run:

```bash
git add README.md docs/project-onboarding.md docs/project-roadmap.md \
  benchmark/core1/README.md docs/reports/current/current-project-status.md
git diff --cached --check
git commit -m "docs: synchronize entry points with validation v1"
```

Expected: `docs/project-onboarding.md` becomes tracked without unrelated files being staged.

---

### Task 5: Promote current architecture, protocols, and runbooks

**Files:**
- Move: `docs/superpowers/specs/2026-08-17-validation-freeze-modular-matrix-design.md` → `docs/architecture/validation-v1-architecture.md`
- Create: `docs/architecture/repository-layout.md`
- Create: `docs/protocols/dataset-and-method-release.md`
- Move and update: `docs/core1-runtime-evidence-interface.md` → `docs/protocols/noise-stage-interface.md`
- Move and update: `docs/reports/token-accounting-status.md` → `docs/protocols/token-timing-and-result-contract.md`
- Create: `docs/operations/validation-runbook.md`
- Create: `docs/operations/collaborator-workflow.md`

**Interfaces:**
- Consumes: current validation code, matrix, release manifests, scheduler behavior, token/timing schemas.
- Produces: stable current documentation independent of completed implementation plans.

- [ ] **Step 1: Move the approved validation architecture**

Run:

```bash
mkdir -p docs/architecture docs/protocols docs/operations
git mv docs/superpowers/specs/2026-08-17-validation-freeze-modular-matrix-design.md \
  docs/architecture/validation-v1-architecture.md
```

Change its header status to `Current validation-v1 architecture` and add links to the matrix, current status, release protocol, noise-stage protocol, and runbook.

- [ ] **Step 2: Write repository layout documentation**

Document these ownership boundaries:

```text
benchmark/datasets/<domain>/<benchmark>/releases/  immutable active DatasetRelease
benchmark/validation/                               historical qualification evidence; stable referenced paths
methods/validated/                                  active or validated method releases and patches
methods/candidates/                                 methods excluded from current matrix
src/rsebench/noise/stages/n1..n4/                   stage-owned plugin interfaces and operators
src/rsebench/validation/                            shared matrix, scheduler, identity, status, aggregation
configs/validation/validation-v1.yaml               executable 4×4 source of truth
docs/progress/                                      human collaboration state
docs/archive/experiment-history/                    historical phase index
outputs/                                            ignored raw/preflight/run evidence
```

Explicitly prohibit stage owners from editing another stage or the central matrix merely to register an operator; registration occurs through the defined plugin surface.

- [ ] **Step 3: Write DatasetRelease and MethodRelease protocol**

Describe immutable IDs, embedded content hashes, portable locators, source-resource retention, patch series order, upstream revision, runtime identity, and the rule that moving a referenced project locator requires a new release rather than an in-place rewrite. List all current release IDs.

- [ ] **Step 4: Update the noise-stage interface**

Preserve reusable N3/N4 replay-pack details from the old Core-1 document, but make validation-v1 authoritative. Include:

- N1/N2 static preparation boundary;
- N3/N4 runtime mutation boundary;
- protected fields for each stage;
- plugin directory and `plugin.yaml` ownership;
- selector/operator/seed identity;
- `applicable=false` failure behavior;
- requirement that runtime outputs record input, output, audit, token, and UTC timing evidence;
- current operator IDs from all 16 matrix cells.

Mark old Core-1 operator implementations as historical references, not validation-v1 runners.

- [ ] **Step 5: Update token, timing, and result contract**

Preserve the unified ledger rules and add the current three-level timing requirement:

```text
run: started_at, completed_at, duration_seconds, status
cell/attempt: queued_at, started_at, completed_at, duration_seconds, status
provider call: started_at, completed_at, latency_seconds, prompt_tokens, completion_tokens, total_tokens, cached
```

Require UTC ISO-8601 timestamps, terminal records on failure, 100% token observation for paid calls, and separate provider, engine, and orchestration totals.

- [ ] **Step 6: Write validation runbook**

Include exact provider-free commands:

```bash
python -m rsebench.cli validation preflight --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation status --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation aggregate --matrix configs/validation/validation-v1.yaml
```

Include the paid command only under a warning and state that it must fail closed until `execution_ready=true`:

```bash
python -m rsebench.cli validation run \
  --matrix configs/validation/validation-v1.yaml \
  --max-parallel 16 \
  --confirm-provider-cost
```

Document attempt isolation, same-baseline serialization only when a shared checkout is mutated, cross-benchmark parallelism, resume identity checks, and aggregate inputs.

- [ ] **Step 7: Write collaborator workflow**

Document one branch per stage, one owner per progress page, no direct external source edits, patches recorded in MethodRelease, no provider calls in PR validation, required unit/static/preflight checks, and coordinator-owned dashboard updates. Include the exact handoff checklist: commit, operator ID, matrix cell, tests, protected-field audit, output locator, token/timing status, blocker, next action.

- [ ] **Step 8: Fix links and commit current references**

Run:

```bash
rg -l 'superpowers/specs/2026-08-17-validation-freeze-modular-matrix-design.md|core1-runtime-evidence-interface.md|reports/token-accounting-status.md' README.md docs benchmark methods
```

Update every returned current document to the new paths. Then run:

```bash
git add docs README.md benchmark methods
git diff --cached --check
git commit -m "docs: promote validation architecture and operating protocols"
```

Expected: no current document links to the three old paths.

---

### Task 6: Archive superseded designs and completed implementation plans

**Files:**
- Create: `docs/archive/README.md`
- Move: all remaining `docs/superpowers/specs/*.md` → `docs/archive/design-specs/`
- Move: all existing `docs/superpowers/plans/*.md` → `docs/archive/implementation-plans/`
- Move: `docs/plans/next-validation-experiments.md` → `docs/archive/implementation-plans/2026-08-13-next-validation-experiments.md`

**Interfaces:**
- Consumes: completed/superseded specs and plans after current architecture was promoted in Task 5.
- Produces: role-classified, ISO-date-sorted historical documentation.

- [ ] **Step 1: Create archive policy**

Create `docs/archive/README.md` defining:

- design specs explain why a historical design was chosen;
- implementation plans explain how a completed change was built;
- status snapshots preserve point-in-time state and are not current instructions;
- experiment history preserves evidence and conclusions by phase;
- filenames retain ISO dates;
- archived commands may no longer be current;
- machine-readable release/matrix files override prose when identities differ.

- [ ] **Step 2: Move every remaining design spec**

Run:

```bash
mkdir -p docs/archive/design-specs docs/archive/implementation-plans
for path in docs/superpowers/specs/*.md; do
  git mv "$path" docs/archive/design-specs/
done
```

Expected moved files include the original benchmark design through the repository-reorganization design. The validation-v1 architecture file is absent because Task 5 already promoted it.

- [ ] **Step 3: Move every implementation plan**

Run:

```bash
for path in docs/superpowers/plans/*.md; do
  git mv "$path" docs/archive/implementation-plans/
done
git mv docs/plans/next-validation-experiments.md \
  docs/archive/implementation-plans/2026-08-13-next-validation-experiments.md
```

The current plan moves to `docs/archive/implementation-plans/2026-08-17-repository-documentation-experiment-archive.md`; continue execution from that stable destination.

- [ ] **Step 4: Repair links to historical designs and plans**

Run:

```bash
rg -n 'docs/superpowers|superpowers/specs|superpowers/plans|docs/plans/next-validation-experiments' \
  README.md docs benchmark methods
```

For current docs, link the promoted current architecture/protocol when that is the intended target. For historical reports, link the corresponding archived filename. Repeat the command until no stale path remains.

- [ ] **Step 5: Verify date ordering and commit**

Run:

```bash
find docs/archive/design-specs docs/archive/implementation-plans -maxdepth 1 -type f -printf '%f\n' | sort
git add docs
git diff --cached --check
git commit -m "docs: archive superseded designs and plans"
```

Expected: no files remain under `docs/superpowers/` or `docs/plans/`.

---

### Task 7: Archive reports by project phase and build the experiment registry

**Files:**
- Move historical reports from: `docs/reports/`
- Move: `docs/reports/current-experiment-status.md` → `docs/archive/status-snapshots/2026-08-17-current-experiment-status.md`
- Move: `docs/reports/2026-08-17-validation-v1-freeze.md` → `docs/reports/current/2026-08-17-validation-v1-freeze.md`
- Create: `docs/archive/experiment-history/README.md`
- Create: `docs/archive/experiment-history/registry.yaml`
- Create: phase `README.md` files under all seven phase directories

**Interfaces:**
- Consumes: historical reports, manifests, configs, restored outputs, current freeze report.
- Produces: chronological experiment navigation and machine-readable preservation metadata.

- [ ] **Step 1: Move foundation reports**

Run:

```bash
mkdir -p \
  docs/archive/status-snapshots \
  docs/archive/experiment-history/00-foundation-and-audits \
  docs/archive/experiment-history/01-api-pilot-and-initial-noise \
  docs/archive/experiment-history/02-expanded-n1 \
  docs/archive/experiment-history/03-clean-qualification-and-repairs \
  docs/archive/experiment-history/04-stable-split-and-skilllearn-screening \
  docs/archive/experiment-history/05-skillflow-screening \
  docs/archive/experiment-history/06-validation-v1-freeze
git mv docs/reports/phase0-download-audit.md \
  docs/archive/experiment-history/00-foundation-and-audits/2026-08-12-phase0-download-audit.md
git mv docs/reports/baseline-benchmark-audit.md \
  docs/archive/experiment-history/00-foundation-and-audits/2026-08-12-baseline-benchmark-audit.md
git mv docs/reports/pilot-readiness.md \
  docs/archive/experiment-history/00-foundation-and-audits/2026-08-12-pilot-readiness.md
```

- [ ] **Step 2: Move pilot and expanded-N1 reports**

Run:

```bash
git mv docs/reports/core1-validation-status.md \
  docs/archive/experiment-history/01-api-pilot-and-initial-noise/2026-08-13-core1-validation-status.md
git mv docs/reports/2026-08-13-expanded-n1-validation.md \
  docs/archive/experiment-history/02-expanded-n1/2026-08-13-expanded-n1-validation.md
```

- [ ] **Step 3: Move clean qualification reports**

Run:

```bash
for file in \
  2026-08-14-clean-v1-diagnostic-archive.md \
  2026-08-14-clean-v2-canaries.md \
  2026-08-14-skilllearn-v2-offline-audit.md \
  2026-08-15-clean-v2-and-fixed-artifact-replay.md \
  2026-08-15-task5-qualification-hardening.md \
  2026-08-15-task6-portable-selection-release.md; do
  git mv "docs/reports/$file" "docs/archive/experiment-history/03-clean-qualification-and-repairs/$file"
done
```

- [ ] **Step 4: Move stable-split and skill-domain reports**

Run:

```bash
for file in \
  2026-08-15-skilllearn-expanded-clean-selection.md \
  2026-08-15-stable-noise-validation-splits.md \
  2026-08-16-skilllearn-clean-expansion-round2.md; do
  git mv "docs/reports/$file" "docs/archive/experiment-history/04-stable-split-and-skilllearn-screening/$file"
done
git mv docs/reports/2026-08-16-skillflow-clean-screening.md \
  docs/archive/experiment-history/05-skillflow-screening/2026-08-16-skillflow-clean-screening.md
```

- [ ] **Step 5: Move current report and historical status snapshot**

Run:

```bash
git mv docs/reports/current-experiment-status.md \
  docs/archive/status-snapshots/2026-08-17-current-experiment-status.md
git mv docs/reports/2026-08-17-validation-v1-freeze.md \
  docs/reports/current/2026-08-17-validation-v1-freeze.md
```

Add a first-paragraph warning to the status snapshot that it contains cumulative historical state and has been superseded by `docs/reports/current/current-project-status.md`.

- [ ] **Step 6: Create phase READMEs**

Each phase README contains, in chronological order: phase purpose, date range, canonical reports, configs, manifests, output roots, conclusion boundary, and the next phase. Use these exact phase ranges:

```text
00: 2026-08-11 to 2026-08-12
01: 2026-08-12 to 2026-08-13
02: 2026-08-13
03: 2026-08-13 to 2026-08-15
04: 2026-08-15 to 2026-08-16
05: 2026-08-16
06: 2026-08-17
```

Phase 06 links the current freeze report rather than copying it into the archive.

- [ ] **Step 7: Create the registry schema and records**

Create `registry.yaml` with this exact top-level shape and one list item for every output root below:

```yaml
schema_version: rsebench.experiment-history.v1
experiments:
  - experiment_id: generation
    phase: 01-api-pilot-and-initial-noise
    date: 2026-08-12
    purpose: offline and model-backed noise generation calibration
    benchmarks: [spreadsheetbench_verified, officeqa, docvqa, dapo_math]
    baselines: []
    status: completed
    conclusion: generation artifacts passed structural checks but did not establish a cross-domain self-evolution noise effect
    config: configs/pilot/
    input_manifest: benchmark/registry/benchmarks.yaml
    output_root: outputs/runs/generation
    canonical_report: docs/archive/experiment-history/00-foundation-and-audits/2026-08-12-pilot-readiness.md
    token_and_timing_record: outputs/runs/generation
    preservation_class: historical-evidence
    superseded_by: validation-v1
```

Every later record uses the same fields and scalar/list types. Determine `status` from terminal aggregate/result evidence: use `completed` when a terminal result exists, `incomplete` when it does not, and never infer success from directory presence. Use the phase report's explicit conclusion; do not create a stronger claim. Use `null` when no config, input manifest, report, or token/timing record exists.

Use this exact phase assignment:

```text
01-api-pilot-and-initial-noise:
  generation
  pilot-a
  paired-evolution
  evolution-noise
  officeqa-calibration
  expanded-evaluation
  difficulty-probe

02-expanded-n1:
  n1-expanded-20260813
  core1-spreadsheet-n3-expanded
  core1-spreadsheet-n3-applicable-confirm
  core1-officeqa-n4-expanded
  core1-screen-smoke-webshop-n1-structural
  core1-screen-smoke-skilllearn-n3-fixed2

03-clean-qualification-and-repairs:
  clean-v2-20260814
  clean-v2-canary-20260814
  clean-v2-canary-officeqa-confirmation-20260814
  clean-v2-canary-officeqa-retry-20260814
  clean-v2-canary-officeqa-retry2-20260814
  skillopt-fixed-replay-20260815

04-stable-split-and-skilllearn-screening:
  noise-screen-v1-qualification
  skilllearn-clean-expanded-v1-20260815
  skilllearn-clean-expansion-round2-20260816
  skilllearn-recovery-round2-20260816

05-skillflow-screening:
  skillflow-clean-qualification-v1-20260816
  skillflow-clean-qualification-v1-20260816-v2
  skillflow-clean-qualification-v1-20260816-v3
  skillflow-clean-qualification-v1-20260816-v4
  skillflow-hwpx-candidate-v1-20260816
  skillflow-second-family-screen-v1-20260816
  skillflow-second-family-screen-v2-20260816
  skillflow-second-family-screen-v3-20260816
  skillflow-second-family-screen-v4-20260816
```

Set the four SkillFlow evidence-bearing roots referenced by `noise_validation_selection.json` to `frozen-evidence`. Set `clean-v2-20260814`, `skillopt-fixed-replay-20260815`, `n1-expanded-20260813`, and all report-cited Core-1 roots to `historical-evidence`. Set superseded failed retries and incomplete v3 roots to `rebuildable-intermediate`, but do not delete them in this task.

- [ ] **Step 8: Create the history overview**

`docs/archive/experiment-history/README.md` contains a seven-row phase table with date range, goal, principal conclusion, canonical report, and current relevance. It states that logical archive phase does not imply physical movement when a frozen locator requires the original path.

- [ ] **Step 9: Repair report and project links**

Run:

```bash
rg -n 'docs/reports/|reports/2026-|reports/core1|reports/phase0|reports/pilot|reports/baseline' \
  README.md docs benchmark methods
```

Update every current link. Historical archived documents may link to adjacent archived files using correct relative paths. Preserve output locators that now resolve after Task 2.

- [ ] **Step 10: Commit the report archive and registry**

Run:

```bash
git add docs README.md benchmark methods
git diff --cached --check
git commit -m "docs: archive experiment history by project phase"
```

Expected: `docs/reports/` contains only `current/`; historical reports are reachable through the phase README and registry.

---

### Task 8: Remove approved rebuildable artifacts and merged worktrees

**Files/directories removed locally:**
- `.pytest_cache/`
- `.ruff_cache/`
- `pytest-of-nvidia/`
- `src/rsebench.egg-info/`
- `outputs/preflight/task7-stale/`
- `outputs/cache/model/`
- source-tree `__pycache__/` under `scripts/`, `src/`, and `tests/`
- `.worktrees/clean-qualification-fixes/`
- `.worktrees/rsebench-pilot/`
- Create: `docs/archive/maintenance/2026-08-17-reorganization-cleanup-report.md`

**Interfaces:**
- Consumes: Task 1 inventory and Task 2 checksum-verified copies.
- Produces: a smaller local repository and an auditable cleanup report; Git branches remain intact.

- [ ] **Step 1: Reconfirm worktree branches and recovered files**

Run:

```bash
git merge-base --is-ancestor feature/rsebench-pilot main
git merge-base --is-ancestor fix/clean-qualification-baselines main
cmp \
  .worktrees/clean-qualification-fixes/docs/superpowers/plans/2026-08-14-officeqa-webshop-clean-v2-execution.md \
  docs/archive/implementation-plans/2026-08-14-officeqa-webshop-clean-v2-execution.md
test -f outputs/archive/2026-08-17-worktree-recovery/SHA256SUMS
test -f outputs/runs/n1-expanded-20260813/aggregate.json
```

Expected: every command exits `0`.

- [ ] **Step 2: Record before-cleanup sizes**

Run:

```bash
du -sh .pytest_cache .ruff_cache pytest-of-nvidia src/rsebench.egg-info \
  outputs/preflight/task7-stale outputs/cache/model .worktrees
```

Record exact values in the cleanup report under `Before`.

- [ ] **Step 3: Remove only explicit rebuildable targets**

Run:

```bash
rm -rf -- \
  .pytest_cache \
  .ruff_cache \
  pytest-of-nvidia \
  src/rsebench.egg-info \
  outputs/preflight/task7-stale \
  outputs/cache/model
find scripts src tests -type d -name __pycache__ -prune -exec rm -rf -- {} +
```

Expected: the listed targets no longer exist; `.venv`, `methods/external`, `data`, and all other `outputs` remain.

- [ ] **Step 4: Remove the two registered worktrees**

Run:

```bash
git worktree remove --force .worktrees/clean-qualification-fixes
git worktree remove --force .worktrees/rsebench-pilot
git worktree prune
git worktree list --porcelain
```

Expected: only the primary worktree remains registered. Do not delete the two branch refs.

- [ ] **Step 5: Write cleanup report**

Create the report with:

```markdown
# Repository reorganization cleanup report

## Scope approved
## Evidence recovered before deletion
## Removed paths and sizes
## Retained high-volume paths
## Frozen paths intentionally unchanged
## Git branches retained
## Recovery procedure
## Verification results
```

Recovery procedure states that worktree source can be recreated from the retained branch refs, while recovered raw evidence is verified by `outputs/archive/2026-08-17-worktree-recovery/SHA256SUMS`.

- [ ] **Step 6: Commit the cleanup report**

Run:

```bash
git add docs/archive/maintenance/2026-08-17-reorganization-cleanup-report.md
git diff --cached --check
git commit -m "docs: record repository cleanup and evidence recovery"
```

Expected: cleanup affects ignored local paths plus one tracked report.

---

### Task 9: Run final identity, documentation, and regression verification

**Files:**
- Modify if necessary: links or status text found by verification
- Read: all files changed by Tasks 1–8

**Interfaces:**
- Consumes: reorganized documentation, historical registry, retained manifests, current code.
- Produces: verified final repository state with no new provider calls.

- [ ] **Step 1: Verify frozen matrix and release identities**

Run:

```bash
rg -n '^content_hash: 07e72a189af40c4436bf7f005a2eae2dd8b9790b54e5c20229bdc637182bf932$' \
  configs/validation/validation-v1.yaml
rg -n '25c9d28c45a470add27b093d59c98e849fad5c6b82113110db531485a5e26632' \
  benchmark/datasets/spreadsheet/spreadsheetbench_verified/releases/validation-v1/manifest.json
rg -n 'a87c3f436ad2ac7d4a0618bb1464a5560515944021c79b78192268cc382b63dd' \
  benchmark/datasets/document/officeqa_full/releases/validation-v1/manifest.json
rg -n 'c2678c6482d7cc3f43662ec34fe7fa562ab8a0a2af0ca02ec9a2487c0f11930d' \
  benchmark/datasets/interactive/webshop/releases/validation-v1/manifest.json
rg -n '028f696980f7f0170da67a8c2969bab6addf14c3c2b6f739b4b47b0b04463c5d' \
  benchmark/datasets/skill/skillflow_tasks/releases/validation-v1/manifest.json
```

Expected: exactly one match per frozen identity.

- [ ] **Step 2: Run provider-free validation preflight**

Run:

```bash
python -m rsebench.cli validation preflight \
  --matrix configs/validation/validation-v1.yaml
```

Expected: 16 structural cells, 139 artifact locators, four release patch replays, `execution_ready=false`, and provider calls `0`.

- [ ] **Step 3: Check all relative Markdown links**

Run:

```bash
rg -n '\]\((?!https?://|#|mailto:)[^)]+\)' README.md docs benchmark methods --pcre2
```

For every returned link, resolve the target relative to its containing Markdown file. Fix any missing target using `apply_patch`. Then run:

```bash
rg -n 'docs/superpowers|superpowers/specs|superpowers/plans|docs/plans/|reports/current-experiment-status.md' \
  README.md docs benchmark methods
```

Expected: no stale path remains. References inside archived prose must also point to the new archive path or be explicitly labeled as a historical literal path.

- [ ] **Step 4: Validate progress and registry completeness**

Run:

```bash
for stage in n1-task-context n2-environment-evidence n3-stored-trajectory n4-update-feedback; do
  test -f "docs/progress/$stage.md"
  rg -q '^## Ownership and status' "docs/progress/$stage.md"
  rg -q '^## Four-benchmark progress' "docs/progress/$stage.md"
  rg -q '^## Current blockers' "docs/progress/$stage.md"
  rg -q '^## Handoff notes' "docs/progress/$stage.md"
done
rg -n '^  - experiment_id:' docs/archive/experiment-history/registry.yaml
```

Expected: four complete progress files and one registry record for every root listed in Task 7 Step 7.

- [ ] **Step 5: Run focused and full tests**

Run:

```bash
pytest -q tests/datasets tests/methods tests/noise tests/validation
pytest -q
```

Expected: focused suites pass; full suite matches or exceeds the previous `876 passed` result, with no new failures. Existing 12 legacy deprecation warnings may remain.

- [ ] **Step 6: Run style and diff checks**

Run:

```bash
git diff --check
ruff check scripts src tests
git status --short
```

Expected: `git diff --check` passes. Ruff may still report only the previously known unrelated failures in `scripts/run_paired_skilllearn.py`, `tests/adapters/test_evoskill.py`, and `tests/skillflow/test_runner.py`; no new file may add a violation. Git status contains only intentional verification fixes, if any.

- [ ] **Step 7: Commit verification fixes if present**

If Step 3–6 required link or status corrections, run:

```bash
git add README.md docs benchmark methods
git diff --cached --check
git commit -m "docs: fix archive links after verification"
```

If there are no corrections, do not create an empty commit.

- [ ] **Step 8: Produce the final handoff summary**

Report:

- final commit range;
- current doc entry points;
- progress dashboard and four stage pages;
- historical registry and phase directories;
- recovered worktree-only evidence;
- paths removed and disk space recovered;
- unchanged validation identities;
- provider-free preflight result;
- focused/full pytest result;
- known pre-existing Ruff findings;
- explicit statement that paid raw evidence, candidate sources, candidate raw data, and frozen paths were not deleted.
