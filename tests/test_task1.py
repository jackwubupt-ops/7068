import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from utils.repo_tools import read_file, search_repo, validate_repository, is_tracked
from prompt_agent import plan_repair


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'calc.py').write_text('def divide(a, b):\n    return a // b\n', encoding='utf8')
        for args in [('init',), ('add', '.'), ('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'fixture')]:
            subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)
        self.commit = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()

    def test_search_and_read(self):
        result = search_repo(self.root, 'return')
        self.assertTrue(result['ok'])
        self.assertEqual(result['matches'][0]['file_path'], 'calc.py')
        self.assertEqual(result['matches'][0]['line_number'], 2)
        self.assertEqual(result['matches'][0]['function'], 'divide')
        result = read_file(self.root, 'calc.py', start_line=2, end_line=2)
        self.assertEqual(result['lines'], [{'line_number': 2, 'text': '    return a // b'}])

    def test_invalid_inputs(self):
        for path in ('../outside', '/etc/passwd', 'C:\\Windows\\win.ini', '.git/config', '.GIT/config', '.env', '.ENV'):
            self.assertFalse(read_file(self.root, path)['ok'], path)
        for args in ({'start_line': 0}, {'start_line': 2, 'end_line': 1}, {'start_line': True}):
            self.assertFalse(read_file(self.root, 'calc.py', **args)['ok'])
        self.assertFalse(read_file(self.root, 'missing')['ok'])
        self.assertFalse(search_repo(self.root, '')['ok'])
        self.assertFalse(search_repo(self.root, 'x', max_results=-1)['ok'])

    def test_limits_and_ignored_files(self):
        (self.root / '.env').write_text('secretneedle')
        (self.root / '.venv').mkdir()
        (self.root / '.venv/x.py').write_text('secretneedle')
        self.assertEqual(search_repo(self.root, 'secretneedle')['matches'], [])
        (self.root / 'many.py').write_text('needle\n' * 250)
        self.assertEqual(len(search_repo(self.root, 'needle', max_results=2)['matches']), 2)
        self.assertTrue(read_file(self.root, 'many.py')['truncated'])
        (self.root / 'binary').write_bytes(b'\x00abc')
        self.assertFalse(read_file(self.root, 'binary')['ok'])

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'outside.py'
            target.write_text('outside_marker')
            try:
                (self.root / 'escape.py').symlink_to(target)
            except OSError:
                self.skipTest('OS does not permit creating symlinks')
            self.assertFalse(read_file(self.root, 'escape.py')['ok'])
            self.assertEqual(search_repo(self.root, 'outside_marker')['matches'], [])

    def test_search_fallback_and_timeout(self):
        with patch('utils.repo_tools.shutil.which', return_value=None):
            result = search_repo(self.root, 'divide')
            self.assertEqual(result['backend'], 'python')
            self.assertEqual(result['matches'][0]['line_number'], 1)
        with patch('utils.repo_tools.shutil.which', return_value='rg'), patch('utils.repo_tools.subprocess.run', side_effect=subprocess.TimeoutExpired('rg', 1)):
            self.assertFalse(search_repo(self.root, 'divide')['ok'])

    def test_oversized_and_long_line(self):
        (self.root / 'large.py').write_text('x' * 262145)
        self.assertFalse(read_file(self.root, 'large.py')['ok'])
        (self.root / 'long.py').write_text('needle' + 'x' * 21000)
        self.assertTrue(read_file(self.root, 'long.py')['truncated'])
        self.assertTrue(search_repo(self.root, 'needle')['truncated'])

    def test_unicode_line_numbers(self):
        (self.root / 'unicode.py').write_text('# extra\u0085line\ndef bug():\n    return 1\n', encoding='utf8')
        result = search_repo(self.root, 'return')
        match = next(m for m in result['matches'] if m['file_path'] == 'unicode.py')
        self.assertEqual(match['line_number'], 3)
        self.assertIn('3:     return 1', match['snippet'])
        self.assertEqual(read_file(self.root, 'unicode.py', start_line=3)['lines'][0]['text'], '    return 1')

    def test_planner_rejects_gitignored_evidence(self):
        (self.root / '.gitignore').write_text('ignored.py\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.gitignore'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'ignore'], check=True, capture_output=True)
        commit = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()
        (self.root / 'ignored.py').write_text('not_from_commit = True\nsecond_line = True\n')
        actions = self.responses()
        actions[1]['arguments']['relative_path'] = 'ignored.py'
        actions[-1]['plan']['suspected_files'][0]['file_path'] = 'ignored.py'
        stream = iter(actions)
        with self.assertRaises(ValueError):
            plan_repair('bug', self.root, commit, completion=lambda _: json.dumps(next(stream)), max_steps=3)

    def test_git_pathspec_is_literal(self):
        (self.root / 'x1.py').write_text('tracked = True')
        subprocess.run(['git', '-C', str(self.root), 'add', 'x1.py'], check=True, capture_output=True)
        (self.root / 'x[1].py').write_text('untracked = True')
        self.assertTrue(is_tracked(self.root, 'x1.py'))
        self.assertFalse(is_tracked(self.root, 'x[1].py'))

    def test_windows_junction_escape(self):
        if os.name != 'nt':
            self.skipTest('Windows junction test')
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside)
            (target / 'outside.py').write_text('junction_marker')
            junction = self.root / 'junction'
            proc = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(target)], capture_output=True)
            if proc.returncode:
                self.skipTest('Junction creation not permitted')
            try:
                self.assertFalse(read_file(self.root, 'junction/outside.py')['ok'])
                self.assertEqual(search_repo(self.root, 'junction_marker')['matches'], [])
            finally:
                os.rmdir(junction)

    def test_commit_validation(self):
        self.assertEqual(validate_repository(self.root, self.commit)['base_commit'], self.commit)
        with patch('utils.repo_tools.subprocess.run', wraps=subprocess.run) as call:
            validate_repository(self.root, self.commit)
            self.assertTrue(all('core.fsmonitor=false' in c.args[0] for c in call.call_args_list))
        with self.assertRaises(ValueError):
            validate_repository(self.root, '--help')
        (self.root / 'calc.py').write_text('changed')
        with self.assertRaises(ValueError):
            validate_repository(self.root, self.commit)

    def responses(self):
        return [
            {'action': 'search_repo', 'arguments': {'query': 'divide'}},
            {'action': 'read_file', 'arguments': {'relative_path': 'calc.py', 'start_line': 1, 'end_line': 2}},
            {'action': 'final', 'plan': {
                'issue_summary': 'Division loses fractional part',
                'suspected_files': [{'file_path': 'calc.py', 'relevant_lines': [1, 2], 'reason': 'Uses floor division', 'evidence_ids': ['E2']}],
                'root_cause_hypothesis': 'Floor division may cause truncation',
                'planned_changes': ['Replace floor division with true division'],
                'limitations': ['Hypothesis has not been execution-tested']}}]

    def test_planner_localization(self):
        actions = iter(self.responses())
        result = plan_repair('divide(3, 2) should return 1.5', self.root, self.commit,
                             completion=lambda messages: json.dumps(next(actions)))
        self.assertEqual(result['suspected_files'][0]['file_path'], 'calc.py')
        self.assertEqual(result['base_commit'], self.commit)
        self.assertIn('a // b', result['evidence'][1]['result']['lines'][1]['text'])
        self.assertEqual((self.root / 'calc.py').read_text(), 'def divide(a, b):\n    return a // b\n')

    def test_planner_repeated_action_is_not_rerun(self):
        first, read, final = self.responses()
        actions = iter([first, read, first, final])
        seen = []
        def completion(messages):
            seen.append(list(messages))
            return json.dumps(next(actions))
        result = plan_repair('divide(3, 2) should return 1.5', self.root, self.commit, completion=completion)
        self.assertEqual(len(result['evidence']), 2)
        self.assertIn('Repeated action', seen[3][-1]['content'])
        self.assertIn('return the final plan', seen[3][-1]['content'])

    def test_planner_rejects_unsupported_evidence_and_budget(self):
        final = self.responses()[-1]
        with self.assertRaises(ValueError):
            plan_repair('bug', self.root, self.commit, completion=lambda _: json.dumps(final), max_steps=2)
        with self.assertRaises(ValueError):
            plan_repair('bug', self.root, self.commit, completion=lambda _: 'invalid json', max_steps=2)

    def test_planner_rejects_fabricated_line_and_recovers_json(self):
        actions = self.responses()
        actions[-1]['plan']['suspected_files'][0]['relevant_lines'] = [1, 99]
        stream = iter(actions)
        with self.assertRaises(ValueError):
            plan_repair('bug', self.root, self.commit, completion=lambda _: json.dumps(next(stream)), max_steps=3)
        stream = iter(['not json'] + [json.dumps(a) for a in self.responses()])
        result = plan_repair('bug', self.root, self.commit, completion=lambda _: next(stream))
        self.assertFalse(result['execution_verified'])

    def test_no_evidence_plan_is_explicit(self):
        actions = [self.responses()[0], {'action': 'final', 'plan': {
            'issue_summary': 'unclear bug', 'suspected_files': [],
            'root_cause_hypothesis': 'Insufficient evidence', 'planned_changes': [],
            'limitations': ['No relevant code was identified']}}]
        stream = iter(actions)
        result = plan_repair('unknown', self.root, self.commit, completion=lambda _: json.dumps(next(stream)))
        self.assertEqual(result['suspected_files'], [])


class DemoRegression(unittest.TestCase):
    def test_save_code_utf8(self):
        from code_agent import save_code
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'example.py'
            save_code('# Unicode: \u03bb', path)
            self.assertEqual(path.read_text(encoding='utf8'), '# Unicode: \u03bb')

    def test_all_pages_are_english(self):
        import re
        import app as web
        for route in ('/', '/localize'):
            html = web.app.test_client().get(route).get_data(as_text=True)
            self.assertIn('lang="en"', html)
            self.assertIsNone(re.search(r'[\u3400-\u9fff]', html))

    def test_review_returns_report(self):
        from test_agent import test_and_improve_code
        with patch('test_agent.score_code', return_value=dict.fromkeys(('correctness', 'readability', 'efficiency', 'style'), 9)):
            report = test_and_improve_code('def f(): return 1', 'example')
        self.assertIsInstance(report, str)
        self.assertIn('no improvement', report)

    def test_invalid_score_is_reported(self):
        from test_agent import score_code
        from types import SimpleNamespace
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='not JSON'))])
        with patch('test_agent.get_client') as client:
            client.return_value.chat.completions.create.return_value = response
            with self.assertRaises(ValueError):
                score_code('def f(): return 1')

    def test_recursion_metric(self):
        from evaluator import analyze_code_quality
        self.assertFalse(analyze_code_quality('def f():\n    return 1')['contains_recursion'])
        self.assertTrue(analyze_code_quality('def f(n):\n    return f(n-1)')['contains_recursion'])

    def test_original_demo(self):
        import app as web
        c = web.app.test_client()
        self.assertEqual(c.get('/').status_code, 200)
        self.assertEqual(c.get('/localize').status_code, 200)
        self.assertEqual(c.post('/localize', data={}).status_code, 400)
        with patch.object(web, 'correct_and_refine_prompt', return_value='refined'), patch.object(web, 'classify_prompt', return_value='other'), patch.object(web, 'generate_code', return_value='def f(): return 1'), patch.object(web, 'test_and_improve_code', return_value='review'):
            r = c.post('/', data={'prompt': 'demo'})
            self.assertEqual(r.status_code, 200)
            self.assertIn(b'def f()', r.data)
            self.assertIn(b'review', r.data)


if __name__ == '__main__':
    unittest.main()
