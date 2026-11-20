"""GitHub CI Qwen-API CONTRACT smoke with SCRIPTED responses, real Docker tests.

This proves the control plane works. It does NOT load weights, contact vLLM,
or count as evidence of real model repair accuracy.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from experiments.qwen_small_dev import run_qwen_smoke
from patchloop_task2.qwen_small import (
    DEFAULT_MODEL, QwenSettings, QwenSmallBackend,
)

PATCH = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n+++ b/calc.py\n"
    # Intentionally inconsistent hunk counts: normalized and recorded.
    "@@ -1,3 +1,4 @@\n"
    " def divide(a, b):\n"
    "-    return a // b\n"
    "+    return a / b\n"
)


class ScriptedChatCompletions:
    def __init__(self):
        self.planner_turn = 0
        self.requests = 0

    def create(self, *, messages, model, max_tokens, temperature):
        assert model == DEFAULT_MODEL
        assert temperature == 0
        self.requests += 1
        content = messages[0]["content"]
        if content.startswith("You are PatchLoop's repository bug localization Planner"):
            self.planner_turn += 1
            if self.planner_turn == 1:
                output = json.dumps({"action": "search_repo", "arguments": {
                    "query": "divide", "max_results": 2, "context_lines": 1
                }})
            elif self.planner_turn == 2:
                output = json.dumps({"action": "read_file", "arguments": {
                    "relative_path": "calc.py", "start_line": 1, "end_line": 2
                }})
            else:
                output = json.dumps({"action": "final", "plan": {
                    "issue_summary": "Divide truncates fractions",
                    "suspected_files": [{"file_path": "calc.py",
                                         "relevant_lines": [1, 2],
                                         "reason": "Floor division used",
                                         "evidence_ids": ["E2"]}],
                    "root_cause_hypothesis": "Use of // rather than /",
                    "planned_changes": ["Replace floor division"],
                    "limitations": ["Offline scripted model, no claim of Qwen inference"],
                }})
        elif content.startswith("You are PatchLoop's Coder"):
            output = PATCH
        elif content.startswith("You are PatchLoop's Reviewer"):
            output = json.dumps({
                "failure_type": "test_failure", "diagnosis": "wrong result",
                "suggested_fix": "replace integer division"
            })
        else:
            output = "READY"
        return SimpleNamespace(
            model=model,
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=output),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
        )


def main():
    scripted = ScriptedChatCompletions()
    client = SimpleNamespace(
        models=SimpleNamespace(
            list=lambda: SimpleNamespace(
                data=[SimpleNamespace(id=DEFAULT_MODEL)]
            ),
        ),
        chat=SimpleNamespace(completions=scripted),
    )
    backend = QwenSmallBackend(QwenSettings(), client=client)
    result = run_qwen_smoke(backend, max_candidates=2)
    result["scripted_model"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert result["status"] == "internal_tests_passed", result
    assert result["original_checkout_clean"]
    assert result["attempts"][0]["hunk_header_corrections"] == 1
    assert result["attempts"][0]["test_status"] == "passed"
    assert scripted.planner_turn == 3
    assert backend.calls[0]["stage"] == "preflight"


if __name__ == "__main__":
    main()
