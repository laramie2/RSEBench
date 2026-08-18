# N3/N4 运行时加噪常见问题

> 本文是概念性说明。实现边界、保护字段和当前 operator 定义以 [noise-stage interface](../protocols/noise-stage-interface.md) 和 validation matrix 为准。

## 1. N1/N2 与 N3/N4 的区别是什么？

N1/N2 改变进入方法的静态任务上下文或环境证据，因此可以在运行前产生带独立 identity 的 clean/noisy artifact。N3/N4 则处理被评估方法在运行时才产生的学习证据：N3 位于 rollout/reward 之后、reflection 之前，N4 位于 feedback 之后、revision/update 之前。它们不是与方法、模型和运行 identity 无关的静态 dataset artifact。

可以把 self-evolution 类比为学生复盘一次练习：N1/N2 像在答题前改动交给学生的题目背景或参考材料；N3 像在答题并评分后，从学生用于复盘的笔记中删掉一个关键步骤；N4 像在学生修订方法前，把老师的错因归到了另一步。N3/N4 不改动学生实际做出的答案和已经产生的官方评分。

Validation-v1 中 N1、N2、N3、N4 是四个独立实验 arm，不组合成 `N1×N2×N3×N4`，N3 和 N4 也不在同一 noisy arm 中串联。

## 2. N3 和 N4 分别修改什么？

| Stage | 只能修改 | 必须保持不变 |
|---|---|---|
| N3 | learner-visible stored trajectory 中 operator 授权的 event | task identity、reward、success、environment state、final result |
| N4 | learner-visible feedback 中 operator 授权的 critique、failure attribution 或 diagnosis | complete trajectory、scalar reward、official score、true environment state |

一个具体的 N3 例子是：WebShop rollout 确实检查了商品的颜色约束，环境和 verifier 也已给出真实结果；N3 仅从交给 learner 复盘的 stored trajectory 中省略这个 constraint event。Task identity、reward、success、environment state 和 final result 都不能随之改变。

一个具体的 N4 例子是：某次 Spreadsheet rollout 的真实 verifier 结果已将错误定位在 `B12`，N4 只把 learner 将要用于 skill revision 的 critique 错置为“应修改 `D20`”。完整 trajectory、scalar reward、official score 和真实工作簿状态仍然不变。

这两个例子只解释运行时边界，不另行定义 operator 或保护字段。任何实际 mutation 都必须通过规范协议中的 protected-field audit。

## 3. N3/N4 是否属于 RSEBench benchmark？

属于。RSEBench 是包含数据、方法运行、噪声注入、审计和统一评测的 evaluation suite；N3/N4 是其中可执行的运行时证据 arm。

但 N3/N4 不是可从 benchmark 中单独下载的通用 noisy output 文件。它们的输入依赖当次 MethodRelease、模型、seed、任务顺序和运行中产生的 native evidence。可移植的是 stage contract、operator spec 和 replay-pack/audit 结构，而不是脱离运行 identity 的“通用 noisy model output”。

## 4. 为什么 N3/N4 会影响自进化？

Self-evolution 更新的并不是已结束的环境执行，而是对那次执行的学习解释。即使任务结果和 reward 正确，看到不完整 trajectory 的 learner 仍可能把成功或失败归因给错误步骤；收到错置 feedback 的 updater 也可能把错误规则写入可复用 skill。

因果链是：

```text
真实执行结果
    ↓
learner-visible trajectory / feedback
    ↓
reflection、归因与 skill revision
    ↓
更新后的 skill
    ↓
untouched clean evaluation
```

所以 RSEBench 保护真实执行结果，只扰动 learner-visible evidence，再观察更新后的 skill 是否在同一份 clean evaluation 上受到持续影响。

## 5. 新 baseline 和新 benchmark 如何接入？

接入层应分成 `Method Adapter + Benchmark Policy + Stage Operator`：

- **Method Adapter** 识别方法原生的 trajectory、feedback 和 update boundary，负责 native evidence 与 normalized record 之间的转换，并审计往返转换没有改变保护字段。
- **Benchmark Policy** 说明该 benchmark 中 event、resource、成功和 official result 的语义，提供 applicability 判定与 protected-field 映射。
- **Stage Operator** 只在 normalized evidence 上实现已授权的 N3 或 N4 mutation，不了解 baseline 的内部更新算法，也不重新定义 benchmark 的官方结果。

接入新 baseline 时，实现 Method Adapter，把两个 runtime hook 放在真实的 reflection 和 revision/update 边界，并证明 clean path 保留 native object identity。接入新 benchmark 时，增加 Benchmark Policy 与相应的 stage applicability/审计映射。两者都不应为了接入而修改方法的核心更新算法。

N4 必须先做 capability negotiation。Adapter 至少要能如实回答：

1. 方法是否生成可观测的 feedback/attribution；
2. 该 feedback 是否真的被 revision/update 消费；
3. 是否能在消费前注入 hook，并把返回值原样交给 updater；
4. 是否能将可变的 attribution 与 complete trajectory、scalar reward、official score 和 true environment state 分离并审计。

只有这些能力都可验证时，该方法才支持 N4。没有 faithful feedback boundary 的方法必须报告 `unsupported`，不能运行一个未被 updater 消费的伪 hook，更不能据此报告 N4 null effect。

## 6. 如何让自研 pipeline 与 N3/N4 完全解耦？

Pipeline 只需依赖两个通用的运行时 hook，并默认注入 identity middleware：

```python
class IdentityEvidenceMiddleware:
    def after_rollout(self, native_trajectory, context):
        return native_trajectory

    def after_feedback(self, native_feedback, native_trajectory, context):
        return native_feedback


learning_trajectory = evidence_middleware.after_rollout(
    native_trajectory,
    context,
)
learning_feedback = evidence_middleware.after_feedback(
    native_feedback,
    native_trajectory,
    context,
)
```

不运行噪声实验时，返回值就是同一个 native object，不经过 normalization round trip。运行 RSEBench arm 时，由外部配置将 middleware 替换为组合 Method Adapter、Benchmark Policy 和单个 Stage Operator 的实现。Pipeline 本身不嵌入 operator ID、selector 或 benchmark-specific mutation；它只保证 hook 位于正确的学习边界，并且 updater 实际消费 hook 返回的 evidence。

每个 noisy arm 只注入一个 stage：N3 arm 的 `after_feedback` 仍为 identity，N4 arm 的 `after_rollout` 仍为 identity。这既保持实验独立性，也让方法代码可以在不安装 RSEBench operator 的情况下正常运行。

## 7. 其他自进化工作如何使用 RSEBench？

外部方法应在相同 seed skill、任务 ID 与顺序、method seed、模型和 runtime budget 下，报告下列六个对照：

| 报告项 | 含义 |
|---|---|
| `Initial` | 未经当前 evolution task stream 更新的 seed skill |
| `Clean` | 使用 clean evolution evidence 更新得到的 skill |
| `N1` | 仅在 N1 arm 进化得到的 skill |
| `N2` | 仅在 N2 arm 进化得到的 skill |
| `N3` | 仅在 N3 arm 进化得到的 skill |
| `N4` | 仅在 N4 arm 进化得到的 skill |

`Initial/Clean/N1/N2/N3/N4` 的最终评测都必须使用同一份、未参与更新或候选筛选的 untouched clean evaluation。N1–N4 是分开运行的单 stage arm，不应把多个 stage 的组合结果填入其中任一列。

除最终 score 外，报告还应包含 release/run identity、applicability、mutation audit、protected-field audit、更新是否真正发生，以及任何 `unsupported` 或 failure。某个 stage 不被方法支持时，保留缺失值并解释 capability gap，不要用 clean 结果或数字零代填。

## 8. 哪些情况不能解释为噪声无效？

以下情况都不是 noise null effect：

- stage 不受方法支持，尤其是 N4 缺少 faithful feedback/update boundary；
- operator 找不到声明的目标，因而 `applicable=false`；
- operator discovery、adapter conversion、protected-field audit、runner 或 replay-pack gate 失败；
- provider/tool 执行失败、超出预算、缺少完整证据，或没有实际执行 skill update；
- clean/noisy arm 不共享要求的 seed、任务、方法、模型、预算或 clean evaluation identity；
- mutation 改动了 reward、official score、environment state 或其他规范保护的执行结果；
- baseline 本身没有可确认的 clean evolution gain，却把 clean/noisy 平局解释为鲁棒性。

只有在 operator 可用、mutation 确已进入 learner 的真实边界、所有保护字段不变、更新与 clean evaluation 均完整执行时，“未观测到差异”才能作为该 stage 在当前方法和实验设置下的 null 结果进入分析；它不能外推为“N3/N4 普遍无效”。
