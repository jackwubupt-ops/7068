# Task 2: Coder and controlled Git patch application

## Integration

This is an incremental upgrade of the existing CodeNexus and Task 1 Demo. No original generation or Flask routes are removed.

Task 1: pipeline_agent.run_localization returns suspected_files, bounded read_file evidence, a root-cause hypothesis and repair plan.

Task 2: patchloop_task2.runner.run_repair takes the Task 1 output, generates a unified diff with a Coder, then validates and applies it to a disposable Git worktree created at the exact base commit.

The target source repo is not modified. Applied patches can be exported with --out-patch. Applied does NOT mean the issue has been resolved: Task 2 does not run tests, the Reviewer, Docker, or SWE-bench.

## Command-line example (PowerShell)

~~~powershell
git -C C:\path\target rev-parse HEAD
.\.venv\Scripts\python.exe repair.py --repo C:\path\target --base-commit FULL_SHA --issue-file issue.txt --out output.json --out-patch C:\temp\candidate.patch
~~~

Live Planner and Coder use the shared Demo configuration OPENAI_MODEL, OPENAI_BASE_URL and OPENAI_API_KEY. Never commit .env.

## Public interface

- patchloop_task2.coder.generate_patch(issue, plan, completion=None): generates a Git diff. Optional completion(messages) injects a scripted response in tests.
- patchloop_task2.runner.apply_repair_plan(issue, plan, coder_completion=None, export_path=None): generates and checks a candidate.
- patchloop_task2.runner.run_repair(issue, repo_root, base_commit, planner_completion=None, coder_completion=None, export_path=None): Task 1 -> Task 2.

Task 1 uses suspected_files, not the standalone Task 2 prototype's candidates field. The integration consumes only successful read_file evidence associated with suspected_files.

Possible status values: generation_failed, patch_invalid, apply_failed, workspace_failed, applied. The result carries changed_files, patch hash, error details, execution_verified=false and test_status=not_run where applicable.

## Safety

Only text diffs modifying already tracked regular files mentioned in suspected_files are supported. Reject renames, new/deleted files, binary patches, symlinks, submodules, unsafe paths and oversized patches. Apply against a detached temporary worktree via git apply --check and git apply --index. No model-provided shell commands are executed. This is not a sandbox against arbitrary malicious repository hooks or concurrent filesystem attacks.

## Verification

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe demo_localization.py --offline
~~~

Task 2's isolated local suite passed 7/7 with temporary repositories and scripted model outputs. Full repository regression, live Planner/Coder, Docker execution and SWE-bench evaluation remain unverified.

## Next task

Task 3 should add Docker-based repository tests, structured failure diagnosis by Reviewer, retries and JSONL tracing. Official SWE-bench evaluation is separate from internal tests.
