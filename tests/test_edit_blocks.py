"""Offline tests for SEARCH/REPLACE edit blocks (scripted model output, real Git)."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from experiments.deepseek_swebench_dev import run_real_dev
from patchloop_task2.edit_blocks import (
    EditBlockError, build_search_replace_messages, edit_blocks_to_diff,
    git_show_reader, parse_edit_blocks,
)
from patchloop_task2.validator import validate_patch
from swebench_dev import DevelopmentTask

ORIGINAL = "def f(x):\n    if x:\n        return 1\n    return 0\n\n\ndef g():\n    return 0\n"
ALLOWED = {"pkg/mod.py", "pkg/other.py"}


def block(search: str, replace: str, path: str = "pkg/mod.py") -> str:
    return f"FILE: {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def make_repo(root: Path, files: dict[str, str]) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode())
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
        "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


class ParseTests(unittest.TestCase):
    def test_fences_and_prose_outside_blocks_are_ignored(self):
        text = "Here is the fix:\n```\n" + block("    return 0", "    return 2") + "```\n"
        [only] = parse_edit_blocks(text, ALLOWED)
        self.assertEqual(only.search, ("    return 0",))
        self.assertEqual(only.replace, ("    return 2",))

    def test_rejections(self):
        cases = {
            "missing_file": "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n",
            "path_not_allowed": block("a", "b", path="setup.py"),
            "malformed_block": "FILE: pkg/mod.py\n<<<<<<< SEARCH\na\n=======\nb\n",
            "empty_search": block("", "b"),
            "no_blocks": "I could not find the bug.",
            "empty_output": "  ",
        }
        for code, text in cases.items():
            with self.subTest(code=code), self.assertRaises(EditBlockError) as ctx:
                parse_edit_blocks(text, ALLOWED)
            self.assertEqual(ctx.exception.code, code)


class ConversionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def convert(self, text: str, files: dict[str, str]):
        repo, sha = make_repo(self.root, files)
        diff, meta = edit_blocks_to_diff(text, ALLOWED, git_show_reader(repo, sha))
        return repo, diff, meta

    def assert_applies_to(self, repo: Path, diff: str, expected: dict[str, str]):
        validate_patch(diff, set(expected))  # the harness's own strict validator
        subprocess.run(["git", "-C", str(repo), "apply", "--check", "-"],
                       input=diff.encode(), check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "apply", "-"], input=diff.encode(), check=True)
        for name, content in expected.items():
            self.assertEqual((repo / name).read_text(), content)

    def test_exact_unique_edit_becomes_applicable_diff(self):
        text = block("        return 1\n    return 0\n\n\ndef g():",
                     "        return 1\n    return -1\n\n\ndef g():")
        repo, diff, meta = self.convert(text, {"pkg/mod.py": ORIGINAL})
        self.assertTrue(diff.startswith("diff --git a/pkg/mod.py b/pkg/mod.py\n"))
        self.assertEqual(meta, {"edit_blocks": 1, "edited_files": ["pkg/mod.py"]})
        self.assert_applies_to(repo, diff, {"pkg/mod.py": ORIGINAL.replace(
            "    return 0\n\n\ndef g", "    return -1\n\n\ndef g")})

    def test_ambiguous_and_missing_search_are_reported_not_guessed(self):
        with self.assertRaises(EditBlockError) as ctx:
            self.convert(block("    return 0", "    return 5"), {"pkg/mod.py": ORIGINAL})
        self.assertEqual(ctx.exception.code, "search_ambiguous")

    def test_whitespace_mismatch_is_not_fixed_but_hinted(self):
        with self.assertRaises(EditBlockError) as ctx:
            self.convert(block("  if x:", "  if not x:"), {"pkg/mod.py": ORIGINAL})
        self.assertEqual(ctx.exception.code, "search_not_found")
        self.assertIn("whitespace", str(ctx.exception))

    def test_sequential_blocks_multiple_files_and_deletion(self):
        text = (block("def f(x):", "def f(x, y=None):")
                # Empty REPLACE section = delete the SEARCH lines.
                + "FILE: pkg/mod.py\n<<<<<<< SEARCH\n    if x:\n        return 1\n=======\n>>>>>>> REPLACE\n"
                + block("B = 2", "B = 3", path="pkg/other.py"))
        repo, diff, meta = self.convert(text, {"pkg/mod.py": ORIGINAL, "pkg/other.py": "A = 1\nB = 2\n"})
        self.assertEqual(meta["edit_blocks"], 3)
        self.assert_applies_to(repo, diff, {
            "pkg/mod.py": ORIGINAL.replace("def f(x):\n    if x:\n        return 1\n", "def f(x, y=None):\n"),
            "pkg/other.py": "A = 1\nB = 3\n",
        })

    def test_file_without_final_newline_keeps_it_that_way(self):
        repo, diff, _ = self.convert(block("B = 2", "B = 3", path="pkg/other.py"),
                                     {"pkg/other.py": "A = 1\nB = 2"})
        self.assertIn("\\ No newline at end of file", diff)
        self.assert_applies_to(repo, diff, {"pkg/other.py": "A = 1\nB = 3"})

    def test_no_op_edit_is_rejected(self):
        with self.assertRaises(EditBlockError) as ctx:
            self.convert(block("def g():", "def g():"), {"pkg/mod.py": ORIGINAL})
        self.assertEqual(ctx.exception.code, "no_change")

    def test_reader_uses_base_commit_not_working_tree(self):
        repo, sha = make_repo(self.root, {"pkg/mod.py": ORIGINAL})
        (repo / "pkg/mod.py").write_text("tampered\n")
        self.assertEqual(git_show_reader(repo, sha)("pkg/mod.py"), ORIGINAL)


def plan_for(sha: str) -> dict:
    lines = [{"line_number": n, "text": t} for n, t in enumerate(ORIGINAL.splitlines(), 1)]
    return {
        "base_commit": sha,
        "suspected_files": [{"file_path": "pkg/mod.py", "relevant_lines": [1, 4], "evidence_ids": ["e1"]}],
        "evidence": [{"id": "e1", "tool": "read_file",
                      "result": {"ok": True, "file_path": "pkg/mod.py", "lines": lines}}],
        "root_cause_hypothesis": "f returns 0 for falsy x", "planned_changes": [],
    }


class ScriptedApi:
    """Scripted replies: proves wiring only, NOT live model quality."""
    model = "scripted"

    def __init__(self, coder_replies):
        self.coder_replies = list(coder_replies)
        self.calls = []
        self.coder_messages = []

    def complete(self, stage, messages):
        self.calls.append({"stage": stage})
        if stage == "coder":
            self.coder_messages.append(messages)
            return self.coder_replies.pop(0)
        if stage == "reviewer":
            return json.dumps({"failure_type": "patch_apply", "diagnosis": "SEARCH text differs",
                               "suggested_fix": "copy lines exactly"})
        return "OK"

    def callback(self, stage):
        return lambda messages: self.complete(stage, messages)


class DevRunSearchReplaceTests(unittest.TestCase):
    def run_dev(self, coder_replies):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        repo, sha = make_repo(root, {"pkg/mod.py": ORIGINAL})
        task = DevelopmentTask(instance_id="owner__proj-1", repo="owner/proj",
                               base_commit=sha, problem_statement="f(0) should return -1")
        api = ScriptedApi(coder_replies)
        with patch("experiments.deepseek_swebench_dev.run_localization", return_value=plan_for(sha)):
            report = run_real_dev(
                root / "out", api=api, instance_id=task.instance_id,
                expected_repo=None, expected_base=None, edit_format="search_replace",
                task_loader=lambda instance_id: task, checkout_fn=lambda t, p: repo,
            )
        return root / "out", report, api

    def test_bad_search_goes_to_reviewer_then_retry_succeeds(self):
        good = block("    return 0\n\n\ndef g():", "    return -1\n\n\ndef g():")
        out, report, api = self.run_dev([block("    return zero", "    return -1"), good])
        self.assertEqual(report["status"], "prediction_ready", report.get("error"))
        self.assertEqual(report["edit_format"], "search_replace")
        first, second = report["candidate_attempts"]
        self.assertEqual(first["patch_status"], "edit_invalid")
        self.assertEqual(first["edit_error_code"], "search_not_found")
        self.assertEqual(second["patch_status"], "applied")
        self.assertEqual(second["edit_blocks"], 1)
        self.assertEqual(report["reviewer_calls"], 1)
        # The retry prompt carries the failed blocks, never a gold patch.
        retry_prompt = json.dumps(api.coder_messages[1])
        self.assertIn("previous_edit_blocks", retry_prompt)
        self.assertIn("SEARCH/REPLACE", api.coder_messages[0][0]["content"])
        patch_text = (out / "candidate.patch").read_text()
        self.assertIn("+    return -1", patch_text)
        prediction = json.loads((out / "predictions.jsonl").read_text())
        self.assertEqual(prediction["model_patch"], patch_text)
        self.assertTrue(report["source_checkout_clean"])

    def test_two_invalid_edits_end_as_patch_failed(self):
        _, report, _ = self.run_dev(["no blocks here", "still nothing"])
        self.assertEqual(report["status"], "patch_failed")
        self.assertEqual([a["edit_error_code"] for a in report["candidate_attempts"]],
                         ["no_blocks", "no_blocks"])

    def test_messages_reuse_bounded_evidence(self):
        messages = build_search_replace_messages("issue", plan_for("a" * 40))
        self.assertIn("SEARCH/REPLACE", messages[0]["content"])
        self.assertIn('"text":"def f(x):"', messages[1]["content"])
        self.assertIn("ONLY SEARCH/REPLACE", messages[-1]["content"])

    def test_unknown_edit_format_rejected(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            run_real_dev(Path(temp) / "o", api=ScriptedApi([]), edit_format="whole_file")


if __name__ == "__main__":
    unittest.main()
