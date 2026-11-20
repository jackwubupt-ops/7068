# 阿里云 GPU 服务器完整流程（推理 + 本地官方评测）

AutoDL 没有 Docker，跑不了官方 SWE-bench harness。阿里云 ECS 是完整虚拟机，**有 root 权限，也能装 Docker**，所以这一台服务器就能把两件事都做完：

1. 用 vLLM 跑 Qwen2.5-Coder-7B 生成补丁；
2. 用官方 harness（`swebench==4.1.0` 加上 Docker Hub 上预构建的镜像）在本地判定补丁是否真正解决了问题。

sb-cli 降为备选方案。本文和 [full-test-runbook.md](full-test-runbook.md) 的阶段编号一一对应；只有服务器准备（阶段 A）和官方评测（阶段 8）不同，其余命令只是把路径从 `/root/autodl-tmp` 换成了 `/data`。

> 已核实（2026-11-20）：SWE-bench Lite dev 的 23 道题在 Docker Hub 上都有预构建评测镜像 `swebench/sweb.eval.x86_64.*:latest`，每个压缩后 1–2 GB，合计约 29 GB。
> 尚未在阿里云上实际跑过：下面的规格名称、镜像版本和驱动版本，请以控制台实际能选的为准。

---

## 阶段 A：购买实例

| 项目 | 推荐 | 说明 |
|---|---|---|
| 地域 | **中国香港**（或新加坡） | 内地地域访问 Docker Hub、GitHub、Hugging Face 都不稳定，评测镜像很可能拉不下来。香港地域不需要任何代理或镜像站 |
| 规格 | `gn7i` 系列，1 × NVIDIA A10 24GB；能选 16 vCPU / 60 GiB 内存的就选它 | 7B 用 bf16 跑和 4090 一样能放下。评测并发受 CPU 核数限制（建议不超过核数的 75%）。不要选 T4（16GB，不支持 bf16） |
| 镜像 | Ubuntu 22.04 64 位，勾选"安装 GPU 驱动"，驱动选 ≥ 535（CUDA 12.x） | 脚本要求驱动 ≥ 525。驱动 ≥ 580 也可以，固定的 CUDA 12 依赖照样能用 |
| 系统盘 | ESSD 100 GB | |
| 数据盘 | ESSD 300 GB，挂载到 `/data` | 用来放权重、venv、Docker 镜像和运行结果 |
| 计费 | 按量付费；跑完立即"停机（节省停机模式）"或释放 | 抢占式实例更便宜，但可能被回收；批处理可以用 `--resume` 接着跑 |
| 安全组 | 只放行 22 端口，并且只允许你自己的 IP | **绝对不要放行 8000**，vLLM 只监听 127.0.0.1 |

从本机连接（如果本机也要访问 vLLM，就加上端口转发）：

```bash
ssh -L 8000:127.0.0.1:8000 root@<公网IP>
```

## 阶段 0：检查服务器状态

```bash
nvidia-smi
lsblk && df -h / /data
nproc && free -g
```

通过标准：

- 能看到 A10，驱动版本 ≥ 525；
- `/data` 已挂载，剩余空间 ≥ 250 GB。

如果数据盘还没挂载（假设设备名是 `/dev/vdb`，以 `lsblk` 的输出为准；**格式化会清空这块盘**）：

```bash
mkfs.ext4 /dev/vdb && mkdir -p /data && mount /dev/vdb /data && echo "/dev/vdb /data ext4 defaults,nofail 0 2" >> /etc/fstab
```

## 阶段 1：搭建环境

### 1.1 系统包和 Docker（数据目录放到 `/data`）

```bash
apt-get update && apt-get install -y git screen curl build-essential docker.io
mkdir -p /data/docker /etc/docker
echo '{"data-root": "/data/docker"}' > /etc/docker/daemon.json
systemctl restart docker && docker info | grep -E "Docker Root Dir|Server Version"
docker run --rm hello-world
```

通过标准：`Docker Root Dir: /data/docker`，并且 `hello-world` 能正常输出。

### 1.2 Python 3.11（Miniforge，装在数据盘）

```bash
cd /data && curl -L -o miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash miniforge.sh -b -p /data/miniforge
/data/miniforge/bin/conda create -y -p /data/py311 python=3.11
/data/py311/bin/python --version
```

### 1.3 缓存目录

香港地域可以直连 Hugging Face，**不要**设置 `HF_ENDPOINT`。

```bash
cat >> ~/.bashrc <<'EOF'
export PIP_CACHE_DIR=/data/.cache/pip
export HF_HOME=/data/.cache/huggingface
export no_proxy=127.0.0.1,localhost NO_PROXY=127.0.0.1,localhost
export MIRROR_ROOT=/data/git-mirrors
EOF
source ~/.bashrc
```

### 1.4 拉取代码

```bash
cd /data && git clone https://github.com/jackwubupt-ops/7068.git && cd 7068 && git switch main && git log --oneline -1
```

### 1.5 三个相互独立的 venv

| venv | 用途 |
|---|---|
| `.venv-qwen-vllm-cu12` | vLLM 服务端（固定 CUDA 12 版本的依赖） |
| `.venv-patchloop-client` | PatchLoop 客户端，加上 `datasets` |
| `/data/venvs/swebench` | 官方评测器 `swebench==4.1.0` |

```bash
cd /data/7068
PYTHON=/data/py311/bin/python bash scripts/setup_qwen_small.sh 2>&1 | tee /data/qwen-setup.log
```

通过标准：输出 `"compatible": true`，并且 `torch_cuda_runtime` 是 12.x。

```bash
/data/py311/bin/python -m venv .venv-patchloop-client
.venv-patchloop-client/bin/python -m pip install -U pip
.venv-patchloop-client/bin/python -m pip install -r requirements-lock.txt "datasets>=3,<5" "huggingface_hub[cli]"
```

```bash
/data/py311/bin/python -m venv /data/venvs/swebench
/data/venvs/swebench/bin/python -m pip install -U pip
/data/venvs/swebench/bin/python -m pip install -r requirements-swebench-eval.txt
/data/venvs/swebench/bin/python -c "import importlib.metadata as m; print(m.version('swebench'))"
```

通过标准：最后一行输出 `4.1.0`。

### 1.6 下载 7B 权重

```bash
source /data/7068/.venv-patchloop-client/bin/activate
huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct --local-dir /data/qwen-models/Qwen2.5-Coder-7B-Instruct
ls /data/qwen-models/Qwen2.5-Coder-7B-Instruct
```

通过标准：目录里有 `config.json` 和 4 个 `model-0000x-of-00004.safetensors`。如果 `huggingface-cli` 提示命令不存在，改用新版命令 `hf download`，参数相同。

## 阶段 1.7：评测器自检（gold 补丁，只需要 Docker，不需要模型）

先确认 Docker 和评测镜像都没问题，再去跑模型。这里使用 SWE-bench 自带的标准答案补丁（gold），它**只在评测容器里使用，不会进入任何 prompt**。

```bash
mkdir -p /data/eval-selftest && cd /data/eval-selftest
/data/venvs/swebench/bin/python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite --split dev \
  --predictions_path gold \
  --instance_ids sqlfluff__sqlfluff-1625 marshmallow-code__marshmallow-1359 \
  --max_workers 2 --run_id gold-selftest-01
cat gold.gold-selftest-01.json
```

通过标准：`resolved_instances` 是 2，`error_instances` 是 0。

这一步还会预先拉下这两个镜像。如果拉取超时，说明网络有问题（多半是选了内地地域），请先解决网络问题再继续。

## 阶段 2–7：与主流程相同

按 [full-test-runbook.md](full-test-runbook.md) 的阶段 2–7 执行，替换规则如下：

- 所有 `/root/autodl-tmp` 换成 `/data`（仓库在 `/data/7068`，结果放在 `/data/runs/...`）；
- 去掉所有 `source /etc/network_turbo` 和 `unset http_proxy https_proxy`；
- 启动 vLLM 时，`QWEN_MODEL_PATH=/data/qwen-models/Qwen2.5-Coder-7B-Instruct`；
- 阶段 5.1 镜像仓库时，因为前面已经设置了 `MIRROR_ROOT=/data/git-mirrors`，镜像会存到 `/data/git-mirrors`。

例如，阶段 6 的 smoke：

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate && mkdir -p /data/runs
IDS=sqlfluff__sqlfluff-1625,marshmallow-code__marshmallow-1359,pvlib__pvlib-python-1707,pylint-dev__astroid-1978,pyvista__pyvista-4315,pydicom__pydicom-1694
python -m experiments.lite_batch --out /data/runs/lite-smoke-pcr-diff --agent pcr --edit-format diff --workers 4 --instances $IDS 2>&1 | tee /data/runs/lite-smoke-pcr-diff.log
python -m experiments.lite_batch --out /data/runs/lite-smoke-pcr-sr --agent pcr --edit-format search_replace --workers 4 --instances $IDS 2>&1 | tee /data/runs/lite-smoke-pcr-sr.log
python -m experiments.lite_batch --out /data/runs/lite-smoke-single-sr --agent single --edit-format search_replace --workers 4 --instances $IDS 2>&1 | tee /data/runs/lite-smoke-single-sr.log
```

## 阶段 8：本地官方评测（替代 sb-cli）

对每个批次目录执行一次。它在独立 venv 里调用官方 harness，然后在批次目录里写出 `official_eval.json`：

- 23 道（或 6 道）题，每题一个结论；
- **分母是这个批次跑的所有题**，没有生成预测的题计为 `no_prediction`，也就是未解决。

```bash
cd /data/7068 && source .venv-patchloop-client/bin/activate
for run in lite-smoke-pcr-diff lite-smoke-pcr-sr lite-smoke-single-sr; do
  python -m experiments.official_eval --batch /data/runs/$run \
    --harness-python /data/venvs/swebench/bin/python --max-workers 4 2>&1 | tee /data/runs/$run.eval.log
done
```

- 评测日志和官方报告保存在 `<批次目录>/official/` 下。
- 退出码为 2 表示存在 `harness_error` 或 `not_evaluated`。这时**不要使用这个解决率**：先在 `official/logs/` 里查看原因，再用一个新的 `--run-id`（例如 `--run-id lite-smoke-pcr-sr-r2`）重新评测。
- 同一个 run id 不能用两次：harness 会直接复用旧结果，脚本会拒绝执行。
- `--max-workers` 不要超过 CPU 核数的 75%。评测时 vLLM 可以继续运行，但它会和评测争抢 CPU。

通过标准：每个目录都有 `official_eval.json`，并且 `"complete": true`。

### 8.1 配对比较（RQ3 / 编辑格式）

```bash
python -m experiments.paired_compare /data/runs/lite-smoke-pcr-sr /data/runs/lite-smoke-single-sr
python -m experiments.paired_compare /data/runs/lite-pilot-pcr /data/runs/lite-pilot-single --out /data/runs/pilot-pcr-vs-single.json
```

输出包括：逐题配对表、精确 McNemar p 值、解决率差值的 bootstrap 95% CI。题数少于 50 时只当作参考，正式结论用 Lite test（300 题）。

### 8.2 备选方案：sb-cli

如果本地评测走不通，按 [full-test-runbook.md](full-test-runbook.md) 的阶段 8 用 sb-cli 提交（香港地域不需要 `network_turbo`）。

## 阶段 9：备份和省钱

```bash
cd /data && tar czf patchloop-results-$(date +%Y%m%d).tar.gz runs/*.log runs/*/manifest.json runs/*/summary.json runs/*/results.jsonl runs/*/all_preds.jsonl runs/*/official_eval.json runs/*/*/run_status.json runs/*/official/*.json
```

在本机执行下载：

```bash
scp root@<公网IP>:/data/patchloop-results-*.tar.gz .
```

用完之后在控制台**停机或释放**实例。停机后数据盘仍然会计费；释放实例前请先确认结果已经下载到本地。

## 常见问题

| 现象 | 处理 |
|---|---|
| 拉取 `swebench/sweb.eval...` 超时或报 `TLS handshake` 错误 | 网络问题。确认地域是香港或新加坡；内地地域请改用 sb-cli |
| `permission denied ... docker.sock` | 用 root 运行，或者执行 `usermod -aG docker $USER` 后重新登录 |
| 磁盘满了 | 运行 `docker system df` 查看占用；执行 `docker image prune` 前，先确认没有正在运行的评测 |
| `official_eval` 报 `run id ... already used` | 换一个新的 `--run-id` |
| `harness_error` 集中在某一个仓库 | 查看 `official/logs/run_evaluation/<run_id>/.../run_instance.log`，先用 gold 跑同一道题，排除镜像本身的问题 |
| 其他问题 | 见 [full-test-runbook.md](full-test-runbook.md) 的"常见问题"一节 |

## 需要发回来的结果

1. 阶段 1.7 gold 自检的报告（`gold.gold-selftest-01.json`）。
2. 阶段 3 中 prefix caching 那一行。
3. 每个批次的 `summary.json` 和 `official_eval.json`（不含 `tasks` 字段的那部分摘要就够了）。
4. 8.1 节 `paired_compare` 的输出。
