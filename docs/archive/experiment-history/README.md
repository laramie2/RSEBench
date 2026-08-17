# RSEBench 历史实验时间线

历史实验按项目目标变化分为七个阶段。报告被移动到对应阶段；manifest、config 和 raw output 在被 release/replay locator 引用时保持原路径，通过 [registry](registry.yaml) 建立逻辑归档。

| Phase | Date | Goal | Principal conclusion | Current relevance |
|---|---|---|---|---|
| [00](00-foundation-and-audits/README.md) | 2026-08-11–12 | 下载、物化、benchmark/baseline 审计 | 建立数据和方法交集，验证离线生成链路 | 环境与来源审计 |
| [01](01-api-pilot-and-initial-noise/README.md) | 2026-08-12–13 | DeepSeek 适配、paired evolution、Core-1 | 初步证明部分噪声能改变更新，但跨域混合 | 早期机制证据 |
| [02](02-expanded-n1/README.md) | 2026-08-13 | 扩大样本 N1 | 单样本问题缓解，N1 尚未四域稳定 | N1 历史候选 |
| [03](03-clean-qualification-and-repairs/README.md) | 2026-08-13–15 | Clean-v1/v2 与 baseline 修复 | 四组执行闭环跑通，clean efficacy 仍混合 | validation-v1 clean 来源 |
| [04](04-stable-split-and-skilllearn-screening/README.md) | 2026-08-15–16 | 稳定样本和 SkillLearn diagnostic | 更新链路可运行，但 family-level gain 不稳定 | SkillLearn diagnostic |
| [05](05-skillflow-screening/README.md) | 2026-08-16 | SkillFlow family 筛选 | 冻结三 family 机制验证切片，只有 HWPX 局部正信号 | 当前 skill 域来源 |
| [06](06-validation-v1-freeze/README.md) | 2026-08-17 | 统一 release、插件和 4×4 控制面 | 身份/结构冻结，具体 runners 待实现 | 当前正式边界 |

## Preservation classes

- `frozen-evidence`：当前 release 或 clean reuse 直接引用，原路径不可移动；
- `historical-evidence`：结论或审计所需，保留并通过 registry 查找；
- `rebuildable-intermediate`：可重建且被完整结果替代，只有单独批准后才能删除。

目录存在不代表实验成功。以 registry 的 `status`、canonical report 和 terminal result 为准。
