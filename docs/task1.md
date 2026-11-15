# PatchLoop Task 1

## 架构与差异

原项目为 Python 3.11 + Flask + OpenAI SDK，以普通函数和字符串实现 Agent 顺序调用。
原流程：需求优化 → 算法分类 → 单函数代码生成 → 静态指标 → compile 语法检查和 LLM 评分。
原 Test Agent 不执行测试，不能视为 execution-grounded repair。

| 模块 | 原实现 | 本次变化 |
| --- | --- | --- |
| Prompt Agent | 文案优化 | 保留原接口，新增 plan_repair 及计划校验 |
| Code Agent | 生成独立 Python 代码 | 保留；Task 2 再扩展仓库 Coder |
| Test Agent | compile、模型评分及改写 | 保留，未提前实现 Patch 执行 |
| Repository Tools | 无 | utils/repo_tools.py：受限搜索、读取、Git 校验 |
| LLM Interface | config.py 客户端和模型 | 直接复用，不迁移模型后端 |
| Pipeline | run_pipeline | 新增 run_localization 返回计划字典 |
| Web | / | 保留并增加 /localize 及首页链接 |

新增 localize.py、demo_localization.py、tests/test_task1.py 和本说明。
没有新依赖，没有删除旧代码，没有初始化或重置当前目录的 Git 仓库。

## 工具接口和边界

- search_repo(repo_root, query, *, max_results=20, context_lines=3)：字面搜索，优先 rg，无 rg 时 Python 回退。返回 ok/matches/truncated/backend；每条包含相对路径、行号、片段及 Python 函数名。
- read_file(repo_root, relative_path, *, start_line=1, end_line=None)：只读，返回 ok/file_path/lines/truncated；每行有 line_number/text。
- 错误返回 ok=false/error；非法文件、路径、类型、范围、二进制和非 UTF-8 均处理。
- 排除 .git、虚拟环境、构建缓存、.env、日志、密钥后缀；大小写变体也排除。拒绝绝对路径、UNC、盘符、路径穿越、符号链接和 Windows reparse point/junction。
- 单文件最多 256 KiB；读取最多 200 行、20000 字符；搜索最多 50 项、每侧 5 行上下文、片段合计 20000 字符。
- 搜索预算为 2000 文件/2000 目录、8 MiB、10 秒。超限标记 truncated，未找到不表示整个大型仓库无匹配。
- 底层单目录枚举仍依赖操作系统。本工具不是并发恶意文件系统沙箱；要求分析期间仓库不被其他进程修改，未提供 TOCTOU 隔离。

## Planner

plan_repair(issue, repo_root, base_commit, *, completion=None, max_steps=10)
沿用 get_client()/OPENAI_MODEL。completion(messages) 是离线测试注入点。
JSON 动作：search_repo/read_file/final；最多 15 轮，单轮响应最多 20000 字符，真实请求 max_tokens=2500。
非法 JSON/参数/计划反馈纠错，占用同一预算。工具参数白名单校验，无 Shell 或执行工具。
仓库及 Issue 作为不可信分析材料，不能授权执行命令。

仓库必须为本地 Git 根目录；Base Commit 是 7–40 位 SHA，HEAD 必须匹配且工作区干净。
不自动 clone/checkout/reset；Git 校验禁用 core.fsmonitor。Planner 仅保留 Git 跟踪文件证据，
拒绝被忽略的本地文件；结束时再次校验仓库。
文件跟踪校验使用 Git 字面路径，文件名中的方括号不按通配符解释。
本阶段读取工作区，而非不可变 Git Blob；假定用户拥有的静态仓库未使用
assume-unchanged/skip-worktree 隐藏工作区变动，不宣称对恶意索引提供快照证明。

输出 issue_summary、suspected_files、root_cause_hypothesis、planned_changes、limitations、
repo_root、base_commit、evidence、execution_verified=false。
候选 relevant_lines 是含首尾的 [start,end]，必须完整落在 evidence_ids 指向的真实读取结果中。
证据由程序添加，模型不能覆盖。没有候选时必须说明限制。
结构校验不能证明根因语义正确或修复有效，输出仍是待执行验证的假设。

## 使用与完整演示

先在 .env 配置实际可用的 API Key、OPENAI_BASE_URL、OPENAI_MODEL。
原启动方式不变；网页定位入口为 http://127.0.0.1:5000/localize 。仅供本机使用，不要公开本地文件读取接口。

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --debug
.\.venv\Scripts\python.exe localize.py --repo C:\path\repo --base-commit YOUR_SHA --issue-file issue.txt
.\.venv\Scripts\python.exe demo_localization.py --offline
.\.venv\Scripts\python.exe demo_localization.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

demo_localization.py 临时创建并提交 calc.py：

```python
def divide(a, b):
    return a // b
```

Issue 为 divide(3,2) 返回 1，应返回 1.5。真实搜索产生 E1，读取产生 E2；
候选 calc.py:1–2，假设为整除丢失小数，计划改用真除并在 Task 2 添加测试。
没有执行或应用修复，退出自动清理临时仓库。
--offline 使用预设模型动作，证明工具、协议和集成，不代表模型自主定位质量。
省略 --offline 才调用真实模型。

## 测试和限制

测试覆盖正常搜索/函数定位、指定行读取、非法路径、大小写排除、junction、Unicode 行号、
大小/数量限制、无 rg 回退、超时、SHA/脏工作区、fsmonitor 禁用、忽略文件证据、
JSON 纠错、伪造行号、无证据计划、预算和旧网页生成（Mock LLM）。
Windows 未获创建符号链接权限时该测试 skip，junction 测试单独执行。
本次没有配置 API Key，未运行真实 LLM 定位；未提供 SWE-bench 开发数据和仓库，
未运行 SWE-bench，也没有使用 Gold Patch。离线结果不能代替这些评估。

Task 2 直接消费 run_localization 的字典，根据 repo_root/base_commit 重建受控工作区，
让 Coder 消费计划/evidence，再实现 Patch、执行反馈、Reviewer 和重试。
本次未把计划送入只会生成单函数的旧 generate_code。

旧 app.py 全局 stdout 重定向、evaluator 递归误报和日志追加格式问题未扩大范围修改。
新 Planner 不依赖这些机制。

最终实测：16 项测试，15 项通过、1 项因 Windows 符号链接创建权限不足跳过；
Windows junction 逃逸测试通过。pip check 无依赖冲突，修改文件 compileall 通过。
真实 HTTP 检查：独立预览端口 5001 的 / 和 /localize 均为 200。
离线演示实际输出保存在 task1-demo.json，临时 repo_root 仅为演示记录，运行结束即清理。
