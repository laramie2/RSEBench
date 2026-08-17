# Validation-v1 noise-stage interface

> 当前范围：N1/N2 static mutation，N3/N4 runtime evidence mutation
>
> 机器真源：[validation-v1 matrix](../../configs/validation/validation-v1.yaml) 和 `src/rsebench/noise/stages/`

## 1. Shared release contract

每个 noise cell 固定：DatasetRelease、MethodRelease、stage、operator ID、selector、seed、mutation budget、protected fields、applicability rule 和 failure policy。

四个 stage 是独立实验 arm，不组合成 N1×N2×N3×N4。Mutation budget 当前固定为 1。找不到声明目标时记录 `applicable=false`，不能自动换成另一种噪声。

Clean/noisy arm 必须从相同 seed skill 出发，使用相同任务 ID、顺序、method seed、provider/model、temperature、thinking 和 runtime budget。最终评测使用同一份 untouched clean evaluation。

## 2. Stable boundaries

| Stage | Injection boundary | Form | Protected fields |
|---|---|---|---|
| N1 | before first action | static task-context mutation | objective, gold, artifact, official environment, verifier |
| N2 | during environment evidence preparation | static resource/artifact mutation | gold reachability, original resource, official environment, verifier |
| N3 | after rollout/reward, before reflection | runtime stored-trajectory mutation | task identity, reward, success, environment state, final result |
| N4 | after feedback, before revision/update | runtime feedback/attribution mutation | complete trajectory, scalar reward, official score, true environment state |

N1/N2 输出独立 clean/noisy artifact identity。N3/N4 输入由被评估方法运行时生成，因此不能发布一个脱离方法、模型和运行身份的“通用 noisy model output 文件”。

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

N3/N4 使用 `rsebench.evidence` 的 normalized record 和 method-specific adapter。公共调用边界为：

```python
from rsebench.evidence import EvidenceNoiseHook, HookContext

hook = EvidenceNoiseHook.from_spec_files(
    adapter=method_adapter,
    spec_paths=[n3_spec_path, n4_spec_path],
)

learning_trajectory = hook.after_rollout(native_trajectory, context)
learning_feedback = hook.after_feedback(
    native_feedback,
    native_trajectory,
    context,
)
```

Clean arm 返回原生对象 identity，不做 normalization round trip。Noisy arm 只能改变 operator 授权字段。Adapter 必须完成 native ↔ normalized 转换，并证明 protected fields 在转换和 mutation 前后保持一致。

旧 Core-1 SkillOpt、SkillAdaptor 和 SkillLearn adapter 是历史参考，不自动成为 validation-v1 runner。SkillFlow 必须使用其独立 MethodRelease 和 shared-skill runtime boundary。

## 6. Runtime replay pack

每次 N3/N4 application 写入不可变 replay pack：

```text
runtime_noise/
├── input.json
├── output.json
├── audit.json
├── token_usage/
└── timing.json
```

`input.json` 记录 normalized pre-mutation evidence；`output.json` 记录 learner-visible post-mutation evidence；`audit.json` 记录 identity、selector、operator、changed fields、protected-field hashes、applicability 和 failure。Token/timing 文件遵循 [统一合同](token-timing-and-result-contract.md)。

Replay pack 不包含 credential。若原生 evidence 包含大文件，JSON 只记录 portable locator 和内容 hash。

## 7. Validation-v1 operator IDs

| Benchmark | N1 | N2 | N3 | N4 |
|---|---|---|---|---|
| Spreadsheet | `spreadsheet_n1_erroneous_handover` | `spreadsheet_n2_unlabeled_stale_sheet` | `spreadsheet_n3_omit_workbook_edit` | `spreadsheet_n4_replace_blamed_range` |
| OfficeQA | `officeqa_n1_one_axis_derivation` | `officeqa_n2_conflicting_period_source` | `officeqa_n3_omit_oracle_source` | `officeqa_n4_replace_failure_axis` |
| WebShop | `webshop_n1_near_match_session` | `webshop_n2_promote_near_match` | `webshop_n3_omit_constraint_event` | `webshop_n4_replace_fault_step` |
| SkillFlow | `skillflow_n1_unverified_prior_skill` | `skillflow_n2_stale_same_family_artifact` | `skillflow_n3_omit_skill_use_event` | `skillflow_n4_replace_patch_attribution` |

Operator ID 已冻结，但具体实现和 `CELL_RUNNERS` 尚未完成。ID 不得因为实现细节调整而重命名；语义发生实质变化时必须发布新 version/release。

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
