# Task 5 跨 baseline clean 资格判定加固

日期：2026-08-15

## 结果

Task 5 的生产入口已收敛为基于 selection root 与 run root 的文件系统证据流。聚合器不再接受合成 `--input`，replay runner 不再接受可执行 `--spec`。所有 Task 8 provider-backed replay 命令均显式要求 `--execute --confirm-provider-cost`。

Candidate-1 历史 clean artifact 的复用不再只检查三次历史运行是否彼此一致。reuse audit 会从当前 fallback matrix、当前 provider config、当前 baseline patch fingerprint、当前冻结候选任务以及当前 seed artifact 生成期望身份，并按 seed 输出逐字段 mismatch。旧 manifest 文件名和旧 RSEBench repository commit 不进入规范化 evolution-input hash；任务内容、runtime、provider/model/config、baseline、method seed 与 artifact 文件 hash 仍必须一致。历史 fixed replay 不被静默采用，当前统一标记为 `replay_required`，由 canonical per-seed replay 重新生成。

## Owned trace 派生

N3/N4 与领域审计只从 baseline 已持久化的真实输出即时派生，预先存在的 `trace_applicability.json` 或 `domain_audit.json` 不作为信任源：

- Spreadsheet / SkillOpt：严格读取 3 个 rollout batch、每题 conversation、minibatch patches 与 native summary；N3 要求 workbook load/save edit trace，N4 要求 sheet/range attribution 和 patch 分母一致，并调用 `audit_spreadsheet` 的 7/7/6 门槛。
- OfficeQA / SkillOpt：严格读取 3 个 rollout batch、每题 local grep/read conversation、patches 与 native summary；按 4/4/4、parseability 和 headroom 调用 `audit_officeqa`。
- WebShop / SkillAdaptor：按冻结 acquisition task exact set 检查 retrieval/prompt-injection event 和 reasoning-fault alternative step，并按 30 个 reachable task、2/5 validation headroom 与 15-step budget 调用 `audit_webshop`。
- SkillLearn：按 family 的两个 acquisition task exact set 检查 visible trajectory、visible feedback、container image record 与官方 verifier result，再加一个 validation execution，调用 `audit_skilllearn` 的固定 3 次执行门槛。

每份派生证据都记录相对文件路径、SHA-256 和整体 evidence hash。缺文件或不可读证据属于 retryable；已完整执行但 N3/N4、领域门槛或 clean replay 决策失败属于 deterministic nonqualification，并按 C1→C2→C3→blocked 前进。

## 只读真实数据探针

对 `outputs/runs/clean-v2-20260814` 的 seed `20260813` 做了不写回 run root 的读取：

- Spreadsheet：N3 `20/20`，N4 `20/20`，领域审计通过；共绑定 36 个 owned evidence 文件。
- OfficeQA：N3 `12/12`，N4 `12/12`；领域审计确定性失败于 `train_batch_not_mixed:1`，因此不能被解释为缺证据重试。
- WebShop：五个 acquisition task 的 N3/N4 均为 `5/5`；用 candidate builder 生成的 Candidate-1 完整 metadata 复核后，30 个 target denominator、2/5 validation headroom 和 15-step budget 全部通过，领域审计为 pass。
- SkillLearn `offer-letter-generator`：N3 `2/2`，N4 `2/2`，两个 acquisition 加一个 validation 的 container/verifier 审计通过。

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
{"N3":"pass","N3_coverage":1.0,"N4":"pass","N4_coverage":1.0,"domain_passed":true,"domain_reasons":[],"target_denominator":30}
```

OfficeQA 输出为 `N3=pass, N4=pass, domain_passed=false, domain_reasons=[train_batch_not_mixed:1]`。这是完整证据上的 deterministic nonqualification：Candidate 1 时动作前进到 Candidate 2；若 Candidate 2 出现同类 N3/N4 或领域失败，动作前进到 Candidate 3；只有缺失/不可读 owned trace 才重试当前 candidate。

另用当前 fallback matrix、当前 baseline checkout/patch series、当前 provider config 与 candidate builder 生成的 Candidate-1 对六个历史 run 做了逐 seed 身份 probe。结果为 OfficeQA `20260813/14/15` 与 WebShop `20260813/14/15` 六行 `failures=[]`；这说明它们在新的 task-content-aware normalized hash 下仍可复用。任何单字段变化会在 `reuse_audit_sources.json.current_identity_audits[].failure_reasons` 中以 `reuse_identity_mismatch:<field>` 落盘并触发 fallback rerun。
