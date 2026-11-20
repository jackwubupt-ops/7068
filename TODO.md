# PatchLoop TODO

> 更新于 2026-11-20。按顺序推进：**前一阶段的"完成标准"没达到，就不要开始下一阶段。**
> 服务器：**阿里云（香港地域，A10 24GB，有 Docker）**，按 [docs/aliyun-runbook.md](docs/aliyun-runbook.md) 操作；阶段细节见 [docs/full-test-runbook.md](docs/full-test-runbook.md)，项目背景见 [README](README.md)。

**当前位置：** 阶段 1–2 的代码已全部合入 main；本地官方评测（`experiments.official_eval`）和配对统计（`experiments.paired_compare`）也已写好（只做过离线测试，122 个通过、1 个跳过）。下一步是在阿里云上做第一次真实运行。

---

## P0 · 拿到第一批真实数据（最紧急）

- [ ] **租阿里云实例**：香港地域，gn7i（A10 24GB），数据盘 300GB 挂到 `/data`，安全组只放行 22（aliyun-runbook 阶段 A、0）
- [ ] **服务器准备**：Docker + 三个独立 venv + 7B 权重；启动 7B，preflight 通过（aliyun-runbook 阶段 1，主流程阶段 2–4）
  - 完成标准：`live_qwen_api_ok`；记下 vLLM 启动日志里 `enable_prefix_caching` 的值
- [ ] **评测器 gold 自检**（aliyun-runbook 阶段 1.7）
  - 完成标准：2 道题 gold 补丁都是 resolved、0 个 error，证明本地 Docker 评测链路可用
- [ ] **镜像仓库，跑单题**（runbook 阶段 5）
  - 完成标准：P-C-R 和单 agent 在 `sqlfluff__sqlfluff-1625` 上都能正常结束
- [ ] **Lite smoke：6 题 × 3 个配置**（runbook 阶段 6）
  - [ ] A：`--agent pcr --edit-format diff`
  - [ ] B：`--agent pcr --edit-format search_replace`
  - [ ] C：`--agent single --edit-format search_replace`
  - 完成标准：三个配置都是 `tasks_finished = 6`，`--workers` 保持一致
  - 需要记录：每题耗时、状态分布、失败集中在哪个阶段
- [ ] **本地官方评测 smoke 的三个配置**（aliyun-runbook 阶段 8，`experiments.official_eval`）
  - 完成标准：三个目录都有 `official_eval.json` 且 `complete: true`，得到第一批真实解决率
  - 备选方案：本地评测不通时用 sb-cli（主流程阶段 8）
- [ ] **备份结果**：打包所有 smoke 目录和日志，下载到本地

## P1 · Lite dev pilot（RQ3 第一批数据）

- [ ] **决定编辑格式**：如果 B 的 `prediction_ready` ≥ A，后续都用 `search_replace`
- [ ] **跑 pilot：23 题 × 2 个配置**（runbook 阶段 7）
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

- [ ] **P3-1 测试环境**：阿里云上有 Docker，直接复用 SWE-bench 预构建的实例镜像（仓库已在 base commit 装好依赖），不再自己建 conda 环境
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
- [ ] 在 4090 上做 4-bit QLoRA 训练（先用小样本验证显存够不够、要多久）
- [ ] 用 vLLM 的 `--enable-lora` 部署，和基座模型配对评测
- 缩小范围的退路：只训练 Coder、只评测一个子集，在论文里写明

## 工程和维护

- [ ] CI：现在的 workflow 只在几个旧的功能分支上触发，要改成在 push 到 main 和 PR 时跑离线测试
- [ ] Web demo 首页（`templates/index.html`）改成 PatchLoop 的介绍（可选）
- [ ] 每完成一个阶段，更新 `CHANGELOG.md`、README 里的状态表和本文件
- [ ] 每次真实运行后，把结果打包备份到本地

## 规则（始终有效）

- 驱动用实例镜像自带的版本，不要手动升级；vLLM、客户端、评测器分别用三个独立的 venv
- gold patch、test_patch、FAIL_TO_PASS 和 hints 不进任何 prompt；开发阶段只读 dev split
- `prediction_ready` ≠ 已解决；是否解决只看官方评测
- 离线测试和 CI 只证明代码接线正确，不代表模型能力
- vLLM 只监听 127.0.0.1，安全组不放行 8000；`.env` 不提交
- 不用时停机或释放实例，释放前先下载结果
- 改代码要开分支、走 PR，并附测试结果
