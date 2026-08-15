# Task 5 跨 baseline clean 资格判定加固

日期：2026-08-15

## 结果

Task 5 的生产入口已收敛为基于 selection root 与 run root 的文件系统证据流。聚合器不再接受合成 `--input`，replay runner 不再接受可执行 `--spec`。所有 Task 8 provider-backed replay 命令均显式要求 `--execute --confirm-provider-cost`。

Candidate-1 历史 clean artifact 的复用不再只检查三次历史运行是否彼此一致。`reuse_audit_sources.json` 现在只保存带内容 hash 的历史 source root 与相对 run-dir 索引，不保存或反序列化 `CleanRunEvidence`。qualification、screening 与 replay discovery 都从声明的不可变历史目录重新调用 `read_clean_run`，重算 owned audit、artifact hash、完整 portable task identity 与当前期望身份；目录缺失、越界、索引被修改或当前身份不匹配都会失败关闭。旧 manifest 文件名和旧 RSEBench repository commit 不进入规范化 evolution-input hash；完整 TaskManifest 内容、runtime、provider/model/config、baseline、method seed 与 artifact 文件 hash 仍必须一致。

默认 discovery 和 C1/C2/C3 新运行继续逐字段比较完整 TaskManifest。仅 `reuse-audit`/rehydration 的 OfficeQA、WebShop historical Candidate-1 使用版本化投影 `clean-v2-derived-annotations-v1`：OfficeQA 只允许当前 builder 新增的 `officeqa_stratum`、`static_applicability`；WebShop 只允许 `constraint_count`、`normalized_query`、`option_count`、`retrieval_rank`、`static_applicability`、`target_reachable`，以及仅 validation task 可有的 `seed_success`。这些 key 必须在 historical task 中完全缺失，任何额外 historical metadata 都失败；prompt、gold、source hash、verifier、artifact、Office source identity 和 WebShop goal identity均不投影。被投影值会从当前 static audit 以及 pinned goal/product/validation-score 资源独立重算。

这里的 hash 用于发现工作流内的意外修改，不是数字签名，也不提供 source root 的密码学来源真实性；能防止错误复用的边界来自“当前冻结 Candidate-1 身份必须存在并完全相等”、重新读取原始 run，以及 run/seed/clean/runtime/replay 路径的 resolve 后目录包含性检查。

## Owned trace 派生

N3/N4 与领域审计只从 baseline 已持久化的真实输出即时派生，预先存在的 `trace_applicability.json` 或 `domain_audit.json` 不作为信任源：

- Spreadsheet / SkillOpt：严格解析 3 个 rollout batch、每题 conversation、minibatch patches 与 native summary；使用 `read_clean_run` 已与 runtime identity/result 核对的 `method_seed` 重建 native `Random(method_seed + 1000)` 的 7/7/6 批次，并要求 `summary.config.seed` 是完全相等的严格整数；将真实 conversation/feedback 归一化后调用已注册的 `spreadsheet_n3_omit_workbook_edit` 与 `spreadsheet_n4_replace_blamed_range`，每题 `MutationAudit.applicable` 都为真才通过。
- OfficeQA / SkillOpt：严格解析 rollout row 与 conversation，按相同的已验证 seed 调度重建 4/4/4 精确批次，使用 row 自带的 source identity 丰富 `oracle_resource_open` selector，再调用已注册的 N3/N4 算子；同样按 parseability 和 headroom 调用 `audit_officeqa`。native worker 并发完成会改变同一批 JSONL 的行顺序，所以顺序不作为身份，跨批重分配、重复、缺失或复制其他 seed 的 trace 仍会失败。
- WebShop / SkillAdaptor：RSEBench wrapper 在外部 baseline 已有 hook 上持久化 provider 产生的原生 dataclass 与归一化 `TrajectoryRecord`/`FeedbackRecord`；outer wrapper、normalized trajectory/feedback、可用时的 native `task_id` 以及 benchmark 必须一致。资格判定只消费这组 ordered evidence 并调用已注册算子。历史 retrieval/fault 摘要不足以重建 exact selector，因此不再作为替代证据。30-task reachability 与 2/5 headroom 从 pinned goal/product/calibration 资源重算。
- SkillLearn：严格解析 family 的两个 acquisition task 的 visible `TrajectoryRecord`/`FeedbackRecord` 并调用已注册 N3/N4 算子，再以严格字符串 image schema 和 CTRF verifier schema（非空 tool/tests、合法 status、精确 summary 计数）核对 container、官方 verifier 与 validation execution。畸形 JSON 统一形成 typed `unreadable_owned_skilllearn_trace`，不再因宽松类型转换而误通过。

每份派生证据都记录 run-relative 或 `rsebench-project://` portable locator、SHA-256 和整体 evidence hash。缺文件或不可读证据属于 retryable；已完整执行但 N3/N4、领域门槛或 clean replay 决策失败属于 deterministic nonqualification，并按 C1→C2→C3→blocked 前进。Candidate 3 缺失/不可读时动作仍是 `run_candidate_3`；只有 Candidate 3 的完整确定性失败才 blocked。

## 只读真实数据探针

对 `outputs/runs/clean-v2-20260814` 的 seed `20260813` 做了不写回 run root 的读取：

- Spreadsheet：N3 `20/20`，N4 仅 `4/20`；其余 16 题的真实 feedback/trajectory 中没有同形非 blame decoy，exact N4 selector 正确返回 inapplicable。领域结构审计通过，但该历史候选不能通过 N4 适用性门槛。
- OfficeQA：N3 `12/12`，N4 `12/12`；领域审计确定性失败于 `train_batch_not_mixed:1`，因此不能被解释为缺证据重试。
- WebShop：历史五个 acquisition task 的 N3/N4 均为 `0/5` 且状态为 `missing`，因为旧 run 没有 wrapper-owned ordered trajectory/feedback；retrieval audit 与单条 fault log 不再被当成 exact selector 的代理。独立从 pinned resources 重算的 30-task denominator、2/5 validation headroom 和 15-step budget 仍通过。reuse audit 因此要求重跑 Candidate 1，并且 replay planner 不会为该 artifact 生成付费任务。
- SkillLearn `offer-letter-generator`：N3 `2/2`，N4 `2/2`，两个 acquisition 加一个 validation 的 container/verifier 审计通过。

SkillOpt 额外检查了真实 step JSONL 与冻结 train 顺序：Spreadsheet 三批为 `7/7/6`，OfficeQA 三批为 `4/4/4`；二者都与 `Random(20260813 + 1000)` 的分批成员集合完全一致且全局无重复。仅同一批内的 JSONL 行完成顺序不同，因此生产校验采用精确 per-batch set + uniqueness。

本次加固没有调用 provider，也没有运行 N1–N4 noisy evolution。

探针通过 `PYTHONPATH=src python - <<'PY' ... derive_owned_run_audits(...) ... PY` 调用生产派生函数；输入 run 分别由以下只读 glob 精确定位：

```text
outputs/runs/clean-v2-20260814/attempts/spreadsheet-skillopt-20260813-*/**/qualification.json
outputs/runs/clean-v2-20260814/attempts/officeqa-skillopt-20260813-*/**/qualification.json
outputs/runs/clean-v2-20260814/attempts/webshop-skilladaptor-20260813-*/**/qualification.json
outputs/runs/clean-v2-20260814/attempts/skilllearn-offer-letter-20260813-*/**/qualification.json
```

WebShop 的完整领域 probe 先调用 `scripts/build_noise_screen_candidates.py::_webshop_bundle(...)` 从 pinned local resources 构造 Candidate-1，再将其与同一 clean-v2 run 传给 `derive_owned_run_audits`；输出为：

```json
{"N3":"missing","N3_coverage":0.0,"N4":"missing","N4_coverage":0.0,"domain_passed":true,"domain_reasons":[],"target_denominator":30}
```

OfficeQA 输出为 `N3=pass, N4=pass, domain_passed=false, domain_reasons=[train_batch_not_mixed:1]`。这是完整证据上的 deterministic nonqualification：Candidate 1 时动作前进到 Candidate 2；若 Candidate 2 出现同类 N3/N4 或领域失败，动作前进到 Candidate 3；只有缺失/不可读 owned trace 才重试当前 candidate。

当前身份比较使用完整、portable 的 TaskManifest payload；metadata、source identity、goal constraint 或 artifact locator/content hash 改变都会 mismatch，而同一 declared root 下 portable URI 与 resolved local path 相等。身份审计详情写入独立的 `reuse_audit_report.json`；消费侧不信任该报告，只信任重新读取历史 run 后的重算结果。

最终真实 `reuse-audit` 只读探针索引并重新 hydrate 了 OfficeQA/WebShop 的全部 6 个 seed；六者当前 expected identity 均匹配。OfficeQA seed `20260814` 仍忠实保留独立的 `qualification_runtime_gates_failed` 运行失败，其他五个 run 的 `failure_reasons=[]`。因此“身份兼容”没有被错误表述为“六个运行均通过资格门”。
