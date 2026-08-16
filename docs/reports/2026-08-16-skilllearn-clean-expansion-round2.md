# SkillLearn clean 扩样第二轮验证报告

日期：2026-08-16

## 结论

本轮最终为 5 个 SkillLearn family 各取得了 3 个合法 clean seed 结果。按照运行前
冻结的门槛，只有 `offer-letter-generator` 合格：三个 seed 全部接受两次更新，
held-out clean gain 分别为 `+0.3333`、`+0.6667`、`+0.6667`。

`court-form-filling`、`earthquake-plate-calculation`、
`dbscan-parameter-tuning` 和 `travel-planning` 都能够执行自进化流程；其中四者至少
有 2/3 seed 接受更新，但严格正向 gain 分别只有 1/3、0/3、0/3、0/3，不能证明
clean 自进化稳定提升能力。

因此本轮只有 **1 个合格 family、3 个合格 clean-test 实例**，没有达到 bundle
冻结所需的 `≥4 families` 和 `≥10 clean-test tasks`。没有创建 SkillLearn noise
selection release，也没有降低门槛。目录
`benchmark/validation/skilllearn_clean_expansion_v1/` 是已版本化的候选输入池，
不是可直接用于 N1–N4 的正式冻结 release。

## 固定设置

- Baseline：`skilllearn_self_feedback`，每个单元两轮 self-feedback。
- Provider/model：DeepSeek / `deepseek-v4-flash`，temperature 0，thinking disabled。
- Method seeds：`20260813`、`20260814`、`20260815`。
- 并发：最多 3 个 SkillLearn 单元。
- 数据：5 个官方 family，共 28 个实例；10 train、5 validation、13 clean test。
- 单 family：2 train、1 validation、2–3 clean test。
- 本轮只运行 clean，不生成或执行 N1–N4。
- Family 资格：3 seeds 全部完成并覆盖 verifier；至少 2 seeds 接受更新；至少
  2 seeds 有严格正向 held-out gain；其余 seed 不退化。
- Bundle 资格：至少 4 个合格 family，且合计至少 10 个 clean-test 实例。

正式矩阵为 `configs/experiments/skilllearn-clean-expansion-round2.yaml`，SHA-256 为
`a152ace35cc66678eba34856ff2a0e53ef709f490425adcea7ac89086180beb3`，执行提交为
`d110e5d`。恢复矩阵为 `configs/experiments/skilllearn-recovery-round2.yaml`，
SHA-256 为
`0f1145df113e427462c8829b61c54535d6f417b767485f6efa3ca8ae350cbcff`，执行提交为
`87e16cd`。

候选输入索引 SHA-256 为
`835ba5c4a71414cc7a79357344f35d0deba6235481907dc9e2672410f0f933d5`。

## Family 结果

分数写作 `seed score → evolved clean score`，括号内为 accepted update 数量。

| Family | Train/val/test | Seed 13 | Seed 14 | Seed 15 | 正增益 seeds | 决定 |
|---|---:|---:|---:|---:|---:|---|
| offer-letter-generator | 2/1/3 | 0.667→1.000 (2) | 0.000→0.667 (2) | 0.333→1.000 (2) | 3/3 | 合格，保留 |
| court-form-filling | 2/1/3 | 1.000→1.000 (0) | 0.667→1.000 (2) | 1.000→1.000 (1) | 1/3 | 正增益不足 |
| earthquake-plate-calculation | 2/1/3 | 0.000→0.000 (2) | 0.000→0.000 (2) | 0.000→0.000 (2) | 0/3 | 稳定 floor |
| dbscan-parameter-tuning | 2/1/2 | 1.000→1.000 (0) | 1.000→0.500 (2) | 1.000→1.000 (2) | 0/3 | ceiling 且一次退化 |
| travel-planning | 2/1/2 | 0.000→0.000 (2) | 0.000→0.000 (2) | 0.500→0.000 (2) | 0/3 | floor 且一次退化 |

`offer-letter-generator` seed 15 复用了上一轮已经完成且通过 clean qualification 的
固定结果；其 split source hash 与本轮候选输入完全一致。本轮只重放此前因 verifier
启动失败而无效的 seed 13/14，没有重复支付 seed 15。

## 两个运行时问题及修复

### Offer verifier

上游 `offer-letter-generator` 的 `/tests/test.sh` 每次都会联网执行系统包更新、下载
工具并解析 pytest 依赖，导致相同镜像在不同时间可能完成或超时。模型任务仍在原始
内容寻址镜像中执行；只有模型工具循环结束后，runner 才复制经过哈希审计的 wheelhouse，
离线安装固定 verifier 依赖，再运行原始 `/tests/test_outputs.py`。正式 wheelhouse
SHA-256 为
`f51141a80afad18511f0b41c290e65432c0fb1d03a02e749c43984e47858d157`。

修复没有改变 self-feedback 算法、task 数据、模型输出或评分测试，只消除了 verifier
bootstrap 的联网方差。offer seed 13/14 均在修复后完整结束并得到正增益。

### DBSCAN 长命令

正式矩阵中 DBSCAN seed 14/15 都在模型自行生成的全量参数重算脚本上触发固定
300 秒 `docker exec` 上限。两个失败具有相同根因，provider 调用和官方 verifier
本身没有报错。

runner 现支持显式、可审计且有界的 `command_timeout_seconds`（1–1800 秒）；只有
DBSCAN 恢复单元设为 900 秒，其他 family 继续使用默认 300 秒。该值同时写入实验
身份和结果参数。恢复后两个 seed 均完整结束：seed 15 用时 995.546 秒，seed 14
用时 2538.188 秒；后者最终退化，说明“修复可运行性”没有被误写成“修复能力”。

原始两个失败 attempt 仍保留在正式矩阵分母、stderr、timing 和 token 账本中。

## 三级时间记录

正式矩阵从 `2026-08-16T02:49:25.928894Z` 至
`2026-08-16T03:45:48.356433Z`，墙钟 **56 分 22.428 秒**。恢复矩阵从
`2026-08-16T03:52:25.567926Z` 至 `2026-08-16T04:34:45.279293Z`，墙钟
**42 分 19.711 秒**。两段付费运行墙钟合计 **1 小时 38 分 42.139 秒**；包含中间
定位、TDD、全量测试和 preflight 后，从正式矩阵开始到恢复矩阵结束共
**1 小时 45 分 19.350 秒**。

16 个新 attempt 中 14 个完成、2 个失败；失败的 DBSCAN seed 14/15 随后各有一个
恢复 attempt。scheduler 累计单元时间为 **14,148.237 秒**。

| 时间层级 | 状态 | 数量 | 累计时间 |
|---|---|---:|---:|
| Run | completed | 14 | 11,905.466 秒 |
| Run | failed | 2 | 2,217.606 秒 |
| Stage | completed | 44 | 13,030.350 秒 |
| Stage | failed | 2 | 1,092.684 秒 |
| Task | completed | 149 | 13,407.242 秒 |
| Task | failed | 2 | 715.620 秒 |

其中完成的 stage 为 seed evaluation 16 个、evolution 14 个、clean-test evaluation
14 个；两个失败都发生在 evolution stage。各 attempt 下均保存
`timing/events.jsonl` 与 `timing/summary.json`。

## Token 账本

计划原为 14 个付费单元；DBSCAN 暴露长命令上限后增加 2 个定向恢复 attempt，
所以本轮实际执行 16 个新 attempt。共记录 1,872 次 provider 调用，usage 观测覆盖率
为 100%。历史 offer seed 15 的 699,420 tokens 只作结果引用，不重复计入本轮成本。

| 口径 | Prompt | Completion | Total |
|---|---:|---:|---:|
| Billed | 20,881,924 | 1,003,109 | 21,885,033 |
| Logical（含 21 次 cache hit） | 20,978,793 | 1,008,664 | 21,987,457 |

正式矩阵 billed tokens 为 19,577,141，其中两个失败 attempt 消耗 1,069,175；恢复
矩阵为 2,307,892。所有失败发生在本地任务命令，不是 provider 调用失败。

## 冻结判断与下一步

`selected_families=["offer-letter-generator"]`，合格 clean-test 数为 3。当前候选池
对样本构建的帮助是：确认了一个稳定正向 family，并排除了四个“能更新但不能稳定
提升 held-out 能力”的 family，避免直接把 13 个 test 实例全部投入 N1–N4。

下一轮若仍要达到 SkillLearn bundle 冻结目标，应保留已经合格的 offer split，只对
尚未筛选且至少有 5 个官方实例的 family 做 clean-only 三 seed 筛选。优先候选为
`anthropic-poster-design`、`chinese-poem-generator`、`temperature-simulation`、
`video-object-counting`、`weighted-gdp-calculation`。获得至少 3 个新增合格 family、
且合格 test 总数达到 10 后，再创建正式 release 并开展 N1–N4。

## 机器可读结果

- `outputs/runs/skilllearn-clean-expansion-round2-20260816/aggregate.json`
- `outputs/runs/skilllearn-clean-expansion-round2-20260816/matrix_status.json`
- `outputs/runs/skilllearn-recovery-round2-20260816/aggregate.json`
- `outputs/runs/skilllearn-recovery-round2-20260816/matrix_status.json`
- `outputs/runs/skilllearn-clean-expansion-round2-20260816/combined_qualification.json`

