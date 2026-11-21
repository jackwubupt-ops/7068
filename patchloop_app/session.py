"""One interactive PatchLoop repair session (used by the web app).

A maintainer gives an issue and a repository at a commit. The session:

1. checks the request (clarification rule): a too-short issue, or one whose text
   matches nothing in the repository, stops with questions instead of guessing;
2. runs the SAME agent code as the batch experiments (P-C-R or single agent,
   retrieval, edit format) through ``experiments.qwen_small_dev.run_qwen_dev``;
3. streams every model step as an event: the tool the agent chose, what the tool
   returned, Planner plans, Coder edits, apply results, Reviewer diagnoses;
4. ends in one of: awaiting_confirmation (a Git-applicable patch the user must
   accept or reject), needs_clarification (could not locate / edit the code),
   failed, cancelled;
5. on accept: exports the patch and, for a local repository, commits it on a NEW
   branch through a temporary worktree (the user's working tree is untouched);
6. follow-ups start a new linked session with the maintainer's extra guidance
   appended to the issue.

Nothing here reads benchmark gold data. Budgets (calls, tokens, steps,
submissions) are the ones enforced by the agent code itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

STATUSES = ("queued", "checking", "running", "awaiting_confirmation", "needs_clarification",
            "accepted", "rejected", "failed", "cancelled")
MIN_ISSUE_WORDS = 8
MAX_FOLLOWUPS = 5


class Cancelled(RuntimeError):
    pass


@dataclass
class Request:
    issue: str
    source: str                      # "swebench" | "local"
    instance_id: str | None = None   # source == "swebench"
    repo_path: str | None = None     # source == "local"
    commit: str = "HEAD"
    agent: str = "pcr"
    edit_format: str = "search_replace"
    retrieval_k: int = 10
    skip_clarification: bool = False
    backend: str = "qwen"            # "qwen" (local vLLM) | "deepseek" (hosted API)
    exec_feedback: bool = False      # run existing repository tests in Docker (RQ2)


@dataclass
class Session:
    id: str
    request: Request
    parent: str | None = None
    round: int = 1
    status: str = "queued"
    events: list[dict] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)
    patch: str = ""
    created: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, kind: str, title: str, detail: str = "", stage: str = "") -> None:
        with self.lock:
            self.events.append({"i": len(self.events), "t": round(time.time() - self.created, 1),
                                "kind": kind, "stage": stage, "title": title[:300],
                                "detail": detail[:6000]})

    def view(self, since: int = 0) -> dict:
        with self.lock:
            return {"id": self.id, "parent": self.parent, "round": self.round,
                    "status": self.status, "request": self.request.__dict__,
                    "events": self.events[since:], "event_count": len(self.events),
                    "questions": self.questions, "patch": self.patch,
                    "result": {k: self.result.get(k) for k in ("model", 
                        "status", "failed_stage", "error", "attempt_count", "suspected_files",
                        "retrieval_candidates", "prompt_tokens", "completion_tokens",
                        "duration_seconds", "patch_status", "stop_reason", "branch",
                        "patch_file")}}


# --------------------------------------------------------------------------- events

def _short(value, limit=300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " …"


def _json(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        stripped = (text or "").strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            try:
                return json.loads("\n".join(lines[1:-1]))
            except ValueError:
                return None
    return None


def describe_feedback(content: str) -> tuple[str, str, str] | None:
    """(kind, title, detail) for the harness message the model is answering."""
    for prefix in ("Tool evidence (untrusted): ", "Tool result (untrusted): "):
        if content.startswith(prefix):
            data = _json(content[len(prefix):]) or {}
            name = data.get("tool") or data.get("action")
            result = data.get("result") or {}
            if not result.get("ok", False):
                return "tool", f"{name} failed", _short(result.get("error", result))
            if name == "search_repo":
                files = sorted({m.get("file_path") for m in result.get("matches", [])})
                return "tool", f"search_repo -> {len(result.get('matches', []))} matches", ", ".join(files[:8])
            if name == "read_file":
                lines = result.get("lines") or []
                span = f"{lines[0]['line_number']}-{lines[-1]['line_number']}" if lines else "empty"
                return "tool", f"read_file {result.get('file_path')} lines {span}", ""
            if name == "run_tests":
                counts = result.get("counts") or {}
                return ("tool", f"run_tests {result.get('test_path')} -> "
                        + (", ".join(f"{v} {k.lower()}" for k, v in sorted(counts.items())) or "no results"),
                        ", ".join(result.get("failing", [])[:8]))
            if name == "find_definition":
                defs = result.get("definitions", [])
                return ("tool", f"find_definition -> {len(defs)} definitions",
                        ", ".join(f"{d.get('qualified_name')} ({d.get('file_path')}:{d.get('start_line')})"
                                  for d in defs[:8]))
            if name == "list_directory":
                entries = result.get("entries", [])
                return ("tool", f"list_directory {result.get('directory')} -> {len(entries)} entries",
                        ", ".join(e.get("name", "") for e in entries[:20]))
            return "tool", f"{name} result", _short(result)
    for prefix, kind in (("Protocol validation error:", "warning"), ("Protocol error:", "warning"),
                         ("Repeated action:", "warning"), ("Submission rejected", "warning"),
                         ("Your previous reply hit the output token limit", "warning"),
                         ("Now write the fix", "info"), ("STOP SEARCHING", "info"),
                         ("Previous edit failed", "info"), ("Previous patch failed", "info")):
        if content.startswith(prefix):
            return kind, prefix.rstrip(":"), _short(content, 600)
    return None


def describe_output(stage: str, raw: str) -> tuple[str, str, str]:
    """(kind, title, detail) for one model reply."""
    if stage in ("planner", "agent"):
        data = _json(raw)
        if isinstance(data, dict):
            action = data.get("action")
            args = data.get("arguments") or {}
            if action == "search_repo":
                return "decision", f"{stage}: search the repository for “{args.get('query')}”", ""
            if action == "read_file":
                span = f" lines {args.get('start_line', 1)}-{args.get('end_line', 'end')}"
                return "decision", f"{stage}: read {args.get('relative_path')}{span}", ""
            if action == "find_definition":
                return "decision", f"{stage}: find where “{args.get('name')}” is defined", ""
            if action == "run_tests":
                return "decision", f"{stage}: run the existing tests in {args.get('test_path')}", ""
            if action == "list_directory":
                return "decision", f"{stage}: list the directory {args.get('relative_path', '.')}", ""
            if action == "final":
                plan = data.get("plan") or {}
                files = [f.get("file_path") for f in plan.get("suspected_files", []) if isinstance(f, dict)]
                return ("decision", f"planner: final plan, candidate files {files or 'none'}",
                        _short({"root_cause_hypothesis": plan.get("root_cause_hypothesis"),
                                "planned_changes": plan.get("planned_changes")}, 1500))
            if action == "edit":
                return "decision", "agent: done investigating, will write the edit", ""
        if "<<<<<<< SEARCH" in raw or "diff --git a/" in raw:
            return "edit", f"{stage}: submitted an edit", _short(raw, 4000)
        return "warning", f"{stage}: reply did not follow the protocol", _short(raw, 400)
    if stage == "coder":
        return "edit", "coder: proposed edit", _short(raw, 4000)
    if stage == "reviewer":
        data = _json(raw) or {}
        return ("review", f"reviewer: {data.get('failure_type', 'diagnosis')}",
                _short({"diagnosis": data.get("diagnosis"), "suggested_fix": data.get("suggested_fix")}, 1500))
    return "info", f"{stage} reply", _short(raw, 200)


class TracingBackend:
    """Wraps the real model backend: emits an event per step, honours cancel."""

    def __init__(self, inner, session: Session):
        self._inner = inner
        self._session = session

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def complete(self, stage, messages):
        if self._session.cancel.is_set():
            raise Cancelled("USER_CANCELLED")
        if stage == "preflight":
            return self._inner.complete(stage, messages)
        if messages and messages[-1].get("role") == "user":
            fb = describe_feedback(str(messages[-1].get("content", "")))
            if fb:
                self._session.emit(fb[0], fb[1], fb[2], stage)
        self._session.emit("thinking", f"{stage}: calling the model", "", stage)
        try:
            raw = self._inner.complete(stage, messages)
        except RuntimeError as exc:
            self._session.emit("warning", f"{stage}: {str(exc)[:120]}", "", stage)
            raise
        kind, title, detail = describe_output(stage, raw)
        self._session.emit(kind, title, detail, stage)
        if self._session.cancel.is_set():
            raise Cancelled("USER_CANCELLED")
        return raw

    def callback(self, stage):
        return lambda messages: self.complete(stage, messages)


# --------------------------------------------------------------------------- rules

def clarification_questions(issue: str, candidates: list[dict]) -> list[str]:
    """Stop-and-ask rule BEFORE spending model calls on an under-specified request."""
    questions = []
    if len(re.findall(r"\w+", issue)) < MIN_ISSUE_WORDS:
        questions.append("The issue is very short. What exactly goes wrong, and what did you expect instead?")
    hinted = [c for c in candidates if any(w != "keyword match" for w in c.get("why", []))]
    if not candidates or (not hinted and candidates[0]["score"] < 0.35):
        questions.append("I could not match the issue to specific code. Can you name a file, class or "
                         "function, or paste the error message / traceback?")
    return questions


def outcome_questions(result: dict) -> list[str]:
    status = result.get("status")
    if status in ("no_candidate_files", "no_submission"):
        return ["I could not pin down which code to change. Which file or function is responsible?",
                "Is there an error message, traceback or minimal example you can add?"]
    if status == "patch_failed":
        return ["My edits did not apply cleanly. Should I focus on a specific function or file?",
                "Do you want me to try again with the other agent mode?"]
    return []


# --------------------------------------------------------------------------- workspace

def _git(*args: str, cwd: str | Path | None = None, timeout: int = 120) -> str:
    proc = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd,
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise ValueError(f"git {args[0]} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def resolve_local(repo_path: str, commit: str) -> tuple[Path, str, str]:
    """(repo root, full commit SHA, 'local/<name>') for a local Git repository."""
    root = Path(repo_path).expanduser().resolve()
    if not (root / ".git").exists():
        raise ValueError(f"{root} is not the root of a Git repository")
    sha = _git("-C", str(root), "rev-parse", "--verify", (commit or "HEAD") + "^{commit}")
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", root.name)[:60] or "repo"
    return root, sha, f"local/{name}"


def local_checkout_fn(root: Path):
    """checkout_fn for run_qwen_dev: a private clone at the base commit."""
    def checkout(task, destination: Path) -> Path:
        _git("clone", "-q", "--shared", "--no-checkout", str(root), str(destination))
        _git("-C", str(destination), "checkout", "-q", "--detach", task.base_commit)
        return destination
    return checkout


def commit_to_branch(root: Path, base: str, patch: str, branch: str, message: str) -> str:
    """Apply the accepted patch on a NEW branch via a temporary worktree."""
    if _git("-C", str(root), "branch", "--list", branch):
        raise ValueError(f"Branch {branch} already exists")
    worktree = root.parent / f".patchloop-wt-{uuid.uuid4().hex[:8]}"
    _git("-C", str(root), "worktree", "add", "-q", "-b", branch, str(worktree), base)
    try:
        # Bytes, not text: text-mode stdin would turn \n into \r\n on Windows.
        applied = subprocess.run(["git", "-C", str(worktree), "apply", "--index", "-"],
                                 input=patch.encode("utf-8"), capture_output=True, timeout=60)
        if applied.returncode:
            raise ValueError("The patch no longer applies to this repository: "
                             + applied.stderr.decode("utf-8", "replace").strip()[:300])
        _git("-C", str(worktree), "-c", "user.name=PatchLoop", "-c", "user.email=patchloop@localhost",
             "commit", "-q", "-m", message)
        return _git("-C", str(worktree), "rev-parse", "HEAD")
    finally:
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)],
                       capture_output=True, timeout=60)


# --------------------------------------------------------------------------- manager

class SessionManager:
    """Runs one session at a time on the single local GPU; others wait."""

    def __init__(self, runs_dir: str | Path, backend_factory, *, task_lookup=None):
        self.runs_dir = Path(runs_dir)
        self.backend_factory = backend_factory
        self.task_lookup = task_lookup          # instance_id -> DevelopmentTask
        self.sessions: dict[str, Session] = {}
        self.gpu = threading.Lock()

    def get(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise KeyError(sid)
        return self.sessions[sid]

    def start(self, request: Request, *, parent: Session | None = None, run_async: bool = True) -> Session:
        if request.agent not in ("pcr", "single") or request.edit_format not in ("search_replace", "diff"):
            raise ValueError("agent must be pcr|single and edit_format search_replace|diff")
        if not 0 <= int(request.retrieval_k) <= 50:
            raise ValueError("retrieval_k must be in [0, 50]")
        if not request.issue.strip() or len(request.issue) > 20000:
            raise ValueError("Issue must contain 1-20000 characters")
        if isinstance(self.backend_factory, dict) and request.backend not in self.backend_factory:
            raise ValueError(f"Model backend {request.backend!r} is not available on this server "
                             f"(available: {', '.join(sorted(self.backend_factory)) or 'none'})")
        sid = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        session = Session(sid, request, parent=parent.id if parent else None,
                          round=parent.round + 1 if parent else 1)
        self.sessions[sid] = session
        if run_async:
            threading.Thread(target=self._run, args=(session,), daemon=True).start()
        else:
            self._run(session)
        return session

    def follow_up(self, sid: str, guidance: str, *, run_async: bool = True, **changes) -> Session:
        parent = self.get(sid)
        if parent.status in ("queued", "checking", "running"):
            raise ValueError("Wait for the current run to finish (or cancel it) first")
        if parent.round > MAX_FOLLOWUPS:
            raise ValueError(f"At most {MAX_FOLLOWUPS} follow-up rounds; start a new request")
        guidance = (guidance or "").strip()
        base = parent.request
        issue = base.issue
        if guidance:
            issue += f"\n\nMaintainer follow-up (round {parent.round + 1}): {guidance}"
        fields = {**base.__dict__, "issue": issue, "skip_clarification": True}
        fields.update({k: v for k, v in changes.items() if v is not None and k in fields})
        return self.start(Request(**fields), parent=parent, run_async=run_async)

    # ----------------------------------------------------------------- run
    def _task(self, session: Session):
        from swebench_dev import DevelopmentTask
        req = session.request
        if req.source == "swebench":
            if not self.task_lookup:
                raise ValueError("SWE-bench tasks are not available on this server")
            base = self.task_lookup(req.instance_id)
            task = DevelopmentTask(base.instance_id, base.repo, base.base_commit, req.issue)
            return task, None
        if req.source == "local":
            root, sha, repo = resolve_local(req.repo_path or "", req.commit)
            iid = f"{repo.split('/')[1]}__local-{sha[:10]}"
            return DevelopmentTask(iid, repo, sha, req.issue), root
        raise ValueError("source must be swebench or local")

    def _run(self, session: Session) -> None:
        req = session.request
        try:
            session.status = "checking"
            task, local_root = self._task(session)
            session.emit("info", f"Repository {task.repo} at {task.base_commit[:10]}",
                         f"agent={req.agent}, edit_format={req.edit_format}, retrieval_k={req.retrieval_k}")
            from swebench_dev import checkout_dev_task
            checkout_fn = local_checkout_fn(local_root) if local_root else checkout_dev_task
            if req.retrieval_k and not req.skip_clarification:
                import tempfile
                from utils.retrieval import rank_files
                with tempfile.TemporaryDirectory(prefix="patchloop-check-") as temp:
                    checkout = checkout_fn(task, Path(temp) / "checkout")
                    candidates = rank_files(checkout, req.issue, req.retrieval_k)
                session.emit("tool", f"retrieval -> {len(candidates)} candidate files",
                             "\n".join(f"{c['file_path']}  ({', '.join(c['why'])})" for c in candidates))
                session.questions = clarification_questions(req.issue, candidates)
                if session.questions:
                    session.status = "needs_clarification"
                    session.emit("stop", "Stopped to ask for clarification before using the model",
                                 "\n".join(session.questions))
                    return
            session.status = "queued"
            if not self.gpu.acquire(blocking=False):
                session.emit("info", "Another repair is running on the GPU; waiting for it to finish")
                self.gpu.acquire()
            try:
                if session.cancel.is_set():
                    raise Cancelled("USER_CANCELLED")
                session.status = "running"
                self._run_agent(session, task, checkout_fn)
            finally:
                self.gpu.release()
        except Cancelled:
            session.status = "cancelled"
            session.emit("stop", "Cancelled by the user")
        except Exception as exc:  # report, never crash the server
            session.status = "failed"
            session.result.setdefault("error", f"{type(exc).__name__}: {exc}"[:500])
            session.emit("error", "Run failed", f"{type(exc).__name__}: {exc}"[:1000])

    @staticmethod
    def _test_env(req: Request):
        from patchloop_task2.test_exec import env_for_local, env_for_swebench
        return env_for_swebench if req.source == "swebench" else (lambda _iid: env_for_local())

    def _run_agent(self, session: Session, task, checkout_fn) -> None:
        from experiments.qwen_small_dev import run_qwen_dev
        req = session.request
        out = self.runs_dir / session.id
        factory = (self.backend_factory[req.backend] if isinstance(self.backend_factory, dict)
                   else self.backend_factory)
        inner = factory()
        backend = TracingBackend(inner, session)
        session.emit("info", f"Model: {inner.model}"
                     + (" (hosted DeepSeek API: the issue and code are sent to DeepSeek)"
                        if getattr(inner, "provider", "") == "deepseek" else " (local, nothing leaves this server)"))
        session.emit("info", f"Starting the {'Planner-Coder-Reviewer' if req.agent == 'pcr' else 'single'} agent")
        result = run_qwen_dev(
            backend, out, agent=req.agent, instance_id=task.instance_id,
            expected_repo=task.repo, expected_base=task.base_commit,
            task_loader=lambda instance_id: task, checkout_fn=checkout_fn,
            edit_format=req.edit_format,
            **({"retrieval_k": req.retrieval_k} if req.retrieval_k else {}),
            **({"exec_feedback": True, "test_env_fn": self._test_env(req)} if req.exec_feedback else {}),
        )
        session.result = result
        if req.exec_feedback and not result.get("test_env_available", False):
            session.emit("warning", "Test execution unavailable",
                         "No Docker test image for this repository (SWE-bench eval image, or "
                         "PATCHLOOP_TEST_IMAGE for local repositories); the run continued without tests.")
        if "USER_CANCELLED" in str(result.get("error", "")):
            raise Cancelled("USER_CANCELLED")
        for attempt in result.get("candidate_attempts", []):
            session.emit("apply" if attempt.get("patch_status") == "applied" else "warning",
                         f"attempt {attempt.get('attempt', '')}: {attempt.get('patch_status')}",
                         _short({k: attempt.get(k) for k in ("error_code", "changed_files",
                                                             "search_match_modes")}, 600))
            check = attempt.get("test_check")
            if check:
                ok = check.get("status") in ("passed", "no_tests", "no_baseline", "infra_error", "unavailable")
                session.emit("tool" if ok else "warning",
                             f"existing tests after the edit: {check.get('status')}",
                             _short({k: check.get(k) for k in ("targets", "regressions", "newly_passing")
                                     if check.get(k)}, 800))
        status = result.get("status")
        if status == "prediction_ready":
            pred = json.loads((out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            session.patch = pred["model_patch"]
            session.status = "awaiting_confirmation"
            tested = any(a.get("test_check", {}).get("status") == "passed"
                         for a in result.get("candidate_attempts", []))
            session.emit("stop", "A Git-applicable patch is ready. Review it, then accept or reject.",
                         "It was applied in an isolated checkout; the existing tests it touches still pass."
                         if tested else "It was applied in an isolated checkout only; no tests confirmed it.")
        elif status == "experiment_error":
            session.status = "failed"
            session.emit("error", f"Agent error at {result.get('failed_stage')}", str(result.get("error")))
        else:
            session.questions = outcome_questions(result)
            session.status = "needs_clarification"
            session.emit("stop", f"Stopped: {status}", "\n".join(session.questions))

    # ----------------------------------------------------------------- user decisions
    def accept(self, sid: str) -> dict:
        session = self.get(sid)
        if session.status != "awaiting_confirmation" or not session.patch:
            raise ValueError("Nothing to accept")
        out = self.runs_dir / sid
        patch_file = out / "accepted.patch"
        patch_file.write_text(session.patch, encoding="utf-8")
        session.result["patch_file"] = str(patch_file)
        req = session.request
        if req.source == "local":
            root, sha, _ = resolve_local(req.repo_path or "", session.result.get("base_commit") or req.commit)
            branch = f"patchloop/{sid}"
            commit = commit_to_branch(root, sha, session.patch, branch,
                                      f"PatchLoop {sid}: candidate fix (unverified, review before merging)")
            session.result["branch"] = branch
            session.emit("info", f"Committed on new branch {branch} ({commit[:10]})",
                         "Your current branch and working tree were not changed.")
        session.status = "accepted"
        session.emit("stop", "Accepted by the user", f"Patch saved to {patch_file}")
        return session.view()

    def reject(self, sid: str) -> dict:
        session = self.get(sid)
        if session.status != "awaiting_confirmation":
            raise ValueError("Nothing to reject")
        session.status = "rejected"
        session.emit("stop", "Rejected by the user; nothing was exported",
                     "Send a follow-up to try again with more guidance.")
        return session.view()

    def cancel(self, sid: str) -> dict:
        session = self.get(sid)
        session.cancel.set()
        session.emit("info", "Cancel requested; stopping after the current model call")
        return session.view()
