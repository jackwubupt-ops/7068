"""Offline tests for the interactive app: scripted model, real Git, no GPU."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from unittest import mock

from patchloop_app.session import (
    Request, SessionManager, clarification_questions, delivered_check, describe_feedback,
    describe_output,
)
from patchloop_app.web import create_app
from tests.test_edit_blocks import ORIGINAL, make_repo
from tests.test_single_agent import GOOD, READ, SEARCH

ISSUE = "Calling f(0) in pkg/mod.py returns 0 but it should return -1 for zero input."
EDIT = json.dumps({"action": "edit"})


class ScriptedBackend:
    model = "Qwen/Qwen2.5-Coder-7B-Instruct"

    def __init__(self, replies, on_call=None):
        self.replies = list(replies)
        self.calls = []
        self.on_call = on_call

    def complete(self, stage, messages):
        self.calls.append({"stage": stage, "prompt_tokens": 10, "completion_tokens": 5})
        if self.on_call:
            self.on_call(len(self.calls))
        if not self.replies:
            raise RuntimeError("QWEN_CALL_BUDGET_EXHAUSTED")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def callback(self, stage):
        return lambda messages: self.complete(stage, messages)


class AppSessionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo, self.sha = make_repo(self.root, {"pkg/mod.py": ORIGINAL, "pkg/other.py": "B = 2\n"})

    def manager(self, replies, **kw):
        backends = []
        def factory():
            backends.append(ScriptedBackend(replies, **kw))
            return backends[-1]
        mgr = SessionManager(self.root / "runs", factory)
        mgr.backends = backends
        return mgr

    def local(self, issue=ISSUE, **kw):
        kw.setdefault("agent", "single")
        return Request(issue=issue, source="local", repo_path=str(self.repo), **kw)

    def test_short_issue_stops_for_clarification_without_model_calls(self):
        mgr = self.manager([])
        s = mgr.start(self.local("it is broken"), run_async=False)
        self.assertEqual(s.status, "needs_clarification")
        self.assertTrue(any("very short" in q for q in s.questions))
        self.assertEqual(mgr.backends, [])  # no model backend was even created

    def test_ordinary_request_streams_trace_then_waits_for_confirmation_and_accept_makes_branch(self):
        mgr = self.manager([SEARCH, READ, EDIT, GOOD])
        s = mgr.start(self.local(), run_async=False)
        self.assertEqual(s.status, "awaiting_confirmation", s.events)
        titles = [e["title"] for e in s.events]
        self.assertTrue(any(t.startswith("retrieval ->") for t in titles))
        self.assertTrue(any("search the repository" in t for t in titles))
        self.assertTrue(any(t.startswith("read_file pkg/mod.py") for t in titles))
        self.assertTrue(any("done investigating" in t for t in titles))
        self.assertTrue(s.patch.startswith("diff --git a/pkg/mod.py"))
        head_before = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True)
        view = mgr.accept(s.id)
        self.assertEqual(view["status"], "accepted")
        branch = view["result"]["branch"]
        log = subprocess.check_output(["git", "-C", str(self.repo), "show", "--stat", branch], text=True)
        self.assertIn("pkg/mod.py", log)
        # The user's checkout is untouched.
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True),
                         head_before)
        self.assertEqual((self.repo / "pkg/mod.py").read_text(), ORIGINAL)
        self.assertTrue(Path(view["result"]["patch_file"]).is_file())

    def test_failed_edits_stop_with_questions_and_follow_up_carries_guidance(self):
        bad = GOOD.replace("    return 0\n\n\ndef g():", "    return 42")
        mgr = self.manager([READ, EDIT, bad, EDIT, bad])
        s = mgr.start(self.local(), run_async=False)
        self.assertEqual(s.status, "needs_clarification")
        self.assertEqual(s.result["status"], "patch_failed")
        self.assertTrue(s.questions)
        mgr.backends.clear()
        mgr.backend_factory = lambda: ScriptedBackend([READ, GOOD])
        follow = mgr.follow_up(s.id, "The bug is the `return 0` at the end of f.", agent="single")
        # follow_up runs async; wait for it.
        import time
        for _ in range(200):
            if follow.status not in ("queued", "checking", "running"):
                break
            time.sleep(0.05)
        self.assertEqual(follow.round, 2)
        self.assertEqual(follow.parent, s.id)
        self.assertIn("Maintainer follow-up (round 2)", follow.request.issue)
        self.assertEqual(follow.status, "awaiting_confirmation", follow.events)

    def test_reject_exports_nothing(self):
        mgr = self.manager([READ, GOOD])
        s = mgr.start(self.local(), run_async=False)
        self.assertEqual(mgr.reject(s.id)["status"], "rejected")
        self.assertFalse((self.root / "runs" / s.id / "accepted.patch").exists())
        with self.assertRaises(ValueError):
            mgr.accept(s.id)

    def test_cancel_stops_after_the_current_model_call(self):
        holder = {}
        mgr = self.manager([SEARCH, READ, GOOD], on_call=lambda n: n == 1 and holder["s"].cancel.set())
        req = self.local()
        # start synchronously, but capture the session before the run begins
        orig_run = mgr._run
        def run(session):
            holder["s"] = session
            orig_run(session)
        mgr._run = run
        s = mgr.start(req, run_async=False)
        self.assertEqual(s.status, "cancelled", s.events)
        self.assertEqual(s.patch, "")

    def test_cancel_while_queued_stops_without_waiting_for_the_running_session(self):
        import time
        mgr = self.manager([READ, GOOD])
        mgr.gpu.acquire()  # another repair holds the execution lock
        try:
            s = mgr.start(self.local())
            for _ in range(200):
                if s.status == "queued":
                    break
                time.sleep(0.02)
            self.assertEqual(s.status, "queued", s.events)
            mgr.cancel(s.id)
            for _ in range(100):
                if s.status == "cancelled":
                    break
                time.sleep(0.02)
            self.assertEqual(s.status, "cancelled", s.events)  # the lock is still held
            self.assertEqual(mgr.backends, [])  # the model was never called
        finally:
            mgr.gpu.release()

    def test_patch_that_breaks_existing_tests_needs_an_explicit_override(self):
        other = self.repo / "pkg/other.py"
        other.write_text("B = 3\n")
        patch = subprocess.check_output(["git", "-C", str(self.repo), "diff"], text=True)
        other.write_text("B = 2\n")
        def fake_run(backend, out, **kw):
            out.mkdir(parents=True, exist_ok=True)
            (out / "predictions.jsonl").write_text(json.dumps({"model_patch": patch}) + "\n")
            return {"status": "prediction_ready", "stop_reason": "x|kept_earlier_candidate_with_test_regressions",
                    "candidate_attempts": [
                        {"patch_status": "applied", "test_check": {"status": "regressions",
                                                                   "regressions": ["tests/test_mod.py::test_g"]}},
                        {"patch_status": "apply_failed"}]}
        mgr = self.manager([])
        with mock.patch("experiments.qwen_small_dev.run_qwen_dev", fake_run):
            s = mgr.start(self.local(), run_async=False)
        self.assertEqual(s.status, "awaiting_confirmation", s.events)
        view = s.view()
        self.assertEqual(view["result"]["verification"], "regressions")
        self.assertEqual(view["result"]["regressions"], ["tests/test_mod.py::test_g"])
        self.assertTrue(any(e["title"].startswith("Unsafe candidate") for e in s.events))
        with self.assertRaisesRegex(ValueError, "breaks existing tests"):
            mgr.accept(s.id)
        self.assertEqual(s.status, "awaiting_confirmation")
        view = mgr.accept(s.id, override=True)
        self.assertEqual(view["status"], "accepted")
        self.assertIn("despite failing existing tests", s.events[-1]["title"])

    def test_bad_requests_are_rejected(self):
        mgr = self.manager([])
        for req in (self.local(agent="x"), self.local(retrieval_k=99),
                    Request(issue=ISSUE, source="local", repo_path=str(self.root))):
            with self.subTest(req=req):
                if req.repo_path == str(self.root):
                    s = mgr.start(req, run_async=False)
                    self.assertEqual(s.status, "failed")
                else:
                    with self.assertRaises(ValueError):
                        mgr.start(req, run_async=False)

    def test_reasoning_effort_is_a_per_request_choice_for_deepseek_only(self):
        efforts = []

        def factory(reasoning_effort=None):
            efforts.append(reasoning_effort)
            return ScriptedBackend([READ, GOOD])
        mgr = SessionManager(self.root / "runs", {"deepseek": factory, "qwen": factory})
        s = mgr.start(self.local(backend="deepseek", reasoning_effort="high", retrieval_k=0), run_async=False)
        self.assertEqual(s.status, "awaiting_confirmation")
        self.assertEqual(efforts, ["high"])
        self.assertTrue(any("reasoning effort high" in e["title"] for e in s.view()["events"]))
        mgr.start(self.local(backend="deepseek", retrieval_k=0), run_async=False)
        self.assertEqual(efforts, ["high", None])              # "none" keeps the default backend
        for bad in (self.local(backend="qwen", reasoning_effort="low"),
                    self.local(backend="deepseek", reasoning_effort="medium")):
            with self.assertRaises(ValueError):
                mgr.start(bad, run_async=False)

    def test_uncommitted_edits_are_what_the_agent_sees_and_stay_untouched(self):
        mod = self.repo / "pkg" / "mod.py"
        edited = ORIGINAL + "\n\ndef h():\n    return 3\n"
        mod.write_text(edited)
        (self.repo / "pkg" / "new.py").write_text("Z = 1\n")
        before = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout
        mgr = self.manager([READ, GOOD])
        s = mgr.start(self.local(retrieval_k=0), run_async=False)
        self.assertEqual(s.status, "awaiting_confirmation")
        self.assertTrue(any(e["title"] == "Using your uncommitted changes" for e in s.view()["events"]))
        self.assertNotEqual(s.result["base_commit"], self.sha)            # a snapshot commit, child of HEAD
        self.assertEqual(mod.read_text(), edited)                         # working tree untouched
        after = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)                                   # index untouched
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, self.sha)                                  # branch untouched
        view = mgr.accept(s.id)
        branch = view["result"]["branch"]
        shown = subprocess.run(["git", "-C", str(self.repo), "show", f"{branch}:pkg/mod.py"], capture_output=True, text=True).stdout
        self.assertIn("def h():", shown)                                  # accepted on top of the snapshot
        self.assertIn("return -1", shown)

    def test_pasted_code_runs_in_a_private_repository(self):
        mgr = self.manager([READ, GOOD])
        req = Request(issue=ISSUE, source="snippet", snippet_name="pkg/mod.py", snippet_code=ORIGINAL,
                      agent="single", retrieval_k=0)
        s = mgr.start(req, run_async=False)
        self.assertEqual(s.status, "awaiting_confirmation", s.view()["events"][-3:])
        self.assertIn("return -1", s.patch)
        self.assertEqual(mgr.accept(s.id)["status"], "accepted")
        for bad in (dict(snippet_name="../x.py", snippet_code="x=1"), dict(snippet_name="a.py", snippet_code=" "),
                    dict(snippet_name="/etc/passwd", snippet_code="x")):
            with self.assertRaises(ValueError):
                mgr.start(Request(issue=ISSUE, source="snippet", agent="single", **bad), run_async=False)


class DescribeTests(unittest.TestCase):
    def test_feedback_and_output_descriptions(self):
        fb = describe_feedback("Tool evidence (untrusted): " + json.dumps(
            {"tool": "read_file", "result": {"ok": True, "file_path": "a.py",
                                             "lines": [{"line_number": 3}, {"line_number": 9}]}}))
        self.assertEqual(fb[1], "read_file a.py lines 3-9")
        self.assertEqual(describe_feedback("Repeated action: x")[0], "warning")
        self.assertIsNone(describe_feedback("hello"))
        kind, title, _ = describe_output("planner", json.dumps(
            {"action": "final", "plan": {"suspected_files": [{"file_path": "a.py"}]}}))
        self.assertEqual(kind, "decision")
        self.assertIn("a.py", title)
        self.assertEqual(describe_output("agent", "nonsense")[0], "warning")
        self.assertEqual(describe_output("reviewer", json.dumps({"failure_type": "patch_apply"}))[1],
                         "reviewer: patch_apply")

    def test_clarification_rule(self):
        self.assertTrue(clarification_questions("short", []))
        hinted = [{"file_path": "a.py", "score": 2.0, "why": ["path named in issue"]}]
        self.assertEqual(clarification_questions("a long enough issue text naming a.py clearly here", hinted), [])
        weak = [{"file_path": "a.py", "score": 0.1, "why": ["keyword match"]}]
        self.assertTrue(clarification_questions("a long enough issue text without any concrete pointers", weak))


class DeliveredCheckTests(unittest.TestCase):
    def test_the_last_applied_attempt_is_the_delivered_patch(self):
        reg = {"patch_status": "applied", "test_check": {"status": "regressions", "regressions": ["t::a"]}}
        ok = {"patch_status": "applied", "test_check": {"status": "passed"}}
        self.assertEqual(delivered_check({"candidate_attempts": [reg, {"patch_status": "apply_failed"}]}),
                         ("regressions", ["t::a"]))
        self.assertEqual(delivered_check({"candidate_attempts": [reg, ok]}), ("tests_passed", []))
        self.assertEqual(delivered_check({"candidate_attempts": [{"patch_status": "applied"}]}),
                         ("unverified", []))
        self.assertEqual(delivered_check({}), ("unverified", []))


class WebRouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo, _ = make_repo(self.root, {"pkg/mod.py": ORIGINAL})

    def test_routes_and_token(self):
        mgr = SessionManager(self.root / "runs", lambda: ScriptedBackend([READ, GOOD]))
        app = create_app(mgr, health=lambda: {"status": "live_qwen_api_ok", "model": "m"}, token="s3cret")
        client = app.test_client()
        self.assertEqual(client.get("/").status_code, 401)
        self.assertEqual(client.get("/?token=s3cret").status_code, 200)  # sets the cookie
        self.assertEqual(client.get("/api/health").get_json()["status"], "live_qwen_api_ok")
        bad = client.post("/api/sessions", json={"issue": "", "source": "local"})
        self.assertEqual(bad.status_code, 400)
        r = client.post("/api/sessions", json={"issue": ISSUE, "source": "local", "repo_path": str(self.repo),
                                               "agent": "single", "retrieval_k": 0})
        self.assertEqual(r.status_code, 200)
        sid = r.get_json()["id"]
        import time
        for _ in range(200):
            view = client.get(f"/api/sessions/{sid}").get_json()
            if view["status"] not in ("queued", "checking", "running"):
                break
            time.sleep(0.05)
        self.assertEqual(view["status"], "awaiting_confirmation", view["events"])
        self.assertIn("diff --git", client.get(f"/api/sessions/{sid}/patch").get_data(as_text=True))
        self.assertEqual(client.post(f"/api/sessions/{sid}/accept").get_json()["status"], "accepted")
        self.assertEqual(client.get("/api/sessions/nope").status_code, 404)
        self.assertEqual(len(client.get("/api/sessions").get_json()), 1)

    def test_deepseek_only_deployment_defaults_to_deepseek(self):
        mgr = SessionManager(self.root / "runs", {"deepseek": lambda: ScriptedBackend([READ, GOOD])})
        client = create_app(mgr).test_client()
        r = client.post("/api/sessions", json={"issue": ISSUE, "source": "local", "repo_path": str(self.repo),
                                               "agent": "single", "retrieval_k": 0})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["request"]["backend"], "deepseek")
        import time
        for _ in range(200):  # let the background run finish before the temp dir goes away
            if client.get(f"/api/sessions/{r.get_json()['id']}").get_json()["status"] not in (
                    "queued", "checking", "running"):
                break
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
