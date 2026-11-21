"""Offline tests for the find_definition and list_directory agent tools.

Real Git repositories; scripted model replies prove the wiring, NOT model quality.
"""
import json
from pathlib import Path
import tempfile
import unittest

from patchloop_app.session import describe_feedback, describe_output
from patchloop_task2.single_agent import run_single_agent
from prompt_agent import plan_repair
from tests.test_edit_blocks import ORIGINAL, block, make_repo
from utils.repo_tools import find_definition, list_directory

CLASSES = ("class Field:\n    def deserialize(self, value):\n        return value\n\n\n"
           "class Nested(Field):\n    class Meta:\n        pass\n\n    async def deserialize(self, v):\n"
           "        return v\n\n\ndef deserialize(raw):\n    return raw\n")


class ToolFunctionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo, self.sha = make_repo(Path(temp.name), {
            "pkg/mod.py": ORIGINAL, "pkg/fields.py": CLASSES, "pkg/sub/deep.py": "X = 1\n",
            "tests/test_fields.py": "def deserialize():\n    pass\n", "README.md": "readme\n"})
        (self.repo / "pkg" / "untracked.py").write_text("def deserialize():\n    pass\n")

    def test_find_definition_kinds_scopes_and_tracked_only(self):
        result = find_definition(self.repo, "deserialize")
        self.assertTrue(result["ok"])
        found = [(d["file_path"], d["qualified_name"], d["kind"], d["start_line"]) for d in result["definitions"]]
        self.assertEqual(found, [("pkg/fields.py", "Field.deserialize", "method", 2),
                                 ("pkg/fields.py", "Nested.deserialize", "method", 10),
                                 ("pkg/fields.py", "deserialize", "function", 14),
                                 ("tests/test_fields.py", "deserialize", "function", 1)])
        self.assertEqual(result["definitions"][0]["signature"], "def deserialize(self, value):")
        meta = find_definition(self.repo, "Meta")["definitions"]
        self.assertEqual([(d["qualified_name"], d["kind"]) for d in meta], [("Nested.Meta", "class")])
        self.assertEqual(find_definition(self.repo, "deserialize", max_results=1)["truncated"], True)
        self.assertEqual(find_definition(self.repo, "missing")["definitions"], [])

    def test_find_definition_rejects_non_identifiers(self):
        for bad in ("a b", "os.path", "../x", "", 3):
            self.assertFalse(find_definition(self.repo, bad)["ok"], bad)

    def test_list_directory_tracked_layout(self):
        top = list_directory(self.repo)
        self.assertEqual(top["entries"], [{"name": "pkg/", "type": "directory", "tracked_files": 3},
                                          {"name": "tests/", "type": "directory", "tracked_files": 1},
                                          {"name": "README.md", "type": "file"}])
        pkg = list_directory(self.repo, "pkg/")
        self.assertEqual([e["name"] for e in pkg["entries"]], ["sub/", "fields.py", "mod.py"])
        for bad in ("../", "/etc", "missing", ".git", "C:\\x"):
            self.assertFalse(list_directory(self.repo, bad)["ok"], bad)


class Scripted:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def __call__(self, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0)


FIND = json.dumps({"action": "find_definition", "arguments": {"name": "f"}})
LIST = json.dumps({"action": "list_directory", "arguments": {"relative_path": "pkg"}})
READ = json.dumps({"action": "read_file", "arguments": {"relative_path": "pkg/mod.py"}})


class AgentWiringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo, self.sha = make_repo(self.root, {"pkg/mod.py": ORIGINAL, "pkg/other.py": "B = 2\n"})

    def test_single_agent_uses_new_tools_then_edits(self):
        good = block("    return 0\n\n\ndef g():", "    return -1\n\n\ndef g():")
        model = Scripted([LIST, FIND, READ, good])
        result = run_single_agent("f(0) should return -1", self.repo, self.sha, completion=model)
        self.assertEqual(result.status, "prediction_ready")
        self.assertEqual([e["action"] for e in result.trace],
                         ["list_directory", "find_definition", "read_file", "submit"])
        self.assertEqual(result.trace[1]["definition_name"], "f")
        self.assertIn('"qualified_name": "f"', model.seen[2][-1]["content"])
        self.assertIn("find_definition", model.seen[0][0]["content"])

    def test_planner_accepts_find_definition_as_localization(self):
        final = json.dumps({"action": "final", "plan": {
            "issue_summary": "f(0) wrong", "root_cause_hypothesis": "returns 0",
            "planned_changes": ["return -1"], "limitations": ["untested"],
            "suspected_files": [{"file_path": "pkg/mod.py", "relevant_lines": [1, 4],
                                 "reason": "defines f", "evidence_ids": ["E3"]}]}})
        model = Scripted([FIND, LIST, READ, final])
        plan = plan_repair("f(0) should return -1", str(self.repo), self.sha, completion=model)
        self.assertEqual([e["tool"] for e in plan["evidence"]], ["find_definition", "list_directory", "read_file"])
        self.assertEqual(plan["suspected_files"][0]["file_path"], "pkg/mod.py")
        bad_args = Scripted([json.dumps({"action": "find_definition", "arguments": {"query": "f"}}),
                             FIND, READ, final.replace("E3", "E2")])
        plan = plan_repair("f(0) should return -1", str(self.repo), self.sha, completion=bad_args)
        self.assertIn("Protocol validation error", bad_args.seen[1][-1]["content"])

    def test_web_timeline_describes_new_tools(self):
        self.assertEqual(describe_output("planner", FIND)[1], "planner: find where “f” is defined")
        self.assertEqual(describe_output("agent", LIST)[1], "agent: list the directory pkg")
        feedback = "Tool result (untrusted): " + json.dumps({"action": "find_definition", "result": find_definition(self.repo, "f")})
        kind, title, detail = describe_feedback(feedback)
        self.assertEqual((kind, title), ("tool", "find_definition -> 1 definitions"))
        self.assertIn("f (pkg/mod.py:1)", detail)
        listing = "Tool evidence (untrusted): " + json.dumps({"tool": "list_directory", "result": list_directory(self.repo)})
        self.assertEqual(describe_feedback(listing)[1], "list_directory . -> 1 entries")


class ManifestTests(unittest.TestCase):
    def test_manifest_records_tools_and_old_batches_default_to_two(self):
        from experiments import final_report
        from experiments.lite_batch import build_manifest
        manifest = build_manifest([], dataset_id="d", settings={})
        self.assertEqual(manifest["agent_tools"], ["find_definition", "list_directory", "read_file", "search_repo"])
        self.assertIn("agent_tools", final_report.VARIABLES)
        self.assertEqual(final_report.LEGACY_TOOLS, ["read_file", "search_repo"])


if __name__ == "__main__":
    unittest.main()
