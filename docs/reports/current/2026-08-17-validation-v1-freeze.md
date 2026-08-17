# RSEBench validation-v1 冻结报告

> 冻结日期：2026-08-17（UTC）
> 范围：四个领域、四个 baseline profile、N1–N4 四个独立 stage、精确 4×4 共 16 个 noisy cell
> 当前状态：数据、方法身份、并行控制面和插件接口已冻结；具体 stage `CELL_RUNNERS` 尚未实现，未启动新的付费 N1–N4 实验

## 1. 冻结结论

validation-v1 已把此前分散在 clean qualification、Core-1 pilot、baseline patch 和 SkillFlow screening 中的可执行事实收敛为一套统一协议：

1. 四个 benchmark 都有 immutable `DatasetRelease`；
2. 三个 active 方法族对应四个精确 `MethodRelease`，SkillOpt 的 Spreadsheet 与 OfficeQA profile 不再错误合并；
3. SkillLearn self-feedback 保留为 `validated_inactive`，其历史结果不再进入主 4×4；
4. N1/N2 使用静态数据接口，N3/N4 使用统一 evidence 接口，四个 stage 分目录独立维护；
5. [validation-v1 matrix](../../../configs/validation/validation-v1.yaml) 只展开 16 个 noisy cell，clean control 通过不可变 evidence identity 复用；
6. scheduler 允许 16 个 cell 并行，并从固定 upstream revision 为每个 attempt 重放对应 MethodRelease 的补丁；
7. provider-free preflight 已验证 139 个本地 artifact locator、四套 active release patch replay 和 16 个 cell，provider 调用数为 0。

这里的“冻结”表示后续加噪比较的输入身份和执行边界稳定，不表示四个领域都已经证明了跨 seed 稳定正向 clean efficacy。

## 2. 数据 release

| Domain | DatasetRelease | 规模 | content hash | Clean 结论边界 |
|---|---|---:|---|---|
| Spreadsheet | `spreadsheetbench-verified-validation-v1` | 20/10/30 | `25c9d28c45a470add27b093d59c98e849fad5c6b82113110db531485a5e26632` | 选定 clean control 为 `0.3333→0.4333`，但历史独立 seed 仍有 no-update/回退 |
| Document | `officeqa-full-validation-v1` | 12/12/20 | `a87c3f436ad2ac7d4a0618bb1464a5560515944021c79b78192268cc382b63dd` | 选定 clean control 完整更新但 score tie：`0.65→0.65` |
| Interactive | `webshop-validation-v1` | 5/5/20 | `c2678c6482d7cc3f43662ec34fe7fa562ab8a0a2af0ca02ec9a2487c0f11930d` | 选定 clean control 为 `0.1025→0.30`；单次运行成本较高 |
| Skill | `skillflow-tasks-validation-v1` | 3 family × 6 | `028f696980f7f0170da67a8c2969bab6addf14c3c2b6f739b4b47b0b04463c5d` | HWPX 有局部正增益；Distribution、Embedded 为完整执行 tie |

机器可读 manifest：

- [SpreadsheetBench-Verified](../../../benchmark/datasets/spreadsheet/spreadsheetbench_verified/releases/validation-v1/manifest.json)
- [OfficeQA Full](../../../benchmark/datasets/document/officeqa_full/releases/validation-v1/manifest.json)
- [WebShop](../../../benchmark/datasets/interactive/webshop/releases/validation-v1/manifest.json)
- [SkillFlow Tasks](../../../benchmark/datasets/skill/skillflow_tasks/releases/validation-v1/manifest.json)

SkillFlow 的三个有序 group 为：

| Family | 冻结任务 |
|---|---|
| `HWPX-Document-Automation` | `hwpx-supplier-contact-sheet`、`hwpx-event-announcement`、`hwpx-clinic-intake-summary`、`hwpx-project-proposal`、`hwpx-training-feedback`、`hwpx-safety-audit-brief` |
| `Distribution-Center-Auditing` | `harbor_receiving_exception_audit`、`harbor_trailer_detention_audit`、`harbor_promo_register_audit`、`harbor_service_queue_sla_audit`、`harbor_timesheet_policy_audit`、`harbor_returns_disposition_audit` |
| `Embedded-Data-Repair` | `fx-spot-matrix-refresh`、`fx-cross-rate-inverse-fix`、`warehouse-slot-factor-refresh`、`supplier-pack-matrix-refresh`、`catalyst-balance-matrix-sync`、`buffer-dilution-matrix-repair` |

Family 内必须按表中顺序进化，family 间必须重置 skill library。该切片用于机制验证，不是 SkillFlow 原论文全集结果的替代品。

## 3. 方法 release 与 harness 边界

| MethodRelease | Dataset | baseline fingerprint | 状态 |
|---|---|---|---|
| `skillopt-spreadsheet-validation-v1` | Spreadsheet | `b209b2686c902166e31062e6473075f5a87d1058759d81ce66f6864efafcc3a3` | active，4-patch profile |
| `skillopt-officeqa-validation-v1` | OfficeQA | `bbf775793ff2cc1e9f22b2c530a82957ba87d05749a50f6f53657c01549d9033` | active，5-patch profile |
| `skilladaptor-webshop-validation-v1` | WebShop | `ebcfa0ccc76c5589bd95da3e7ae21a4065dd5e060f9abc207954e4cd750ef014` | active |
| `skillflow-validation-v1` | SkillFlow Tasks | `e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875` | active |
| `skilllearn-self-feedback-diagnostic-v1` | SkillLearnBench history | `033cc887ba59a8692a7c416f0a050dff37f086e4d8715b690096189a8df1ebf7` | validated_inactive |

Release 文件位于 [validated methods](../../../methods/validated/)。候选方法位于 [candidate methods](../../../methods/candidates/)，不能满足 validation-v1 的 active method 解析。

Harness 仍归各 baseline 所有。RSEBench 只负责 DatasetRelease 转换、身份、secret 注入、attempt 隔离、token/timing/audit 和聚合，不在外层静默改写 baseline 的 prompt、动作选择、skill update 或 scorer。DeepSeek 兼容属于明确登记的 patch identity。

特别需要保留 SkillOpt 的两个 profile：Spreadsheet clean 发生在 force-final patch 之前，OfficeQA clean 使用包含该 patch 的后续身份。运行时不能让两个 cell 直接共享当前已打满补丁的 checkout；scheduler 会从共同 upstream revision 归档，并分别重放 4 或 5 个 patch。

## 4. N1–N4 stage 所有权

| Stage | 边界 | 形式 | 负责人只需修改的目录 | 必须保护 |
|---|---|---|---|---|
| N1 | task context | static | [n1](../../../src/rsebench/noise/stages/n1/) | objective、gold、artifact、verifier |
| N2 | environment evidence | static | [n2](../../../src/rsebench/noise/stages/n2/) | gold 可达性、原解法、verifier |
| N3 | stored trajectory | runtime | [n3](../../../src/rsebench/noise/stages/n3/) | reward、success、环境状态、final result |
| N4 | update feedback | runtime | [n4](../../../src/rsebench/noise/stages/n4/) | trajectory、scalar reward、official score |

四位协作者不需要修改中央 registry。每位负责人在自己的 `operators/` 包内实现 benchmark-specific operator，并在该包的 `CELL_RUNNERS` 映射中登记 matrix 已冻结的 operator ID。共享合同只允许 N1/N2 返回 `StaticNoiseResult`，N3/N4 返回带 input/output/audit 的 `MutationResult`。

当前四个 operators 包仍为接口骨架，因此 preflight 报告 `ready_cell_count=16`、`execution_ready=false`。前者表示 16 个 cell 的 release/identity/control-plane 完整，后者表示具体噪声逻辑尚未完成。`validation run` 在这种状态下会拒绝启动，即使提供费用确认也不会调用模型。

## 5. 4×4 matrix 与隔离

Matrix 是四个领域 × 四个独立 stage，不是 N1×N2×N3×N4 的组合实验：

| Domain | N1 | N2 | N3 | N4 |
|---|---|---|---|---|
| Spreadsheet | erroneous handover | unlabeled stale sheet | omit workbook edit | replace blamed range |
| Document | one-axis derivation | conflicting-period source | omit oracle source | replace failure axis |
| Interactive | near-match session | promote near match | omit constraint event | replace fault step |
| Skill | unverified prior skill | stale same-family artifact | omit skill-use event | replace patch attribution |

每个 cell identity 包含 matrix hash、DatasetRelease、MethodRelease、baseline fingerprint、clean evidence、stage plugin、operator、provider、runtime、noise seed 和 source mode。任意一项变化都必须产生新 identity；不能覆盖旧结果。

16 个 cell 可以同时进入 running。每个 attempt 独享 output、tmp、cache、workspace、noisy、token ledger、mutation audit、container prefix 和 result identity。单个 cell 的 `failed`、`blocked` 或 `invalid` 不会取消其余 cell，聚合始终保留 16-cell 固定分母。

## 6. 协作者执行顺序

1. 在所属 stage 目录实现四领域 operator 和 provider-free hard-gate 测试；
2. 运行统一 preflight，直到 `execution_ready=true`；
3. 先只运行 N1，并按预注册规则判断是否至少 3/4 领域出现有效噪声机制；
4. 只有 N1 第一阶段完成 3/4 判定后，再决定是否推进 N2–N4；
5. 不按 noisy outcome 换样本、提高 severity、丢弃 zero-update 或重写 clean control；
6. 若修改 dataset、method patch、provider、runtime 或 seed，创建新 release，不复用 validation-v1 clean identity。

统一入口：

```bash
python -m rsebench.cli validation preflight \
  --matrix configs/validation/validation-v1.yaml

python -m rsebench.cli validation run \
  --matrix configs/validation/validation-v1.yaml \
  --max-parallel 16 \
  --confirm-provider-cost

python -m rsebench.cli validation status \
  --matrix configs/validation/validation-v1.yaml

python -m rsebench.cli validation aggregate \
  --matrix configs/validation/validation-v1.yaml
```

旧 clean-v2、Core-1 和分领域 launcher 只作为兼容与历史重放入口。完整的架构约束见 [validation-v1 architecture](../../architecture/validation-v1-architecture.md)，后续任务状态见 [项目路线图](../../project-roadmap.md)。

## 7. 当前未完成项

- 四个 stage 的具体 `CELL_RUNNERS`；
- SkillFlow 四种 operator 的 benchmark-specific hard gates；
- N1 第一阶段 3/4 领域的正式验证结果；
- N2–N4 是否进入验证的后续决策；
- GitHub 多仓库并行运行产生的 result/aggregate 回收。

在这些项目完成前，不应把 validation-v1 描述为“加噪实验已经跑完”或“N1–N4 已经有效”。当前完成的是可复现输入、方法身份和并行控制面的冻结。
