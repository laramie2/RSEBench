# 稳定加噪验证样本 clean 资格实验：阻塞报告

## 结论

本轮没有生成可发布的四领域样本 release。SpreadsheetBench-Verified 在三个预注册候选上都未通过 N3/N4 clean-trace 适用性门，最终状态为
`clean_blocked_after_three_candidates`。按照预注册规则，不生成 Candidate 4、不动态替换样本、不放宽门槛；四领域同时达到
`clean_generalization_ready` 的 release 条件因此已经不可达。

这不是 N1–N4 的效果结论：**N1–N4 均未运行**。本轮只执行 clean 自进化及其 owned-trace 资格审计；screening test、confirmation test、resource lock 和 release freeze 均未执行。

## 固定协议与候选

- Baseline/model：Spreadsheet 与 OfficeQA 使用 SkillOpt，WebShop 使用 SkillAdaptor，SkillLearn 使用 self-feedback；provider/model 固定为 DeepSeek / `deepseek-v4-flash`，温度为 0，thinking disabled。
- Method seeds：`20260813`、`20260814`、`20260815`。
- 候选上限：每个非 SkillLearn 领域最多 C1、C2、C3；禁止 C4、动态换题和事后放宽资格门。
- Spreadsheet 每个候选为 `20/10/30/30`（train/validation/qualification-test/screening-test）；OfficeQA 为 `12/12/20/20`；WebShop 为 `5/5/20/20`。
- SkillLearn screening 固定四个 family：`organize-messy-files`、`offer-letter-generator`、`schedule-planning`、`dependency-vulnerability-check`，每个 family 为 2 train、1 validation、2–3 screening-test。
- confirmation 仍保持 sealed、未执行：Spreadsheet `20/10/30`，OfficeQA `12/12/20`，WebShop `5/5/20`，SkillLearn 四个未曝光 family 合计 `8/4/10`。seal 的 exposure-registry hash 为 `adb8c69904e820b5ebedab9d4957223b8a97aa38fd6fd52101fb689fbc69ff15`。

候选的精确、按序 task IDs 已冻结在 `benchmark/validation/noise_screen_v1/candidates/`；由于没有候选被选中，本报告不存在可以冒充为最终 release 的“selected IDs”。候选 identity 如下：

| 领域 | 候选 | selection hash |
|---|---:|---|
| Spreadsheet | C1 | `fe6a7d4e4e4725d9f2695506eef8e47b337f1ab5559959bf0c5ebafe1906fe80` |
| Spreadsheet | C2 | `aaf4e60e998d2741975429f962a25a6845883eb749b354dac5dc71b46213bdae` |
| Spreadsheet | C3 | `dd40035ef7092a6789919284cfc6fb30c736b421dedc0ef2da6aea45364d9b0b` |
| OfficeQA | C1 | `cb742606d52ebe42a2dab6a4265366008e3cef63eaaec957de905752a529a17f` |
| OfficeQA | C2 | `96e88eefe9052fd88a0694d7341c913f134326d1d2ffbdb339c85a674fed3ce2` |
| OfficeQA | C3 | `5f7cf052f51fb5b1ac62b9b0733a44b54f6250558adfa151b720eee88549089a` |
| WebShop | C1 | `769686e8feea9f24b37e08c1eeb942790d3b450a1104771023175c1e5a311c90` |
| WebShop | C2 | `6e9d980810b878c8703a7197ab5013bd65cb90fab6b69fbe939f75207ed12d66` |
| WebShop | C3 | `e1debc90dc17d2e515cad2c390c460ec79ed0dabbcacc20b7fbb7f7c687b1bc6` |
| SkillLearn | C1（四 family） | `69fb49a8529ead368e7cbba6e284bf135e632ea725f1fdbd25f344d4b20f73ce` |

confirmation manifest hashes 分别为 Spreadsheet `239e803b6691b4b454d5a345ca054e65d6e5622a7d9efc4da50d9e037e083c16`、OfficeQA `d45f19f539b68cff54317fa154e5adcfe27d1241e3b76c9af0724f0f78d3bce5`、WebShop `fb700b3cd6738ed53bc3b0e80433b4c60daade457a28aad60dae3c55789c01e4`、SkillLearn `2475f1e732ea13fcb32aedaac3ff160ced8eb8f404fc43f4b8f37efcf90b8ca8`。

## Provider-free preflight 与历史复用

SkillLearn image preflight 为 `all_ready=true`：覆盖 screening/confirmation 共 8 个 family、44 个 task identity 和 21 个预构建镜像，无失败，`provider_calls=0`。

历史 C1 复用审计重新校验了内容 hash、baseline fingerprint、provider 配置、method seed、artifact 和完整 evolution-input identity。初始 typed action 为：

| 领域 | 初始动作 | 原因 |
|---|---|---|
| Spreadsheet | `run_candidate_2` | 历史 C1 seed13 单次 probe 确定性失败；该 probe 的 N3 为 `20/20`、N4 仅 `4/20`，不能写成候选级三 seed 结果 |
| OfficeQA | `rerun_candidate_1` | 旧运行的 batch-mix/runtime/applicability 证据不足 |
| WebShop | `rerun_candidate_1` | 旧运行没有 wrapper-owned ordered N3/N4 trace |
| SkillLearn | `run_candidate_2` | 执行四个固定 screening family 的资格矩阵 |

## 运行结果

### Spreadsheet / SkillOpt

C2 和 C3 的六个 clean 单元都正常结束；baseline 能执行自进化，但更新与收益不稳定。

| 候选 | seed | accepted updates | seed score | clean score | gain | launcher qualification |
|---|---:|---:|---:|---:|---:|---|
| C2 | 20260813 | 0 | 0.3000 | 0.3000 | 0.0000 | fail：无更新 |
| C2 | 20260814 | 1 | 0.3667 | 0.3667 | 0.0000 | pass |
| C2 | 20260815 | 1 | 0.4000 | 0.3667 | -0.0333 | fail：退化 |
| C3 | 20260813 | 0 | 0.3667 | 0.3667 | 0.0000 | fail：无更新 |
| C3 | 20260814 | 2 | 0.4667 | 0.4000 | -0.0667 | fail：退化 |
| C3 | 20260815 | 0 | 0.3333 | 0.3333 | 0.0000 | fail：无更新 |

更关键的是，owned clean trajectory 无法满足“每个 acquisition task 对 N3/N4 都可合法变异”的预注册适用性门：C2 三个 seed 的 N3 分别为 `18/20`、`16/20`、`18/20`，N4 分别为 `3/20`、`3/20`、`4/20`；C3 三个 seed 的 N3 分别为 `18/20`、`17/20`、`19/20`，N4 分别为 `3/20`、`4/20`、`4/20`。领域结构审计通过，但 C1–C3 均确定性不合格，最终动作是 `clean_blocked_after_three_candidates`，原因为 `incomplete_noise_applicability:N3` 和 `incomplete_noise_applicability:N4`。

这里存在一个必须在下一版协议中正面处理、但本轮不能事后改门的结构性冲突。六个 C2/C3 run 中，N4 applicable IDs 都只是 failed rows 的子集，与 success rows 的交集始终为空；所有 success rows 的原生 `fail_reason` 和 `source_files` 均为空，因此规范化后的 `blamed_resource_refs=[]`，无法执行“把被归因范围重定向到同形 decoy”的 N4。与此同时，领域门要求每个 train batch 同时包含 success/failure，而当前 noise-applicability 门又要求全部 acquisition rows 达到 100%。只要 batch 保持 mixed，success rows 就会使 blame-redirect N4 低于 100%。本轮忠实保留这两个预注册门并返回 blocked，没有越界调整算子或门槛。

### OfficeQA / SkillOpt

C1 三个 clean 单元均正常结束并产生更新，说明当前 baseline/接口能够完成 OfficeQA 自进化执行：

| seed | accepted updates | seed score | clean score | gain | launcher qualification |
|---:|---:|---:|---:|---:|---|
| 20260813 | 1 | 0.60 | 0.60 | 0.00 | pass |
| 20260814 | 2 | 0.50 | 0.55 | +0.05 | pass |
| 20260815 | 1 | 0.60 | 0.65 | +0.05 | pass |

但 owned evidence 的资格审计仍确定性失败：seed13/14 的 N3、N4 均为 `11/12`，seed15 为 `12/12`；三个 seed 还分别出现两个非混合 train batch（seed13 为 batch 1、3；seed14/15 为 batch 1、2）。因此当前动作仍为 `run_candidate_2`，不能冻结 C1。本轮在 Spreadsheet 已达到全局终止条件后没有启动 OfficeQA C2。

### WebShop / SkillAdaptor

历史 C1 因缺少 wrapper-owned ordered trajectory/feedback 而不能复用。本轮 C1 seed13 执行了 1,657.9 秒后，随全局终止被优雅中断；它已生成 seed evaluation 和部分 evolution 证据，但没有顶层 result/qualification，因此不是有效 clean 结果。seed14/15 在 launcher 启动前中断。当前 typed action 仍为 `rerun_candidate_1`，没有启动 C2/C3。

### SkillLearn / self-feedback

四 family、三 method seed 共 12 个单元中，11 个正常完成且 launcher qualification 均通过。所有已完成单元 clean gain 都为 0；baseline 能接受并写出更新，但尚未观察到能力提升。

| family | 完成 seed | accepted updates | clean gain |
|---|---|---|---|
| `dependency-vulnerability-check` | 3/3 | `2,2,2` | 全部 0 |
| `offer-letter-generator` | 3/3 | `1,2,2` | 全部 0 |
| `schedule-planning` | 3/3 | `2,2,2` | 全部 0 |
| `organize-messy-files` | 2/3 | seed13/15 均为 2 | 均为 0 |

`organize-messy-files/20260814` attempt 1 在 277.1 秒后因 DeepSeek `run_shell` tool arguments 被截断为非法 JSON 而失败，属于 provider 输出/解析基础设施失败，不是 clean 资格结果。保持同一 unit/experiment identity 的 attempt 2 运行 368.5 秒后随全局终止中断。这是 12 个 SkillLearn 单元中唯一真实缺失/中断的 unit。

首次聚合还暴露了一个 provider-free 聚合器 bug：冻结候选会把 family allocation 从 JSON list 深冻结为 `_ImmutableSequence`，而 `_match_candidate` 只接受 `list`，导致上述 11 个 completed run 全部被静默跳过。修复后的匹配接受非字符串 `Sequence[str]`，但仍严格核对 task ID、顺序和完整 TaskManifest；字符串、乱序或错误 ID 继续拒绝。使用同一份 outputs 重新聚合后，共发现 20 个 completed run（Spreadsheet 6、OfficeQA 3、SkillLearn 11），没有新增 provider 调用。

重新聚合后的 SkillLearn 状态仍为 `clean_blocked_skilllearn_families`，但 reasons 已校正为真实证据：`organize-messy-files:missing_exact_three_method_seeds`，以及 `schedule-planning:incomplete_noise_applicability:N3/N4`。后者的三个 completed seed 均为 N3 `1/2`、N4 `1/2`；其他 completed family/seed 的 N3/N4 均为 `2/2`。因此只有 organize seed14 是运行缺失，schedule 是完整运行后的确定性适用性失败，两者不能混为一谈。

## 中断与恢复状态

终止请求时间为 `2026-08-15T15:58:41Z`。两个 scheduler 及其子进程收到 SIGTERM 后在 5 秒内退出，无需 SIGKILL；未删除任何 attempt、runner output、cache、timing 或 token ledger。

| unit | 最后 attempt | 状态 | 结束时间 |
|---|---|---|---|
| WebShop seed13 | `87fe07ea-f501-4826-97e8-c903c2f8eacb` | execution interrupted (`returncode=-15`) | `2026-08-15T15:58:42.106848Z` |
| WebShop seed14 | `692d4f44-0a34-4ece-bb7e-06a41264cfcf` | interrupted before launcher | `2026-08-15T15:58:42.108403Z` |
| WebShop seed15 | `58a6daf4-beb4-4d67-90ad-b77da4932690` | interrupted before launcher | `2026-08-15T15:58:42.107775Z` |
| SkillLearn organize seed14 | `83c41382-300d-4c7a-9c8e-69606665b211` | attempt 2 execution interrupted (`returncode=-15`) | `2026-08-15T15:58:42.116507Z` |

这些 unit 的 immutable experiment identity 和既有 attempts 均保留；若未来明确决定继续调查，可由 scheduler 在相同 unit identity 下追加新 attempt，而不会覆盖或伪装已有结果。但继续它们不能解除 Spreadsheet 的预注册 terminal block，也不能产生本轮四领域 release。

## 调用、token 与时间记录

账本覆盖 `2026-08-15T15:16:06.779650Z` 至 `2026-08-15T15:58:42.018603Z`。共记录 3,906 次 provider 调用，usage 观测 3,906/3,906（100%）；其中 3,886 次 billed，20 次 cache hit。单次调用状态均为 success；这不改变上层 WebShop/SkillLearn launcher 被中断的状态。

| benchmark | calls | prompt tokens | completion tokens | total tokens |
|---|---:|---:|---:|---:|
| Spreadsheet | 767 | 1,465,975 | 474,392 | 1,940,367 |
| OfficeQA | 1,426 | 16,437,247 | 702,865 | 17,140,112 |
| WebShop（partial） | 888 | 748,423 | 117,201 | 865,624 |
| SkillLearn | 825 | 8,565,899 | 394,355 | 8,960,254 |
| **总计** | **3,906** | **27,217,544** | **1,688,813** | **28,906,357** |

完整结束的 20 个顶层 run 都包含 run/stage/task 三级时间记录：

| benchmark | completed runs | run duration 合计 | 单 run 范围 | task records |
|---|---:|---:|---:|---:|
| Spreadsheet | 6 | 3,616.1 s | 510.9–683.0 s | 540 |
| OfficeQA | 3 | 2,750.4 s | 897.5–952.0 s | 192 |
| SkillLearn | 11 | 4,995.5 s | 297.7–683.5 s | 55 |

WebShop partial 和 SkillLearn retry 的 scheduler durations 分别为 1,657.9 秒和 368.5 秒；其部分 timing events 同样保留在各自 attempt 中，但不计入 completed-run 表。

## 最终 typed 状态与后续决策

| 领域 | 最终状态 | 本轮是否选择样本 |
|---|---|---|
| Spreadsheet | `clean_blocked_after_three_candidates` | 否；C1–C3 全部确定性失败 |
| OfficeQA | `run_candidate_2` | 否；按全局终止停止 |
| WebShop | `rerun_candidate_1` | 否；C1 未完成 |
| SkillLearn | `clean_blocked_skilllearn_families` | 否；organize seed14 缺失，schedule 三 seed 的 N3/N4 均为 `1/2` |

因此：

1. 不生成 `screening_generalization.json`、`resource_lock.json`、`base_splits/` 或 `releases/validation/noise-screen-v1/`；
2. 不声明 release ID，也不把任一候选称为最终稳定样本；
3. 不启动 screening、confirmation 或 N1–N4；
4. 原始 provider 输出继续只保存在 gitignored `outputs/runs/noise-screen-v1-qualification/`，不纳入 Git；
5. 若要重开该研究问题，应先修改并重新预注册“Spreadsheet N3/N4 必须 100% 适用”的样本设计/算子约束，形成新版本 selection policy，而不是在本轮事后增加 C4 或替换任务。

## 验证

- tuple/frozen-sequence 回归测试遵循 RED→GREEN：修复前目标用例失败，修复后 focused qualification suite 为 `59 passed`；
- `PYTHONPATH=src python -m pytest -q`：`753 passed`；
- `ruff check src/rsebench/selection/qualification_io.py tests/selection/test_qualification.py`：通过；
- `git diff --check`：通过；
- candidate/confirmation 目录的绝对路径、worktree 和 credential marker 扫描：通过；
- `ruff check src scripts tests`：未通过，但只报告仓库既有的 8 项，与本轮 Markdown 变更无关：`scripts/run_paired_skilllearn.py` 的 7 项 E402，以及 `tests/adapters/test_evoskill.py` 的 1 项 F401。本轮没有扩大范围修改这些文件。
