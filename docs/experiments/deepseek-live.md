# Experiment 01: real DeepSeek API end-to-end repair

## Objective

Validate existing PatchLoop Task 1 Planner -> Task 2 Coder -> Task 3 Docker harness / Reviewer with REAL HTTP requests to official DeepSeek API.

Only count success when a real model response yields a patch which applies to a disposable Git worktree and passes actual Docker tests. This is not a SWE-bench resolution measure.

Current official DeepSeek docs list deepseek-flash and deepseek-v4-pro at https://api.deepseek.com. The experiment explicitly disables thinking mode to obtain concise structured JSON and unified diffs.

## Small deterministic task

Create a real Git repository containing calc.py with divide(a,b) returning a // b. The issue asks for divide(3,2) == 1.5; the test suite also checks divide(8,2) == 4. Tests are real Python unittest cases, run in an isolated network-disabled Docker container. Only calc.py needs modifying.

## GitHub Actions setup

In the repository, use Settings -> Secrets and variables -> Actions -> New repository secret.

Name: DEEPSEEK_API_KEY
Value: your own valid DeepSeek API key.

Never paste a key into code, chat, an issue or a committed environment file. This GitHub connector cannot create or view the user's Actions secrets.

The workflow "LIVE DeepSeek API repair experiment" triggers for pushes to experiment/deepseek-live-smoke, or manual workflow dispatch. If the key is absent, the workflow reports NOT_RUN_MISSING_CREDENTIALS and exits nonzero. It MUST NOT claim that mock completions constituted a real experiment.

The experiment limits the SDK to no automatic retry and at most 10 model requests, with a total completion-token ceiling, at most two patch candidates, no model-directed shell access and a trusted pre-pulled Docker image. It writes a sanitized JSON report and uploads that report as a short-lived CI artifact.

## Run locally

~~~bash
python -m pip install "openai>=1.68,<3" "python-dotenv>=1,<2"
docker pull python:3.11-slim
export DEEPSEEK_API_KEY="your-key-in-your-shell-only"
export DEEPSEEK_MODEL=deepseek-flash
python -m experiments.live_deepseek --report /tmp/deepseek-live-result.json
~~~

The report never contains the key, full model prompt or raw response.

## Interpreting outcomes

- NOT_RUN_MISSING_CREDENTIALS: no API request was sent.
- API_ERROR: genuine provider/network/credential error.
- PIPELINE_ERROR or model_error: Planner/Coder protocol or inference failure.
- reviewer_error: reviewer response missing/invalid.
- retry_exhausted: neither candidate passed validation and Docker tests.
- infrastructure_error: Git/Docker failure, not code repair failure.
- internal_tests_passed: actual DeepSeek completion produced a patch that passed the internal Docker unittest suite. This is not an official SWE-bench result.
- official_swebench_evaluated: always false for this first experiment.

The result captures stages, token counts, patch hashes, test outcomes and original checkout isolation.

## Next stage

After a successful live API smoke, run DeepSeek with official full SWE-bench dev task sqlfluff__sqlfluff-4764 and evaluate the generated candidate using the official SWE-bench Docker harness. SWE-bench Lite test remains held out.

Sources: https://api-docs.deepseek.com/ and docs/qwen-swebench.md
