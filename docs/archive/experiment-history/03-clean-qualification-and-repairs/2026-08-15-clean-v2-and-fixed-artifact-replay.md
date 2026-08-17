# Clean-v2 与固定产物重复评测报告（2026-08-15）

## 1. 结论摘要

截至 2026-08-15，`clean-v2` 正式矩阵的 12 个单元均已完成，四组当前配置都能够执行完整的 seed 评测、自进化和 clean-test 评测。当前已不再存在阻断实验的 baseline 运行错误。

需要区分两个问题：

1. **baseline 是否能运行并产生更新**：四组当前配置均已证明可以。
2. **一次自进化是否必然提升能力**：不是。产物生成和模型评测都存在随机性，单次 seed→clean 差值不能稳定代表产物质量。

固定产物重复评测给出的最重要结论是：

- Spreadsheet 的 clean1 产物确实有效，尤其 `clean1_seed14` 在五轮中始终优于 seed；本次 formal seed13 失败是产物质量较差与 seed 评测抖动共同造成的，不是 Spreadsheet baseline 代码退化。
- OfficeQA 的两个 formal 产物在五轮固定重评中都保持非负差值且平均明显为正；原始 formal 的 `0/-0.10` 主要是单次评测波动，其中 seed14 还叠加过一次 clean 执行失败。
- WebShop seed15 已完成有效更新，20 题 clean-test 从 `0.1150` 提升到 `0.2525`；三颗正式 seed 全部为正增益。
- SkillLearn offer-letter 在 seed14、seed15 上均提升 `+0.3333`，但 seed13 为 0 分 floor；这只能资格化当前 family，不能外推到整个 SkillLearn。

## 2. Clean-v2 正式矩阵

矩阵状态：`12/12 completed`。

### 2.1 原始单次 formal 结果

| 组合 | seed | 接纳更新数 | seed score | clean score | 单次差值 | 执行失败 |
|---|---:|---:|---:|---:|---:|---:|
| Spreadsheet / SkillOpt | 20260813 | 1 | 0.4000 | 0.3333 | -0.0667 | 0 |
| Spreadsheet / SkillOpt | 20260814 | 0 | 0.4333 | 0.4333 | 0.0000 | 0 |
| Spreadsheet / SkillOpt | 20260815 | 0 | 0.3333 | 0.3333 | 0.0000 | 0 |
| OfficeQA / SkillOpt | 20260813 | 1 | 0.6000 | 0.6000 | 0.0000 | 0 |
| OfficeQA / SkillOpt | 20260814 | 1 | 0.6500 | 0.5500 | -0.1000 | clean 1 |
| OfficeQA / SkillOpt | 20260815 | 0 | 0.5000 | 0.5000 | 0.0000 | 0 |
| WebShop / SkillAdaptor | 20260813 | 4 | 0.1500 | 0.2000 | +0.0500 | 0 |
| WebShop / SkillAdaptor | 20260814 | 1 | 0.1000 | 0.1525 | +0.0525 | 0 |
| WebShop / SkillAdaptor | 20260815 | 1 | 0.1150 | 0.2525 | +0.1375 | 0 |
| SkillLearn / self-feedback | 20260813 | 0 | 0.0000 | 0.0000 | 0.0000 | 0 |
| SkillLearn / self-feedback | 20260814 | 2 | 0.3333 | 0.6667 | +0.3333 | 0 |
| SkillLearn / self-feedback | 20260815 | 2 | 0.6667 | 1.0000 | +0.3333 | 0 |

这些是每个产物只评一次的原始结果，不能单独用于判断 Spreadsheet 和 OfficeQA 的产物质量。

## 3. SkillOpt 固定产物重复评测

### 3.1 设置

- 模型：`deepseek-v4-flash`
- temperature：`0.0`
- 每个固定产物重复评测 5 次
- 每轮使用完全相同且顺序固定的 clean-test
- 产物执行顺序使用 `cyclic_rotation`，避免某个标签始终处于服务时间序列的同一位置
- 每个产物文件、任务清单和任务 ID 均记录 SHA-256 或等价稳定哈希
- 第 4、5 轮通过严格 resume 补跑，没有重复消费前 3 轮

规模：

| Benchmark | 产物数 | 重复数 | test 题数 | 任务回合 | 模型调用 | 失败调用 | Tokens | 活动时长 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Spreadsheet | 5 | 5 | 30 | 750 | 750 | 0 | 1,823,052 | 3,598.4 秒 |
| OfficeQA | 5 | 5 | 20 | 500 | 2,114 | 0 | 21,498,009 | 4,041.6 秒 |

OfficeQA 的模型调用数高于任务回合数，是因为多文档问答允许多个 tool/LLM turn。

### 3.2 Spreadsheet 结果

| 产物 | 五轮分数 | 平均分 | 分数 SD | 相对 seed 的五轮差值 | 平均差值 | 差值 SD | 判断 |
|---|---|---:|---:|---|---:|---:|---|
| seed | 0.2667 / 0.4000 / 0.4333 / 0.3333 / 0.3667 | 0.3600 | 0.0641 | 0 / 0 / 0 / 0 / 0 | 0 | 0 | seed 本身明显抖动 |
| clean1 seed13 | 0.4333 / 0.4667 / 0.4333 / 0.4333 / 0.4000 | 0.4333 | 0.0236 | +0.1667 / +0.0667 / 0 / +0.1000 / +0.0333 | +0.0733 | 0.0641 | 五轮非负，较稳健 |
| clean1 seed14 | 0.5000 / 0.5333 / 0.5000 / 0.4667 / 0.5667 | 0.5133 | 0.0380 | +0.2333 / +0.1333 / +0.0667 / +0.1333 / +0.2000 | +0.1533 | 0.0650 | 五轮全正，强证据 |
| v2 canary seed14 | 0.4667 / 0.4667 / 0.4000 / 0.3667 / 0.3667 | 0.4133 | 0.0506 | +0.2000 / +0.0667 / -0.0333 / +0.0333 / 0 | +0.0533 | 0.0901 | 符号不稳定 |
| v2 formal seed13 | 0.3000 / 0.2667 / 0.2667 / 0.3667 / 0.2333 | 0.2867 | 0.0506 | +0.0333 / -0.1333 / -0.1667 / +0.0333 / -0.1333 | -0.0733 | 0.0983 | 总体负向 |

判断：Spreadsheet / SkillOpt 的自进化能力已经被 clean1 两个不同产物证明；本次 v2 formal seed13 产物本身较差。原始单次 formal 的 `-0.0667` 不是 baseline 不能进化的证据，但也不能被解释成纯评测噪声，因为该固定产物五轮平均确实低于 seed。

### 3.3 OfficeQA 结果

| 产物 | 五轮分数 | 平均分 | 分数 SD | 相对 seed 的五轮差值 | 平均差值 | 差值 SD | 判断 |
|---|---|---:|---:|---|---:|---:|---|
| seed | 0.45 / 0.60 / 0.55 / 0.50 / 0.45 | 0.5100 | 0.0652 | 0 / 0 / 0 / 0 / 0 | 0 | 0 | seed 本身明显抖动 |
| canary positive | 0.60 / 0.60 / 0.60 / 0.65 / 0.55 | 0.6000 | 0.0354 | +0.15 / 0 / +0.05 / +0.15 / +0.10 | +0.0900 | 0.0652 | 五轮非负 |
| canary repaired | 0.60 / 0.55 / 0.60 / 0.65 / 0.65 | 0.6100 | 0.0418 | +0.15 / -0.05 / +0.05 / +0.15 / +0.20 | +0.1000 | 0.1000 | 平均正，一轮翻负 |
| formal seed13 | 0.60 / 0.65 / 0.55 / 0.70 / 0.65 | 0.6300 | 0.0570 | +0.15 / +0.05 / 0 / +0.20 / +0.20 | +0.1200 | 0.0908 | 五轮非负 |
| formal seed14 | 0.60 / 0.60 / 0.65 / 0.55 / 0.70 | 0.6200 | 0.0570 | +0.15 / 0 / +0.10 / +0.05 / +0.25 | +0.1100 | 0.0962 | 五轮非负 |

25 次固定产物评测共覆盖 500 个任务回合，任务级 execution failure 为 0。

判断：OfficeQA / SkillOpt 已能正常执行和产生有效产物。原始 formal seed13 的 0 差值和 seed14 的 -0.10 不能代表产物能力；五轮重评中两个 formal 产物均保持非负差值。seed14 原始 clean 评测还包含一次执行失败，这进一步放大了单次负值。

## 4. WebShop seed15

- 训练 / validation / clean-test：5 / 5 / 20
- 完成 3 个原生迭代
- 接纳更新：1 次，种子技能从 v1 更新至 v2
- clean-test：20/20 合法执行，execution failure 为 0
- seed score：0.1150
- clean score：0.2525
- 差值：+0.1375
- 总活动时长：18,015.0 秒（约 5 小时）
- 调用：7,349，失败 0
- Tokens：8,668,744，观测覆盖率 100%

运行时间长的主要原因不是 hang，而是 3 轮中生成或修订了大量候选，并对每个候选反复执行 5 题完整 validation 回归检查。最终报告记录了 1 次接纳和大量被回归保护拒绝的候选。

三颗 WebShop formal seed 的 clean-test 差值分别为 `+0.0500`、`+0.0525`、`+0.1375`，说明修复后的 SkillAdaptor 已能够稳定完成更新并在当前样本上产生正增益。

## 5. 当前资格判断

| 组合 | 执行资格 | 更新资格 | 能力提升证据 | 当前判断 |
|---|---|---|---|---|
| Spreadsheet / SkillOpt | 通过 | 通过 | clean1 两产物；其中 seed14 五轮全正 | baseline 可用于后续实验，但必须多 seed、重复评测 |
| OfficeQA / SkillOpt | 通过 | 通过 | 两个 formal 产物五轮非负、均值为正 | 可进入 N1，保留重复评测和执行失败审计 |
| WebShop / SkillAdaptor | 通过 | 通过 | 三颗 formal seed 全为正增益 | 可进入 N1，但需要单独控制高成本与长运行时间 |
| SkillLearn / self-feedback（offer-letter） | 通过 | 2/3 seed 更新 | 2/3 seed 为 +0.3333；1 seed floor | 当前 family 条件通过，不能外推到其他 family |

## 6. 后续实验约束

1. N1 clean/noisy 比较必须使用相同任务、相同产物评测次数和循环轮换顺序。
2. 不再使用一次 seed→clean 差值判断某个方法是否有效；至少保留 3 次，边界或符号不一致时扩展到 5 次。
3. Spreadsheet 不应只选择历史成功产物后再开展 N1。应预注册 method seed，并报告更新率、产物质量和评测方差三个层次。
4. OfficeQA 必须保留任务级 execution failure 与缺失答案审计，避免把执行失败计成能力退化。
5. WebShop 应单独设置 token/时间预算；不能为了缩短实验而改变 SkillAdaptor 的候选验证语义。
6. SkillLearn 在扩展到其他 family 前，需要逐 family 完成相同 clean 资格验证并排除 seed floor。

## 7. 机器可读结果

- `outputs/runs/clean-v2-20260814/matrix_status.json`
- `outputs/runs/skillopt-fixed-replay-20260815/spreadsheet/result.json`
- `outputs/runs/skillopt-fixed-replay-20260815/officeqa/result.json`
- `outputs/runs/skillopt-fixed-replay-20260815/spreadsheet.resume-plan.json`
- `outputs/runs/skillopt-fixed-replay-20260815/officeqa.resume-plan.json`
