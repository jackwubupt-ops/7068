# 阿里云香港 GPU 单机流程（推理 + 官方评测，一台机器全包）

> **这是现在的主流程。** 它取代了"AutoDL 推理 + 阿里云 CPU 机评测"的双机方案。
> 旧文档 [full-test-runbook.md](full-test-runbook.md)（AutoDL）和 [aliyun-runbook.md](aliyun-runbook.md)（CPU 评测机）先保留作参考。

## 为什么换成一台机器

AutoDL 用下来有两个绕不过去的问题：

1. **访问 GitHub 很慢**：学术加速只有约 50 KB/s，pyvista 的镜像来回下了好几次；
2. **不能跑 Docker**：官方评测和 RQ2 的执行反馈都只能放到另一台机器上，结果要经本机来回 scp。

阿里云香港的 GPU 云服务器是完整虚拟机，**直连 GitHub、Hugging Face 和 Docker Hub，也能跑 Docker**。所以这一台机器就能完成全部工作：

- vLLM 推理（smoke、pilot、Lite test）；
- 官方 SWE-bench 评测；
- 以后 RQ2 的测试执行。

推理只用 GPU，评测只用 CPU 和 Docker，两件事在同一台机器上也能同时进行。

> **核实情况（2026-11-20）**
> - 已核实：代码里的 vLLM 依赖（0.19.1，CUDA 12）只要求驱动版本 ≥ 525；Lite dev 的 23 个评测镜像在 Docker Hub 上都有，合计约 29 GB。
> - **未核实**：本文还没有在阿里云 GPU 实例上实际跑过。规格名称、镜像名称、价格和库存，都以控制台实际显示为准。

**规则：每一阶段都有"通过标准"，当前阶段没达标，就不要进入下一阶段。**

| 阶段 | 内容 | 预计耗时 |
|---|---|---|
| A | 购买实例 | 10 分钟 |
| 0 | 检查机器 | 2 分钟 |
| 1 | 数据盘、Docker、基础工具 | 10 分钟 |
| 2 | Python、拉代码、三个环境 | 20–30 分钟 |
| 3 | 下载 7B 权重 | 5–10 分钟 |
| 4 | 离线测试 | 1 分钟 |
| 5 | 启动 7B 服务 | 3–5 分钟 |
| 6 | 客户端配置和 preflight | 2 分钟 |
| 7 | 仓库镜像和数据集缓存 | 5 分钟 |
| 8 | 官方评测器自检（gold） | 10–20 分钟（主要在拉镜像） |
| 9 | 单题验证（3 次） | 5–10 分钟 |
| 10 | Lite smoke：6 题 × 3 个配置，并做官方评测 | 约 1 小时 |
| 11 | Lite pilot：23 题 × 2 个配置，官方评测和配对统计 | 1–3 小时 |
| 12 | 备份和停机 | 5 分钟 |

全程有效的规则：

- **不升级 NVIDIA 驱动。**
- vLLM、客户端、评测器各用一个独立的 venv。
- vLLM 只监听 127.0.0.1，安全组不开放 8000 端口。
- `.env` 不提交。
- gold patch、test_patch、FAIL_TO_PASS 和 hints 不进入任何 prompt。gold 只在阶段 8 的评测容器里出现。
- `prediction_ready` 只表示补丁能应用，不等于问题解决；是否解决只看官方评测。

---

## 阶段 A：购买实例

在阿里云控制台进入"云服务器 ECS → 创建实例"，按下表选择：

| 项目 | 推荐 | 说明 |
|---|---|---|
| 付费模式 | 按量付费 | 不用时停机 |
| 地域 | **中国香港** | 直连 GitHub、HF、Docker Hub。**不要选内地地域**，否则又回到 AutoDL 的网络问题 |
| 规格 | GPU 计算型 **gn7i**（NVIDIA A10，24 GB），**16 vCPU** 那一档 | A10 的 24 GB 显存和 4090 一样，7B 推理和以后的 QLoRA 都够用。16 核用来同时跑官方评测。8 核那一档也能用，但评测的并发要调低 |
| 架构 | x86_64 | 评测镜像都是 x86_64 的 |
| 镜像 | 公共镜像 **Ubuntu 22.04 64 位**，勾选**"安装 GPU 驱动"** | 驱动版本 ≥ 525 就行，CUDA 版本无所谓。我们的 vLLM 环境自带 CUDA 12 运行时 |
| 系统盘 | ESSD 100 GB | |
| 数据盘 | ESSD **300 GB** | 7B 权重约 15 GB、各个 venv 约 15 GB、dev 评测镜像约 29 GB。以后跑 Lite test 300 题需要更多空间，到时先看实际占用再扩容 |
| 公网 | 分配公网 IPv4，按流量计费，带宽 50–100 Mbps | 下载权重和镜像要用，带宽越大下载越快 |
| 安全组 | **只开放 22 端口**，来源只填你自己的 IP | 这台机器不对外提供任何服务 |
| 登录 | 密钥对，或者自定义 root 密码 | |

> **停机前要注意：** GPU 实例停机时，如果选的是"节省停机模式"，GPU 资源会被释放，再次开机时可能因为没有库存而开不起来。离开时间短（几个小时以内）可以保持开机；要停很久的话，先做阶段 12 的备份再停机。

创建好后，在本机用 SSH 登录：

```bash
ssh root@<公网IP>
```

## 阶段 0：检查机器

```bash
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv; uname -m; nproc; free -g; lsblk
```

通过标准：

- 能看到 A10，显存约 24 GB，驱动版本 ≥ 525；
- `uname -m` 输出 `x86_64`；
- `lsblk` 里能看到 300 GB 的数据盘，一般叫 `vdb` 或 `nvme1n1`。

如果 `nvidia-smi` 找不到命令，说明驱动还在后台安装，等 10 分钟后再试。还是不行就重装系统，并确认勾选了"安装 GPU 驱动"。**不要自己用 apt 装驱动。**

## 阶段 1：数据盘、Docker、基础工具

### 1.1 挂载数据盘到 `/data`

先确认设备名：`lsblk` 里那块 300 GB、而且没有挂载点的盘。下面以 `/dev/vdb` 为例。**格式化会清空这块盘**，只在第一次挂载时做。

```bash
mkfs.ext4 /dev/vdb && mkdir -p /data && mount /dev/vdb /data && echo "/dev/vdb /data ext4 defaults,nofail 0 2" >> /etc/fstab && df -h /data
```

通过标准：`/data` 显示约 295 GB 可用。

### 1.2 安装 Docker 和工具，Docker 数据放到 `/data`

```bash
apt-get update && apt-get install -y git screen curl docker.io && mkdir -p /data/docker /etc/docker && echo '{"data-root": "/data/docker"}' > /etc/docker/daemon.json && systemctl restart docker && docker info | grep -E "Docker Root Dir|Server Version" && docker run --rm hello-world | head -3
```

通过标准：

- 输出里有 `Docker Root Dir: /data/docker`；
- `hello-world` 打印出 `Hello from Docker!`。

评测容器只用 CPU，不需要装 nvidia-container-toolkit。

## 阶段 2：Python、代码、三个环境

### 2.1 环境变量和 Python 3.11

所有缓存都放到数据盘上。香港直连 HF，**不需要设置 `HF_ENDPOINT`**。

```bash
cat >> ~/.bashrc <<'EOF'
export PIP_CACHE_DIR=/data/.cache/pip
export HF_HOME=/data/.cache/huggingface
export MIRROR_ROOT=/data/git-mirrors
export no_proxy=127.0.0.1,localhost NO_PROXY=127.0.0.1,localhost
EOF
source ~/.bashrc
```

```bash
cd /data && curl -L -o miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && bash miniforge.sh -b -p /data/miniforge && /data/miniforge/bin/conda create -y -p /data/py311 python=3.11 && /data/py311/bin/python --version
```

通过标准：输出 `Python 3.11.x`。

### 2.2 拉代码

```bash
cd /data && git clone https://github.com/jackwubupt-ops/7068.git && cd 7068 && git switch main && git log --oneline -1
```

通过标准：显示一个提交号，不能比 `bddd072` 更旧。

### 2.3 vLLM 服务端环境（约 10–20 分钟）

```bash
cd /data/7068 && PYTHON=/data/py311/bin/python bash scripts/setup_qwen_small.sh 2>&1 | tee /data/qwen-setup.log
```

通过标准：最后输出的 JSON 里有 `"compatible": true`，并且 `torch_cuda_runtime` 是 `12.x`。

报错时把 `tail -30 /data/qwen-setup.log` 发回来。**不要自己 pip 安装别的版本。**

### 2.4 客户端环境

```bash
cd /data/7068 && /data/py311/bin/python -m venv .venv-patchloop-client && .venv-patchloop-client/bin/python -m pip install -U pip && .venv-patchloop-client/bin/python -m pip install -r requirements-lock.txt "datasets>=3,<5"
```

### 2.5 官方评测环境

```bash
/data/py311/bin/python -m venv /data/venvs/swebench && /data/venvs/swebench/bin/python -m pip install -U pip && /data/venvs/swebench/bin/python -m pip install -r /data/7068/requirements-swebench-eval.txt && /data/venvs/swebench/bin/python -c "import importlib.metadata as m; print(m.version('swebench'))"
```

通过标准：最后一行输出 `4.1.0`。

## 阶段 3：下载 7B 权重（约 15 GB）

用 vLLM 环境里自带的 `hf` 命令，直接从 Hugging Face 下载：

```bash
cd /data/7068 && .venv-qwen-vllm-cu12/bin/hf download Qwen/Qwen2.5-Coder-7B-Instruct --local-dir /data/qwen-models/Qwen2.5-Coder-7B-Instruct && ls /data/qwen-models/Qwen2.5-Coder-7B-Instruct
```

通过标准：目录里有 `config.json` 和 4 个 `model-0000x-of-00004.safetensors`。

## 阶段 4：离线测试

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate && python -m unittest discover -s tests 2>&1 | grep -E "^(Ran|OK|FAILED|ERROR|FAIL:)"
```

通过标准：有 `Ran 1xx tests` 和 `OK (skipped=1)` 两行，没有 `FAIL` 或 `ERROR`。

说明：

- 必须用 `grep` 筛选，因为有个测试会打印配对统计报告，会把结果行挤掉；
- 离线测试用的是写死的模型回复，只能证明代码接线正确，**不能说明模型的修复能力**。

## 阶段 5：启动 7B 服务

```bash
screen -S vllm
```

在 screen 里执行：

```bash
cd /data/7068 && source .venv-qwen-vllm-cu12/bin/activate && QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct QWEN_MODEL_PATH=/data/qwen-models/Qwen2.5-Coder-7B-Instruct QWEN_MAX_MODEL_LEN=32768 bash scripts/start_qwen_small.sh 2>&1 | tee /data/vllm-7b.log
```

看到 `Application startup complete` 后，按 `Ctrl+A` 再按 `D` 退出 screen，服务会继续在后台运行。然后检查：

```bash
grep -o -E "enable_prefix_caching=[A-Za-z]+|max_seq_len=[0-9]+" /data/vllm-7b.log | sort -u; curl -s http://127.0.0.1:8000/v1/models | head -c 200; echo
```

通过标准：

- `max_seq_len=32768`（vLLM 日志里上下文长度叫这个名字）；
- `/v1/models` 返回的模型 id 是 `Qwen/Qwen2.5-Coder-7B-Instruct`；
- 把 prefix caching 的值记下来。

**为什么把上下文从默认的 16384 调到 32768：** 见阶段 6 的说明。Qwen2.5-Coder-7B 原生支持 32K 上下文。在 24 GB 显存上，7B 每个 token 的 KV cache 约 56 KB，权重占用后剩下的显存大约还能放 8–9 万个 token，4 个并发也够用。

## 阶段 6：客户端配置和 preflight

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate && cp -n .env.qwen-small.example .env && sed -i 's#^QWEN_MODEL=.*#QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct#; s#^QWEN_TIMEOUT=.*#QWEN_TIMEOUT=300#; s#^QWEN_CONTEXT_CHARS=.*#QWEN_CONTEXT_CHARS=48000#' .env && grep -E '^QWEN_' .env && python -m experiments.qwen_small_dev --mode preflight
```

通过标准：

- `.env` 里是 `QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct`、`QWEN_TIMEOUT=300`、`QWEN_CONTEXT_CHARS=48000`；
- 输出里有 `"status": "live_qwen_api_ok"`。

**为什么 `QWEN_CONTEXT_CHARS` 从 18500 调到 48000：**

- 这个值决定 Planner 和单 agent 每次调用最多带多少字符的对话历史。18500 是当初给 0.5B 小模型定的，大约只有 5K token；
- 裁剪的规则是：放不下的消息直接丢掉。在 AutoDL 上，单 agent 读了一个完整的文件，结果太大被丢掉，模型看不到读到的内容，就在"搜索 → 读文件"之间原地打转，16 步全部用完，一次都没提交（sqlfluff-1625，`no_submission`）；
- 48000 字符大约 12–16K token，加上最多 3500 个输出 token，在 32768 的上下文以内；
- 这个设置对 P-C-R 和单 agent **同样生效**，RQ3 的对比仍然公平。`lite_batch` 会把它写进每个批次的 `manifest.json`（`context_chars` 字段）。**smoke 开始之后就不要再改**，否则前后批次之间没法比较。

> 这个原因还没有完全证实。阶段 9 会检查 `dropped_history_messages`，用数据确认。

## 阶段 7：仓库镜像和数据集缓存

香港直连 GitHub，镜像 6 个仓库只要几分钟。镜像目录由 `~/.bashrc` 里的 `MIRROR_ROOT=/data/git-mirrors` 决定。

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate && python -m experiments.lite_batch --list-repos | bash scripts/mirror_repos.sh
```

通过标准：6 个仓库都显示 `mirrored ...`，没有 `FAILED`。

核对 23 道题的 base commit 是否都在镜像里（同时会把数据集缓存下来）：

```bash
cd /data/7068 && python - <<'EOF'
import os, subprocess
from pathlib import Path
from swebench_dev import load_dev_tasks
root = Path(os.environ.get("MIRROR_ROOT", "/data/git-mirrors"))
ok = {}
for t in load_dev_tasks("princeton-nlp/SWE-bench_Lite"):
    m = root / f"{t.repo}.git"
    r = subprocess.run(["git", "-C", str(m), "cat-file", "-t", t.base_commit], capture_output=True, text=True) if m.exists() else None
    ok.setdefault(t.repo, []).append(bool(r and r.stdout.strip() == "commit"))
for repo, s in sorted(ok.items()):
    print(f"{repo:30s} {'全部就绪' if all(s) else '未就绪'} ({sum(s)}/{len(s)})")
print("合计", sum(sum(s) for s in ok.values()), "/ 23")
EOF
```

通过标准：6 行都是"全部就绪"，合计 `23 / 23`。

> **镜像必须是完整克隆**（`mirror_repos.sh` 默认就是）。不要手动做 `--depth=1` 的浅克隆：程序从镜像克隆时会加 `--filter=blob:none`，从浅克隆的仓库这样克隆，git 会一直空转到 240 秒超时。AutoDL 上 pyvista 就是这样出的 `experiment_error`。

## 阶段 8：官方评测器自检（gold）

先用 SWE-bench 自带的标准答案补丁（gold）确认 Docker 和评测镜像都没问题。gold 只在评测容器里使用，**不会进入任何 prompt**。

```bash
mkdir -p /data/eval-selftest && cd /data/eval-selftest && /data/venvs/swebench/bin/python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite --split dev --predictions_path gold --instance_ids sqlfluff__sqlfluff-1625 marshmallow-code__marshmallow-1359 --max_workers 2 --run_id gold-selftest-01 && cat gold.gold-selftest-01.json
```

通过标准：`resolved_instances` 是 2，`error_instances` 是 0。

这一步会拉两个评测镜像，每个 1–2 GB。香港直连 Docker Hub，一般几分钟就能完成。

## 阶段 9：单题验证（3 次运行）

| 运行 | 验证什么 |
|---|---|
| `one-pcr` | P-C-R 的流程能跑通 |
| `one-single` | 单 agent 不再原地打转，验证阶段 6 的修复 |
| `one-pyvista` | 能从镜像正常建出 pyvista 的工作区，验证阶段 7 |

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate && mkdir -p /data/runs && python -m experiments.lite_batch --out /data/runs/one-pcr --agent pcr --edit-format search_replace --instances sqlfluff__sqlfluff-1625 2>&1 | tail -3; python -m experiments.lite_batch --out /data/runs/one-single --agent single --edit-format search_replace --instances sqlfluff__sqlfluff-1625 2>&1 | tail -3; python -m experiments.lite_batch --out /data/runs/one-pyvista --agent pcr --edit-format search_replace --instances pyvista__pyvista-4315 2>&1 | tail -3
```

查看结果：

```bash
cd /data/runs && python - <<'EOF'
import json, glob
for path in sorted(glob.glob("one-*/*/run_status.json")):
    d = json.load(open(path))
    print("=====", path)
    print("status:", d.get("status"), "| failed_stage:", d.get("failed_stage"), "| stop_reason:", d.get("stop_reason"))
    print("error:", str(d.get("error"))[:300])
    print("dropped_history_messages per call:", [c.get("dropped_history_messages") for c in d.get("model_calls", [])])
    for e in (d.get("agent_action_trace") or [])[:8]:
        print("  step", json.dumps(e, ensure_ascii=False)[:200])
EOF
```

通过标准：

- 3 次都不是 `experiment_error`。`patch_failed`、`no_submission`、`prediction_ready` 都算流程跑通；
- **one-single：** `dropped_history_messages` 都是 0（或者绝大多数是 0），trace 不再是"搜索 → 读同一个文件"反复循环；
- **one-pyvista：** 没有卡在 `checkout_real_base_commit`。

如果 one-single 还是原地打转，而且 `dropped_history_messages` 都是 0，说明问题不在上下文裁剪。**先停下来，把输出发回来**，不要开始 smoke。

## 阶段 10：Lite smoke，6 题 × 3 个配置，并做官方评测

三个配置用同一组题（每个仓库 1 题），一次只改一个变量：

| 配置 | 目录 | 回答的问题 |
|---|---|---|
| A | `lite-smoke-pcr-diff` | 基线：P-C-R，diff 格式 |
| B | `lite-smoke-pcr-sr` | 换成查找/替换格式，能应用的补丁会不会变多 |
| C | `lite-smoke-single-sr` | 和 B 相比，单 agent 和 P-C-R 差多少 |

### 10.1 生成补丁

```bash
screen -S smoke
```

在 screen 里执行：

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate && IDS=sqlfluff__sqlfluff-1625,marshmallow-code__marshmallow-1359,pvlib__pvlib-python-1707,pylint-dev__astroid-1978,pyvista__pyvista-4315,pydicom__pydicom-1694 && for cfg in "pcr-diff pcr diff" "pcr-sr pcr search_replace" "single-sr single search_replace"; do set -- $cfg; python -m experiments.lite_batch --out /data/runs/lite-smoke-$1 --agent $2 --edit-format $3 --workers 4 --instances $IDS 2>&1 | tee /data/runs/lite-smoke-$1.log; done
```

开跑后按 `Ctrl+A` 再按 `D` 退出 screen。用 `screen -r smoke` 可以回来查看。

注意事项：

- 中途断了的话，用**完全相同的参数**加上 `--resume` 就能接着跑；
- 三个配置的 `--workers` 必须相同；
- 如果出现大量超时，三个配置都改成 `--workers 2` 重新跑。

通过标准：三个目录都有 `summary.json`，并且 `tasks_finished` 都是 6。

### 10.2 官方评测（同一台机器，不用再传文件）

```bash
cd /data/7068 && for run in lite-smoke-pcr-diff lite-smoke-pcr-sr lite-smoke-single-sr; do /data/py311/bin/python -m experiments.official_eval --batch /data/runs/$run --harness-python /data/venvs/swebench/bin/python --max-workers 8 2>&1 | tee /data/runs/$run.eval.log; done
```

- `--max-workers` 不要超过 CPU 核数的 75%：16 核用 8–12，8 核用 4；
- 评测只用 CPU，可以和后面 pilot 的生成同时跑；
- 退出码为 2，表示有题目是 `harness_error` 或 `not_evaluated`。这时**不要使用这个解决率**：先到 `<批次目录>/official/logs/` 里查原因，然后换一个新的 `--run-id` 重新评测（例如 `--run-id lite-smoke-pcr-sr-r2`）。同一个 run id 不能用两次。

通过标准：三个目录都有 `official_eval.json`，并且 `"complete": true`。**这就是项目的第一批官方解决率。**

汇总三个配置：

```bash
cd /data/runs && for run in lite-smoke-pcr-diff lite-smoke-pcr-sr lite-smoke-single-sr; do python3 -c "import json,sys;s=json.load(open(sys.argv[1]+'/summary.json'));e=json.load(open(sys.argv[1]+'/official_eval.json'));print(sys.argv[1],'ready=',s['prediction_ready'],s['status_counts'],{k:v for k,v in e.items() if k!='tasks'})" $run; done
```

## 阶段 11：Lite pilot，23 题 × 2 个配置（RQ3 第一批数据）

根据 smoke 的结果选定编辑格式：如果 B 的 `prediction_ready` 不少于 A，就用 `search_replace`（下面的命令默认用它）。

```bash
screen -S pilot
```

在 screen 里执行：

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate && for agent in pcr single; do python -m experiments.lite_batch --out /data/runs/lite-pilot-$agent --agent $agent --edit-format search_replace --workers 4 2>&1 | tee /data/runs/lite-pilot-$agent.log; done
```

通过标准：两个目录的 `tasks_finished` 都是 23。

然后做官方评测和配对统计：

```bash
cd /data/7068 && for run in lite-pilot-pcr lite-pilot-single; do /data/py311/bin/python -m experiments.official_eval --batch /data/runs/$run --harness-python /data/venvs/swebench/bin/python --max-workers 8 2>&1 | tee /data/runs/$run.eval.log; done && /data/py311/bin/python -m experiments.paired_compare /data/runs/lite-pilot-pcr /data/runs/lite-pilot-single --out /data/runs/pilot-pcr-vs-single.json
```

输出包括：逐题配对表、精确 McNemar p 值、解决率差值的 bootstrap 95% CI。23 道题只能作参考，正式结论要用 Lite test 的 300 题。

**检查点：** 如果两个配置的解决率都接近 0，先停下来分析失败分布，不要扩大规模（见 [TODO.md](../TODO.md) 的 P1 检查点）。

## 阶段 12：备份和停机

打包所有运行结果（不包括权重、镜像和 venv）：

```bash
cd /data && tar czf patchloop-runs-$(date +%Y%m%d-%H%M).tar.gz runs vllm-7b.log 7068/.env eval-selftest/*.json && ls -lh patchloop-runs-*.tar.gz
```

在本机执行：

```bash
scp root@<公网IP>:/data/patchloop-runs-*.tar.gz .
```

确认已经下载到本地之后，再去控制台停机。停机前注意阶段 A 里关于 GPU 库存的提醒。

## 以后的阶段在这台机器上怎么做

- **RQ2 执行反馈：** 测试直接在本机的 Docker 里跑，用 SWE-bench 预构建的实例镜像，不再需要远程调用。泄漏红线不变：只能运行仓库原有的测试和模型自己写的复现脚本，`test_patch` 和 FAIL_TO_PASS 测试一律不能用。
- **RQ1 QLoRA：** A10 24 GB 可以训练 7B 的 4-bit QLoRA。训练前先停掉 vLLM（`screen -r vllm` 后按 `Ctrl+C`），训练环境单独建一个 venv。如果想省钱，训练也可以继续放在 AutoDL 上：训练不需要 Docker，也基本不用访问 GitHub。

## 常见问题

| 现象 | 处理 |
|---|---|
| `nvidia-smi` 找不到命令 | 驱动还在后台安装，等 10 分钟；还是不行就重装系统，并勾选"安装 GPU 驱动" |
| vLLM 启动时报 `driver too old` | 驱动版本 < 525。换一个带较新驱动的镜像，**不要自己升级驱动** |
| vLLM 启动时显存不够（OOM） | 先确认没有其他进程占用 GPU（`nvidia-smi`）；还是不够的话，把 `QWEN_MAX_MODEL_LEN` 降到 24576，并把 `QWEN_CONTEXT_CHARS` 降到 36000 |
| 请求报 `maximum context length` | prompt 超过了 vLLM 的上下文长度。确认阶段 5 的 `max_seq_len=32768` 已经生效 |
| 单题卡在 `checkout_real_base_commit`，正好 240 秒 | 镜像是浅克隆或者不完整。删掉 `/data/git-mirrors/<仓库>`，重新运行阶段 7 的镜像命令 |
| 拉取 `swebench/sweb.eval...` 超时 | 确认地域是香港；用 `docker pull hello-world` 测试网络 |
| `exec format error` | 买成了 ARM 实例，需要换成 x86_64 |
| 磁盘满了 | `docker system df` 查看占用；确认没有正在运行的评测后，再执行 `docker image prune` |
| `run id ... already used` | 换一个新的 `--run-id` |

## 需要发回来的结果

1. 阶段 5 的 `max_seq_len` 和 prefix caching 那两行；
2. 阶段 8 gold 自检的报告；
3. 阶段 9 三次单题的检查输出；
4. 阶段 10 三个配置的汇总；
5. 阶段 11 `paired_compare` 的输出。
