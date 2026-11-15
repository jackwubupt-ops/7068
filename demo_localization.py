"""Reproducible temporary-repository demo. Default uses live LLM; --offline is scripted."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from pipeline_agent import run_localization


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Script model actions; repository tools still run for real')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='patchloop-demo-') as directory:
        root = Path(directory)
        (root / 'calc.py').write_text('def divide(a, b):\n    return a // b\n', encoding='utf8')
        for command in [('init',), ('add', '.'), ('-c', 'user.name=PatchLoop Demo', '-c', 'user.email=demo@example.com', 'commit', '-m', 'division fixture')]:
            subprocess.run(['git', '-C', directory, *command], check=True, capture_output=True)
        commit = subprocess.check_output(['git', '-C', directory, 'rev-parse', 'HEAD'], text=True).strip()
        issue = 'divide(3, 2) returns 1, but should return 1.5. Preserve fractional results.'
        options = {}
        if args.offline:
            actions = iter([
                {'action': 'search_repo', 'arguments': {'query': 'divide'}},
                {'action': 'read_file', 'arguments': {'relative_path': 'calc.py', 'start_line': 1, 'end_line': 2}},
                {'action': 'final', 'plan': {
                    'issue_summary': issue,
                    'suspected_files': [{'file_path': 'calc.py', 'relevant_lines': [1, 2], 'reason': 'The function uses floor division.', 'evidence_ids': ['E2']}],
                    'root_cause_hypothesis': 'Floor division likely discards the fractional component.',
                    'planned_changes': ['Use true division in divide; add fractional and integral input tests in Task 2.'],
                    'limitations': ['Scripted offline model responses; not a live LLM evaluation. No execution tests were run.']}}
            ])
            options['completion'] = lambda messages: json.dumps(next(actions))
        result = run_localization(issue, root, commit, **options)
        result['demo_mode'] = 'scripted-offline' if args.offline else 'live-llm'
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
