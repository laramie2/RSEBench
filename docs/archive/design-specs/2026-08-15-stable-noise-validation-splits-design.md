# N1–N4 稳定验证样本冻结设计

日期：2026-08-15

## 1. 目标与当前阶段范围

本设计首先为四个领域确定一组能够稳定执行 clean 自进化、规模足够且可跨仓库复现的筛选样本，并同时封存一组独立确认样本。样本冻结完成后再开展 N1–N4 加噪实验。

当前阶段只完成以下工作：

1. 建立历史样本暴露表；
2. 生成并审计候选 train/validation；
3. 通过 clean 资格验证选择首个合格候选；
4. 冻结新的 screening test 和独立 confirmation split；
5. 生成可提交到 GitHub、可被多个仓库消费的 manifest、哈希和资源解析信息。

当前阶段不运行正式 N1–N4 noisy evolution，也不根据 noisy 结果修改样本。

四个领域及 baseline 固定为：

| 领域 | Benchmark | Baseline |
|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt |
| Document QA | OfficeQA Full | SkillOpt |
| Interactive | WebShop | SkillAdaptor |
| Skill Learning | SkillLearnBench | Self-Feedback |

模型身份固定为 `deepseek-v4-flash`、temperature 0、thinking disabled，method seeds 固定为 `20260813`、`20260814`、`20260815`。

## 2. 已选择的方法

采用“两阶段、顺序资格验证后冻结”的方案：

1. 第一阶段在经过 clean 资格验证的 screening split 上筛选 N1–N4；
2. 只有达到至少 3/4 领域有效的噪声阶段才进入独立 confirmation split；
3. 第二阶段只确认第一阶段晋级的噪声阶段；
4. 同一阶段在第一阶段和第二阶段都达到至少 3/4 领域有效，才能标记为 `confirmed_cross_domain_noise`。

候选 split 不按 clean 提升幅度排名。候选按固定顺序运行，首个通过即冻结，最多尝试三个候选。该规则提高 clean 更新概率，同时避免在多个结果中挑选最好看的 split。

## 3. 数据边界

### 3.1 三类数据用途

数据分为三类：

- `qualification_test`：已经在历史 clean-v2 或固定产物重评中看过结果，只用于选择稳定 train/validation；
- `screening_test`：不参与候选选择，train/validation 冻结后才首次执行，用于第一阶段 N1–N4 比较；
- `confirmation_split`：与第一阶段独立，在第一阶段开始前生成并锁定，只有噪声阶段晋级后才执行。

当前 clean-v2 test 全部降级为 development/qualification evidence，不再作为新的 screening test。

### 3.2 规模

| Benchmark | 第一阶段 train | 第一阶段 validation | 第一阶段 screening test | 独立确认 train/validation/test |
|---|---:|---:|---:|---:|
| Spreadsheet | 20 | 10 | 30 | 20/10/30 |
| OfficeQA | 12 | 12 | 20 | 12/12/20 |
| WebShop | 5 | 5 | 20 | 5/5/20 |
| SkillLearn | 4 families × 2 | 4 families × 1 | 每 family 剩余 2–3 | 另外 4 families，按 2/1/剩余实例划分 |

Spreadsheet 保持 `7/7/6` 三个 SkillOpt 更新批次。OfficeQA 保持 `4/4/4` 三个更新批次。WebShop 保持三轮、15 episode steps 和原生 `min_sample_size=5`。SkillLearn 每个 acquisition 实例执行一轮 self-feedback，family 之间不共享技能。

### 3.3 SkillLearn family 固定分组

第一阶段使用此前预注册顺序中的前四个 family：

1. `organize-messy-files`；
2. `offer-letter-generator`；
3. `schedule-planning`；
4. `dependency-vulnerability-check`。

独立确认保留另外四个 family：

1. `court-form-filling`；
2. `earthquake-plate-calculation`；
3. `dbscan-parameter-tuning`；
4. `travel-planning`。

这四个 family 是在冻结前根据历史暴露登记确定的固定集合：均未产生历史执行证据，实例规模均满足 `2/1/2–3`，并覆盖文档、科学计算、数据分析与规划。原拟集合中的 `github-repo-analytics` 和 `stock-data-visualization` 已有真实历史运行，导致原四族整体不能作为预注册的独立确认集合；`financial-analysis` 与 `enterprise-information-search` 只有 preflight 记录，但为避免保留一个混合历史集合，本次一并替换。此次替换发生在任何新 clean/noisy 筛选结果产生之前，后续仍禁止动态替补。

family 不得在看到 clean 或 noisy 结果后互换或替补。

## 4. 历史暴露与独立性

样本生成前扫描仓库内的 machine-readable manifests、release records 和 results，形成 `exposure_registry.json`。每个 task ID 至少记录：

- benchmark 和 source partition；
- 是否出现在历史 train、validation 或 test；
- 是否已经产生模型输出或正式分数；
- 首次和最近一次暴露的实验 ID；
- 暴露级别：`manifest_only`、`executed` 或 `score_observed`。

暴露级别由实际 artifact 语义约束：preflight、镜像预构建和 dry-run 中仅声明的 task ID 只能记为 `manifest_only`；只有真实 task timing/执行记录才能提升为 `executed`，真实逐题分数才能提升为 `score_observed`。当前 `noise_screen_v1` 输出子树必须从自己的历史扫描中排除，以保证重复生成不会自污染。

规则如下：

1. qualification 数据允许来自 `score_observed` 集合；
2. 除第 4.1 节记录的 SkillLearn 有限实例例外外，新 screening test 不得包含 `score_observed` task；
3. confirmation split 不得包含第一阶段 train、validation、screening test，也不得包含历史 `executed` task；
4. confirmation 数据先于第一阶段结果生成并锁定；
5. 如果可用池不足则 fail closed，不降低独立性要求或静默复用样本。

confirmation manifest 可以随代码提交到 GitHub；“封存”表示禁止运行和用结果调整第一阶段，不依赖隐藏 task ID。

### 4.1 SkillLearn 有限实例例外

`organize-messy-files` 和 `offer-letter-generator` 的 family 末端实例已有历史分数，而每个 family 只有 5–6 个实例，无法在保留相同 family 的同时构造新的未评分 test。因此：

- 第一阶段四个 SkillLearn family 明确属于 development-screening；
- 其分数可以筛选噪声，但不能单独支持跨-family 普适性结论；
- 第二阶段四个 confirmation family 当前没有历史结果记录，必须保持完全未执行；
- 最终 SkillLearn 普适性证据必须来自第二阶段的跨-family 复现。

该例外只适用于 SkillLearn 第一阶段，不放宽 Spreadsheet、OfficeQA、WebShop 的新 screening test 要求。

## 5. 确定性候选生成

### 5.1 通用排序

所有新样本采用确定性哈希排序，不使用进程相关随机状态：

```text
sha256(canonical_json(["noise-screen-v1", benchmark, role,
                       candidate_index, stratum, task_id]))
```

在每个预声明 stratum 内按哈希升序，再以 round-robin 合并 strata。最终 manifest 记录 selection version、哈希输入字段、source hash、选中 ID 顺序和拒绝原因。

### 5.2 候选顺序

- Candidate 1 是现有 clean-v2 train/validation；
- Candidate 2 和 Candidate 3 从剩余 development pool 按上述哈希规则生成；
- Candidate 1 失败后才运行 Candidate 2，Candidate 2 失败后才运行 Candidate 3；
- Candidate 通过后不再运行后续候选。

`canonical_json` 使用 UTF-8、无额外空白的 JSON 数组编码。Spreadsheet 的官方 validation 池只有 20 题：第一阶段沿用当前 10 题 validation，另外 10 题完整保留给 confirmation。为保持候选间验证门槛一致，四个领域的 Candidate 2/3 均只更换 train；第一阶段 validation 保持 Candidate 1 的固定内容和顺序。confirmation train/validation 在任何候选生成前优先预留，并与第一阶段完全互斥。

现有证据的初始状态为：

- Spreadsheet Candidate 1 在当前 formal identity 下只有 1/3 seed 接受更新，预登记为资格失败，从 Candidate 2 开始执行；
- OfficeQA Candidate 1 已有 2/3 seed 接受更新和固定产物正向重评证据，先做身份审计；
- WebShop Candidate 1 三颗 seed 均接受更新并得到正向 clean gain，先做身份审计；
- SkillLearn 单个 `offer-letter-generator` 结果不能替代四-family 资格验证。

## 6. 结构资格与分层

### 6.1 通用资格

候选 task 必须满足：

1. 原始输入、资源和官方 verifier 可解析；
2. 无缺失文件、无未声明外部依赖、无已知数学欠定题；
3. seed 执行中的系统、provider、parser、协议和接口失败率为 0；
4. validation 具备 headroom，不是全 0 或全满；
5. 每条实际送入 updater 的 noisy acquisition evidence 在对应的 N1–N4 阶段均有合法作用位置；
6. noise 不改变 protected instruction、gold、verifier 或 clean validation/test。

如果 clean trace 尚未生成，N3/N4 适用性在 clean qualification 中补充检查；找不到目标时该候选失败，不得把 no-op 计为 noisy 样本。

### 6.2 Spreadsheet

- 每个 `7/7/6` batch 至少包含一个 seed 成功和两个正常任务失败；
- 覆盖至少四类表格操作；
- validation seed score 位于闭区间 `[0.2, 0.8]`；
- N1/N2 有合法静态目标，N3 有 workbook-edit event，N4 有可替换的 sheet/range attribution。

### 6.3 OfficeQA

- 按 released difficulty、source-file count 和 period/unit/entity/aggregation 等问题轴分层；
- 每个四题 batch 同时包含 seed 成功和正常任务失败；
- validation parseable-answer rate 至少 0.9，seed score 位于闭区间 `[0.25, 0.75]`；
- 排除已记录为数学欠定的 `UID0240`；
- N2 必须存在真实近邻文档，N3 必须存在 oracle open/read event，N4 必须存在可替换 attribution。

### 6.4 WebShop

- goal 的 target ASIN 在 15 步预算内可达；
- normalized query 不重复；
- validation 固定为两个 seed success 加三个 seed failure，即 2/5 headroom；
- N1 near-match 只违反一个硬约束；
- N2 保留有效 target 可达；
- N3/N4 有合法 trajectory event 和 alternative fault step。

### 6.5 SkillLearn

- 每个实例能够启动预构建容器并完成官方 verifier；
- 训练阶段不暴露 hidden tests、reference solution 或 verifier internals；
- instance 1–2 用于 acquisition，instance 3 用于 validation，其余用于 test；
- 四个阶段在 acquisition 实例上均有合法作用位置；
- 至少三个第一阶段 family 必须 clean-ready，SkillLearn 领域才可进入 noisy 筛选。

## 7. Clean 资格验证与顺序停止

每个 Candidate 使用全部三颗 method seed。候选通过要求：

1. train 和 validation 执行覆盖率 100%；
2. 至少两颗 seed 接受一次真实更新；
3. 对应 final artifact 与 seed artifact 的语义哈希不同；
4. 在 qualification test 上至少两颗 seed 的固定产物平均 `clean - seed >= 0`；
5. 三颗 seed 汇总平均 `clean - seed > 0`；
6. 没有系统性执行失败或预算不一致；
7. noisy acquisition 的结构适用性检查通过。

固定 artifact 在 qualification test 上先重复评测三次；差值符号不一致时扩展至五次。该评测只生成 pass/fail，不按 gain 大小选择候选。

SkillLearn family clean-ready 要求三颗 seed 中至少两颗接受更新且 validation 合法执行；四个 family 中至少三个 clean-ready，领域才通过。

发布资格决定保留这一方法差异：Spreadsheet、OfficeQA、WebShop 使用固定产物重评得到的 `CandidateDecision`；SkillLearn 没有 qualification-test 固定产物重评，不能伪造 `mean_clean_gain` 或 nondegrading seed，因此使用独立的 `SkillLearnQualificationDecision`，绑定四个固定 family 的逐 family/seed 资格摘要、执行覆盖率、N1–N4 适用性和 owned-evidence 哈希。发布层使用带 `decision_type` 的显式 union，并重新从 run/replay 证据派生后校验 aggregator 写出的 companion。

三个候选均以完整、确定性的证据失败时，该领域标记为 `clean_blocked_after_three_candidates`，停止样本冻结，不继续更换数据。Candidate 3 证据缺失或不可读时仍返回 `run_candidate_3` 以重试同一候选，不能把不完整执行误记为三次确定性失败。

## 8. Screening test 首次评测后的约束

train/validation 通过后立即冻结新的 screening test。首次评测后：

- 至少两颗 seed 的 screening `clean_gain >= 0`；
- 三颗 seed 汇总平均 `clean_gain > 0`；
- 不满足时标记 `clean_generalization_failed`；
- 不得因为 screening test 结果更换 train、validation 或 test。

这一步决定该领域是否能进入 N1–N4，而不参与样本再选择。

## 9. Clean 复用与后续噪声判定

第一阶段每颗 method seed 只运行一次 clean evolution。通过身份校验的 clean artifact 同时作为 N1–N4 的公共对照。

四个 noisy arm 完成后统一评测：

```text
seed + clean + N1 + N2 + N3 + N4
```

先重复三次，边界或符号不一致时整体扩展到五次。artifact 顺序按 method seed 和 repeat 循环轮换。历史单次 clean 分数不直接复用。

对领域 `d`、噪声阶段 `n` 和 method seed `s`：

```text
clean_gain = mean(score(clean)) - mean(score(seed))
noise_gap  = mean(score(clean)) - mean(score(noisy_n))
```

单领域分类：

- `effective`：平均 `noise_gap >= 0.05` 且至少 2/3 seeds 严格为正；
- `null`：平均 gap 位于 `(-0.05, 0.05)` 或 seed 方向不一致；
- `opposite`：平均 `noise_gap <= -0.05`；
- `blocked`：clean 不合格、噪声不适用、预算不一致或存在系统性执行问题。

SkillLearn 先按 family 计算，再对 family 宏平均；至少 3/4 family 的 gap 为正且宏平均 gap 至少 0.05，领域才为 `effective`。

某 N 阶段第一阶段晋级要求：

1. 四个领域均得到合法、非 blocked 结果；
2. 至少 3/4 领域为 `effective`；
3. 剩余领域可以是 `null`，不能是 `opposite`。

独立确认重新运行 clean/noisy evolution，不复用第一阶段 artifact，并再次应用相同判定。paired bootstrap 95% 区间作为证据强度报告，不作为本轮验证硬门槛。

## 10. 后续执行顺序与早停

正式 N1–N4 阶段按成本递增：

1. Spreadsheet 与 OfficeQA；
2. 仍可能达到 3/4 时运行 SkillLearn；
3. 前三个领域至少两个 effective 时运行 WebShop；
4. 只对第一阶段晋级噪声运行独立确认。

允许的预注册 futility stop：

- Spreadsheet 和 OfficeQA 均为 null/opposite 时跳过后续高成本领域；
- 任一领域为 opposite 时，该阶段不再竞争跨领域晋级；
- 前三个领域少于两个 effective 时不运行 WebShop。

已启动单元正常完成；不能根据第一或第二颗 seed 跳过第三颗 seed。基础设施失败可用完全相同身份自动重试两次，仍失败则暂停修复，不能计成 null。

## 11. GitHub 与多仓库可移植发布

样本冻结产物使用以下结构：

```text
benchmark/validation/noise_screen_v1/
  manifest.json
  base_splits/
    spreadsheetbench_verified.json
    officeqa_full.json
    webshop.json
    skilllearnbench/<family>.json
  candidate_audits/
  exposure_registry.json
  confirmation_seal.json
  resource_lock.json
```

发布约束：

1. JSON 中禁止绝对路径和当前 worktree 路径；
2. 资源使用 `rsebench-data://`、`rsebench-methods://` 或仓库相对 URI；
3. 每个 manifest、任务顺序、source resource 和 selection policy 均记录 SHA-256；
4. `resource_lock.json` 记录许可证允许提交的小型资源以及必须外部 materialize 的大型资源；
5. Git 仓库保存 exact task manifests 和资源哈希，不默认复制大型原始 benchmark、WebShop catalog 或 SkillLearn container image；
6. 多仓库运行前通过 bootstrap/preflight 将 URI 映射到各仓库的数据根目录，并验证哈希；
7. 每个结果记录 selection release hash，确保不同仓库使用同一组样本；
8. confirmation split 随 release 提交但保持未执行状态，解锁动作写入后续实验 manifest。

因此，GitHub 中的冻结对象是可审计、可解析的样本清单和资源锁；大型数据按原 benchmark 分发方式获取，不能仅依赖本仓库 Git history 隐式存在。

## 12. 当前阶段的完成标准

“样本已经确定”必须同时满足：

1. 四个领域 candidate selection 均结束；
2. 每个选择都有完整 pass/fail audit，未隐藏失败候选；
3. 四个领域均有冻结的第一阶段 base split；
4. 四个领域均有互斥的 confirmation split；
5. exposure registry、resource lock、task/source hashes 完整；
6. manifest schema、路径可移植性、split 互斥性和 task count 测试通过；
7. clean 资格证据和 screening clean-generalization 状态写入 machine-readable aggregate；
8. 四个领域的状态均为 `clean_generalization_ready`；任何 `clean_generalization_failed` 都使样本 release 保持 blocked；
9. 没有正式 N1–N4 noisy result 混入本阶段 release。

达到上述条件后，样本 release 才提交到 GitHub，并作为多个实验仓库的唯一 split identity。
