# 验证数据冻结、方法分层与 4×4 模块化实验矩阵设计

> 状态：Current validation-v1 architecture
>
> 日期：2026-08-17 UTC
>
> 相关入口：[matrix](../../configs/validation/validation-v1.yaml)、[current status](../reports/current/current-project-status.md)、[release protocol](../protocols/dataset-and-method-release.md)、[noise-stage protocol](../protocols/noise-stage-interface.md)、[runbook](../operations/validation-runbook.md)

## 1. 目标

本设计停止继续进行 clean 样本筛选，直接使用当前已经完成的执行证据冻结四领域验证数据和能够完成自进化闭环的方法版本。在此基础上，建立统一的数据读取协议、baseline 生命周期、N1–N4 插件接口和可完全并行的 4×4 验证矩阵，为四位协作者分别实现四个噪声阶段提供稳定边界。

本阶段的目标是验证可迁移的噪声机制，而不是精确复现每篇方法论文的原模型结果。模型固定为 `deepseek-v4-flash`；harness 由对应 baseline 自己拥有，可以包含经过版本化、可重放的 DeepSeek 适配，不要求强制替换为同一个全局 agent harness。

本设计必须保持以下事实边界：

1. clean 数据和已生成的 clean evidence 不重新采样；
2. 不因 N1–N4 结果修改 frozen clean release；
3. “能够执行并更新”与“在总体分布上稳定提高能力”分别报告；
4. SkillFlow 的三-family release 是用于机制验证的执行稳定切片，不是原论文 166-task 总体效果的无偏复现；
5. 迁移本身不产生 provider 调用。

## 2. 已确认的架构选择

采用渐进式兼容迁移：建立新的 canonical 目录和协议，新实验只写新结构；旧 manifest 和旧路径在一个过渡版本内保持可读，现有历史 evidence 不移动、不改写、不重新哈希。

第三方 baseline 源码不直接提交到 RSEBench Git 仓库。Git 只跟踪 method metadata、upstream lock、patch series、bootstrap 配置和 RSEBench integration；本地源码 clone 位于各 method 的 `source/`，保持 gitignored，并由统一命令重建。

当前正式矩阵是四个领域乘四个独立噪声阶段，共 16 个 cell，不是 16×16 或 N1–N4 的组合加噪：

```text
spreadsheet × {N1, N2, N3, N4}
document    × {N1, N2, N3, N4}
interactive × {N1, N2, N3, N4}
skill       × {N1, N2, N3, N4}
```

## 3. Canonical 目录结构

### 3.1 Benchmark 定义与本地数据

Git 跟踪 benchmark 定义、release manifest 和 schema：

```text
benchmark/
  datasets/
    spreadsheet/
      spreadsheetbench_verified/
        benchmark.yaml
        releases/validation-v1/manifest.json
    document/
      officeqa_full/
        benchmark.yaml
        releases/validation-v1/manifest.json
    interactive/
      webshop/
        benchmark.yaml
        releases/validation-v1/manifest.json
    skill/
      skillflow_tasks/
        benchmark.yaml
        releases/validation-v1/manifest.json
  noise/
    N1/plugins/
    N2/plugins/
    N3/specs/
    N4/specs/
  schemas/
```

本地大体积数据保持 gitignored，并使用相同的 domain/benchmark 层次：

```text
data/
  benchmarks/
    spreadsheet/spreadsheetbench_verified/{raw,materialized,cache}/
    document/officeqa_full/{raw,materialized,cache}/
    interactive/webshop/{raw,materialized,cache}/
    skill/skillflow_tasks/{raw,materialized,cache}/
  noisy/
    <dataset-release-id>/
      N1/<operator-version>/<task-id>/
      N2/<operator-version>/<task-id>/
```

现有 `data/raw`、`data/materialized` 和 `data/splits` 在过渡版本中由 resolver 读取并给出弃用提示。新代码不得继续向这些旧路径写入。

### 3.2 Method 定义与本地 clone

```text
methods/
  validated/
    skillopt/
      method.yaml
      upstream.lock
      patches/
      integration/
      releases/
        spreadsheet-validation-v1.json
        officeqa-validation-v1.json
      source/                 # gitignored
    skilladaptor/
    skillflow/
    skilllearn_self_feedback/
  candidates/
    trace2skill/
    skillgrad/
    evoskill/
    rethinkskill/
    federatedskill/
    skills_coach/
    coevoskills/
    skillsbench/
    ...
```

`validated` 表示工程闭环已经验证，不等价于该方法具有稳定的总体 clean efficacy。每个 `method.yaml` 还必须声明 `active` 或 `validated_inactive`。当前 active 方法族是 SkillOpt、SkillAdaptor 和 SkillFlow；SkillLearn self-feedback 保留为 `validated_inactive`，不进入当前 4×4。一个方法族可以按 benchmark/runtime profile 冻结多个 MethodRelease，但每个 matrix cell 只能引用一个精确 release ID。

## 4. 统一数据读取协议

### 4.1 DatasetRelease

新增 immutable `DatasetRelease`，至少包含：

```python
class DatasetRelease:
    schema_version: Literal["rsebench.dataset-release.v1"]
    release_id: str
    domain: str
    benchmark: str
    benchmark_version: str
    loader: str
    verifier: str
    tasks: dict[str, TaskManifest]
    partitions: dict[str, tuple[str, ...]]
    groups: dict[str, tuple[str, ...]]
    source_resources: tuple[ResourceIdentity, ...]
    provenance: tuple[EvidenceReference, ...]
    content_hash: str
```

约束如下：

1. `tasks` 是 release 内唯一 task identity 表；
2. `partitions` 支持 `train`、`validation`、`test` 等任意命名分区；
3. `groups` 表示有序序列，主要用于 SkillFlow family；
4. task ID 在同一 release 中唯一；
5. partition 和 group 内不得出现未知或重复 task ID；
6. portable artifact 使用 `rsebench-data://`、`rsebench-methods://` 或 `rsebench-project://`；
7. `release_id` 和 `content_hash` 覆盖 task、顺序、资源身份和 provenance，不覆盖本机绝对路径；
8. loader 只能解析 release，不得隐式改变 task 顺序或动态补样。

统一 reader 暴露：

```python
class BenchmarkDataset(Protocol):
    release: DatasetRelease

    def task(self, task_id: str) -> TaskManifest: ...
    def partition(self, name: str) -> tuple[TaskManifest, ...]: ...
    def group(self, name: str) -> tuple[TaskManifest, ...]: ...
    def group_names(self) -> tuple[str, ...]: ...
```

普通 benchmark 通过 partition 消费数据；SkillFlow 通过 group 消费数据，并保证 family 内顺序学习、family 间重置 skill library。Baseline adapter 只负责把 `DatasetRelease` 转成原方法格式，不能拥有第二份样本选择逻辑。

## 5. 四领域最终冻结数据

### 5.1 SpreadsheetBench-Verified

- Domain：`spreadsheet`
- Baseline：SkillOpt
- 规模：train 20、validation 10、test 30
- 来源：`benchmark/validation/clean_qualification_v2/spreadsheetbench_verified.json`
- 来源文件 SHA-256：`b27721f6c317e6af26acb11311276e42987ca24a4872b89722a245a782ad1838`
- 原 manifest `source_hash`：`4e6d076bbcfa1e2793233361b1782f88a1e955104480117502af88ffa31b1174`

task ID 和顺序直接继承该 manifest，不重新采样。

### 5.2 OfficeQA Full

- Domain：`document`
- Baseline：SkillOpt
- 规模：train 12、validation 12、test 20
- 来源：`benchmark/validation/clean_qualification_v2/officeqa_full.json`
- 来源文件 SHA-256：`8c715c2917c4db111f2bddeb80b6b7937c426276fe72f61e07166981363a85d6`
- 原 manifest `source_hash`：`b942f7f8f947daff9d48dfc3bf8206cfb2010afdd3c0a74af2346e123d69cd16`

task ID 和顺序直接继承该 manifest，不重新采样。

### 5.3 WebShop

- Domain：`interactive`
- Baseline：SkillAdaptor
- 规模：train 5、validation 5、test 20
- 来源：`benchmark/validation/clean_qualification_v2/webshop.json`
- 来源文件 SHA-256：`56f6a68e348c9006882f3b6ba9b77add161f01b863737993a4bc5e474390bbf8`
- 原 manifest `source_hash`：`0a2bd44ca5f26d5f8cd28c6b0d883c02b0fc01565173f21f907f2b5200d95f55`

goal ID 和顺序直接继承该 manifest，不重新校准 retrieval rank 或替换 goal。

### 5.4 SkillFlow Tasks

- Domain：`skill`
- Baseline：SkillFlow
- 规模：3 个 family，每个 6 个有序任务，共 18 题
- Family 内串行；family 间重置 skill library
- Runtime：沿用已验证的 `deepseek-v4-flash` method-owned Harbor adapter

`HWPX-Document-Automation`：

1. `hwpx-supplier-contact-sheet`
2. `hwpx-event-announcement`
3. `hwpx-clinic-intake-summary`
4. `hwpx-project-proposal`
5. `hwpx-training-feedback`
6. `hwpx-safety-audit-brief`

来源为 `benchmark/validation/skillflow_clean_qualification_v1/noise_validation_selection.json`。

`Distribution-Center-Auditing`：

1. `harbor_receiving_exception_audit`
2. `harbor_trailer_detention_audit`
3. `harbor_promo_register_audit`
4. `harbor_service_queue_sla_audit`
5. `harbor_timesheet_policy_audit`
6. `harbor_returns_disposition_audit`

`Embedded-Data-Repair`：

1. `fx-spot-matrix-refresh`
2. `fx-cross-rate-inverse-fix`
3. `warehouse-slot-factor-refresh`
4. `supplier-pack-matrix-refresh`
5. `catalyst-balance-matrix-sync`
6. `buffer-dilution-matrix-repair`

后两个 family 来源为 `benchmark/validation/skillflow_clean_qualification_v1/second_family_candidates_batch2.json`，来源文件 SHA-256 为 `205fea257c57537e8f7ea54f3fcc97530106d6a0b43202a717f17504c2476016`。

选择理由是三个 family 均完整完成 base/evolution，无 task exception，base 具有非全 0/全 1 的区分度，evolution 产生非空 patch 且后续任务读取 skill。其 clean 信号分别为 HWPX 局部正增益、Distribution tie、Embedded tie；release 用于噪声机制验证，不宣称三个 family 都具有稳定正向 clean efficacy。

## 6. MethodRelease 与 baseline 生命周期

### 6.1 MethodRelease

每个 validated baseline 生成 immutable `MethodRelease`：

```python
class MethodRelease:
    schema_version: Literal["rsebench.method-release.v1"]
    release_id: str
    method: str
    status: Literal["active", "validated_inactive"]
    upstream_repository: str
    upstream_revision: str
    patch_series: tuple[PatchIdentity, ...]
    harness: HarnessIdentity
    provider: ProviderIdentity
    environment_lock: str
    supported_datasets: tuple[str, ...]
    clean_evidence: tuple[EvidenceReference, ...]
    smoke_command: tuple[str, ...]
    content_hash: str
```

Validated gate：

1. upstream revision 固定；
2. patch series 可从 clean checkout 重放；
3. source worktree 除已登记 patch 外没有未记录修改；
4. harness entrypoint 能运行；
5. 能完成 task execution、skill update 和 clean evaluation；
6. 能输出 evolved artifact、trajectory、token、时间和 typed error；
7. semantic smoke 通过；
8. 不依赖 secret 文件或本机绝对路径。

### 6.2 Harness 边界

Harness 归 baseline 所有，不建立一个强制接管所有 baseline 行为的全局 harness。DeepSeek 适配允许存在，但必须包含在 patch fingerprint 和 MethodRelease 中。

RSEBench 外层只负责：

- DatasetRelease 转换；
- experiment identity；
- provider secret 注入；
- attempt 隔离；
- token/timing/audit；
- 结果聚合。

RSEBench 外层不得隐式修改 baseline prompt、动作选择、skill update 或 scorer。已经存在的行为性兼容 patch不会在本次冻结中被悄悄移除，而是作为当前验证版本的一部分被显式列入 MethodRelease；未来替换 harness 或 patch 必须产生新的 release ID 和新的 clean control。

### 6.3 当前方法状态

当前是三个 active 方法族、四个 active MethodRelease。SkillOpt 必须按 benchmark profile 分成两个 release，因为已冻结 clean evidence 的 baseline fingerprint 不同；不得为了目录整齐把两个身份合并。

| Method release | Status | Dataset | Clean baseline fingerprint |
|---|---|---|---|
| SkillOpt / spreadsheet-validation-v1 | active | SpreadsheetBench-Verified | `b209b2686c902166e31062e6473075f5a87d1058759d81ce66f6864efafcc3a3` |
| SkillOpt / officeqa-validation-v1 | active | OfficeQA Full | `bbf775793ff2cc1e9f22b2c530a82957ba87d05749a50f6f53657c01549d9033` |
| SkillAdaptor / webshop-validation-v1 | active | WebShop | `ebcfa0ccc76c5589bd95da3e7ae21a4065dd5e060f9abc207954e4cd750ef014` |
| SkillFlow / skillflow-validation-v1 | active | SkillFlow Tasks | `e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875` |
| SkillLearn self-feedback | validated_inactive | 历史 SkillLearnBench | 由历史 release 保留 |
| 其余 registry 方法 | candidate | 不得进入 validation-v1 | 不适用 |

## 7. N1–N4 插件接口

### 7.1 共享合同

共享 `src/rsebench/noise/contracts.py` 只定义稳定数据类型，不包含具体 benchmark 逻辑。四位协作者分别拥有：

```text
src/rsebench/noise/stages/n1/
src/rsebench/noise/stages/n2/
src/rsebench/noise/stages/n3/
src/rsebench/noise/stages/n4/
```

每个 stage 通过自身目录中的 `plugin.yaml` 注册 operator。Discovery 按 stage 目录确定性扫描，避免四位协作者共同修改一个中央 Python registry。

### 7.2 N1/N2 静态算子

```python
class StaticNoiseOperator(Protocol):
    stage: Literal["N1", "N2"]

    def materialize(
        self,
        task: TaskManifest,
        spec: StaticNoiseSpec,
        output_dir: Path,
    ) -> StaticNoiseResult: ...
```

`StaticNoiseResult` 保存 clean/noisy hash、operator identity、version、seed、applicability、protected-field audit、portable noisy URI 和可逆变更说明。算子只能写 `data/noisy/` 或 attempt-local workspace，不能原地修改 clean artifact。

### 7.3 N3/N4 runtime 算子

```python
class MethodEvidenceAdapter(Protocol):
    def normalize_trajectory(self, native, context) -> TrajectoryRecord: ...
    def denormalize_trajectory(self, record, native): ...
    def normalize_feedback(self, native, context) -> FeedbackRecord: ...
    def denormalize_feedback(self, record, native): ...

class RuntimeNoiseOperator(Protocol):
    stage: Literal["N3", "N4"]

    def mutate(
        self,
        record: TrajectoryRecord | FeedbackRecord,
        spec: RuntimeNoiseSpec,
        context: NoiseContext,
    ) -> MutationResult: ...
```

职责边界：

1. N3/N4 operator 只理解统一 evidence；
2. method adapter 只负责 native evidence 的无损 normalize/denormalize；
3. operator 不直接 import SkillOpt、SkillAdaptor 或 SkillFlow；
4. clean identity mode 必须结构相等，能字节保持时要求字节相等；
5. N3 不能改 reward/success；
6. N4 不能改 reward 或 trajectory；
7. 无适用目标返回 `applicable=false`，不得换算子或算作 noisy success；
8. 每次 mutation 写入输入/输出 hash、目标事件、before/after fragment 和 protected-field audit。

## 8. 4×4 validation matrix

### 8.1 Matrix manifest

```yaml
schema_version: rsebench.validation-matrix.v1
release_id: validation-v1
datasets:
  spreadsheet: <dataset-release-id>
  document: <dataset-release-id>
  interactive: <dataset-release-id>
  skill: <dataset-release-id>
methods:
  spreadsheet: <skillopt-release-id>
  document: <skillopt-release-id>
  interactive: <skilladaptor-release-id>
  skill: <skillflow-release-id>
stages: [N1, N2, N3, N4]
execution:
  cell_parallelism: 16
  seed_parallelism: 1
```

Preflight 必须确认展开结果恰好包含 16 个唯一 cell，且每个 cell 的 dataset、method、operator、clean evidence、runtime 和 seed 均进入 experiment identity。

### 8.2 并行与隔离

16 个 cell 可以同时进入 running。Seed-level 并行独立配置，不属于 16-cell 完全并行的必要条件。

每个 cell/attempt 具有独立：

- output、tmp 和 cache；
- noisy artifact 或 runtime spec；
- token/timing ledger；
- container prefix；
- mutation audit 和 replay pack；
- result identity 与 resume 状态。

Baseline source 在运行中只读。若上游 baseline 会写源码目录，scheduler 使用 copy-on-run workspace。Docker image 在正式运行前预构建。同一 baseline 不再自动成为互斥资源；只有 preflight 证明无法隔离的具体 mutable resource 才允许声明 resource lock。

一个 cell 失败、blocked 或 invalid 不会取消其他 cell。所有终态保留在固定分母中。

### 8.3 Clean 对照复用

validation-v1 引用当前 frozen clean evidence，不为 N1、N2、N3、N4 重复生成四份 clean。16 个 cell 只运行 noisy arm，并分别比较同领域 frozen clean control。

任何 dataset release、MethodRelease、provider、runtime、seed 或 clean evidence identity 变化，都会使旧 clean reuse 失败；此时必须创建新 release，而不是静默重跑或覆盖。

### 8.4 Result 状态

每个 cell 至少报告：

- clean score；
- noisy score；
- clean-minus-noisy；
- clean/noisy artifact 或 update difference；
- applicability；
- execution validity；
- token/timing；
- mutation audit completeness；
- `passed`、`null`、`opposite`、`blocked` 或 `invalid`。

## 9. 统一 CLI

协作者只使用：

```bash
rsebench validation preflight --matrix configs/validation/validation-v1.yaml
rsebench validation run --matrix configs/validation/validation-v1.yaml --max-parallel 16
rsebench validation status --matrix configs/validation/validation-v1.yaml
rsebench validation aggregate --matrix configs/validation/validation-v1.yaml
```

旧 `core1`、`clean-v2` 和分领域 launcher 保留为兼容实现，但不再是首选入口。Provider-backed `run` 必须显式确认成本；`preflight`、`status` 和 provider-free plugin validation 不得调用模型。

## 10. Fail-closed 与错误隔离

以下情况只阻塞对应 cell：

- dataset 或 method release hash 不匹配；
- baseline checkout 或 patch fingerprint 不匹配；
- N1/N2 修改 clean artifact；
- N3/N4 修改 protected reward 或不能无损还原；
- operator 不适用；
- token、timing 或 mutation audit 缺失；
- result identity 与 matrix cell 不一致；
- attempt 写入共享 source 或越过 output root。

Preflight 错误不得产生 provider 调用。运行时错误写入 attempt-local status，并保留其他 cell 的执行资格。

## 11. 迁移顺序

1. 新增 DatasetRelease、MethodRelease、noise plugin 和 validation matrix schema；
2. 从现有 manifest 生成四个 `validation-v1` DatasetRelease；
3. 生成 validated/candidate method metadata，并把现有 patch series 迁移或建立兼容引用；
4. 建立旧路径 resolver 和一致性测试；
5. 稳定 N1/N2 static 和 N3/N4 runtime 接口；
6. 将已有 stage 实现注册为插件；
7. 将现有 scheduler 扩展为 16-cell 完全并行和 copy-on-run；
8. 新增统一 validation CLI；
9. 生成 freeze report 和协作者入口文档；
10. 通过 provider-free preflight 后，才允许开始 N1–N4 付费验证。

迁移不删除旧 manifest、历史报告或 output。新 release 通过 hash 和 provenance 引用它们。

## 12. 测试要求

实施采用 TDD，并至少覆盖：

1. 新旧路径加载得到相同 task ID、顺序和 source hash；
2. 四个 DatasetRelease 内容固定；
3. SkillFlow 恰好 3 family × 6 task；
4. active baseline 恰好为 SkillOpt、SkillAdaptor、SkillFlow；
5. candidate 和 `validated_inactive` 方法不能进入 validation-v1；
6. method bootstrap 能从 lock + patch 重建 fingerprint；
7. N1/N2 clean artifact 不变；
8. N3/N4 identity-hook parity；
9. 四个 stage 的 plugin discovery 互不依赖中央编辑；
10. matrix 恰好展开 16 个唯一 cell；
11. 模拟调度中 16 个 cell 可以同时进入 running；
12. 同一 SkillOpt source 被八个 cell 并发读取时没有共享写入；
13. resume 不重复 completed cell；
14. aggregate 保留 failed/null/opposite/blocked/invalid；
15. manifest 不包含 secret、本机绝对路径、raw data 或第三方 clone；
16. provider-free preflight 的 provider call count 为 0。

## 13. 非目标

本次迁移不做：

- 重新筛选 clean 数据；
- 重跑十个 SkillFlow family；
- 精确复现 SkillFlow 论文的模型–harness组合；
- 实现新的通用 self-evolution harness；
- 确定 N1–N4 的最终领域具体扰动；
- 运行正式 noisy experiment；
- 删除历史目录或 output；
- vendoring 第三方 baseline 源码。

## 14. 完成标准

设计实施完成需要同时满足：

1. 四个 DatasetRelease、三个 active 方法族和四个 active MethodRelease 已冻结；
2. 新 reader 是正式唯一入口，旧 reader 只承担兼容；
3. 四个 noise stage 能由四位协作者独立实现和测试；
4. 4×4 manifest 恰好展开 16 个隔离 cell；
5. provider-free preflight 能验证全部 release、operator、method 和 clean reuse；
6. 16-cell simulated concurrency、resume 和错误隔离测试通过；
7. freeze report 明确记录数据、方法、harness、clean evidence 和限制；
8. 仓库没有新增 secret、绝对路径、大规模 raw/output 或第三方 source；
9. 只有在上述条件通过后，validation-v1 才标记为 ready-for-noise-screen。
