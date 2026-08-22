# Noise-stage interface

> 当前范围：N1/N2 static mutation，N3 runtime evidence-node mutation，N4 runtime update-evidence binding mutation
>
> `validation-v1` 冻结身份的机器真源是 [validation-v1 matrix](../../configs/validation/validation-v1.yaml) 和 `src/rsebench/noise/stages/`。最新版 N4 设计见 [N4 Update-Evidence Misbinding 交接方案](../architecture/2026-08-21-n4-update-evidence-misbinding-handoff.md)，其机器合同和新 release 尚待实现。

[运行时加噪 FAQ](../qa/runtime-noise-faq.md) 是 N3/N4 的概念性伴读；本协议仍是 stage 边界、保护字段和实现约束的规范性来源。

## 1. Shared release contract

每个 noise cell 固定：DatasetRelease、MethodRelease、stage、operator ID、selector、seed、mutation budget、protected fields、applicability rule 和 failure policy。

四个 stage 是独立实验 arm，不组合成 N1×N2×N3×N4。冻结的 `validation-v1` mutation budget 固定为 1。最新版 N4 的预算单位是发生错误绑定的 eligible update attempt，必须在新的 version/release 中冻结；找不到兼容 decoy 时记录 `applicable=false`，不能自动换成另一种噪声或强制 baseline 更新。

Clean/noisy arm 必须从相同 seed skill 出发，使用相同任务 ID、顺序、method seed、provider/model、temperature、thinking 和 runtime budget。最终评测使用同一份 untouched clean evaluation。

## 2. Stable boundaries

| Stage | Injection boundary | Form | Protected fields |
|---|---|---|---|
| N1 | before first action | static task-context mutation | objective, gold, artifact, official environment, verifier |
| N2 | during environment evidence preparation | static resource/artifact mutation | gold reachability, original resource, official environment, verifier |
| N3 | after rollout/reward, before reflection | runtime stored-trajectory mutation | task identity, reward, success, environment state, final result |
| N4 | baseline 已决定更新之后、updater 消费输入之前 | runtime outcome→update-evidence binding mutation | evidence node、outcome、reward/verifier、更新前 skill、update trigger、updater contract |

N1/N2 输出独立 clean/noisy artifact identity。N3/N4 输入由被评估方法运行时生成，因此不能发布一个脱离方法、模型和运行身份的“通用 noisy model output 文件”。N4 不要求 baseline 原生生成显式 feedback；feedback 只是在存在时可被绑定的一类 evidence node。

## 3. Plugin ownership

```text
src/rsebench/noise/stages/
├── n1/
│   ├── plugin.yaml
│   └── operators/
├── n2/
│   ├── plugin.yaml
│   └── operators/
├── n3/
│   ├── plugin.yaml
│   └── operators/
└── n4/
    ├── plugin.yaml
    └── operators/
```

Stage owner 只修改自己的 `operators/` 和进度页。共享 plugin contract、中央 matrix、DatasetRelease 和 MethodRelease identity 不因单个 operator 实现而原地改变。

`plugin.yaml` 声明 stage、mode、supported domains、protected fields、operator discovery surface 和 runner readiness。只有所有必需实现存在并通过静态审计时，plugin 才能令对应 cell 报告 executable。

## 4. Static N1/N2 obligations

Static operator 输入 DatasetRelease task/resource identity，输出 clean/noisy pair 和 audit：

```text
input release/task identity
operator ID + selector + seed + mutation budget
clean artifact locator + hash
noisy artifact locator + hash
changed fields
protected-field comparison
applicable + reason
```

N1 不能改写原 prompt objective 或 gold；新增 context 必须可与原始任务区分。N2 必须保留原始资源和正确解法可达性，不能通过删除正确证据制造不可完成任务。

Static artifact 写入与原 benchmark 数据分隔的 noise release 路径，不能修改 `benchmark/datasets/.../releases/validation-v1/manifest.json`。

## 5. Runtime N3/N4 obligations

N3 使用 trajectory record 和 rollout adapter，在 rollout/reward 后、reflection 前改变 learner-visible evidence node：

```python
from rsebench.evidence import EvidenceNoiseHook, HookContext

hook = EvidenceNoiseHook.from_spec_files(
    adapter=method_adapter,
    spec_paths=[n3_spec_path],
)

learning_trajectory = hook.after_rollout(native_trajectory, context)
```

最新版 N4 使用独立的 `UpdateConditioningRecord` 和 `UpdateBindingAdapter`，公共调用边界为：

```python
native_update_input = update_hook.before_update(
    native_update_input,
    context,
)
candidate_update = native_updater(native_update_input)
```

N4 的 clean/noisy arm 都经过同一条 normalize、binding policy、denormalize 和审计路径；clean policy 保持原绑定，noisy policy 只替换绑定边。两臂都必须证明 node 内容、reward/verifier、更新前 skill、update trigger 和 updater contract 保持一致，并记录 updater 实际消费的 input hash。Noisy arm 不得修改 node 内容或调用 LLM 生成 decoy。

只有 baseline 自身已经决定调用 updater 的事件才属于 N4 applicability 分母。未触发更新的任务仍计入最终评分，但 N4 不得为了提高覆盖率制造一次更新。

上述 `UpdateConditioningRecord`、`UpdateBindingAdapter` 和 `before_update` 是最新版 N4 的设计合同，当前 `main` 尚未实现。实现时必须发布新的 N4 operator version、matrix/release 和 replay schema，不能把冻结的 `validation-v1` 原地重解释。旧 Core-1 SkillOpt、SkillAdaptor 和 SkillLearn adapter 是历史参考，不自动成为新 N4 runner。SkillFlow 必须使用其独立 MethodRelease 和 shared-skill runtime boundary。

## 6. Runtime replay pack

每次 N3 application 写入现有不可变 replay pack。最新版 N4 的 replay pack 至少包含：

```text
runtime_noise/
├── input-binding.json
├── output-binding.json
├── protected-nodes.json
├── decoy-selection.json
├── updater-consumption.json
├── audit.json
├── token_usage/
└── timing.json
```

`input-binding.json` 和 `output-binding.json` 记录 mutation 前后的 outcome→evidence 边；`protected-nodes.json` 证明所有 node 内容和其他保护状态未变；`decoy-selection.json` 记录 batch derangement 或 frozen decoy-bank 的确定性选择；`updater-consumption.json` 记录 updater 实际消费的输入。Token/timing 文件遵循 [统一合同](token-timing-and-result-contract.md)。完整 schema 见最新版 N4 交接方案。

Replay pack 不包含 credential。若原生 evidence 包含大文件，JSON 只记录 portable locator 和内容 hash。

## 7. Frozen validation-v1 operator IDs

下表是已冻结的 `validation-v1` 机器身份，用于复现旧定义，不能被重新解释为最新版 N4：

| Benchmark | N1 | N2 | N3 | N4 |
|---|---|---|---|---|
| Spreadsheet | `spreadsheet_n1_erroneous_handover` | `spreadsheet_n2_unlabeled_stale_sheet` | `spreadsheet_n3_omit_workbook_edit` | `spreadsheet_n4_replace_blamed_range` |
| OfficeQA | `officeqa_n1_one_axis_derivation` | `officeqa_n2_conflicting_period_source` | `officeqa_n3_omit_oracle_source` | `officeqa_n4_replace_failure_axis` |
| WebShop | `webshop_n1_near_match_session` | `webshop_n2_promote_near_match` | `webshop_n3_omit_constraint_event` | `webshop_n4_replace_fault_step` |
| SkillFlow | `skillflow_n1_unverified_prior_skill` | `skillflow_n2_stale_same_family_artifact` | `skillflow_n3_omit_skill_use_event` | `skillflow_n4_replace_patch_attribution` |

N1–N3 的定义不因本次 N4 修订而变化。表中旧 N4 是 feedback/attribution replacement；最新版 N4 的建议身份是 `n4_update_evidence_misbinding@v1`。两者语义发生了实质变化，因此必须发布新的 version/release，不能覆盖、重命名或静默修改上表的冻结身份。

## 8. Conformance gates

每个 cell 在 provider call 之前依次通过：

1. DatasetRelease/MethodRelease/matrix identity；
2. operator discovery 和 supported-domain；
3. artifact/resource locator 与 hash；
4. applicability 和 mutation budget；
5. protected-field audit；
6. clean identity path；
7. runtime replay-pack schema（N3/N4）；
8. concrete runner registration；
9. attempt isolation 和 resume identity。

任一 gate 失败都必须 fail closed。`execution_ready=false` 不是 noise null effect，也不能启动模型调用。

最新版 N4 还必须在 provider call 之前证明：compatibility class 可解析、batch derangement 无 fixed point、singleton 有冻结 decoy、protected node hashes 完全一致、clean identity binding 可重放，以及 updater consumption 与 output binding 一致。
