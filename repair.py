"""CLI: python repair.py --repo PATH --base-commit SHA --issue-file FILE"""
import argparse
import json
from pathlib import Path

from patchloop_task2.runner import run_repair


def main():
    parser = argparse.ArgumentParser(description="PatchLoop Task 2 patch generation/application")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--issue-file", required=True)
    parser.add_argument("--out", help="Write JSON outcome")
    parser.add_argument("--out-patch", help="Write applied diff outside target repository")
    args = parser.parse_args()
    issue = Path(args.issue_file).read_text(encoding="utf-8-sig")
    data = run_repair(issue, args.repo, args.base_commit, export_path=args.out_patch)
    rendered = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if data["patch_result"]["status"] == "applied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
