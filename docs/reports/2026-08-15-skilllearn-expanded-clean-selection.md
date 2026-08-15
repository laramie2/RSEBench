# SkillLearn 扩大样本 clean 自进化筛选报告

日期：2026-08-15

## 结论

本轮 24 个固定实验单元已经全部进入终态，其中 19 个完成、5 个失败。
按照运行前冻结的选择规则，8 个候选 family 中 **0 个具备冻结资格**，因此本轮
没有创建 SkillLearn clean selection release，也没有为了得到可用集合而降低门槛。

本轮得到的核心证据是：`skilllearn_self_feedback` 的更新链路能够工作，但在当前
`deepseek-v4-flash`、每个 family 2/1/2–3 的 train/validation/test 配置下，更新极少
转化为 held-out 能力提升。19 个完成单元全部接受了两次更新，共 38 次 accepted
update；其中 17 个单元 clean gain 为 0，1 个为正，1 个为负。

唯一正向单元来自 `offer-letter-generator` seed `20260815`：clean test 从
`0.3333` 提升至 `1.0000`，gain 为 `+0.6667`。该 family 的另两个 seed 因上游
verifier 超时而无效，不能据此宣称自进化稳定有效。

## 固定实验设置

- Baseline：`skilllearn_self_feedback`，每个单元执行两轮 self-feedback。
- Provider/model：DeepSeek / `deepseek-v4-flash`，temperature 0，thinking disabled。
- Seeds：`20260813`、`20260814`、`20260815`。
- 并发：最多 3 个 SkillLearn 单元。
- 数据：8 个官方 family，共 44 个实例；16 train、8 validation、20 clean test。
- 单 family 划分：前 2 个实例为 train，第 3 个为 validation，剩余 2–3 个为
  clean test。
- 本轮只运行 clean，不生成或执行 N1–N4。
- Matrix：`configs/experiments/skilllearn-clean-expanded-v1.yaml`。
- Matrix hash：
  `77d092f61d45b1949020d6630f94ea780f215d3dccd4e367950d94bc482fab32`。
- 执行代码 HEAD：
  `8fc30a840599aa06ec528d4c6650156d082e36c5`。

预注册的 family 资格门槛为：3 个 seed 全部完成并覆盖官方 verifier；至少 2 个
seed 接受更新；至少 2 个 seed 有严格正向 held-out clean gain；其余 seed 不退化。
最终 bundle 还必须至少包含 4 个合格 family 和 10 个 clean-test 实例。

## Family 结果

表中每个分数写作 `seed score → evolved score`；括号内为 accepted update 数量。

| Family | Train/val/test | Seed 13 | Seed 14 | Seed 15 | 决定 |
|---|---:|---:|---:|---:|---|
| dependency-vulnerability-check | 2/1/2 | 0→0 (2) | 0→0 (2) | 0→0 (2) | 无正增益，排除 |
| enterprise-information-search | 2/1/3 | 0→0 (2) | 0→0 (2) | 0→0 (2) | 无正增益，排除 |
| financial-analysis | 2/1/3 | 0→0 (2) | 0→0 (2) | 0→0 (2) | 无正增益，排除 |
| github-repo-analytics | 2/1/2 | 失败 | 失败 | 失败 | 3/3 超时，排除 |
| offer-letter-generator | 2/1/3 | 失败 | 失败 | 0.3333→1.0000 (2) | 有强单次信号，但未完成 3 seeds |
| organize-messy-files | 2/1/3 | 0→0 (2) | 0→0 (2) | 0→0 (2) | 无正增益，排除 |
| schedule-planning | 2/1/2 | 0.5→0 (2) | 0→0 (2) | 0→0 (2) | 一次退化，其余 floor，排除 |
| stock-data-visualization | 2/1/2 | 0→0 (2) | 0→0 (2) | 0→0 (2) | 无正增益，排除 |

因此 `selected_families=[]`，合格 family 数为 0，冻结条件 `≥4 families` 与
`≥10 clean-test tasks` 均未满足。

## 五个失败单元

`github-repo-analytics` 的三个 seed 都触发 300 秒命令超时。模型为 119 个 PR
生成了逐 PR 的 GitHub API 请求，并在循环中加入等待或重复 rate-limit 查询；
分别在 seed evaluation 或 evolution 阶段耗尽命令预算。这是当前任务、模型输出
策略与命令预算不匹配，不能把它解释为“self-feedback 无效”，也不适合原样盲重试。

`offer-letter-generator` 的 seed `20260813` 和 `20260814` 在 seed evaluation
执行官方 `/tests/test.sh` 时达到 600 秒 verifier 超时。运行时检查显示上游脚本的
联网安装步骤（包括 `apt-get update`）发生阻塞。seed `20260815` 在相同实验矩阵下
完成并产生正增益，说明任务本身不是稳定的能力 floor；但另外两个 seed 在修复
verifier 环境并合法重放前仍必须计为失败。

所有失败都保留了 typed `TimeoutExpired` timing 记录、stderr 和 provider token
账本，没有从固定的 24 单元分母中删除。

## 三级时间记录

Matrix 从 `2026-08-15T17:34:57.299884Z` 运行至
`2026-08-15T19:39:46.155703Z`，实际墙钟时间为 **2 小时 4 分 48.856 秒**。
由于最多并行 3 个单元，scheduler 累计单元时间为 **21,742.917 秒**
（6 小时 2 分 22.917 秒），runner 内部记录为 **21,707.461 秒**。

| 时间层级 | 记录 | 完成/失败 | 累计时间 |
|---|---|---:|---:|
| Run | 24 个 clean qualification run | 19/5 | 21,707.461 秒 |
| Stage: seed evaluation | 24 | 21/3 | 6,463.649 秒 |
| Stage: evolution | 21 | 19/2 | 10,712.083 秒 |
| Stage: clean-test evaluation | 19 | 19/0 | 4,531.673 秒 |
| Task | 201 条 task timing | 196/5 | 21,707.170 秒 |

每个 runner 结果目录都保存 `timing/events.jsonl` 与 `timing/summary.json`；完成单元
还把 run/stage/task 三级摘要嵌入 `result.json`。失败单元同样保留失败层级、
`error_type=TimeoutExpired`、起止时间和 duration。

按 scheduler 累计时间统计，各 family 的三个 seed 总耗时如下：

| Family | 完成/失败 | 三 seed 累计时间 |
|---|---:|---:|
| dependency-vulnerability-check | 3/0 | 2,386.138 秒 |
| enterprise-information-search | 3/0 | 2,453.149 秒 |
| financial-analysis | 3/0 | 3,334.804 秒 |
| github-repo-analytics | 0/3 | 1,604.484 秒 |
| offer-letter-generator | 1/2 | 2,097.735 秒 |
| organize-messy-files | 3/0 | 3,116.026 秒 |
| schedule-planning | 3/0 | 3,898.884 秒 |
| stock-data-visualization | 3/0 | 2,851.696 秒 |

## Token 账本

24 个单元共记录 2,956 次 provider 调用；这些调用全部拿到了可观测 usage，观测
覆盖率为 100%。实验单元失败发生在任务命令或 verifier 超时，不应与 provider
调用状态混为一谈。

| 口径 | Prompt | Completion | Total |
|---|---:|---:|---:|
| Billed（排除 93 次本地 cache hit） | 28,200,953 | 1,187,550 | 29,388,503 |
| Logical（包含 cache hit 所代表的工作量） | 28,554,162 | 1,201,758 | 29,755,920 |

机器可读账本和实验汇总位于：

- `outputs/runs/skilllearn-clean-expanded-v1-20260815/aggregate.json`
- `outputs/runs/skilllearn-clean-expanded-v1-20260815/matrix_status.json`
- 各 attempt 下的 `timing/summary.json` 与 `token_usage/summary.json`

## 对样本冻结目标的帮助

这次扩大样本不是“没有结果”。它完成了三个必要筛选：

1. 证明 baseline 在 6/8 个 family、19/24 个单元上能完整执行两轮更新与 held-out
   评测，更新信号本身并不缺失。
2. 排除了 6 个稳定完成但没有 held-out 正增益的 family，避免后续在这些 floor
   数据上浪费 N1–N4 成本。
3. 定位出一个应优先保留并修复 verifier 的强候选
   `offer-letter-generator`，以及一个在改变执行策略前不应继续消耗成本的
   `github-repo-analytics`。

因此，本轮不能冻结数据，但明显缩小了下一轮搜索空间。后续也不应把“accepted
update”当作“能力提升”；clean control 必须继续以 held-out gain 为准。

## 建议的下一轮

先做 provider-free 的 verifier/image 检查并消除 `offer-letter-generator` 的联网
安装不确定性，然后只重放其两个失败 seed，保持原 task IDs、模型、seed、轮数和
选择标准不变。

同时另建一个 clean-only 候选矩阵，优先运行此前已规划为 confirmation 的四个
未筛选 family：

- `court-form-filling`：2/1/3；
- `earthquake-plate-calculation`：2/1/3；
- `dbscan-parameter-tuning`：2/1/2；
- `travel-planning`：2/1/2。

这对应 4 family × 3 seeds，加上 offer 的 2 个合法重放，共 14 个付费单元。
仍只看 clean 自进化，不与 N1–N4 绑定，也不更改当前资格门槛。按本轮吞吐粗略
估计，最大并发 3 时墙钟约 1.5–3 小时，token 约 15M–25M；正式启动前应先给出
provider-free preflight 的精确单元清单和 image/verifier 就绪状态。

若这一轮仍无法得到至少四个合格 family，再依次筛选其余拥有至少五个官方实例的
family：`anthropic-poster-design`、`chinese-poem-generator`、
`temperature-simulation`、`video-object-counting`、`weighted-gdp-calculation`。
不使用只有 2–3 个实例、无法满足当前 2/1/test 划分的 family。
