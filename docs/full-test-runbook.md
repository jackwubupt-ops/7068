# PatchLoop 完整测试流程（main 分支）

本流程覆盖：从一台全新的 AutoDL 服务器（RTX 4090，24GB）出发 → 离线测试 → 7B 服务 → 单题验证 → Lite smoke 对比 → Lite pilot（RQ3）→ sb-cli 官方评测 → 备份。

**每一阶段都有"通过标准"。当前阶段没达标，就不要进入下一阶段。**

| 阶段 | 内容 | 预计耗时 |
|---|---|---|
| 0 | 检查服务器状态 | 1 分钟 |
| 1 | 搭建环境 | 30–60 分钟（主要花在下载） |
| 2 | 离线单元测试 | 1 分钟 |
| 3 | 启动 7B 服务 | 3–5 分钟 |
| 4 | 客户端 preflight | 1 分钟 |
| 5 | 单题真实运行 | 5–15 分钟 |
| 6 | Lite smoke：6 题 × 3 个配置 | 约 1 小时 |
| 7 | Lite pilot：23 题 × 2 个配置（RQ3） | 1–3 小时 |
| 8 | sb-cli 官方评测 | 视排队情况 |
| 9 | 汇总对比与备份 | 5 分钟 |

规则（全程有效）：

- 不升级 NVIDIA 驱动。
- 不往 OpenPI 等已有环境里装包。
- 不提交 `.env`。
- vLLM 只监听 127.0.0.1。
- gold patch、test_patch、FAIL_TO_PASS 不进入任何 prompt。
- `prediction_ready` 只表示补丁能应用，不等于问题被解决；是否解决只看官方评测。

---

## 阶段 0：检查服务器状态

```bash
nvidia-smi
df -h /root/autodl-tmp
ls /root/autodl-tmp
```

通过标准：

- 驱动版本 ≥ 525。
- 数据盘剩余空间 ≥ 40GB。

如果 `ls` 列出了之前留下的 `7068`、`py311`、`qwen-models`，可以跳过对应的安装步骤。

## 阶段 1：搭建环境

### 1.1 缓存目录和 Python 3.11

```bash
cat >> ~/.bashrc <<'EOF'
export PIP_CACHE_DIR=/root/autodl-tmp/.cache/pip
export HF_HOME=/root/autodl-tmp/.cache/huggingface
export MODELSCOPE_CACHE=/root/autodl-tmp/.cache/modelscope
export HF_ENDPOINT=https://hf-mirror.com
export no_proxy=127.0.0.1,localhost NO_PROXY=127.0.0.1,localhost
EOF
source ~/.bashrc
conda create -y -p /root/autodl-tmp/py311 python=3.11
```

### 1.2 拉取代码（main 分支）

```bash
cd /root/autodl-tmp
source /etc/network_turbo
git clone https://github.com/jackwubupt-ops/7068.git
cd 7068 && git switch main && git pull --ff-only && git log --oneline -1
unset http_proxy https_proxy
```

如果之前已经 clone 过，只需执行：

```bash
cd /root/autodl-tmp/7068 && git fetch && git switch main && git pull --ff-only
```

### 1.3 vLLM 服务端环境（独立 venv）

```bash
cd /root/autodl-tmp/7068
PYTHON=/root/autodl-tmp/py311/bin/python bash scripts/setup_qwen_small.sh 2>&1 | tee /root/autodl-tmp/qwen-setup.log
```

通过标准：最后输出的 JSON 里有 `"compatible": true`，并且 `torch_cuda_runtime` 是 12.x。

### 1.4 客户端环境和 7B 权重

```bash
cd /root/autodl-tmp/7068
/root/autodl-tmp/py311/bin/python -m venv .venv-patchloop-client
source .venv-patchloop-client/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-lock.txt "datasets>=3,<5" modelscope
modelscope download --model Qwen/Qwen2.5-Coder-7B-Instruct --local_dir /root/autodl-tmp/qwen-models/Qwen2.5-Coder-7B-Instruct
ls /root/autodl-tmp/qwen-models/Qwen2.5-Coder-7B-Instruct
```

通过标准：目录里有 `config.json` 和 4 个 `model-0000x-of-00004.safetensors`。

## 阶段 2：离线单元测试（不需要 GPU，也不需要模型）

```bash
cd /root/autodl-tmp/7068 && source .venv-patchloop-client/bin/activate
python -m unittest discover -s tests 2>&1 | tail -3
```

通过标准：输出 `Ran 111 tests ... OK (skipped=1)`（数量以实际为准，不能出现 FAIL 或 ERROR）。

说明：这一阶段用的是写死的模型回复，只能证明代码接线是对的，**不能说明模型修复能力**。

## 阶段 3：启动 7B 服务（在 screen 里）

```bash
command -v screen || apt-get install -y screen
screen -S vllm
```

进入 screen 后执行：

```bash
cd /root/autodl-tmp/7068 && source .venv-qwen-vllm-cu12/bin/activate
QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct QWEN_MODEL_PATH=/root/autodl-tmp/qwen-models/Qwen2.5-Coder-7B-Instruct bash scripts/start_qwen_small.sh 2>&1 | tee /root/autodl-tmp/vllm-7b.log
```

看到 `Application startup complete` 后，按 `Ctrl+A` 再按 `D` 退出 screen（服务继续在后台运行）。然后检查：

```bash
grep -o "enable_prefix_caching=[A-Za-z]*" /root/autodl-tmp/vllm-7b.log | head -1
curl -s http://127.0.0.1:8000/v1/models
```

通过标准：

- `/v1/models` 返回的模型 id 是 `Qwen/Qwen2.5-Coder-7B-Instruct`。
- 记下 prefix caching 那一行（理想情况是 `True`）。

## 阶段 4：客户端 preflight

```bash
cd /root/autodl-tmp/7068 && source .venv-patchloop-client/bin/activate
[ -f .env ] || cp .env.qwen-small.example .env
sed -i 's#^QWEN_MODEL=.*#QWEN_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct#; s#^QWEN_TIMEOUT=.*#QWEN_TIMEOUT=300#' .env
grep -E '^QWEN_(MODEL|TIMEOUT)=' .env
python -m experiments.qwen_small_dev --mode preflight
```

通过标准：输出里有 `"status": "live_qwen_api_ok"`。

## 阶段 5：镜像仓库，跑一道单题

### 5.1 镜像 Lite dev 涉及的 6 个仓库

```bash
source /etc/network_turbo
python -m experiments.lite_batch --list-repos | bash scripts/mirror_repos.sh
unset http_proxy https_proxy
```

通过标准：6 个仓库都显示 `mirrored ...`，并且没有 `FAILED`。

### 5.2 单题，两种 agent 各跑一次

```bash
python -m experiments.lite_batch --out /root/autodl-tmp/one-pcr --agent pcr --edit-format search_replace --instances sqlfluff__sqlfluff-1625
```

```bash
python -m experiments.lite_batch --out /root/autodl-tmp/one-single --agent single --edit-format search_replace --instances sqlfluff__sqlfluff-1625
```

通过标准：两次都能正常结束，并生成 `summary.json`。这一步只看流程能不能跑通，不要求 `prediction_ready`。

如果状态是 `experiment_error`，查看错误信息：

```bash
python -c "import json;d=json.load(open('/root/autodl-tmp/one-pcr/sqlfluff__sqlfluff-1625/run_status.json'));print(d['status'],d.get('failed_stage'),d.get('error'))"
```

## 阶段 6：Lite smoke，6 题 × 3 个配置

三个配置用同一组题（每个仓库 1 题），一次只改一个变量：

| 配置 | 目录 | 回答的问题 |
|---|---|---|
| A | `lite-smoke-pcr-diff` | 基线：P-C-R，diff 格式 |
| B | `lite-smoke-pcr-sr` | 换成查找/替换格式，能应用的补丁会不会变多 |
| C | `lite-smoke-single-sr` | 和 B 相比，单 agent 和 P-C-R 差多少 |

```bash
screen -S smoke
```

进入 screen 后执行：

```bash
cd /root/autodl-tmp/7068 && source .venv-patchloop-client/bin/activate
IDS=sqlfluff__sqlfluff-1625,marshmallow-code__marshmallow-1359,pvlib__pvlib-python-1707,pylint-dev__astroid-1978,pyvista__pyvista-4315,pydicom__pydicom-1694
python -m experiments.lite_batch --out /root/autodl-tmp/lite-smoke-pcr-diff --agent pcr --edit-format diff --workers 4 --instances $IDS 2>&1 | tee /root/autodl-tmp/lite-smoke-pcr-diff.log
python -m experiments.lite_batch --out /root/autodl-tmp/lite-smoke-pcr-sr --agent pcr --edit-format search_replace --workers 4 --instances $IDS 2>&1 | tee /root/autodl-tmp/lite-smoke-pcr-sr.log
python -m experiments.lite_batch --out /root/autodl-tmp/lite-smoke-single-sr --agent single --edit-format search_replace --workers 4 --instances $IDS 2>&1 | tee /root/autodl-tmp/lite-smoke-single-sr.log
```

注意事项：

- 中途断了的话，用**完全相同的参数**加上 `--resume` 就能接着跑。
- 如果日志里出现大量超时，就改成 `--workers 2`，或者把 `.env` 里的 `QWEN_TIMEOUT` 调大。
- 三个配置的 `--workers` 必须相同。

通过标准：三个目录都有 `summary.json`，并且 `tasks_finished` 都是 6。

## 阶段 7：Lite pilot，23 题 × 2 个配置（RQ3 第一批数据）

根据 smoke 的结果选定编辑格式：如果 B 的 `prediction_ready` 不少于 A，就用 `search_replace`。

```bash
screen -S pilot
```

进入 screen 后执行：

```bash
cd /root/autodl-tmp/7068 && source .venv-patchloop-client/bin/activate
python -m experiments.lite_batch --out /root/autodl-tmp/lite-pilot-pcr --agent pcr --edit-format search_replace --workers 4 2>&1 | tee /root/autodl-tmp/lite-pilot-pcr.log
python -m experiments.lite_batch --out /root/autodl-tmp/lite-pilot-single --agent single --edit-format search_replace --workers 4 2>&1 | tee /root/autodl-tmp/lite-pilot-single.log
```

通过标准：两个目录的 `tasks_finished` 都是 23。

## 阶段 8：sb-cli 官方评测

### 8.1 安装和注册（只做一次，装在独立 venv 里）

```bash
/root/autodl-tmp/py311/bin/python -m venv /root/autodl-tmp/venv-sbcli
source /root/autodl-tmp/venv-sbcli/bin/activate
source /etc/network_turbo
pip install sb-cli
sb-cli gen-api-key 你的邮箱
```

从邮箱拿到 key 和验证码后执行：

```bash
echo 'export SWEBENCH_API_KEY=邮件里的key' >> ~/.bashrc && source ~/.bashrc
sb-cli verify-api-key 验证码
```

### 8.2 提交每个目录

每个目录先把 JSONL 转成 JSON 列表，再提交。预测结果为空的目录会被跳过：

```bash
source /root/autodl-tmp/venv-sbcli/bin/activate && source /etc/network_turbo
for run in lite-smoke-pcr-diff lite-smoke-pcr-sr lite-smoke-single-sr lite-pilot-pcr lite-pilot-single; do
  d=/root/autodl-tmp/$run
  [ -s $d/all_preds.jsonl ] || { echo "skip $run: no predictions"; continue; }
  python -c "import json,sys;p=sys.argv[1];json.dump([json.loads(l) for l in open(p) if l.strip()],open(p[:-1],'w'))" $d/all_preds.jsonl
  sb-cli submit swe-bench_lite dev --predictions_path $d/all_preds.json --run_id $run
done
```

评测完成后取回报告：

```bash
sb-cli get-report swe-bench_lite dev lite-pilot-pcr
```

注意事项：

- 参数以 `sb-cli submit --help` 为准。
- 如果 dev 有配额限制，优先提交 pilot 的两个目录。
- sb-cli 只评测提交了预测的题。**没有生成预测的题按"未解决"计入分母，分母始终是该配置跑的总题数。**

通过标准：每个提交都拿到报告，从报告里能读出已解决的 instance 列表。

## 阶段 9：汇总对比与备份

### 9.1 各配置的状态分布

```bash
cd /root/autodl-tmp
for run in lite-smoke-pcr-diff lite-smoke-pcr-sr lite-smoke-single-sr lite-pilot-pcr lite-pilot-single; do
  [ -f $run/summary.json ] && python -c "import json,sys;s=json.load(open(sys.argv[1]));print(sys.argv[2], s['tasks_finished'], s['status_counts'], 'ready=', s['prediction_ready'])" $run/summary.json $run
done
```

### 9.2 pilot 逐题对照（RQ3 配对）

```bash
python - <<'EOF'
import json
def load(d): return {l["instance_id"]: l["status"] for l in map(json.loads, open(f"/root/autodl-tmp/{d}/results.jsonl"))}
a, b = load("lite-pilot-pcr"), load("lite-pilot-single")
for k in sorted(a): print(f"{k:45s} pcr={a[k]:22s} single={b.get(k)}")
EOF
```

拿到 sb-cli 报告后，把逐题的"已解决/未解决"补进这张表，就是 McNemar 检验要用的配对数据。

### 9.3 打包备份

```bash
cd /root/autodl-tmp && tar czf patchloop-results-$(date +%Y%m%d).tar.gz lite-smoke-* lite-pilot-* one-* *.log
```

把打包文件下载到本地，和之前的备份放在一起。

---

## 常见问题

| 现象 | 原因或处理 |
|---|---|
| `has no config.json/*.safetensors` | 权重没下载完整，或者路径写错了 |
| `NVIDIA driver too old` | 装到了 CUDA 13 版本的 torch，按阶段 1.3 重新建 venv |
| preflight 报 `Connection refused` | vLLM 还没启动完成，或者已经退出了，查看 `vllm-7b.log` |
| `QWEN_MODEL_ID_MISMATCH` | `.env` 里的 `QWEN_MODEL` 和启动时用的模型不一致 |
| `--out must be new or empty` | 目录里已有结果：换一个目录，或者用相同参数加 `--resume` |
| 某道题 `checkout` 失败 | 这个仓库没镜像好，重新执行 5.1 |
| 大量超时 | 减小 `--workers`，或者调大 `QWEN_TIMEOUT`（上限 300） |
| `docker: command not found` | AutoDL 本来就没有 Docker，本流程不需要它 |

## 需要发回来的结果

1. 阶段 2 测试输出的最后 3 行。
2. 阶段 3 中 prefix caching 那一行。
3. 阶段 6 三个配置的 `summary.json`。
4. 阶段 7 两个配置的 `summary.json`，以及 9.2 的逐题对照表。
5. 阶段 8 的 sb-cli 报告。
