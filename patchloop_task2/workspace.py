"""Apply one candidate patch in a temporary worktree rooted at a fixed commit.

No generated code is executed here; no arbitrary shell is available to models.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from contextlib import contextmanager
import ast
import hashlib
import os
import re
import subprocess
import tempfile
from typing import Iterator

from .validator import PatchValidationError, validate_patch


class WorkspaceError(RuntimeError):
    pass


@dataclass
class ApplyResult:
    status: str
    base_commit: str
    changed_files: list[str]
    patch_sha256: str
    hunk_count: int = 0
    exported_patch: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _run_git(repo: Path, *args: str, data: bytes | None = None, timeout: int = 25) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    return subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", "-C", str(repo), *args],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, check=False, env=env,
    )


def _good_result(result: subprocess.CompletedProcess, label: str) -> bytes:
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()[:1200]
        raise WorkspaceError(f"{label} failed: {message}")
    return result.stdout


def resolve_base(repo: Path, base_commit: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", base_commit):
        raise WorkspaceError("base_commit must be a full 40- or 64-character SHA")
    top = _good_result(_run_git(repo, "rev-parse", "--show-toplevel"), "git root").decode().strip()
    if Path(top).resolve() != repo.resolve():
        raise WorkspaceError("repo path must be the top-level working tree")
    actual = _good_result(_run_git(repo, "rev-parse", "--verify", f"{base_commit}^{{commit}}"), "base_commit").decode().strip()
    if actual.lower() != base_commit.lower():
        raise WorkspaceError("base_commit mismatch")
    return actual


@contextmanager
def isolated_worktree(repo: Path, base_commit: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="patchloop-task2-") as directory:
        worktree = Path(directory) / "checkout"
        _good_result(_run_git(repo, "worktree", "add", "--detach", "--", str(worktree), base_commit, timeout=60), "worktree add")
        try:
            head = _good_result(_run_git(worktree, "rev-parse", "HEAD"), "worktree HEAD").decode().strip()
            if head != base_commit:
                raise WorkspaceError("isolated worktree at wrong commit")
            yield worktree
        finally:
            rm = _run_git(repo, "worktree", "remove", "--force", "--", str(worktree), timeout=60)
            if rm.returncode:
                raise WorkspaceError("worktree cleanup failed: " + rm.stderr.decode(errors="replace")[:500])


def _regular_tracked_paths(worktree: Path) -> set[str]:
    raw = _good_result(_run_git(worktree, "ls-files", "--stage", "-z"), "ls-files")
    allowed: set[str] = set()
    for row in raw.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0]
        if mode in {b"100644", b"100755"}:
            allowed.add(name.decode("utf-8", "surrogateescape"))
    return allowed


def _parses(source: bytes) -> str | None:
    """None if the Python source parses, else the SyntaxError text (ast only)."""
    try:
        ast.parse(source)
        return None
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    except (ValueError, RecursionError, MemoryError) as exc:
        return str(exc)[:200]


def _syntax_regressions(worktree: Path, base_commit: str, changed: list[str]) -> list[str]:
    """Changed .py files that parsed at the base commit but no longer parse."""
    broken = []
    for path in changed:
        if not path.endswith(".py"):
            continue
        before = _run_git(worktree, "show", f"{base_commit}:{path}")
        if before.returncode or _parses(before.stdout) is not None:
            continue  # new file, or already unparsable at base: not this edit's fault
        try:
            after = (worktree / path).read_bytes()
        except OSError:
            continue
        problem = _parses(after)
        if problem:
            broken.append(f"{path} {problem}")
    return broken


def apply_candidate(
    repo_path: str | Path, base_commit: str, patch: str,
    export_path: str | Path | None = None, *, allowed_paths: set[str] | None = None,
) -> ApplyResult:
    repo = Path(repo_path).expanduser().resolve()
    digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    result = ApplyResult(status="workspace_failed", base_commit=base_commit, changed_files=[], patch_sha256=digest)
    try:
        sha = resolve_base(repo, base_commit)
        result.base_commit = sha
        with isolated_worktree(repo, sha) as wt:
            try:
                tracked = _regular_tracked_paths(wt)
                if allowed_paths is not None:
                    tracked &= allowed_paths
                info = validate_patch(patch, tracked)
            except PatchValidationError as e:
                result.status = "patch_invalid"
                result.error_code = e.code
                result.error_message = str(e)
                return result
            result.hunk_count = info.hunk_count
            result.changed_files = list(info.paths)
            checked = _run_git(wt, "apply", "--check", "--index", "--whitespace=nowarn", "-", data=patch.encode())
            if checked.returncode:
                result.status = "apply_failed"
                result.error_code = "does_not_apply"
                result.error_message = checked.stderr.decode("utf-8", "replace").strip()[:1200]
                return result
            applied = _run_git(wt, "apply", "--index", "--whitespace=nowarn", "-", data=patch.encode())
            if applied.returncode:
                result.status = "apply_failed"
                result.error_code = "apply_race_or_error"
                result.error_message = applied.stderr.decode("utf-8", "replace").strip()[:1200]
                return result
            exported = _good_result(_run_git(wt, "diff", "--cached", "--no-ext-diff", "--binary", "--"), "export patch")
            if not exported:
                result.status = "apply_failed"
                result.error_code = "no_effect"
                result.error_message = "Patch had no resulting staged changes"
                return result
            broken = _syntax_regressions(wt, sha, result.changed_files)
            if broken:
                # Harness check, no code executed: an edit that turns a parsable
                # Python file into an unparsable one is a failed attempt.
                result.status = "syntax_invalid"
                result.error_code = "python_syntax_error"
                result.error_message = "; ".join(broken)[:1200]
                return result
            if export_path is not None:
                target = Path(export_path).expanduser().resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(exported)
                result.exported_patch = str(target)
            result.status = "applied"
            return result
    except (WorkspaceError, OSError, subprocess.TimeoutExpired) as e:
        result.status = "workspace_failed"
        result.error_code = "workspace_error"
        result.error_message = str(e)[:1200]
        return result
