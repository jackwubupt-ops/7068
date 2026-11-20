# 阿里云评测机（只用 CPU，只跑官方评测）

## 两台机器怎么分工

| 机器 | 负责什么 | 操作文档 |
|---|---|---|
| **AutoDL（RTX 4090）** | vLLM 推理（smoke、pilot、Lite test 生成补丁）、QLoRA 训练、挑 checkpoint | [full-test-runbook.md](full-test-runbook.md) 阶段 0–7 |
| **阿里云（只用 CPU，香港地域）** | 用 Docker 跑官方 SWE-bench harness，做配对统计 | 本文 |

为什么这样分：

- 官方评测需要 Docker，但不需要 GPU；AutoDL 没有 Docker，但 GPU 便宜。
- 两台机器之间只需要传批次目录（预测和日志），每次只有几 MB。
- 所以阿里云**只买一台 CPU 机器**，比 GPU 实例便宜得多。

> 已核实（2026-11-20）：SWE-bench Lite dev 的 23 道题在 Docker Hub 上都有预构建的评测镜像 `swebench/sweb.eval.x86_64.*:latest`，每个压缩后 1–2 GB，合计约 29 GB。
> 还没核实：本文还没有在阿里云上实际跑过；实例规格名称和镜像版本以控制台实际可选为准。

---

## 阶段 A：购买实例

| 项目 | 推荐 | 说明 |
|---|---|---|
| 地域 | **中国香港**（或新加坡） | 内地地域访问 Docker Hub 和 Hugging Face 不稳定，评测镜像很可能拉不下来；香港可以直连，不需要代理 |
| 规格 | 通用型，**x86_64**，16 vCPU / 64 GiB | **不要选 ARM（倚天）实例**：评测镜像都是 x86_64 的。评测并发不要超过核数的 75%，16 核大约开 8–12 个 worker |
| 镜像 | Ubuntu 22.04 64 位 | 不需要 GPU 驱动 |
| 系统盘 | ESSD 60 GB | |
| 数据盘 | ESSD 300 GB，挂载到 `/data` | Docker 镜像和结果都放在这里。跑 Lite test 的 300 题需要更多空间，到时先用 `docker system df` 看实际占用再扩容 |
| 计费 | 按量付费；不用时"停机（节省停机模式）" | 停机后数据盘还在，已经拉下来的镜像下次直接复用 |
| 安全组 | 只放行 22 端口，且只允许你自己的 IP | 这台机器不需要对外提供任何服务 |

## 阶段 0：检查

```bash
uname -m && nproc && free -g
lsblk && df -h / /data
```

通过标准：

- `uname -m` 输出 `x86_64`；
- `/data` 已经挂载，剩余空间 ≥ 250 GB。

如果数据盘还没有挂载（设备名以 `lsblk` 显示的为准；**格式化会清空这块盘**）：

```bash
mkfs.ext4 /dev/vdb && mkdir -p /data && mount /dev/vdb /data && echo "/dev/vdb /data ext4 defaults,nofail 0 2" >> /etc/fstab
```

## 阶段 1：搭建环境

### 1.1 安装 Docker，数据目录放到 `/data`

```bash
apt-get update && apt-get install -y git screen curl docker.io
mkdir -p /data/docker /etc/docker
echo '{"data-root": "/data/docker"}' > /etc/docker/daemon.json
systemctl restart docker && docker info | grep -E "Docker Root Dir|Server Version"
docker run --rm hello-world
```

通过标准：

- 输出里有 `Docker Root Dir: /data/docker`；
- `hello-world` 能正常输出。

### 1.2 安装 Python 3.11，拉取代码，建评测 venv

```bash
cd /data && curl -L -o miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash miniforge.sh -b -p /data/miniforge
/data/miniforge/bin/conda create -y -p /data/py311 python=3.11
echo 'export HF_HOME=/data/.cache/huggingface PIP_CACHE_DIR=/data/.cache/pip' >> ~/.bashrc && source ~/.bashrc
```

```bash
cd /data && git clone https://github.com/jackwubupt-ops/7068.git && cd 7068 && git switch main && git log --oneline -1
/data/py311/bin/python -m venv /data/venvs/swebench
/data/venvs/swebench/bin/python -m pip install -U pip
/data/venvs/swebench/bin/python -m pip install -r requirements-swebench-eval.txt
/data/venvs/swebench/bin/python -c "import importlib.metadata as m; print(m.version('swebench'))"
```

通过标准：最后一行输出 `4.1.0`。

`experiments.official_eval` 和 `experiments.paired_compare` 只用到 Python 标准库，所以在仓库目录下直接用 `/data/py311/bin/python` 运行即可，不需要再装客户端环境。

## 阶段 2：评测器自检（用 gold 补丁）

先用 SWE-bench 自带的标准答案补丁（gold）确认 Docker 和评测镜像都没问题。gold 只在评测容器里使用，**不会进入任何 prompt**。

```bash
mkdir -p /data/eval-selftest && cd /data/eval-selftest
/data/venvs/swebench/bin/python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite --split dev \
  --predictions_path gold \
  --instance_ids sqlfluff__sqlfluff-1625 marshmallow-code__marshmallow-1359 \
  --max_workers 2 --run_id gold-selftest-01
cat gold.gold-selftest-01.json
```

通过标准：`resolved_instances` 为 2，`error_instances` 为 0。

如果拉取镜像超时，说明网络有问题（多半是选了内地地域）。先把网络问题解决，再往下做。

## 阶段 3：把 AutoDL 的结果传过来

### 3.1 在 AutoDL 上打包

只打包评测需要的文件，不包括仓库镜像和权重：

```bash
cd /root/autodl-tmp
tar czf to-eval-$(date +%Y%m%d-%H%M).tar.gz \
  lite-smoke-*/manifest.json lite-smoke-*/all_preds.jsonl lite-smoke-*/results.jsonl lite-smoke-*/summary.json \
  lite-pilot-*/manifest.json lite-pilot-*/all_preds.jsonl lite-pilot-*/results.jsonl lite-pilot-*/summary.json
```

如果某一组目录还不存在，先把命令里对应的那两行删掉，否则 tar 会报错。

### 3.2 经本机中转

AutoDL 的 SSH 地址和端口在实例页面的"登录指令"里。在本机执行：

```bash
scp -P <AutoDL端口> root@<AutoDL地址>:/root/autodl-tmp/to-eval-*.tar.gz .
```

```bash
scp to-eval-*.tar.gz root@<阿里云公网IP>:/data/
```

### 3.3 在阿里云上解包

```bash
mkdir -p /data/runs && cd /data/runs && tar xzf /data/to-eval-*.tar.gz && ls
```

通过标准：每个批次目录里都有 `manifest.json` 和 `all_preds.jsonl`。如果某个批次一个补丁都没生成，`all_preds.jsonl` 可能是空的，这种情况也属于正常。

## 阶段 4：官方评测

每个批次目录跑一次。这一步在独立的 venv 里调用官方 harness，然后在批次目录里写出 `official_eval.json`：每道题一个结论，**分母是这个批次跑的全部题目**，没有生成预测的题记为 `no_prediction`，也就是未解决。

```bash
cd /data/7068 && git pull --ff-only
for run in lite-smoke-pcr-diff lite-smoke-pcr-sr lite-smoke-single-sr; do
  /data/py311/bin/python -m experiments.official_eval --batch /data/runs/$run \
    --harness-python /data/venvs/swebench/bin/python --max-workers 8 2>&1 | tee /data/runs/$run.eval.log
done
```

- 评测日志和官方报告都保存在 `<批次目录>/official/` 里。
- 退出码为 2，表示有题目是 `harness_error` 或 `not_evaluated`。这时**不要使用这个解决率**：先到 `official/logs/` 里查原因，然后换一个新的 `--run-id` 重新评测（例如 `--run-id lite-smoke-pcr-sr-r2`）。
- 同一个 run id 不能用两次。harness 会直接复用旧结果，所以脚本会拒绝执行。

通过标准：每个目录都有 `official_eval.json`，并且 `"complete": true`。

### 4.1 配对比较（编辑格式 / RQ3 / 以后的 RQ1、RQ2）

```bash
cd /data/7068
/data/py311/bin/python -m experiments.paired_compare /data/runs/lite-smoke-pcr-diff /data/runs/lite-smoke-pcr-sr
/data/py311/bin/python -m experiments.paired_compare /data/runs/lite-pilot-pcr /data/runs/lite-pilot-single --out /data/runs/pilot-pcr-vs-single.json
```

输出包括：逐题配对表、精确 McNemar p 值、解决率差值的 bootstrap 95% CI。题目少于 50 道时结论只能作参考，正式结论要用 Lite test 的 300 题。

### 4.2 备选：sb-cli

如果本地评测跑不通，就按 [full-test-runbook.md](full-test-runbook.md) 的阶段 8 用 sb-cli 提交。在 AutoDL 上就能提交，不需要这台机器。

## 阶段 5：取回结果，停机

```bash
cd /data && tar czf eval-results-$(date +%Y%m%d).tar.gz runs/*/official_eval.json runs/*/official/*.json runs/*.eval.log runs/*.json
```

在本机执行：

```bash
scp root@<阿里云公网IP>:/data/eval-results-*.tar.gz .
```

做完后到控制台**停机**。停机后数据盘和镜像都还在，下次直接用；确定不再需要了再释放实例。

## 常见问题

| 现象 | 处理 |
|---|---|
| 拉取 `swebench/sweb.eval...` 超时，或者报 `TLS handshake` 错误 | 网络问题。确认地域是香港或新加坡；内地地域的话改用 sb-cli |
| `exec format error` | 买成了 ARM 实例，需要换 x86_64 |
| `permission denied ... docker.sock` | 用 root 运行 |
| 磁盘满了 | `docker system df` 查看占用；确认没有正在运行的评测后，再执行 `docker image prune` |
| `run id ... already used` | 换一个新的 `--run-id` |
| `harness_error` 集中在某个仓库 | 查看 `official/logs/run_evaluation/<run_id>/.../run_instance.log`，先用 gold 跑同一道题，排除镜像本身的问题 |
| `Prediction ... is not in the manifest` | 传过来的 `all_preds.jsonl` 和 `manifest.json` 不属于同一个批次，重新打包 |

## 需要发回来的结果

1. 阶段 2 gold 自检的报告。
2. 每个批次 `official_eval.json` 里不含 `tasks` 字段的摘要部分。
3. 阶段 4.1 `paired_compare` 的输出。
