"""Run pinned SWE-bench 3.0.0 with one documented historical dependency fix.

The reference evaluation tests, gold patch and prediction are NEVER modified.
Only the historical sqlfluff environment's missing type-stub dependency is
substituted. This is a *nonstandard environment compatibility override* and
must be disclosed alongside any resulting benchmark verdict.

Usage:
  python -m experiments.swebench_eval_compat \
    --dataset_name princeton-nlp/SWE-bench --split dev \
    --instance_ids sqlfluff__sqlfluff-4764 \
    --predictions_path /path/predictions.jsonl --max_workers 1 --run_id my-run
"""
from __future__ import annotations

import importlib.metadata
import re
import runpy

OLD_NAME = "types-pkg_resources"
NEW_NAME = "types-setuptools"
PACKAGE_LINE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)types-pkg_resources(?P<suffix>[ \t]*(?:#.*)?)$"
)


def replace_legacy_stub(reqs: str) -> tuple[str, int]:
    if not isinstance(reqs, str):
        raise TypeError("Expected the original SWE-bench requirements text")
    return PACKAGE_LINE.subn(
        lambda match: match.group("indent") + NEW_NAME + match.group("suffix"),
        reqs,
    )


def install_scoped_compat_override() -> None:
    version = importlib.metadata.version("swebench")
    if version != "3.0.0":
        raise RuntimeError(
            f"This override is reviewed only for swebench==3.0.0, got {version}"
        )
    from swebench.harness.test_spec import python as spec

    original = spec.get_requirements

    def get_requirements_with_compat(instance):
        reqs = original(instance)
        if not isinstance(instance, dict) or instance.get("repo") != "sqlfluff/sqlfluff":
            return reqs
        replaced, count = replace_legacy_stub(reqs)
        if count:
            print(
                "[SWE-bench environment override] sqlfluff requirements: "
                "types-pkg_resources -> types-setuptools; "
                "test definitions and model patch unchanged",
                flush=True,
            )
        return replaced

    spec.get_requirements = get_requirements_with_compat


def main() -> None:
    install_scoped_compat_override()
    # Re-enter the *same official CLI* in-process after the compatibility hook.
    # All official test execution and scoring code stays in the pinned package.
    runpy.run_module("swebench.harness.run_evaluation", run_name="__main__")


if __name__ == "__main__":
    main()
