"""CLI: python localize.py --repo PATH --base-commit SHA --issue-file issue.txt"""
import argparse
import json
from pathlib import Path
import sys

from pipeline_agent import run_localization


def main():
    parser = argparse.ArgumentParser(description='PatchLoop read-only bug localization')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--base-commit', required=True)
    parser.add_argument('--issue-file', required=True)
    args = parser.parse_args()
    try:
        with Path(args.issue_file).open(encoding='utf-8-sig') as stream:
            issue = stream.read(20001)
        result = run_localization(issue, args.repo, args.base_commit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
