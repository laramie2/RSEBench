# N4 Update-Evidence Misbinding：实现与验证实验交接方案

> 交接基线：`origin/main` at `3fbc7257cf3903d044082b11f319a5df5169135d`
>
> 日期：2026-08-21 UTC
>
> 目标：在远端 `main` 基础上实现一种不要求 baseline 原生提供显式 feedback、可覆盖不同自进化方法的 N4 runtime noise，并完成四领域验证性实验。

## 1. 核心结论

N4 定义为 **update-evidence misbinding**：在 baseline 自然进入一次更新调用时，保持任务执行、轨迹内容、结果、reward、verifier、当前技能状态和更新算法不变，只把 outcome 与 updater 所消费 evidence 之间的正确绑定改成兼容但错误的绑定。

正常更新：

```text
outcome A ──binding──> evidence A ──> updater
```

N4 更新：

```text
outcome A ──binding──> evidence B ──> updater
```

Evidence A 和 B 都是实际产生、内容不可修改且有 hash 的证据。N4 只修改绑定边，不生成虚假轨迹，不修改 reward，不修改 verifier 结果。

这种噪声对应真实自进化系统中的：

- 异步 worker 返回顺序与任务顺序错位；
- task/result 按数组位置而非稳定 ID join；
- 延迟反馈进入下一任务的更新队列；
- replay buffer 将 outcome 或 reward 关联到错误 experience；
- patcher 读取了错误 trial 的轨迹；
- 聚合器把一个样本的学习证据分配给另一个样本。

## 2. 研究问题与适用分母

N4 的研究问题是：

> 当自进化方法准备更新时，如果更新所依据的执行证据被错误关联，该方法产生的更新是否仍然有益，以及最终能力相对 matched clean 是否下降？

N4 的适用分母不是全部任务，而是全部 **update attempts**：baseline 已经按照自身原始逻辑进入 updater、reflection、patcher 或 revision 调用的事件。

需要分别记录：

```text
task_count
update_attempt_count
eligible_binding_count
applied_binding_count
committed_update_count
```

如果一个任务没有触发任何更新调用，它仍计入任务和最终评分，但不进入 N4 applicability 分母。N4 不得为了提高覆盖率而强制 baseline 更新。

建议发布以下机器身份：

```text
stage: N4
operator: n4_update_evidence_misbinding
operator_version: v1
selector: compatible_update_evidence
```

## 3. N3 与 N4 的硬边界

N3 修改 evidence node 本身，例如删除一次 observation：

```text
trajectory A → trajectory A'
```

N4 保持所有 node 不变，只修改 node 之间的 binding：

```text
outcome A → evidence A
变成
outcome A → evidence B
```

每次 N4 application 必须满足：

```text
trajectory_node_hashes_before == trajectory_node_hashes_after
outcome_node_hashes_before == outcome_node_hashes_after
reward_and_verifier_hashes_before == reward_and_verifier_hashes_after
skill_state_before_update_hash_before == skill_state_before_update_hash_after
updater_contract_hash_before == updater_contract_hash_after
binding_hash_before != binding_hash_after
```

Updater 生成的 patch、选择的修改目标、accept/reject 决策和更新后的技能可以变化，因为它们是 N4 的下游结果，而不是噪声算子直接修改的 protected input。

## 4. 公共数据合同

建议在 `rsebench.evidence` 中新增独立合同，不以 `FeedbackRecord` 作为前提。

```python
from typing import Literal

from pydantic import Field

from rsebench.contracts import StrictModel


class UpdateOutcomeNode(StrictModel):
    outcome_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    kind: Literal[
        "execution_result",
        "verifier_result",
        "episode_result",
        "trial_result",
    ]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reward: float | None = None
    success: bool | None = None
    failure_class: str = Field(min_length=1)


class UpdateEvidenceNode(StrictModel):
    evidence_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    kind: Literal[
        "trajectory",
        "tool_trace",
        "conversation",
        "verifier_record",
        "feedback",
        "trial",
        "skill_usage",
    ]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1)
    compatibility_key: str = Field(min_length=1)


class UpdateBindingEdge(StrictModel):
    outcome_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    role: str = Field(min_length=1)


class UpdateConditioningRecord(StrictModel):
    schema_version: Literal["rsebench.update-conditioning.v1"]
    update_id: str = Field(min_length=1)
    method_release_id: str = Field(min_length=1)
    updater_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_nodes: list[UpdateOutcomeNode] = Field(min_length=1)
    evidence_nodes: list[UpdateEvidenceNode] = Field(min_length=1)
    bindings: list[UpdateBindingEdge] = Field(min_length=1)
```

合同必须验证：

1. 所有 binding 引用已声明 node；
2. outcome、evidence 和 binding ID 唯一；
3. 每个 update attempt 至少有一个 outcome→evidence binding；
4. locator 是 portable locator 或 attempt-local locator；
5. `content_hash` 覆盖 node 原始内容，不覆盖 binding；
6. `updater_contract_hash` 覆盖 baseline updater 名称、参数 schema 和 release identity。

## 5. 方法适配接口

每个 baseline 实现一个 `UpdateBindingAdapter`：

```python
class UpdateBindingAdapter(Protocol):
    def normalize_update_input(
        self,
        native_update_input: object,
        context: HookContext,
    ) -> UpdateConditioningRecord: ...

    def denormalize_update_input(
        self,
        native_update_input: object,
        normalized: UpdateConditioningRecord,
        resolver: EvidenceResolver,
        context: HookContext,
    ) -> object: ...

    def capture_protected_update_state(
        self,
        native_update_input: object,
        context: HookContext,
    ) -> ProtectedUpdateState: ...
```

其中 `ProtectedUpdateState` 至少包含 outcome hashes、evidence node hashes、reward/verifier hash、更新前 skill hash、update trigger hash 和 updater contract hash。`EvidenceResolver` 只能根据冻结 locator 读取 node，读取后必须重新计算并核对 `content_hash`；它不能调用 provider、改写 evidence 或动态寻找新的 decoy。

公共 hook 放在 baseline 已决定调用 updater、但 updater 尚未读取输入的位置：

```python
native_update_input = hook.before_update(
    native_update_input,
    context,
)
candidate_update = native_updater(native_update_input)
```

`before_update` 负责：

1. 捕获 protected state；
2. normalize 原生 updater 输入；
3. matched clean 执行 identity binding；
4. noisy arm 执行 binding mutation；
5. denormalize 为原生 updater 输入；
6. 再次验证 protected state；
7. 写入 replay pack；
8. 记录 updater 实际消费的 input hash。

显式 feedback 可以作为一种 `UpdateEvidenceNode`，但不是公共接口的必要条件。

## 6. Decoy 选择

### 6.1 Compatibility key

每个 evidence node 由 benchmark policy 和 method adapter 共同声明 compatibility key，至少包含：

```text
method_release_id
domain
update_input_schema
evidence_role
outcome_class
target_artifact_type
```

可以加入轨迹长度区间、工具类型、任务 family 等通用特征，但不得按具体 task ID、固定错误字符串或 operator ID 写特判。

### 6.2 Batch 内置换

同一 updater batch 中，一个 compatibility group 有两个及以上 update event 时：

1. 用 `hash(noise_seed, update_id)` 对事件排序；
2. 用非零 offset 做确定性循环置换；
3. 要求置换无 fixed point；
4. 保持 outcome 和 evidence node 的 multiset 不变；
5. 只替换 binding edge。

示例：

```text
A→a, B→b, C→c
变成
A→b, B→c, C→a
```

### 6.3 Singleton 冻结池

一个 compatibility group 只有一个 update event 时，从预先冻结的 decoy bank 选择 evidence：

```text
A→a
变成
A→frozen-decoy-b
```

Decoy bank 必须满足：

- 只来自 evolution train partition；
- 与当前方法 release、domain、input schema 和 evidence role 兼容；
- 不包含 validation/test outcome；
- 在 noisy run 前生成并冻结；
- 每个 node 有 immutable locator 和 content hash；
- 当前 evidence ID 不得成为自己的 decoy；
- 选择由 frozen seed 和 node identity 唯一决定。

Decoy-bank freezer 只能消费仓库已经登记的 frozen clean training evidence，运行期间必须保持 `provider_calls == 0`。如果现有 clean evidence 不足以覆盖某个 compatibility class，应报告 blocked 并补充独立的 clean evidence release，不能在 noisy run 中即时生成。

正式实验开始前，preflight 必须证明所有预注册 compatibility class 都有 decoy。运行时发现无 decoy 时，cell 记为 invalid，不得临时降低匹配要求。

## 7. 四领域方法映射

远端 `main` 当前 active 方法映射如下。

### 7.1 SpreadsheetBench-Verified + SkillOpt

原生更新过程：

```text
rollout result + conversation/tool trace
→ analyst/reflection minibatch
→ edit/patch proposal
→ skill update gate
```

Hook 位置：analyst/reflection minibatch 完成组装后、调用 analyst 之前。

Node 映射：

```text
outcome  = hard/soft、execution/verifier result、failure class
evidence = conversation、generated code、tool trace、resource-use trace
```

N4 将 outcome A 与兼容 evidence B 组合后交给 analyst。该方案不要求 failure message 包含单元格或范围，因此 execution error、syntax error 和 verifier mismatch 都可以进入同一公共机制。

### 7.2 OfficeQA Full + SkillOpt

使用同一个 SkillOpt adapter 和 hook。

Node 映射：

```text
outcome  = scorer/verifier result
evidence = retrieval、document read、tool use、reasoning conversation
```

Compatibility policy 应要求相同 scorer 类型、相同 evidence schema 和相同 outcome class，避免把完全无关的执行类型配在一起。

### 7.3 WebShop + SkillAdaptor

原生更新过程：

```text
episode result
→ fault localization/linking
→ revision input
→ skill update
```

Hook 位置：fault/revision update input 完成组装后、revision model 调用之前。

Node 映射：

```text
outcome  = episode reward、success、terminal status
evidence = action/observation trajectory、localized step、skill-use evidence
```

N4 将 episode outcome A 与另一个兼容 episode 或 step evidence B 绑定。更新器仍使用原始 revision 算法。

### 7.4 SkillFlow Tasks + SkillFlow

原生更新过程：

```text
TrialOutcome + compacted trajectory + skill snapshot
→ patcher input
→ shared skill file update
```

Hook 位置：patcher input/prompt 完成组装后、patcher model 调用之前。

Node 映射：

```text
outcome  = verifier result、reward、trial status
evidence = compacted trajectory、tool records、skill-use records
```

SkillFlow family 内任务顺序保持不变。Batch 内有兼容 trial 时优先置换；顺序更新导致 singleton 时使用同 family 冻结 decoy bank。

### 7.5 后续方法接入

新 baseline 接入 N4 只需要回答四个问题：

1. updater invocation 在哪里？
2. outcome node 是什么？
3. updater 实际读取哪些 evidence node？
4. 如何在不修改 node 的情况下重建错误 binding 的原生 updater input？

如果方法把执行和更新封装在不可观测的远端调用中，无法证明 updater 消费了错误 binding，则不得声明支持 N4。语义上的公共合同不意味着无需 method adapter 或 instrumentation。

## 8. Matched clean 与 noisy arm

四个领域都运行相同 instrumentation：

```text
Matched clean:
  normalize
  → identity binding
  → denormalize
  → updater

N4 noisy:
  normalize
  → misbound binding
  → denormalize
  → updater
```

两个 arm 必须从相同 seed skill 出发，并固定：

- DatasetRelease 和任务顺序；
- MethodRelease 和 upstream revision；
- method seed；
- provider、model、temperature、thinking；
- runtime budget；
- updater algorithm 和 accept/reject gate；
- untouched clean evaluation set。

Matched clean round-trip 必须证明原生 updater 输入 byte-identical；无法 byte-identical 时，必须使用 baseline-owned semantic equivalence checker，并在 provider call 前完成验证。

## 9. Replay pack 与审计

每次 update attempt 写入：

```text
runtime_noise/<update-id>/N4/
├── input-binding.json
├── output-binding.json
├── protected-nodes.json
├── decoy-selection.json
├── updater-consumption.json
├── audit.json
├── token-usage.json
└── timing.json
```

`audit.json` 至少包含：

```text
update_id
method_release_id
input_binding_hash
output_binding_hash
changed_binding_count
fixed_point_count
protected_node_hashes_before/after
compatibility_key
decoy_source_kind: batch | frozen_pool
applicable + reason
```

`updater-consumption.json` 必须证明 native updater 实际收到的 evidence hashes 与 output binding 一致。仅生成一个 noisy JSON、但 updater 仍消费 clean input，必须判定为机制失败。

Replay pack、noise label、clean binding、operator identity 和 audit 路径不得暴露给被测 updater。

## 10. Provider-free preflight

任何真实模型调用前必须通过：

1. DatasetRelease、MethodRelease、matrix 和 decoy-bank hash；
2. 四个 method adapter 可 import；
3. matched-clean native round-trip；
4. update/outcome/evidence ID 唯一性；
5. compatibility groups 完整；
6. batch permutation 无 fixed point；
7. singleton decoy 选择确定、可重放；
8. protected nodes 在 mutation 前后相等；
9. 仅 binding 字段发生变化；
10. updater-consumption proof 可在 fixture 上成立；
11. clean/noisy 输出和技能目录隔离；
12. resume 不会重复应用同一个 binding mutation；
13. `provider_calls == 0`。

Preflight 不能用“selection 非空”代替真实 applicability。必须用冻结 update-input fixture 对每个方法执行完整 normalize → mutate → denormalize → consumption replay。

## 11. Smoke 验证

Smoke 按领域独立执行：

1. Spreadsheet；
2. OfficeQA；
3. WebShop；
4. SkillFlow。

每个领域先运行最小 matched-clean/noisy pair。单个领域失败不能改写其他领域状态，也不能阻止后续通过独立命令诊断。

Smoke 机制门：

```text
matched_clean_roundtrip_passed == true
update_attempt_count >= 1
applied_binding_count >= 1
fixed_point_count == 0
protected_nodes_identical == true
updater_consumed_output_binding == true
update_process_terminal == true
token_and_timing_coverage == 1.0
```

Smoke 不要求分数必须下降。分数方向是效果结果，不是机制有效性的判断条件。

## 12. 四领域完整验证性实验

### 12.1 实验单元

在四个冻结 DatasetRelease 上运行 paired arms：

```text
matched clean
vs
N4 update-evidence misbinding
```

使用相同 method seeds；最低使用当前项目已登记的三个 seeds。每个 domain × seed 独立输出，禁止覆盖和跨 seed resume。

### 12.2 主要效应

```text
clean_gain = clean_post_score - clean_pre_score
n4_gain    = n4_post_score - n4_pre_score
N4_effect  = n4_gain - clean_gain
```

`N4_effect < 0` 表示错误的 update-evidence binding 削弱了自进化收益。

### 12.3 必报指标

```text
task_count
update_attempt_count
eligible_binding_count
applied_binding_count
binding_coverage
committed_update_count
zero_update_rate
harmful_update_rate
pre_score / post_score / gain
provider_calls / billed_tokens / wall_time
```

同时报告每个领域、每个 seed 和总体 paired aggregate。不能只报告成功产生负效应的 cell。

### 12.4 结果解释

- binding 未改变或 updater 未消费 noisy binding：实验无效；
- binding 正确改变但 `N4_effect≈0`：有效 null effect；
- `N4_effect<0`：支持错误 credit binding 损害自进化；
- 部分领域 `N4_effect>0`：照实报告，不得按方向替换 task、seed 或 decoy；
- applicability 不足：报告覆盖问题，不能把它解释为方法鲁棒。

## 13. 防止未来鲁棒 pipeline 对具体 operator 过拟合

N4 需要同时预注册两套 realization：

```text
N4-dev:
  公开的 compatibility features
  公开的 batch rotation
  公开的 pool selection fixture

N4-heldout:
  不同的无 fixed-point permutation
  不同的通用 compatibility feature 组合
  未公开的 seed 和 decoy assignment
```

未来鲁棒 pipeline 可以知道“update binding 可能不可靠”，但不能读取：

- N4 realization 名称；
- noise label；
- clean binding；
- mutation audit；
- frozen decoy assignment；
- operator-specific sentinel。

最终至少测试：

| 设置 | 目的 |
|---|---|
| clean | 防止永远不更新式伪鲁棒 |
| seen N4 realization | 验证 threat-model-aware robustness |
| held-out N4 realization | 排除对具体程序化 operator 的记忆 |
| held-out domain 或 baseline | 验证跨方法泛化 |
| naturalistic routing fault | 验证与真实系统错误一致 |

论文或报告的结论应限定为：对预注册的 update-evidence misbinding threat class 具有鲁棒性，而不是对任意反馈噪声或任意自进化错误都鲁棒。

## 14. 建议代码布局

以下为职责边界，不要求机械照搬文件名：

```text
src/rsebench/evidence/
├── update_contracts.py
├── update_hooks.py
├── update_replay.py
└── adapters/
    ├── skillopt_update.py
    ├── skilladaptor_update.py
    └── skillflow_update.py

src/rsebench/noise/stages/n4/
├── operator.py
├── decoy_bank.py
├── compatibility.py
└── policies/
    ├── spreadsheet.py
    ├── officeqa.py
    ├── webshop.py
    └── skillflow.py

benchmark/noise/N4/
├── specs/
├── fixtures/
└── decoy-banks/

configs/validation/
└── validation-n4-update-binding-v1.yaml
```

公共 operator 不得 import baseline runner。Baseline adapter 可以依赖公共合同，但不能拥有 decoy 选择算法。Benchmark policy 只声明 compatibility，不能直接执行 provider 调用。

## 15. 实施顺序

1. 定义 `UpdateConditioningRecord`、protected-state 和 replay schema；
2. 实现纯函数 binding mutator、batch derangement 和 singleton selector；
3. 建立 provider-free fixtures 和 decoy-bank freezer；
4. 实现 SkillOpt adapter，并先打通 Spreadsheet；
5. 运行 Spreadsheet provider-free replay 和 paid smoke；
6. 复用 SkillOpt adapter 接入 OfficeQA；
7. 实现 SkillAdaptor adapter；
8. 实现 SkillFlow adapter；
9. 执行四领域 provider-free full suite；
10. 按领域执行 smoke；
11. 冻结正式 matrix、selection、decoy bank 和 method releases；
12. 执行三 seeds 的四领域 paired validation。

## 16. 完成标准

只有同时满足以下条件，才能声明 N4 实现完成：

- 不要求 baseline 原生提供独立 feedback object；
- 三个 active method family 都有可重放 update boundary；
- 四个领域 provider-free preflight 通过；
- formal cells 的 update-attempt binding coverage 达到预注册门槛；
- matched clean round-trip 通过；
- noisy arm 只修改 binding；
- updater-consumption proof 通过；
- protected node hashes 完全一致；
- token、时间、attempt、resume 和 failure evidence 完整；
- 四领域 smoke 分别完成；
- paired validation 使用冻结任务、seeds 和 decoy assignment；
- 机制有效性和效果方向分开报告；
- dev/heldout N4 realization 在 formal run 前冻结。

## 17. 明确不做的事情

- 不修改 frozen DatasetRelease 的任务、顺序、gold 或 verifier；
- 不把 N3 与 N4 放入同一 arm；
- 不修改 reward 或 official score；
- 不为了覆盖率强制 baseline 产生更新；
- 不用 LLM 临时生成未经冻结的 decoy；
- 不允许 updater 读取 noise label 或 audit；
- 不因第一次结果方向不符合预期而更换 task、seed、decoy 或统计口径。
