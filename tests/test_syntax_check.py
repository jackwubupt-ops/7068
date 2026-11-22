"""Offline tests for the harness Python syntax check (real Git; no code is executed)."""
from pathlib import Path
import json
import tempfile
import unittest

from patchloop_task2.single_agent import run_single_agent
from patchloop_task2.workspace import apply_candidate
from tests.test_edit_blocks import ORIGINAL, block, make_repo


def diff(path, old, new):
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1 +1 @@\n-{old}\n+{new}\n")


class SyntaxCheckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo, self.sha = make_repo(self.root, {
            "pkg/a.py": "X = 1\n", "pkg/legacy.py": "print 'py2'\n", "notes.txt": "a(\n"})

    def test_edit_that_breaks_python_is_rejected_and_not_exported(self):
        out = self.root / "c.patch"
        result = apply_candidate(self.repo, self.sha, diff("pkg/a.py", "X = 1", "X = (1"), export_path=out)
        self.assertEqual((result.status, result.error_code), ("syntax_invalid", "python_syntax_error"))
        self.assertIn("pkg/a.py line 1", result.error_message)
        self.assertFalse(out.exists())

    def test_valid_edit_non_python_and_already_broken_files_still_apply(self):
        for path, old, new in (("pkg/a.py", "X = 1", "X = 2"), ("notes.txt", "a(", "b("),
                               ("pkg/legacy.py", "print 'py2'", "print 'still py2'")):
            self.assertEqual(apply_candidate(self.repo, self.sha, diff(path, old, new)).status, "applied", path)

    def test_single_agent_gets_the_syntax_error_and_resubmits(self):
        (self.root / "two").mkdir()
        repo, sha = make_repo(self.root / "two", {"pkg/mod.py": ORIGINAL})
        read = json.dumps({"action": "read_file", "arguments": {"relative_path": "pkg/mod.py"}})
        broken = block("    return 0\n\n\ndef g():", "    return (-1\n\n\ndef g():")
        good = block("    return 0\n\n\ndef g():", "    return -1\n\n\ndef g():")
        replies, seen = [read, broken, good], []

        def model(messages):
            seen.append(messages[-1]["content"])
            return replies.pop(0)
        result = run_single_agent("f(0) should return -1", repo, sha, completion=model)
        self.assertEqual(result.status, "prediction_ready")
        self.assertEqual([s["patch_status"] for s in result.submissions], ["syntax_invalid", "applied"])
        self.assertIn("python_syntax_error", seen[-1])


if __name__ == "__main__":
    unittest.main()
