# 为什么最终实验换成 DeepSeek Flash：Qwen2.5-Coder-7B 的局限性证据

proposal 里的模型是本地的 Qwen2.5-Coder-7B-Instruct。最终的对比实验（RQ1 推理强度、RQ3 P-C-R 对比单 agent）改用 DeepSeek API 的 `deepseek-flash`。本文整理换模型的依据，以及在报告里怎么用这些数据。

> 下表的数字都来自 README 第 5 节记录的 pilot 结果（SWE-bench Lite dev，23 题，search_replace 编辑格式，官方 harness 评测）。原始数据在服务器的 `/data/runs`（pilot v1/v2/v3）和 `/data/analysis/`（诊断报告）里，**不在仓库里**，报告定稿前要先打包下载（runbook 阶段 12）。

## 1. 证据：7B 的解决率在三轮改进后一直是 0

| 版本 | 改了什么 | P-C-R 能应用的补丁 | 单 agent 能应用的补丁 | 官方解决（P-C-R / 单 agent） |
|---|---|---|---|---|
| pilot v1 | 修完 harness 之后的基线（#18–#20） | 3 | 2 | 0 / 0 |
| pilot v2 | Planner 放弃规则 + 容忍空白差异的匹配（#21） | 7 | 7 | 0 / 0 |
| pilot v3 | + 检索 top-10（#23，recall@10 = 0.83） | 14 | 11 | 0 / 0 |

- **工程改进有效，但只改善了"能不能打上补丁"**：能应用的补丁从 3 个涨到 14 个，官方解决数一直是 0。
- **定位已经不是瓶颈**：v3 里 gold 文件被读到的比例是 83%（P-C-R）/ 74%（单 agent），v2 时是 44% / 56%。剩下的失败大多是"在正确位置附近改错了"，也就是模型本身写不出正确的修复。
- **结论**：瓶颈在模型的代码推理能力，而不在 agent 框架。在 7B 上继续调整框架，RQ1 和 RQ3 都只会得到 0 对 0 的对比，没有统计意义。

## 2. 推理强度为什么能接替 QLoRA 成为 RQ1

proposal 的 RQ1 想回答"**多投入算力能不能提高修复能力**"，手段是 QLoRA 微调（训练阶段的算力）。改成推理强度后，问题保持不变，手段换成推理阶段的算力：

| | proposal（原） | 现在 |
|---|---|---|
| 问题 | 多投入算力能否提高解决率 | 同左 |
| 自变量 | 是否做 QLoRA 微调 | DeepSeek 推理强度：none / low / high / max |
| 控制变量 | 同一个 agent、同样的预算 | 同一个模型、同一个 agent（P-C-R）、同样的回答输出上限和调用预算 |
| 成本这一轴 | 训练 GPU 时间 | 每题的思考 token 数（`reasoning_tokens`，按输出 token 计费） |

在 7B 上做 QLoRA 不可行的原因：基线是 0，就算微调后有提升，23 题上也很难看到；而且 4 天内来不及准备训练数据、训练和重新评测。

**这是对 proposal 目标的重大变更，按评分要求要走课程的变更流程。提交前先和老师确认。**

## 3. 报告里怎么用这些数据

1. **7B 一节**放 pilot v1–v3 的表，以及诊断数据（gold 文件读取率、失败类型分布）；
2. **跨模型对比**：`scripts/run_final_deepseek.sh` 会在修复后的同一批评测镜像上重新评测 7B 的 v3 批次（旧结果保留为 `official_eval.pre-repair.json`），然后在 `final-comparison.md` 里给出 DeepSeek 对比 7B 的配对检验（P-C-R 和单 agent 各一组）。两边的设置必须一致（search_replace、检索 top-10、同样的预算）；如果 v3 的 manifest 和最终批次有不同的设置，会出现在 "Comparability warnings" 里，报告里要照实说明；
3. **最终结论**只用 DeepSeek 的批次：RQ3 是 `ds-pcr` 对比 `ds-single`，RQ1 是 `ds-pcr-low` / `ds-pcr-high` / `ds-pcr-max` 对比 `ds-pcr`。结果见 README 第 5 节 "Final results"：推理强度提高没有带来更高的解决率（none 10、low 11、high 6、max 9）；最终那一轮是在新服务器上跑的，7B 的数字来自第一轮在修复后的镜像上的重评测（两组都是 0/23）；
4. **局限性**：只有 23 题，p 值和置信区间只能作参考；思考模式下 DeepSeek 不使用 temperature，low/high/max 每个配置只跑了一次，结果带有随机性；DeepSeek 后端会把 issue 和代码发送到外部服务。
