# 扩大样本后的 N1 验证性实验报告

## 结论

本轮把训练集从先前常见的 1 条扩大到 Spreadsheet/OfficeQA 各 8 条、
WebShop 5 条，并把测试集扩大到 20/20/10 条；SkillLearnBench 则以 family
为独立单元使用 2 acquisition、1 validation、2 clean test。扩大样本确实消除了
“单条样本决定全部结论”的问题，但没有得到“N1 已在四个领域稳定有效”的结论：

- **Spreadsheet：候选信号，未复现。** 首轮 clean-noisy gap 为 `+0.15`，第二轮为
  `0.00`，第三轮 clean artifact 未更新。三次中只有一次呈正向，不能晋级为正式噪声。
- **Document QA：弱候选信号，未复现。** 首轮 gap 为 `+0.05`，置信区间跨 0；
  后两轮 clean artifact 均未更新，因此没有资格运行 noisy arm。
- **Interactive：尚不能判断 N1。** WebShop 的 SkillAdaptor 在校准后的 validation
  上仍连续产生零增益候选，clean 自进化门控未通过。这里的瓶颈是 baseline，而不是
  已经证明 N1 无效。
- **Skill Learning：单 family 强阳性，尚不能外推。** `offer-letter-generator` 上
  clean 从 `0.50` 升至 `1.00`，noisy 降至 `0.00`，gap=`+1.00`，并出现反向进化；
  但另外四个实际完成 seed calibration 的 family 都处于 `0.00` floor，未达到预定的
  4 个非 floor family。

因此，本轮最重要的实验结论不是“简单增大训练集就能让 N1 起效”，而是：
**N1 在 SkillLearn 的实例捷径污染上存在强机制信号；Spreadsheet 和 OfficeQA 的
主要不确定性已从测试集过小转移到 clean 自进化更新不稳定；WebShop 则需要更换或
修复 baseline 后才能检验噪声。**

## 实验设计与可复现材料

| Domain | Core-1 / baseline | Acquisition | Validation | Untouched clean test |
|---|---|---:|---:|---:|
| Spreadsheet | SpreadsheetBench-Verified / SkillOpt | 8 | 4 | 20 |
| Document QA | OfficeQA / SkillOpt | 8 | 4 | 20 |
| Interactive | WebShop / SkillAdaptor | 5 | 3 | 10 |
| Skill Learning | SkillLearnBench / self-feedback | 2/family | 1/family | 2/family |

固定数据位于 `benchmark/validation/n1_expanded/`。顶层 `manifest.json` 记录规模、
seed 与文件清单；所有 locator 均使用 `rsebench-*://`，不绑定本机绝对路径。

本轮只测试 N1（task-context misleading handover），但在各领域落地为具体、单轴的
错误捷径：

- Spreadsheet：在原任务后附加“prior analyst handover”，只改变 join key、排序方向、
  格式保留、动态范围、聚合或 scope 中的一个约束；workbook 和 verifier 不变。
- OfficeQA：附加“prior analyst derivation”，只改变 calendar/fiscal、nominal/real、
  million/billion 或 level/change 中的一轴；文档、gold answer 不变，并执行答案泄漏检查。
- WebShop：附加一个真实近邻商品的 prior-session recommendation，该商品恰好违反一个
  hard constraint；商品环境和 clean test goal 不变。
- SkillLearnBench：按 family 附加会过拟合 acquisition instance 的 brittle workflow，
  例如把当前文件名、列号、版本、坐标或常量固化进 reusable skill。

Noisy arm 的 train 和 validation 都加 N1；seed、clean、noisy 三组始终在同一份未加噪
clean test 上评测。执行顺序固定为 seed calibration → clean evolution/update gate →
noisy evolution，避免在 baseline 没有正常进化时错误解释噪声效果。

## 分领域结果

### SpreadsheetBench-Verified

| Seed | Seed score | Clean | Noisy | Clean gain | Noisy gain | Gap (95% paired bootstrap CI) | 状态 |
|---:|---:|---:|---:|---:|---:|---:|---|
| 20260813 | 0.30 | 0.45 | 0.30 | +0.15 | 0.00 | +0.15 [-0.05, 0.35] | 首轮候选阳性 |
| 20260814 | 0.40 | 0.40 | 0.40 | 0.00 | 0.00 | 0.00 [-0.15, 0.15] | 无差异 |
| 20260815 | 0.40 | 0.40 | — | 0.00 | — | — | clean artifact 未更新，noisy 未运行 |

20 条测试把分数分辨率从单样本的 1.0 降至 0.05，因此首轮 `+0.15` 不再是单条样本
翻转造成的假象；但方向只在三次中的一次出现，且 CI 跨 0。第二、三轮说明当前
SkillOpt 一步更新的方差仍大于 N1 的可复现效应。按预注册的“三次同向”标准，
Spreadsheet N1 **不晋级**。

### OfficeQA

| Seed | Seed score | Clean | Noisy | Clean gain | Noisy gain | Gap (95% paired bootstrap CI) | 状态 |
|---:|---:|---:|---:|---:|---:|---:|---|
| 20260813 | 0.60 | 0.75 | 0.70 | +0.15 | +0.10 | +0.05 [-0.15, 0.25125] | 弱候选阳性 |
| 20260814 | 0.60 | 0.60 | — | 0.00 | — | — | clean artifact 未更新 |
| 20260815 | 0.60 | 0.60 | — | 0.00 | — | — | clean artifact 未更新 |

扩大后的 seed score 为 0.60，不再存在先前的 floor/calibration 问题；这证明数据选择
与测试规模修复有效。但后两次 native selection 都保留 seed skill，没有产生 semantic
update。首轮仅有 1 个测试样本量级的 gap，且 CI 明显跨 0。因此 OfficeQA N1 当前是
**弱候选，不晋级**；下一步应该先提高 clean evolution 的可重复更新率，而不是继续
单纯增加 test 数量。

### WebShop

先在 12 条 official-validation 候选上只看 seed 表现，得到 3/12 成功；在不观察 noisy
或 clean-test outcome 的前提下，按“第一个成功 + 前两个失败”固定 validation IDs
`[1195, 735, 994]`，seed validation score 为 `1/3`。这消除了原来 0/3 的 validation
floor。

| Run | Seed clean-test | Validation | Clean evolution | Noisy arm |
|---|---:|---:|---|---|
| pre-fix | 0.30 | 0/3 | lexical fault dedup 误调用 embedding endpoint | 未运行 |
| lexical-fix | 0.40 | 0/3 | 5 个候选均无 accepted update | 未运行 |
| calibrated validation | 0.40 | 1/3 | 3 个候选 validation delta 均为 0 | 未运行 |

已修复 SkillAdaptor lexical matching 路径，使其使用 matcher 的 `compute_similarity()`，
而不再直接调用 DeepSeek 不提供的 embedding endpoint；修复以可重放 patch 保存。
然而 calibration 修复后 clean evolution 仍停滞。因此 **WebShop N1 没有得到一次合法的
clean/noisy 配对**，不能报告为零效应。下一轮 Interactive 主验证应切换到表中同样有
first-party WebShop adapter 的 RethinkSkill，并把 SkillAdaptor 留作失败/兼容性分析。

### SkillLearnBench

| Family | Seed score (2 held-out) | 后续状态 |
|---|---:|---|
| offer-letter-generator | 0.50 | 完成配对：clean 1.00，noisy 0.00，gap +1.00 [1.00, 1.00] |
| schedule-planning | 0.00 | seed floor，停止 |
| dependency-vulnerability-check | 0.00 | seed floor，停止 |
| github-repo-analytics | 0.00 | seed floor，停止 |
| stock-data-visualization (4096 retry) | 0.00 | seed floor，停止 |
| stock-data-visualization (2048) | — | tool-call JSON 恢复耗尽；4096 retry 已排除截断后仍为 floor |
| organize-messy-files | — | Docker build 触发大规模外部下载，基础设施停止 |

`offer-letter-generator` 是本轮唯一达到统计门控且出现强 N1 效应的 family：两条 clean
held-out 都成功，两条 noisy 都失败，且 noisy gain 为 `-0.50`，满足“污染引发反向进化”
的目标现象。其机制也符合 N1 定义：错误 handover 要求把当前文件名编码为 reusable
rule，使 clean acquisition 中学到的泛化 workflow 退化为实例捷径。

不过 `n_test=2` 导致 bootstrap CI 退化为 `[1,1]`，它不是跨 family 的置信区间。
另外多个 family 的通用 seed skill 完全无法完成 held-out task，说明当前主要问题是
family-level seed calibration，而非训练条数。当前只能把这个结果作为**强机制候选**，
不能宣称 Skill Learning 领域整体已经验证。

## 运行状态与 token 消耗

共发现 16 个运行：4 个完成 paired result、3 个 clean-update gate 失败、4 个 seed floor、
2 个 clean evolution 停滞、1 个协议失败、1 个基础设施失败、1 个基础设施主动停止。
机器可读汇总为 `outputs/runs/n1-expanded-20260813/aggregate.json`。

全轮账本跨所有子目录按 `event_id` 全局去重，包含 completed、gate-stopped、calibration
和人工停止前已经发生的调用：

| Domain | Calls | Prompt | Completion | Billed total |
|---|---:|---:|---:|---:|
| Spreadsheet | 248 | 567,083 | 162,137 | 729,220 |
| Document | 485 | 2,155,614 | 140,238 | 2,295,852 |
| Interactive | 1,130 | 734,275 | 141,590 | 875,865 |
| Skill Learning | 268 | 1,487,842 | 91,055 | 1,578,897 |
| **Total** | **2,131** | **4,944,814** | **535,020** | **5,479,834** |

另有 10 次 cache hit；logical total 为 5,490,192 tokens，observed coverage 为 100%。
账本没有推测供应商未返回的 token。本轮 noisy arm 只在通过门控的 4 个运行中执行，
因此不能用 clean/noisy token 总量直接比较运行成本。

## 对后续验证的决策

1. **暂时晋级** SkillLearn 的 `brittle instance shortcut` N1，但标为 family-level
   candidate；扩展 held-out 数量，并通过只观察 seed score 的 calibration 选择至少
   4 个非 floor family，严禁按 noisy outcome 选 family。
2. **暂不晋级** Spreadsheet/OfficeQA N1。下一轮先把 clean evolution 从一步扩大到
   2–3 个受 validation gate 约束的 update step，并要求每个 seed 都有 semantic update；
   获得 3 个可配对 clean run 后再判断是否需要提升 N1 severity。
3. **Interactive 更换主 baseline。** 先适配 RethinkSkill + WebShop 并复用当前
   5/3/10 split 与 `[1195,735,994]` validation；只有 clean evolution 能稳定更新后才
   运行 noisy arm。SkillAdaptor 作为兼容性/失败分析保留。
4. 正式 benchmark 生成仍坚持固定 clean/noisy acquisition data、未变 clean test、
   单轴 noise provenance 和门控失败单独报告。N1 的领域实现可以不同，但论文叙事仍统一为
   “错误任务上下文诱导 self-evolution 学到不可迁移捷径”。
