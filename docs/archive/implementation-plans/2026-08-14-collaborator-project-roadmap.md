# RSEBench 协作者项目路线图实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一份中文协作者入口文档，准确说明当前 Core-1 benchmark、baseline、N1–N4 加噪矩阵、实验门槛和后续工作，并从根 README 提供入口。

**Architecture:** `docs/project-roadmap.md` 是人类可读的权威路线图，但所有可执行事实仍以 active registry 和实验 YAML 为机器真源。文档把当前 Core-1 与候选扩展分开，用一张四领域 × 四阶段矩阵连接噪声设计与实现，并用依赖式工作清单指导后续贡献。

**Tech Stack:** GitHub-flavored Markdown、YAML registry/config、Bash/rg、pytest。

## Global Constraints

- 正文使用中文，保留正式 benchmark、baseline、schema、metric 和 status 名称的英文写法。
- 当前正文范围仅包含 SpreadsheetBench-Verified、OfficeQA Full、WebShop 和 SkillLearnBench 四个 active Core-1 benchmark。
- 数学、DocVQA、WikiTableQuestions、SearchQA、SealQA、SkillsBench 和 SkillFlow-Task 只能出现在候选扩展区。
- 当前 reference baseline 是 SkillOpt、SkillAdaptor、SkillLearnBench self-feedback，以及 N4 使用的 teacher-feedback。
- N1/N2 是静态 paired artifact；N3/N4 是确定性 runtime mutation；四个阶段是独立实验 arm。
- Clean-v2 与 Core-1 pilot 的样本规模必须分开标注。
- 不把 process 可启动、单次 positive signal、单 family 结果或 zero-update run 表述为稳定 efficacy 结论。
- 所有链接使用仓库相对路径；不得写入 credential、本机绝对路径或仅在 gitignored output 中存在的证据。

---

## 文件结构

- Create: `docs/project-roadmap.md` — 协作者阅读的项目目标、当前范围、方法、噪声矩阵、实验门槛和工作清单。
- Modify: `README.md` — 更新过时的阶段描述，并加入项目路线图入口。
- Reference: [collaborator roadmap design](../design-specs/2026-08-14-collaborator-project-roadmap-design.md) — 已批准的范围和章节职责。
- Reference: `benchmark/registry/{benchmarks,methods,adapters,noise_operators}.yaml` — active 状态、仓库 revision、方法角色和 operator 的机器真源。
- Reference: `configs/experiments/clean-v2.yaml` — clean-v2 四单元规模、runtime 和三固定 seed。
- Reference: `configs/core1/{spreadsheetbench_verified,officeqa,skilllearnbench,webshop}/N{1,2,3,4}.yaml` — 16 个 Core-1 operator 单元。

### Task 1: 撰写协作者项目路线图

**Files:**
- Create: `docs/project-roadmap.md`
- Reference: [collaborator roadmap design](../design-specs/2026-08-14-collaborator-project-roadmap-design.md)
- Reference: `benchmark/registry/benchmarks.yaml`
- Reference: `benchmark/registry/methods.yaml`
- Reference: `benchmark/registry/adapters.yaml`
- Reference: `benchmark/registry/noise_operators.yaml`
- Reference: `configs/experiments/clean-v2.yaml`
- Reference: `configs/core1/*/N*.yaml`

**Interfaces:**
- Consumes: active registry entries、clean-v2 task counts、Core-1 operator/protected-field 定义和已批准的文档设计。
- Produces: 一个包含且仅包含四个当前 Core-1 benchmark、16 个 operator 单元、baseline 状态层级和依赖式工作清单的 Markdown 文件。

- [ ] **Step 1: 生成写作前事实清单**

Run:

```bash
rg -n 'active: true|tier: core1|primary_method:' \
  benchmark/registry/benchmarks.yaml benchmark/registry/methods.yaml
rg -n '^  - key:|task_counts:|method_seeds:' configs/experiments/clean-v2.yaml
rg -n '^operator:|^protected_fields:' configs/core1/*/N*.yaml
```

Expected:

- active Core-1 benchmark 恰好为 `spreadsheetbench_verified`、`officeqa_full`、`skilllearnbench`、`webshop`；
- clean-v2 包含三个 method seed 和四个 cell；
- Core-1 配置输出 16 个 `operator:`，每个配置均声明 protected fields 或由静态 paired-artifact contract 保护原始 task/verifier。

- [ ] **Step 2: 创建路线图并写入固定章节**

Create `docs/project-roadmap.md` with these headings in this exact order:

```markdown
# RSEBench 项目路线图

## 1. 项目目标
## 2. 当前 Core-1 范围
## 3. Benchmark 介绍
## 4. Baseline 方法
## 5. N1–N4 加噪模型
## 6. 四领域加噪矩阵
## 7. 实验协议与晋级门槛
## 8. 当前状态与已知限制
## 9. 协作者后续任务
## 10. 可复现性与仓库索引
## 11. 候选扩展
```

The Core-1 summary must contain these exact rows:

```markdown
| 领域 | Benchmark | 当前 reference baseline | Clean-v2 规模（train/validation/test） |
|---|---|---|---:|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt | 20/10/30 |
| Document QA | OfficeQA Full | SkillOpt | 12/12/20 |
| Interactive | WebShop | SkillAdaptor | 5/5/20 |
| Skill Learning | SkillLearnBench (`offer-letter-generator`) | self-feedback | 2/1/3 |
```

The baseline section must use these status tiers:

```markdown
| 层级 | 方法 | 原生/主要领域 | 文档中的状态 |
|---|---|---|---|
| 当前 reference | SkillOpt | Spreadsheet、Document QA | active；当前 clean-v2 reference |
| 当前 reference | SkillAdaptor | Interactive/WebShop | active；当前 clean-v2 reference |
| 当前 reference | SkillLearnBench self-/teacher-feedback | Skill Learning | active；teacher-feedback 主要用于 N4 |
| 计划 comparison | Trace2Skill、SkillGrad | Spreadsheet | inactive；待统一 harness 正式验证 |
| 计划 comparison | EvoSkill | Document QA | inactive；待 shared OfficeQA manifest adapter |
| 计划 comparison | RethinkSkill | Interactive/WebShop | inactive secondary baseline |
| 计划 diagnostic | Skills-Coach、SkillFlow、FederatedSkill | Skill-native | inactive；不替代四域主结果 |
| 研究参考 | CoEvoSkills | Skill-native | paper-only |
```

The noise matrix must represent these 16 cells exactly once:

```markdown
| Benchmark | N1：task context | N2：environment evidence | N3：stored trajectory | N4：update feedback |
|---|---|---|---|---|
| SpreadsheetBench-Verified | `spreadsheet_n1_erroneous_handover`：改变一个真实约束 | `spreadsheet_n2_unlabeled_stale_sheet`：加入未标注旧版语义 sheet | `spreadsheet_n3_omit_workbook_edit`：删除一个 workbook-write event | `spreadsheet_n4_replace_blamed_range`：把归因指向同形状 decoy range |
| OfficeQA Full | `officeqa_n1_one_axis_derivation`：改变 period/unit/aggregation 中一轴 | `officeqa_n2_conflicting_period_source`：把同主题冲突时期来源排入 top-3 | `officeqa_n3_omit_oracle_source`：删除一次 oracle source open/read event | `officeqa_n4_replace_failure_axis`：替换 source/period/unit/aggregation 归因 |
| SkillLearnBench | `skilllearn_n1_brittle_handover`：诱导 acquisition instance 的固定捷径 | `skilllearn_n2_competing_stale_resource`：加入旧资源但不改变 hidden tests | `skilllearn_n3_omit_artifact_event`：删除一次 artifact-producing event | `skilllearn_n4_replace_revision_diagnosis`：把诊断目标换成同类 decoy step |
| WebShop | `webshop_n1_near_match_session`：推荐违反一个 hard constraint 的真实近邻商品 | `webshop_n2_promote_near_match`：提升近邻排序但保留可达 valid target | `webshop_n3_omit_constraint_event`：删除 required-option/query-refinement event | `webshop_n4_replace_fault_step`：把 actionable fault 定位到另一 eligible step |
```

Immediately after the operator matrix, include this protected-invariant matrix:

```markdown
| Benchmark | N1 保护项 | N2 保护项 | N3 保护项 | N4 保护项 |
|---|---|---|---|---|
| SpreadsheetBench-Verified | 原 instruction、workbook、gold range、verifier | 全部 original sheet digest、answer workbook、verifier | reward、success、task/environment、save event、final response | trajectory、scalar reward、verifier score、result files |
| OfficeQA Full | question、answer、released sources、oracle page、official scorer | oracle 保留且可访问、answer 和 retrieval budget | reward、success、question、retrieved documents、final answer | trajectory、scalar reward、retrieved text、answer、official score |
| SkillLearnBench | instruction、official environment、hidden tests、reference solution | original resource、official environment、hidden tests | reward、success、instruction、environment、hidden tests、reference solution | trajectory、scalar reward、hidden tests、verifier details |
| WebShop | original goal、catalog、reward function、target reachability | catalog record、valid action、valid target reachability | reward、success、goal、catalog、valid actions、reward function | trajectory、scalar reward、reward/success、goal、catalog |
```

Then state the shared mutation rule:

```markdown
所有 operator 的 mutation budget 均为 1。原始 task identity、gold/verifier、scalar reward 和 untouched clean test 按阶段契约受到保护；找不到声明目标时记录 `applicable=false`，不得静默切换到其他噪声。
```

- [ ] **Step 3: 写入实验门槛和协作者任务依赖**

The workflow must appear as:

```text
baseline bootstrap/verify
-> clean engineering_ready
-> clean efficacy_ready
-> freeze clean release
-> validate N1/N2/N3/N4 independently
-> freeze promoted benchmark operators
-> comparison baselines
-> RGSE and final full experiments
```

The readiness definitions must state:

```markdown
- `engineering_ready`：三个固定 method seed 中至少两个完成 100% 指定覆盖、没有系统性执行失败、产生语义不同的 artifact、至少接受一次通过原生 validation gate 的 update，且 evolved clean score 不低于 seed score。
- `efficacy_ready`：满足 `engineering_ready`，并且三个固定 seed 中至少两个取得严格为正的 clean gain。
- 在所有必需 Core-1 单元达到 `efficacy_ready` 并冻结 clean release 前，不开始正式 N1–N4。
```

The contributor checklist must explicitly include:

1. freeze current clean-v2 evidence;
2. repair typed interface failures and rerun every invalidated seed under a new experiment identity;
3. reach both clean readiness levels;
4. validate one noise stage at a time without outcome-based sample selection;
5. freeze manifests, hashes, replay packs, token/timing summaries, and reports;
6. add comparison baselines by native-domain priority;
7. design/implement RGSE only after benchmark freeze;
8. run three-seed paired statistics, cost accounting, ablations, and publish the benchmark card.

The date-stamped status section must report these four separate facts without upgrading them into a stronger claim:

```markdown
- **Execution/interface：** 统一 runner、scheduler、identity、timing、token ledger、baseline patch replay 和四域 canary 已建立；个别模型输出仍可能触发 typed interface failure，需要按 experiment identity 重跑受影响单元。
- **Clean update：** 四域主流程均已观察到可执行的 evolution/update 路径，但 accepted update 的出现率并不稳定。
- **Clean efficacy：** 尚无可公开冻结、覆盖四个 Core-1 单元的统一 `efficacy_ready` clean release。
- **Noise efficacy：** 当前没有 N1–N4 operator 完成跨 seed 稳定晋级；已有结果只能标为 candidate、weak signal、null、opposite 或 blocked。
```

- [ ] **Step 4: 加入相对仓库链接和候选扩展边界**

Link at least these tracked sources using paths relative to `docs/project-roadmap.md`:

```markdown
- [Benchmark registry](../benchmark/registry/benchmarks.yaml)
- [Method registry](../benchmark/registry/methods.yaml)
- [Adapter registry](../benchmark/registry/adapters.yaml)
- [Noise operator registry](../benchmark/registry/noise_operators.yaml)
- [Clean-v2 matrix](../configs/experiments/clean-v2.yaml)
- [Core-1 definition](../benchmark/core1/README.md)
- [Runtime evidence interface](core1-runtime-evidence-interface.md)
- [Clean release design](../design-specs/2026-08-14-unified-clean-baseline-release-design.md)
- [Core-1 validation report](reports/core1-validation-status.md)
- [Expanded N1 report](reports/2026-08-13-expanded-n1-validation.md)
```

Candidate extensions must be marked inactive and must not block Core-1. Include DocVQA, SearchQA/SealQA, WikiTableQuestions, Mathematics/DAPO/LiveMathematicianBench/AIME, SkillsBench, SkillFlow-Task, and the inactive method set from the baseline table.

- [ ] **Step 5: 验证路线图事实覆盖**

Run:

```bash
test "$(rg -o 'spreadsheet_n[1-4]_[a-z0-9_]+' docs/project-roadmap.md | sort -u | wc -l)" -eq 4
test "$(rg -o 'officeqa_n[1-4]_[a-z0-9_]+' docs/project-roadmap.md | sort -u | wc -l)" -eq 4
test "$(rg -o 'skilllearn_n[1-4]_[a-z0-9_]+' docs/project-roadmap.md | sort -u | wc -l)" -eq 4
test "$(rg -o 'webshop_n[1-4]_[a-z0-9_]+' docs/project-roadmap.md | sort -u | wc -l)" -eq 4
rg -n '20/10/30|12/12/20|5/5/20|2/1/3' docs/project-roadmap.md
rg -n 'engineering_ready|efficacy_ready|applicable=false|paper-only' docs/project-roadmap.md
```

Expected: all four count assertions exit 0; every clean-v2 scale and required status term is present.

- [ ] **Step 6: 提交路线图主体**

```bash
git add docs/project-roadmap.md
git commit -m "docs: add collaborator project roadmap"
```

Expected: one commit that creates only `docs/project-roadmap.md`.

### Task 2: 接入 README 并完成发布验证

**Files:**
- Modify: `README.md:1-16`
- Verify: `docs/project-roadmap.md`
- Test: `tests/test_registry.py`
- Test: `tests/core1/test_registry.py`

**Interfaces:**
- Consumes: Task 1 生成的 `docs/project-roadmap.md`。
- Produces: 从仓库首页可发现的路线图入口，以及 registry、链接和 Markdown 一致性证据。

- [ ] **Step 1: 更新 README 的当前范围说明**

Replace the opening paragraph and add a collaborator entry before `## Setup`:

```markdown
# RSE-Bench

RSE-Bench evaluates whether skill self-evolution remains effective when task context, environment evidence, stored trajectories, or update feedback contain controlled noise. The active Core-1 scope covers SpreadsheetBench-Verified, OfficeQA Full, WebShop, and SkillLearnBench.

## Collaborator roadmap

Start with the [Chinese project roadmap](docs/project-roadmap.md) for the active benchmarks, baseline methods, N1–N4 noise matrix, experiment gates, current limitations, and pending work. Machine-readable registries and executable configs remain the source of truth.

## Setup
```

Keep all existing setup and reproduction commands after this insertion.

- [ ] **Step 2: 验证所有新增相对链接**

Run:

```bash
for path in \
  docs/project-roadmap.md \
  benchmark/registry/benchmarks.yaml \
  benchmark/registry/methods.yaml \
  benchmark/registry/adapters.yaml \
  benchmark/registry/noise_operators.yaml \
  configs/experiments/clean-v2.yaml \
  benchmark/core1/README.md \
  docs/core1-runtime-evidence-interface.md \
  docs/superpowers/specs/2026-08-14-unified-clean-baseline-release-design.md \
  docs/reports/core1-validation-status.md \
  docs/reports/2026-08-13-expanded-n1-validation.md; do
  test -e "$path" || exit 1
done
```

Expected: exit 0 with no output.

- [ ] **Step 3: 扫描文档占位符、绝对路径和格式错误**

Run:

```bash
git diff --check
if rg -n 'T''BD|T''ODO|FIX''ME|PLACE''HOLDER|/home/|DEEPSEEK_API_KEY=' docs/project-roadmap.md; then
  exit 1
fi
```

Expected: `git diff --check` exits 0; the prohibited-pattern scan returns no matches and the conditional exits 0.

- [ ] **Step 4: 运行 registry 一致性测试**

Run:

```bash
PYTHONPATH="$PWD/src" pytest -q tests/test_registry.py tests/core1/test_registry.py
```

Expected: `7 passed` and zero failures.

- [ ] **Step 5: 复核最终 diff 和提交范围**

Run:

```bash
git status --short
git diff -- README.md docs/project-roadmap.md
```

Expected: Task 1 已提交后，工作树中只剩 `README.md` 的预期修改；diff 不含实验代码、配置、raw outputs 或 credential。

- [ ] **Step 6: 提交 README 入口**

```bash
git add README.md
git commit -m "docs: link collaborator roadmap"
```

Expected: one commit modifying only `README.md`.

- [ ] **Step 7: 最终验证**

Run:

```bash
git status -sb
git log --oneline -4
PYTHONPATH="$PWD/src" pytest -q tests/test_registry.py tests/core1/test_registry.py
```

Expected: clean working tree on `main`, the two roadmap commits appear in the latest history, and `7 passed` with zero failures.
