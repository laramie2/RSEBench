# Task 6：可移植 selection release 实现记录

Task 6 的正式冻结入口只接受 `selection_root`、`run_root` 和
`release_root`。CLI 与脚本均不提供合成输入入口；冻结前会从 owned clean
run 与 replay 文件重新派生 qualification 和 screening 结果，并分别写入
`release_qualification.json` 与 `screening_release.json`。

冻结屏障重新计算 candidate/confirmation 的 `source_hash`、`selection_hash`
和预注册样本数，校验四个 SkillLearn screening family、四个 confirmation
family、confirmation 历史执行隔离，以及非 SkillLearn screening 的
`score_observed` 暴露限制。发布写入拒绝凭据字段、嵌入式绝对路径、URL
userinfo、worktree 路径、目标 symlink 和父目录 symlink。

资源锁由以下 provider-free 命令生成：

```bash
PYTHONPATH=src python scripts/build_noise_screen_resource_lock.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --data-root "${RSEBENCH_DATA_ROOT:-data}" \
  --methods-root "${RSEBENCH_METHODS_ROOT:-methods/external}" \
  --methods-registry benchmark/registry/methods.yaml \
  --image-manifest outputs/preflight/noise-screen-v1/skilllearn_image_manifest.json \
  --output benchmark/validation/noise_screen_v1/resource_lock.json
```

该锁覆盖所有聚合 candidate/confirmation 中的 data/method URI、三套 baseline
的固定 Git revision 与本地 patched worktree hash，以及八个固定 SkillLearn
family 的预构建 OCI digest 和 task-to-context 映射。生成和冻结时都拒绝
descendant symlink；冻结时会再次对本地 materialization 和预构建 image
manifest 做精确核验。

SkillLearn image 预构建直接读取正式聚合 selection schema：

```bash
PYTHONPATH=src python scripts/prebuild_clean_skilllearn_images.py \
  --selection-root benchmark/validation/noise_screen_v1 \
  --output outputs/preflight/noise-screen-v1/skilllearn_image_manifest.json
```

该路径同时遍历四个 screening family 与四个 confirmation family 的全部任务，
不再把聚合 `StableSplitCandidate` 误当作 `CleanEvolutionSplitManifest` 解析。
以上流程均报告 `provider_calls=0`。
