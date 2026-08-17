# RSEBench 项目路线图

> 状态基准：2026-08-17 UTC。机器可读的 release manifest、registry 和 validation matrix 是可执行事实的最终来源。

## 1. 研究目标

RSEBench 评测完整的 skill self-evolution loop：

```text
Initial Skill
→ Clean/Noisy Evolution Tasks
→ Trajectory + Tool Observation + Reward + Feedback
→ Self-Evolution Method
→ Evolved Skill
→ Untouched Clean Evaluation
```

项目要回答三个递进问题：

1. 现有 baseline 在 clean 条件下是否能完成可审计的 self-evolution；
2. N1–N4 的受控噪声是否会削弱 clean evolution gain 或引入 harmful update；
3. 后续鲁棒自进化方法能否降低 harmful update acceptance，同时保留 clean 能力。

Validation-v1 当前服务于第 2 个问题的机制验证，不宣称四领域已经证明跨 seed 稳定正向 clean efficacy。

## 2. Milestones

| Milestone | 目标 | 完成标志 | 状态 |
|---|---|---|---|
| M0：范围与 taxonomy | 定义研究对象和 N1–N4 边界 | 四阶段、保护字段、比较对象确定 | 已完成 |
| M1：执行闭环 | 跑通 benchmark、baseline、自进化和评测 | 四主领域产生完整执行/更新证据 | 已完成 |
| M2：validation-v1 冻结 | 冻结机制验证输入与方法身份 | 4 DatasetRelease、4 MethodRelease profile、4×4 matrix | 已完成 |
| M3：operator 与 runner | 实现 N1–N4 并接入四领域 | 16 cell 有保护字段审计和可执行 runner | **当前阶段** |
| M4：stage 级验证 | 确认至少一个 stage 在 3/4 领域产生可解释效应 | bounded pilot、失败分类、token/timing 完整 | 待开始 |
| M5：正式 4×4 | 并行运行冻结矩阵 | 16 noisy cell 与复用 clean control 可聚合 | 待开始 |
| M6：鲁棒方法与扩展 | 实现 RGSE、comparison baseline、候选 benchmark | 主实验、消融、跨方法/领域验证 | 待开始 |
| M7：发布 | 对外发布 benchmark、代码和结果 | 可复现、可审计、文档完整 | 待开始 |

## 3. Validation-v1 冻结范围

| Domain | Benchmark | DatasetRelease | MethodRelease | Scale |
|---|---|---|---|---:|
| Spreadsheet | SpreadsheetBench-Verified | `spreadsheetbench-verified-validation-v1` | `skillopt-spreadsheet-validation-v1` | 20/10/30 |
| Document | OfficeQA Full | `officeqa-full-validation-v1` | `skillopt-officeqa-validation-v1` | 12/12/20 |
| Interactive | WebShop | `webshop-validation-v1` | `skilladaptor-webshop-validation-v1` | 5/5/20 |
| Skill | SkillFlow-Task | `skillflow-tasks-validation-v1` | `skillflow-validation-v1` | 3 families × 6 |

SkillFlow families 为 `HWPX-Document-Automation`、`Distribution-Center-Auditing` 和 `Embedded-Data-Repair`。Family 内保持官方顺序，family 间重置 shared skill library。

SkillLearn Self-/Teacher-Feedback 为 `validated_inactive` diagnostic history，不进入当前 4×4。

## 4. Clean evidence 和 reuse 边界

- Spreadsheet 和 WebShop 的选定 clean control 有正增益，但历史其他 seed 仍显示随机性和 no-update 风险；
- OfficeQA 已完整更新但 score tie，证明流程可运行，不证明能力提升；
- SkillFlow 只有 HWPX 有局部正信号，另外两个 family 为执行/更新 tie；
- clean evidence 只能在 dataset、method patch series、provider/model、runtime、seed 和 task identity 全部一致时复用；
- 任何身份变化都需要新 release，不能在 validation-v1 原地改写。

## 5. M3 当前工作

### 5.1 四个 stage

| Stage | Owner | Static/runtime | Main deliverable |
|---|---|---|---|
| N1 task context | member-1 | static | task-context operator + protected-field audit |
| N2 environment evidence | member-2 | static | clean/noisy artifact + resource/hash audit |
| N3 stored trajectory | member-3 | runtime | replay-pack mutation + method hook |
| N4 update feedback | member-4 | runtime | attribution mutation + update-boundary hook |

人工进度统一记录在 [N1–N4 dashboard](progress/README.md)。

### 5.2 第一批完成 gate

- [ ] 在每个 stage 的 `operators/` 目录实现 benchmark-specific operator；
- [ ] 为 16 个 cell 增加 protected-field 和 applicability audit；
- [ ] 注册具体 `CELL_RUNNERS`，只有全部依赖存在时才报告 `execution_ready=true`；
- [ ] 每个 stage 先跑一个 provider-free executable cell；
- [ ] 每个 stage 再跑 bounded paid validation，不直接启动完整 4×4；
- [ ] 每次付费调用记录 prompt/completion/total tokens 和 UTC timing；
- [ ] 失败必须区分 operator 不适用、baseline 执行失败、zero-update、score tie 和 noise effect。

### 5.3 并行边界

- 同一可变 baseline checkout 默认串行；
- 不涉及共享 checkout 修改时，不同 benchmark 可以并行；
- 16 个正式 cell 使用隔离 attempt directory 和固定 upstream revision 重放 MethodRelease patch；
- SkillOpt Spreadsheet/OfficeQA 必须使用各自精确 patch profile；
- clean control 复用，不为每个 noisy cell 重跑 clean arm。

## 6. M4–M5：验证与正式矩阵

第一阶段只要求确认一个 noise stage 在至少 3/4 领域产生可解释效应。这个效应必须满足：

- clean baseline 本身完成有效或至少可审计的更新流程；
- noisy arm 改变了声明位置的 evidence/update，而不是制造系统性执行失败；
- final evaluation 使用相同 untouched clean data；
- provider/token/timing 覆盖完整；
- 无效、相反和 zero-update seed 全部保留，不能按结果筛除。

满足 stage 级 gate 后，再冻结 operator version、selector、seed、severity、protected fields 和 failure policy，启动精确 4×4。

## 7. M6：方法和 benchmark 扩展

优先 comparison baseline：

1. Spreadsheet：Trace2Skill、SkillGrad；
2. Document QA：EvoSkill + shared OfficeQA adapter；
3. Interactive：RethinkSkill，保留 SkillAdaptor reference；
4. Skill：Skills-Coach、FederatedSkill；
5. CoEvoSkills 只有在代码发布或明确 reimplementation 后进入。

候选 benchmark 包括 DocVQA、SearchQA、WikiTableQuestions、SkillsBench 和数学 calibration 数据。进入 active 范围前必须具备可靠 verifier、冻结 split、无泄漏 identity 和可运行 baseline。

RGSE 在 benchmark/noise freeze 后实现，不能访问 noise metadata、clean/noisy pair 或 final test outcome。

## 8. 当前可复现入口

Provider-free 控制流程：

```bash
python -m rsebench.cli validation preflight \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation status \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation aggregate \
  --matrix configs/validation/validation-v1.yaml
```

付费命令只有在 `execution_ready=true` 后才能使用：

```bash
python -m rsebench.cli validation run \
  --matrix configs/validation/validation-v1.yaml \
  --max-parallel 16 \
  --confirm-provider-cost
```

当前 runner 未实现，所以上述 run 必须在 provider call 前 fail closed。

## 9. 文档与机器真源

- [文档索引](README.md)
- [项目入门](project-onboarding.md)
- [当前项目状态](reports/current/current-project-status.md)
- [Validation-v1 freeze report](reports/current/2026-08-17-validation-v1-freeze.md)
- [Validation-v1 matrix](../configs/validation/validation-v1.yaml)
- [Benchmark registry](../benchmark/registry/benchmarks.yaml)
- [Method registry](../benchmark/registry/methods.yaml)
- [Validated methods](../methods/README.md)
- [N1–N4 progress](progress/README.md)
- [Historical experiment archive](archive/experiment-history/README.md)
