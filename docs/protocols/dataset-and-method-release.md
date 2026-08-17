# DatasetRelease 与 MethodRelease 协议

## 1. Identity principle

Release 是不可变、可重放的实验输入身份，不是指向“最新文件”的便捷别名。任何影响任务、方法源码、patch、runtime 或评测的变化都必须创建新 release ID，而不是原地覆盖 validation-v1。

## 2. DatasetRelease

DatasetRelease 至少固定：

- release ID、domain、benchmark 和 benchmark version；
- loader、verifier 和 schema version；
- task identity、prompt/gold identity、artifact locator 和 content hash；
- train/validation/test 或 ordered family grouping；
- source resource locator、license/status 和已知限制；
- release content hash。

当前 release：

| Release | Embedded content hash |
|---|---|
| `spreadsheetbench-verified-validation-v1` | `25c9d28c45a470add27b093d59c98e849fad5c6b82113110db531485a5e26632` |
| `officeqa-full-validation-v1` | `a87c3f436ad2ac7d4a0618bb1464a5560515944021c79b78192268cc382b63dd` |
| `webshop-validation-v1` | `c2678c6482d7cc3f43662ec34fe7fa562ab8a0a2af0ca02ec9a2487c0f11930d` |
| `skillflow-tasks-validation-v1` | `028f696980f7f0170da67a8c2969bab6addf14c3c2b6f739b4b47b0b04463c5d` |

Locator 字符串和被引用 artifact byte 分别受路径协议和内容 hash 保护。移动 `rsebench-project://` source resource 会改变可重放边界；若必须移动，应发布新 release 或保留旧路径兼容资产。

## 3. MethodRelease

MethodRelease 至少固定：

- release ID、method family、status 和适用 DatasetRelease；
- upstream repository、revision 和 source bootstrap；
- ordered patch series 及每个 patch hash；
- environment/runtime lock、provider/model compatibility；
- harness ownership、entry point 和 result/evidence contract；
- clean efficacy evidence reference、baseline fingerprint 和 release content hash。

当前 active profiles：

| Release | Baseline fingerprint | Content hash |
|---|---|---|
| `skillopt-spreadsheet-validation-v1` | `b209b2686c902166e31062e6473075f5a87d1058759d81ce66f6864efafcc3a3` | `4e33580c96e2dac23f7d2f360c0312c1d2672522b834415fb856d4076a408e12` |
| `skillopt-officeqa-validation-v1` | `bbf775793ff2cc1e9f22b2c530a82957ba87d05749a50f6f53657c01549d9033` | `261c2dc38206efc173227ce8285240f3179b42ee2d977b60b559cd3d2365f4d1` |
| `skilladaptor-webshop-validation-v1` | `ebcfa0ccc76c5589bd95da3e7ae21a4065dd5e060f9abc207954e4cd750ef014` | `f8d55b9943a0a91f6cb084395839ac13aabe6165f289aadc79535eba8c04eaca` |
| `skillflow-validation-v1` | `e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875` | `e97deb7babd9016831d73a0ca2ca6a984996dab0c82687e173d13a887dcbfff8` |

`skilllearn-self-feedback-diagnostic-v1` 状态为 `validated_inactive`，只用于历史诊断。

## 4. Patch replay

Patch 从共同 upstream revision 按 `series.yaml` 顺序重放。验证器在应用前后检查 expected hash、patch order、reverse applicability 和最终 fingerprint。

实验不能直接依赖开发者当前 `methods/external/` checkout 的偶然状态。每个 attempt 从固定 upstream source snapshot 开始，应用一个精确 MethodRelease。不同 profile 不共享已修改 checkout。

DeepSeek compatibility patch 可以修复 provider/tool JSON/runtime API 兼容，但必须登记为 release identity。未披露的 prompt、action policy、skill update、acceptance gate 或 scorer 修改不允许进入结果。

## 5. Release reuse

Clean evidence 只有在以下全部相同时可复用：

```text
DatasetRelease
MethodRelease and patch series
provider/model/temperature/thinking
runtime and budget
task IDs and order
method seed and seed skill
evaluation identity
```

任何字段变化都会使 reuse 失效。Zero-update、score tie、execution failure 和 clean regression 不能被删除或重标为噪声结果。

## 6. Validation

Provider-free preflight 必须验证 release schema、content hash、portable locator、source resource、patch replay、matrix binding 和 secret absence。只有 release 验证通过后，runner 才能进入 executable gate。
