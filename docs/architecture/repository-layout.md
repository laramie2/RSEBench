# RSEBench 仓库布局

> 状态：validation-v1 当前目录约定

## 1. Tracked source of truth

```text
benchmark/datasets/<domain>/<benchmark>/
├── benchmark.yaml
└── releases/validation-v1/manifest.json

benchmark/validation/              historical qualification evidence
benchmark/registry/                benchmark/method/adapter/operator registry
methods/validated/                 active or validated method releases and patches
methods/candidates/                methods excluded from the active matrix
src/rsebench/noise/stages/n1..n4/  stage-owned plugin interfaces and operators
src/rsebench/validation/           shared matrix, scheduler, identity, status, aggregate
configs/validation/validation-v1.yaml
docs/progress/                     human collaboration state
docs/archive/experiment-history/   historical phase index
```

DatasetRelease、MethodRelease、matrix 和 registry 是执行身份。文档、脚本和结果不能静默覆盖它们。

## 2. Local ignored state

```text
data/                     raw and materialized benchmark assets
methods/external/         shared legacy external checkouts during transition
methods/*/*/source/       method-local canonical source checkout
outputs/                  preflight, run, token, timing and archive evidence
.venv/                    project environment
.worktrees/               temporary linked worktrees
```

这些目录不提交到 Git。可移植 manifest 使用 `rsebench-data://`、`rsebench-methods://` 和 `rsebench-project://` locator，运行前再解析到本机路径。

## 3. Benchmark ownership

每个 benchmark 小类拥有 benchmark metadata、loader/verifier identity 和 immutable DatasetRelease。`benchmark/validation/` 保存旧 clean qualification 和 screening 证据，其中部分路径仍被 validation-v1 source-resource locator 引用，因此不能为了目录整齐而移动。

加噪数据与原 benchmark release 分开。N1/N2 materialization 生成新的 noise artifact/release；N3/N4 生成 attempt-local runtime replay pack。

## 4. Method ownership

`methods/validated/` 只放已验证或已冻结方法的 metadata、upstream lock、runtime lock、patch series 和 release。第三方源码位于 ignored source checkout，不能直接 vendoring 到主仓库。

`methods/candidates/` 表示尚未进入当前 matrix 的方法。Candidate 不能被 active resolver 静默选中，也不能直接替换 reference baseline。

同一方法可以有多个 benchmark-specific MethodRelease。SkillOpt Spreadsheet 和 OfficeQA 是两个精确 profile，不能共享一个已经打满补丁的可变 checkout。

## 5. Noise ownership

四位 stage owner 分别拥有：

```text
src/rsebench/noise/stages/n1/operators/
src/rsebench/noise/stages/n2/operators/
src/rsebench/noise/stages/n3/operators/
src/rsebench/noise/stages/n4/operators/
```

成员不通过修改中央 matrix 注册临时 operator。共享 discovery surface 从 stage plugin 发现实现；identity、scheduler、aggregate 和 provider safety 由 `src/rsebench/validation/` 统一负责。

## 6. Execution ownership

每个 matrix cell 在隔离 attempt directory 中：

1. 解析固定 DatasetRelease 和 MethodRelease；
2. 从 pinned upstream revision 创建 source snapshot；
3. 按 release 顺序重放 patch；
4. 物化 clean/noisy input 或 runtime hook；
5. 执行 baseline 原生 harness；
6. 写入 result、audit、token 和 timing；
7. 聚合器只读 attempt 结果。

同一可变 baseline checkout 默认串行；使用隔离 source snapshot 时，不同 benchmark/cell 可以并行。

## 7. Documentation ownership

- `docs/project-onboarding.md`：新人理解项目；
- `docs/project-roadmap.md`：当前阶段、gate 和未来工作；
- `docs/architecture/`：稳定结构和边界；
- `docs/protocols/`：release、noise、token/timing/result 合同；
- `docs/operations/`：可执行 runbook 和协作流程；
- `docs/progress/`：四位成员当前状态；
- `docs/reports/current/`：当前结论；
- `docs/archive/`：过期设计、计划、状态和历史实验。

当前文档使用稳定职责名；归档文档保留 ISO 日期前缀。
