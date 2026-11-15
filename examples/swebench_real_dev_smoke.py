"""CI smoke with one REAL SWE-bench full-dev issue and historical Git checkout.

No model call, no gold patch, no hidden tests, no repository code execution.
"""
import json
from pathlib import Path
import tempfile

from swebench_dev import checkout_dev_task, inspect_dev_task, select_dev_task


def main():
    last_error = None
    # Prefer smaller repositories to keep CI smoke bounded.
    for repository in ("psf/requests", "pytest-dev/pytest"):
        try:
            task = select_dev_task(repository=repository)
            break
        except ValueError as exc:
            last_error = exc
    else:
        raise RuntimeError("No approved small-repository task in full dev") from last_error

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
