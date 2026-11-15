"""Classify a pinned SWE-bench harness report without conflating errors and fails.

The old harness can exit 0 even when Docker environment build failed.
This reporter treats environment/build errors as NO_VERDICT, not Unresolved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def classify_official_report(data: dict, instance_id: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Official report must be a JSON object")
    resolved = data.get("resolved_ids", [])
    unresolved = data.get("unresolved_ids", [])
    errored = data.get("error_ids", [])
    if not all(isinstance(v, list) for v in (resolved, unresolved, errored)):
        raise ValueError("Official ID fields must be lists")
    if instance_id in errored or data.get("error_instances", 0):
        status = "infrastructure_error"
    elif instance_id in resolved:
        status = "resolved"
    elif instance_id in unresolved:
        status = "unresolved"
    elif (data.get("submitted_instances") == 1
          and data.get("completed_instances") == 1
          and data.get("resolved_instances") == 1):
        status = "resolved"
    elif (data.get("submitted_instances") == 1
          and data.get("completed_instances") == 1
          and data.get("unresolved_instances") == 1):
        status = "unresolved"
    else:
        status = "no_verdict"
    return {
        "instance_id": instance_id,
        "status": status,
        "official_evaluated": status in {"resolved", "unresolved"},
        "official_resolved": (
            True if status == "resolved"
            else False if status == "unresolved" else None
        ),
        "error_instances": data.get("error_instances"),
        "completed_instances": data.get("completed_instances"),
        "environment_override": "sqlfluff types-pkg_resources to types-setuptools",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source = Path(f"{args.model}.{args.run_id}.json")
    if source.is_file():
        data = json.loads(source.read_text(encoding="utf-8"))
        result = classify_official_report(data, args.instance_id)
    else:
        result = {
            "instance_id": args.instance_id, "status": "no_verdict",
            "official_evaluated": False, "official_resolved": None,
            "error": f"Official harness did not create {source}",
            "environment_override": "sqlfluff types-pkg_resources to types-setuptools",
        }
    target = Path(args.out).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["official_evaluated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
