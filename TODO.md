# PatchLoop TODO

> 更新于 2026-11-20。按顺序推进：**前一阶段的"完成标准"没达到，就不要开始下一阶段。**
> **一台机器：阿里云香港 GPU 云服务器（A10 24GB，有 Docker，直连 GitHub/HF）**，推理和官方评测都在上面做，按 [docs/aliyun-gpu-runbook.md](docs/aliyun-gpu-runbook.md) 操作。原来的 AutoDL + 阿里云 CPU 双机方案已停用（AutoDL 访问 GitHub 太慢、不能跑 Docker），旧文档仅作参考。项目背景见 [README](README.md)。

**当前位置：** 代码全部合入 main（含 `official_eval`、`paired_compare`）。AutoDL 上做过单题验证：P-C-R 能跑通（`patch_failed`）；发现两个问题，已写进新 runbook：
- 单 agent 原地打转（`no_submission`），怀疑是 `QWEN_CONTEXT_CHARS=18500` 太小，读文件的结果被裁掉了 → 新 runbook 改为 48000，并把 vLLM 上下文调到 32768（待阶段 9 证实）；
- pyvista 的浅克隆镜像导致 checkout 超时 → 镜像必须是完整克隆。

下一步：在阿里云香港 GPU 机上从头搭建，跑到第一批官方解决率。

---

## ★ 最终实验（2026-11-21 起，截止 11-25 23:59）：DeepSeek Flash

方向调整：最终对比实验全部用 `deepseek-flash`；7B 的 pilot v1–v3 只作为"7B 撑不起这个系统"的证据（[docs/qwen7b-limits.md](docs/qwen7b-limits.md)）。RQ1 从 QLoRA 改为推理强度对比。下面的 P2–P5 不再推进。

- [ ] **和老师确认 RQ1 的变更**（QLoRA → 推理强度），按课程流程登记
- [x] **跑最终实验**（2026-11-21，新的 16 核 / 32 GiB 实例，`RQ1_EFFORTS="low high max"`）：5 个 DeepSeek 批次都 `tasks_finished = 23`，gold 自检 23/23；结果见 README 第 5 节 "Final results"；之后又各重复了 2 次（`final-ds-r2`、`final-ds-r3`），README 里是 3 次的汇总（`experiments.repeat_report`）
  - 旧服务器上的 7B pilot 批次没有迁移过来；模型对比用第一轮（旧服务器上在修复后的镜像上重评测）的 7B 结果 0/23
- [ ] 把 README 的 "Final results" 两张表放进报告；写明 23 题的统计局限、每个配置跑了 3 次且波动较大（high：6/8/10）、思考模式的随机性、第一次额度过小那一轮作废的原因
- [ ] 打包下载 `/data/runs` 和 `/data/analysis`，然后停机（按量计费）

---

## P0 · 拿到第一批真实数据（最紧急）

所有步骤见 [docs/aliyun-gpu-runbook.md](docs/aliyun-gpu-runbook.md)，括号里是阶段号。

- [ ] **购买实例并搭建环境**（阶段 A–6）：香港，gn7i（A10）16 vCPU，数据盘 300GB 挂到 `/data`，安全组只放行 22
  - 完成标准：`live_qwen_api_ok`；vLLM 日志里 `max_seq_len=32768`；记下 `enable_prefix_caching` 的值
- [ ] **仓库镜像**（阶段 7）
  - 完成标准：dev 23/23 题的 base commit 都在本地镜像里
- [ ] **评测器 gold 自检**（阶段 8）
  - 完成标准：2 道题 gold 补丁都是 resolved、0 个 error，证明本地 Docker 评测链路可用
- [ ] **单题验证**（阶段 9）：`one-pcr`、`one-single`、`one-pyvista`
  - 完成标准：都不是 `experiment_error`；单 agent 的 `dropped_history_messages` 基本为 0，不再原地打转
- [ ] **Lite smoke：6 题 × 3 个配置**（阶段 10.1）
  - [ ] A：`--agent pcr --edit-format diff`
  - [ ] B：`--agent pcr --edit-format search_replace`
  - [ ] C：`--agent single --edit-format search_replace`
  - 完成标准：三个配置都是 `tasks_finished = 6`，`--workers` 保持一致
  - 需要记录：每题耗时、状态分布、失败集中在哪个阶段
- [ ] **官方评测 smoke 的三个配置**（阶段 10.2，`experiments.official_eval`）
  - 完成标准：三个目录都有 `official_eval.json` 且 `complete: true`，得到第一批真实解决率
- [ ] **备份结果**（阶段 12）：打包所有运行目录和日志，下载到本地

## P1 · Lite dev pilot（RQ3 第一批数据）

- [ ] **决定编辑格式**：如果 B 的 `prediction_ready` ≥ A，后续都用 `search_replace`
- [ ] **跑 pilot：23 题 × 2 个配置**（aliyun-gpu-runbook 阶段 11）
  - [ ] `--agent pcr`
  - [ ] `--agent single`
  - 完成标准：两个配置都是 `tasks_finished = 23`
- [ ] **两个配置都用 `official_eval` 评测**，再用 `paired_compare` 出逐题配对表、McNemar p 值和 bootstrap CI
- [ ] **检查点**：如果两个配置的解决率都接近 0，先停下来分析失败分布，不要扩大规模
  - 定位失败多（`no_candidate_files`）→ 做 P2-1 的 BM25 检索
  - 补丁打不上多（`patch_failed`）→ 继续改进编辑格式和提示词
  - 能应用但没修好（假修复）→ 优先做 P3 的复现脚本

## P2 · 提升 7B 的补丁质量（根据 P1 的失败分布挑着做）

- [ ] **P2-1 定位前置检索**：Planner 开始前，用 BM25 按 issue 文本给文件排序，把排名靠前的候选交给 Planner
  - 完成标准：有离线测试；在 dev 上和不加检索的版本对比 `localized_any_file`
- [ ] **P2-2 辅助指标脚本**：运行结束后用 gold 改动的文件计算文件级定位命中率
  - gold 只用于评分，**绝不能进 prompt**；脚本和推理代码完全分开
- [ ] **P2-3 失败分析脚本**：从 `results.jsonl` 和 `run_status.json` 汇总各阶段的失败原因

## P3 · 执行反馈（RQ2）

- [ ] **P3-1 测试环境**：执行反馈需要在生成过程中跑测试。阿里云香港 GPU 机本身有 Docker，测试直接在本机容器里跑，不需要远程调用。容器直接用 SWE-bench 预构建的实例镜像（仓库已在 base commit 装好依赖）
  - 只在容器里跑仓库原有的测试和模型写的复现脚本；**不能运行镜像里的官方 eval 脚本**（它会打上 test_patch）
  - 完成标准：每个 dev 仓库在 base commit 上能在容器里跑通它自带的测试
- [ ] **P3-2 测试执行模块**：在指定环境里对补丁跑指定测试，有超时和隔离，返回结构化结果
- [ ] **P3-3 复现脚本**：让模型根据 issue 写一个复现脚本——修复前应该失败，修复后应该通过
- [ ] **P3-4 Reviewer 接入测试结果**，给 Coder 反馈
- [ ] **P3-5 最多 3 个候选**，按测试结果挑出最好的一个
- [ ] **P3-6 在 dev 上对比**："1 个候选、无反馈"和"执行反馈 + 最多 3 个候选"，都用 `official_eval` 评测，`paired_compare` 比较
- 泄漏红线：反馈只能来自仓库原有的测试和模型自己写的复现脚本，**`test_patch` 和 FAIL_TO_PASS 测试一律不能用**
- 论文里要写明：反馈只用仓库原有测试 + 复现脚本，最终打分用官方 harness

## P4 · Lite test 集正式实验

- [ ] 估算磁盘：Lite test 300 个评测镜像需要的空间（先用 `docker system df` 查看 dev 的实际占用，再按比例推算）
- [ ] 镜像 test 集用到的仓库
- [ ] 在 300 题上跑通过筛选的配置；同一组对比里，`--workers` 和编辑格式保持一致
- [ ] `official_eval` 评测（或 sb-cli），得到逐题的解决结果
- [ ] 统计：`paired_compare`（McNemar + bootstrap 置信区间）；结论措辞用"效应有多大"，而不只是"是否显著"
- [ ] 先估算时间：用 pilot 的平均每题耗时 × 300 × 配置数

## P5 · QLoRA（RQ1，时间不够可以缩小范围）

- [ ] 核实 SWE-smith 公开了哪些数据，以及许可证
- [ ] 构造训练样本：issue + 相关文件 → 补丁，先只训练 Coder
- [ ] 防泄漏过滤：排除 Lite test 涉及的仓库，按 issue 文本相似度去掉近似重复，过滤记录要留存
- [ ] 在阿里云 A10（或 AutoDL 4090，训练不需要 Docker）上做 4-bit QLoRA 训练（独立 venv，不需要 Docker；训练前停掉 vLLM；先用 200 条样本试训，测显存和速度）
- [ ] 训练和推理用同一份基座权重，把 safetensors 哈希和 adapter 哈希写进 manifest；adapter 训完立刻下载备份
- [ ] 用 vLLM 的 `--enable-lora` 部署，和基座模型配对评测
- 缩小范围的退路：只训练 Coder、只评测一个子集，在论文里写明

## 工程和维护

- [ ] CI：现在的 workflow 只在几个旧的功能分支上触发，要改成在 push 到 main 和 PR 时跑离线测试
- [ ] Web demo 首页（`templates/index.html`）改成 PatchLoop 的介绍（可选）
- [ ] 每完成一个阶段，更新 `CHANGELOG.md`、README 里的状态表和本文件
- [ ] 每次真实运行后，把结果打包备份到本地

## 规则（始终有效）

- 不升级 NVIDIA 驱动；vLLM、客户端、训练、评测器各用独立的 venv
- gold patch、test_patch、FAIL_TO_PASS 和 hints 不进任何 prompt；开发阶段只读 dev split
- `prediction_ready` ≠ 已解决；是否解决只看官方评测
- 离线测试和 CI 只证明代码接线正确，不代表模型能力
- vLLM 只监听 127.0.0.1，安全组不放行 8000；`.env` 不提交
- 不用时停机或释放实例，释放前先下载结果
- 改代码要开分支、走 PR，并附测试结果
