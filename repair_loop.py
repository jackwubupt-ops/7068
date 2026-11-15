"""Task 3 CLI. Execute only in a Docker test environment controlled by operator.

Example:
  python repair_loop.py --repo PATH --base-commit FULL_SHA --issue-file issue.txt --image python:3.11-slim --out result.json
"""
import argparse
import json
from pathlib import Path

from patchloop_task2.execution import DockerTestSpec
from patchloop_task2.loop import run_execution_loop


def main() -> int:
    parser = argparse.ArgumentParser(description="PatchLoop execution-grounded repair")
    parser.add_argument("--repo", required=True, help="Clean local Git checkout (not the application repository)")
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--issue-file", required=True)
    parser.add_argument("--image", required=True, help="Trusted, already-pulled Docker image")
    parser.add_argument("--test-runner", choices=("unittest", "pytest"), default="unittest")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--out", help="Write result JSON outside the target repository")
    parser.add_argument("--out-patch", help="Export a patch only after internal tests pass")
    parser.add_argument("--trace", help="Write JSONL trace outside the target repository")
    args = parser.parse_args()

    command = (("python", "-m", "pytest", "-q") if args.test_runner == "pytest"
               else ("python", "-m", "unittest", "discover", "-s", "tests", "-v"))
    spec = DockerTestSpec(image=args.image, command=command, timeout_seconds=args.timeout)
    issue = Path(args.issue_file).read_text(encoding="utf-8-sig")
    output = run_execution_loop(
        issue, args.repo, args.base_commit, spec, max_candidates=args.max_candidates,
        export_path=args.out_patch, trace_path=args.trace,
    )
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.out:
        path = Path(args.out).expanduser().resolve()
        source = Path(args.repo).expanduser().resolve()
        if path.is_relative_to(source):
            raise ValueError("--out must be outside target repository")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if output["repair"]["internal_tests_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
