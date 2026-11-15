# Task 3: Execution-Grounded Reviewer Loop

## Goal and scope

Task 3 extends existing CodeNexus and PatchLoop Tasks 1/2 without replacing them.

1. Planner (Task 1) localizes an Issue, using real repository search and numbered file evidence.
2. Coder (Task 2) generates a complete Git diff; the Harness validates and applies it in a detached temporary worktree at Base Commit.
3. Task 3 runs operator-selected tests in a constrained Docker container with no network.
4. If tests fail, Reviewer sees patch, structured status and a bounded test log. The Coder receives feedback and generates a COMPLETE replacement diff against the SAME Base Commit.
5. At most three candidates are tried. A patch is exported only if configured internal tests pass.

Original CodeNexus Flask routes, localize.py, repair.py and code generation remain available.

## Running Task 3

Requirements: Python 3.11, Git, Docker Engine, a trusted pre-pulled Docker image with the repository's test dependencies, and API settings in local .env.

Prepare a clean local target repository checkout at its Base Commit. Then:

~~~powershell
docker pull python:3.11-slim
.\.venv\Scripts\python.exe repair_loop.py --repo C:\target_repo --base-commit FULL_SHA --issue-file issue.txt --image python:3.11-slim --test-runner unittest --max-candidates 3 --out C:\logs\result.json --out-patch C:\logs\candidate.patch --trace C:\logs\trace.jsonl
~~~

A plain Python image is suitable only for a project with no external test dependencies. For SWE-bench, the trusted operator must prepare the correct repository-specific environment and test commands. This implementation is not a replacement for the official evaluator.

A reproducible real Docker smoke needs no LLM API calls:

~~~powershell
docker pull python:3.11-slim
.\.venv\Scripts\python.exe -m examples.task3_docker_smoke
~~~

The smoke constructs a fresh Git repository and Python unittest file, applies a deliberately incorrect patch, observes an actual Docker test failure, feeds scripted Reviewer diagnosis to the Coder, applies the replacement patch from the base commit, and observes tests pass. The source repository remains unmodified.

## Security boundaries

- Model output cannot select Docker flags, commands, images, mount paths or run a shell.
- Coder patches can modify only Planner-suspected tracked regular files; modifications are restricted in size and reject path traversal, renames, additions, deletions and binary content.
- Docker runs with network=none, read-only filesystem, unprivileged user, dropped caps, no-new-privileges, limits on CPU, memory and process count, explicit timeout, ephemeral tmpfs, and read-only bind mount of the disposable checkout.
- Test code is never run on the host. The Docker socket is not mounted in the container.
- Real test failures may be reviewed; Docker failures and timeouts stop the loop as infrastructure errors rather than being counted as product-code failures.
- Every candidate is checked out from the identical base commit, never incremental changes against a previous failed candidate.
- Do not store output or trace files in the target repository. JSONL traces may include sensitive output snippets; protect them and do not commit.
- This is an isolation layer, not a proof of safety against Docker daemon vulnerabilities, malicious container images or a hostile concurrent filesystem.

## API and output contracts

- DockerTestSpec is trusted operator configuration, with image, fixed argv tuple, timeout, memory, CPU and pids limits.
- DockerTestRunner.run(worktree, spec) returns passed, failed, timeout or docker_error with exit code, bounded log tail and timing.
- review_failure(issue, plan, failed_patch, failure, completion=...) returns strict JSON fields: failure_type, diagnosis and suggested_fix.
- run_execution_loop(issue, repo_root, base_commit, spec, ...) returns Task 1 plan and Task 3 repair history.
- repair.status is internal_tests_passed, retry_exhausted, infrastructure_error, model_error or reviewer_error. An internal pass is NOT an official SWE-bench resolution result.
- official_evaluated is always false in Task 3; the official evaluator and QLoRA are future work.

## Verification

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe demo_localization.py --offline
docker pull python:3.11-slim
.\.venv\Scripts\python.exe -m examples.task3_docker_smoke
~~~

CI runs Linux/Windows unit regressions and an Ubuntu Docker execution smoke with scripted LLM responses. The live-model, official SWE-bench and QLoRA experiments are not verified by these tests.

## Next

Introduce a SWE-bench-compatible evaluator adapter, optional LangGraph orchestration and budget accounting, then run matched Qwen Base / QLoRA and single/multi-role experiments with leakage controls.
