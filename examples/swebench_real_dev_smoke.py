"""CI smoke with one REAL SWE-bench full-dev issue and historical Git checkout.

No model call, no gold patch, no hidden tests, no repository code execution.
"""
import json
from pathlib import Path
import tempfile

from swebench_dev import checkout_dev_task, inspect_dev_task, select_dev_task


def main():
    # The full dev split is NOT guaranteed to contain pytest or requests.
    # Select a genuine task from the split; never fall back to Lite test.
    task = select_dev_task()

    with tempfile.TemporaryDirectory(prefix="swebench-real-dev-ci-") as temporary:
        checkout = checkout_dev_task(task, Path(temporary) / "checkout")
        result = inspect_dev_task(task, checkout)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        assert result["search_ok"], result
        assert result["base_commit"].lower() == task.base_commit.lower()
        assert result["instance_id"] == task.instance_id
        assert result["model_called"] is False
        assert result["official_evaluated"] is False


if __name__ == "__main__":
    main()
