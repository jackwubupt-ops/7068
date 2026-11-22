"""Execution feedback (RQ2): run the repository's EXISTING tests in a Docker sandbox.

Two uses, both optional (``exec_feedback``):

* ``run_tests(test_path)`` is an agent tool: it runs one tracked test file (or a
  pytest node id) at the BASE commit, so the agent can see which tests exist and
  how they behave before it edits anything.
* ``check_patch(patch, changed_files)`` is a harness step after a candidate applies:
  the tests the agent ran plus the test files named after the changed modules run
  at the base commit and with the patch; tests that passed before and fail after
  are regressions, which go back to the agent (P-C-R: Reviewer -> Coder retry).

Leakage rule: only tests that exist in the repository at the base commit run here.
SWE-bench's hidden ``test_patch`` and FAIL_TO_PASS tests are never used; the
official harness alone decides "resolved".

Sandbox: no network, all capabilities dropped, no new privileges, memory/CPU/pid
limits, a timeout that kills the container, and an argv the model cannot shape
(the test target is validated against tracked files and passed as one argument).
Two environments:

* ``swebench``: the task's prebuilt evaluation image already holds the repository
  at /testbed with its dependencies; the patch is applied inside a throw-away
  container (``--rm``) and pytest runs with the image's interpreter.
* ``mount``: any image named by PATCHLOOP_TEST_IMAGE (for local repositories); a
  temporary worktree (with the patch applied) is mounted read-only at /workspace
  and the container runs as nobody on a read-only root filesystem.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from utils.repo_tools import is_tracked

SWEBENCH_PYTHON = "/opt/miniconda3/envs/testbed/bin/python"
MAX_TARGETS = 4
MAX_TOOL_RUNS = 3
TARGET = re.compile(r"[A-Za-z0-9_./-]{1,200}(::[A-Za-z0-9_.\[\]-]{1,120}){0,3}")
PYTEST_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS)\s+(\S+)", re.M)
UNITTEST_LINE = re.compile(r"^(\w+) \(([\w.]+)\)\s*(?:\n.*?)?\.\.\.\s*(ok|FAIL|ERROR|skipped|expected failure)",
                           re.M)


@dataclass(frozen=True)
class TestEnv:
    image: str
    mode: str                      # "swebench" | "mount"
    python: str = SWEBENCH_PYTHON
    timeout_seconds: int = 300
    memory_mb: int = 4096
    cpus: float = 2.0

    def __post_init__(self):
        if self.mode not in ("swebench", "mount"):
            raise ValueError("mode must be swebench or mount")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}", self.image):
            raise ValueError("invalid image name")


def swebench_image(instance_id: str) -> str:
    return "swebench/sweb.eval.x86_64." + instance_id.replace("__", "_1776_").lower() + ":latest"


def _image_present(image: str) -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", image], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def env_for_swebench(instance_id: str) -> TestEnv | None:
    image = swebench_image(instance_id)
    return TestEnv(image, "swebench") if _image_present(image) else None


def env_for_local() -> TestEnv | None:
    image = os.environ.get("PATCHLOOP_TEST_IMAGE", "").strip()
    if not image or not _image_present(image):
        return None
    return TestEnv(image, "mount", python="python", memory_mb=2048, cpus=1.0)


@dataclass
class RunResult:
    status: str                    # completed | timeout | docker_error
    exit_code: int | None
    outcomes: dict                 # test id -> PASSED | FAILED | ERROR | SKIPPED | XFAIL | XPASS
    tail: str
    seconds: float


def parse_outcomes(text: str) -> dict:
    out = {node: status for status, node in PYTEST_LINE.findall(text)}
    for name, where, status in UNITTEST_LINE.findall(text):
        node = where if where.endswith("." + name) else f"{where}.{name}"
        out[node] = {"ok": "PASSED", "FAIL": "FAILED", "ERROR": "ERROR",
                     "skipped": "SKIPPED", "expected failure": "XFAIL"}[status]
    return out


def _docker_argv(env: TestEnv, name: str, targets: list[str], *, apply: bool,
                 worktree: Path | None) -> list[str]:
    common = ["docker", "run", "-i", "--rm", "--name", name, "--pull", "never", "--network", "none",
              "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "512",
              "--memory", f"{env.memory_mb}m", "--cpus", str(env.cpus),
              "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTEST_ADDOPTS=", "-e", f"APPLY={int(apply)}"]
    pytest = [env.python, "-m", "pytest", "-rA", "-q", "-p", "no:cacheprovider", "--tb=short",
              "--color=no", *targets]
    if env.mode == "swebench":
        script = ('set -e; cd /testbed; if [ "$APPLY" = 1 ]; then git apply --whitespace=nowarn -; '
                  'else cat >/dev/null; fi; set +e; exec "$@"')
        return [*common, env.image, "bash", "-c", script, "patchloop", *pytest]
    script = ('cat >/dev/null; if "$0" -c "import pytest" 2>/dev/null; then exec "$0" -m pytest -rA -q '
              '-p no:cacheprovider --tb=short --color=no "$@"; else exec "$0" -m unittest -v "$@"; fi')
    return [*common, "--read-only", "--user", "65534:65534", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
            "-e", "HOME=/tmp", "-e", "PYTHONPATH=/workspace", "--workdir", "/workspace",
            "--mount", f"type=bind,src={worktree},dst=/workspace,readonly",
            env.image, "sh", "-c", script, env.python, *targets]


def docker_run(env: TestEnv, checkout: Path, base_commit: str, patch: str | None,
               targets: list[str]) -> RunResult:
    """Run the targets once, at the base commit (patch None) or with the patch applied."""
    start = time.monotonic()
    name = "patchloop-test-" + uuid.uuid4().hex[:12]

    def execute(argv, data: bytes) -> RunResult:
        try:
            with tempfile.TemporaryFile() as output:
                proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT)
                try:
                    proc.stdin.write(data)
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    code = proc.wait(timeout=env.timeout_seconds)
                    status = "completed"
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30, check=False)
                    code, status = None, "timeout"
                output.seek(0)
                text = output.read().decode("utf-8", "replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RunResult("docker_error", None, {}, str(exc)[:1000], round(time.monotonic() - start, 2))
        lowered = text.lower()
        if status == "completed" and code not in (0, 1, 5) and not parse_outcomes(text) and (
                "error response from daemon" in lowered or "cannot connect to the docker" in lowered
                or "error: patch failed" in lowered or "unable to find image" in lowered):
            status = "docker_error"
        return RunResult(status, code, parse_outcomes(text), text[-6000:], round(time.monotonic() - start, 2))

    data = (patch or "").encode("utf-8")
    if not shutil.which("docker"):
        return RunResult("docker_error", None, {}, "Docker CLI unavailable", 0.0)
    if env.mode == "swebench":
        return execute(_docker_argv(env, name, targets, apply=bool(patch), worktree=None), data)
    from .workspace import _run_git, isolated_worktree
    with isolated_worktree(Path(checkout), base_commit) as worktree:
        if patch:
            done = _run_git(worktree, "apply", "--whitespace=nowarn", "-", data=data)
            if done.returncode:
                return RunResult("docker_error", None, {}, "git apply failed: "
                                 + done.stderr.decode("utf-8", "replace")[:800], 0.0)
        return execute(_docker_argv(env, name, targets, apply=False, worktree=worktree.resolve()), b"")


def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.endswith(".py") and name != "__init__.py" and (
        name.startswith("test_") or name.endswith("_test.py")
        or any(d in "/" + path for d in ("/tests/", "/test/", "/testing/")))


class TestTool:
    """Per-task test execution shared by the run_tests tool and the post-apply check."""

    def __init__(self, env: TestEnv | None, checkout: str | Path, base_commit: str, *, runner=None):
        self.env, self.checkout, self.base = env, Path(checkout), base_commit
        self.runner = runner or docker_run
        self.requested: list[str] = []
        self.base_cache: dict[str, RunResult] = {}
        self.records: list[dict] = []
        self.tool_runs = 0

    @property
    def available(self) -> bool:
        return self.env is not None

    def validate_target(self, target) -> str:
        if not isinstance(target, str) or not TARGET.fullmatch(target.strip()):
            raise ValueError("test_path must be a tracked test file, optionally with ::TestClass::test_name")
        target = target.strip()
        path = target.split("::", 1)[0]
        if path.startswith(("/", "-")) or ".." in path.split("/"):
            raise ValueError("test_path must be a relative path inside the repository")
        if not _is_test_file(path) or not is_tracked(self.checkout, path):
            raise ValueError(f"{path} is not a tracked test file at the base commit")
        return target

    def _base(self, targets: list[str]) -> RunResult:
        key = "\n".join(targets)
        if key not in self.base_cache:
            self.base_cache[key] = self.runner(self.env, self.checkout, self.base, None, targets)
        return self.base_cache[key]

    # ---- agent tool -------------------------------------------------------------
    def run_tool(self, repo_root=None, *, test_path=None) -> dict:
        if not self.available:
            return {"ok": False, "error": "Test execution is unavailable here (no Docker test image); "
                                          "continue without running tests"}
        try:
            target = self.validate_target(test_path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if self.tool_runs >= MAX_TOOL_RUNS:
            return {"ok": False, "error": f"run_tests may be used at most {MAX_TOOL_RUNS} times per task"}
        self.tool_runs += 1
        if target not in self.requested:
            self.requested.append(target)
        result = self._base([target])
        summary = _summary(result)
        self.records.append({"kind": "tool", "target": target, **summary})
        return {"ok": result.status == "completed", "test_path": target, "at": "base commit (before any edit)",
                **summary, "output_tail": result.tail[-1500:]}

    # ---- harness check after a candidate applies -------------------------------
    def select_targets(self, changed_files: list[str]) -> list[str]:
        targets = list(self.requested)
        tracked = _tracked_test_files(self.checkout)
        for changed in changed_files:
            stem = changed.rsplit("/", 1)[-1].removesuffix(".py")
            if not stem or stem.startswith("test_") or stem == "__init__":
                continue
            names = {p: p.rsplit("/", 1)[-1] for p in tracked}
            exact = sorted(p for p, n in names.items() if n in (f"test_{stem}.py", f"{stem}_test.py"))
            # e.g. sqlfluff: src/sqlfluff/rules/L031.py -> test/rules/std_L031_test.py
            near = sorted(p for p, n in names.items() if p not in exact and len(stem) >= 4
                          and re.search(rf"(^|[_\-]){re.escape(stem)}([_\-.]|$)", n.removesuffix(".py") + "."))
            targets += [m for m in (exact + near)[:2] if m not in targets]
        return targets[:MAX_TARGETS]

    def check_patch(self, patch: str, changed_files: list[str]) -> dict:
        if not self.available:
            return {"status": "unavailable", "targets": []}
        targets = self.select_targets(changed_files)
        if not targets:
            record = {"status": "no_tests", "targets": []}
            self.records.append({"kind": "check", **record})
            return record
        before = self._base(targets)
        after = self.runner(self.env, self.checkout, self.base, patch, targets)
        record = {"targets": targets, "base": _summary(before), "patched": _summary(after),
                  "seconds": round(before.seconds + after.seconds, 2)}
        if before.status != "completed" or after.status == "docker_error":
            record["status"] = "infra_error"      # cannot judge: never blocks a candidate
        elif not before.outcomes:
            record["status"] = "no_baseline"      # nothing ran at the base commit: cannot judge
        elif after.status == "timeout":
            record.update(status="regressions", regressions=["(test run timed out with the patch)"])
        else:
            passed_before = {t for t, s in before.outcomes.items() if s == "PASSED"}
            regressions = sorted(t for t in passed_before if after.outcomes.get(t) != "PASSED")
            if passed_before and not after.outcomes:
                regressions = ["(tests could not be collected with the patch: import or syntax error)"]
            fixed = sorted(t for t, s in after.outcomes.items()
                           if s == "PASSED" and before.outcomes.get(t) in ("FAILED", "ERROR"))
            record.update(status="regressions" if regressions else "passed",
                          regressions=regressions[:20], newly_passing=fixed[:20])
        record["log_tail"] = after.tail[-3000:]
        self.records.append({"kind": "check", **{k: v for k, v in record.items() if k != "log_tail"}})
        return record


def _summary(result: RunResult) -> dict:
    counts: dict = {}
    for status in result.outcomes.values():
        counts[status] = counts.get(status, 0) + 1
    failing = [t for t, s in result.outcomes.items() if s in ("FAILED", "ERROR")]
    return {"run_status": result.status, "exit_code": result.exit_code, "counts": counts,
            "failing": failing[:10], "seconds": result.seconds}


def _tracked_test_files(checkout: Path) -> list[str]:
    proc = subprocess.run(["git", "-C", str(checkout), "ls-files", "-z", "--", "*.py"],
                          capture_output=True, timeout=20)
    if proc.returncode:
        return []
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p and _is_test_file(p)]


def regression_message(check: dict) -> str:
    """Feedback text for the agent when its applied candidate breaks existing tests."""
    return ("The edit applied, but existing repository tests that passed before your change now fail "
            f"(tests run: {', '.join(check.get('targets', []))}). Regressions: "
            + ", ".join(check.get("regressions", [])[:10])
            + ".\nTest output tail:\n" + str(check.get("log_tail", ""))[-1500:])
