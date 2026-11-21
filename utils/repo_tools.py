"""Bounded, read-only repository inspection. No shell or repository code executes."""
import ast
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import time

IGNORED = {'.git', '.venv', 'venv', 'env', '__pycache__', 'node_modules',
           'dist', 'build', '.pytest_cache', '.mypy_cache', 'results', 'logs'}
MAX_FILE_BYTES = 262144
MAX_OUTPUT = 20000


def _error(exc):
    return {'ok': False, 'error': str(exc), 'truncated': False}


def _root(repo_root):
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Repository must be a directory')
    return root


def _allowed(parts):
    return not any(p.casefold() in IGNORED or p.casefold().startswith('.env') or p.casefold().endswith(('.pyc', '.log', '.pem', '.key')) for p in parts)


def _linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _lines(text):
    if not text:
        return []
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()
    return [line.removesuffix('\r') for line in lines]


def _path(root, relative):
    if not isinstance(relative, str) or not relative or '\x00' in relative:
        raise ValueError('Expected a relative file path')
    win = PureWindowsPath(relative)
    parts = relative.replace('\\', '/').split('/')
    if Path(relative).is_absolute() or win.drive or win.root or '..' in parts or ':' in relative:
        raise ValueError('Absolute paths and traversal are forbidden')
    if not _allowed(parts):
        raise ValueError('Excluded file')
    lexical = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if _linked(current):
            raise ValueError('Links and junctions are forbidden')
    resolved = lexical.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError('File must stay inside repository')
    return resolved


def _text(path):
    with path.open('rb') as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES or b'\x00' in data:
        raise ValueError('Oversized or binary file')
    return data.decode('utf-8-sig')


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer in [{low}, {high}]')


def action_key(name, arguments):
    """Canonical identity of a read-only tool call (after argument clamping)."""
    return name + ':' + json.dumps(arguments, sort_keys=True, ensure_ascii=False)


def repeated_action_message(name, first_step, finish_hint):
    """Same nudge for Planner and single agent (RQ3 parity) when a 7B model
    re-issues an identical call at temperature 0 instead of moving on."""
    return (f'Repeated action: this exact {name} call was already made at step {first_step} '
            'and its result is earlier in this conversation. It was not run again. '
            'Use that result, read a different line range or file, search a different '
            f'keyword, or {finish_hint}.')


def read_file(repo_root, relative_path, *, start_line=1, end_line=None):
    try:
        _integer(start_line, 1, 1000000, 'start_line')
        if end_line is not None:
            _integer(end_line, start_line, 1000000, 'end_line')
        root = _root(repo_root)
        path = _path(root, relative_path)
        lines = _lines(_text(path))
        if start_line > len(lines) and lines:
            raise ValueError('start_line exceeds file length')
        requested = min(end_line if end_line is not None else len(lines), len(lines))
        stop = min(requested, start_line + 199)
        output, size = [], 0
        for index in range(start_line - 1, stop):
            text = lines[index]
            if size + len(text) > MAX_OUTPUT:
                break
            output.append({'line_number': index + 1, 'text': text})
            size += len(text)
        return {'ok': True, 'file_path': path.relative_to(root).as_posix(),
                'lines': output, 'truncated': len(output) < max(0, requested - start_line + 1)}
    except (OSError, ValueError, TypeError) as exc:
        return _error(exc)


def _function(text, number):
    try:
        nodes = [n for n in ast.walk(ast.parse(text))
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.lineno <= number <= n.end_lineno]
        return max(nodes, key=lambda n: n.lineno).name if nodes else None
    except (SyntaxError, RecursionError):
        return None


def search_repo(repo_root, query, *, max_results=20, context_lines=3):
    try:
        if not isinstance(query, str) or not query.strip() or len(query) > 200 or '\n' in query or '\x00' in query:
            raise ValueError('query must contain 1-200 characters on one line')
        _integer(max_results, 1, 50, 'max_results')
        _integer(context_lines, 0, 5, 'context_lines')
        root = _root(repo_root)
        matches, size, scanned, total_bytes, directories = [], 0, 0, 0, 0
        truncated = False
        deadline = time.monotonic() + 10
        backend = 'ripgrep' if shutil.which('rg') else 'python'
        for directory, dirs, files in os.walk(root, followlinks=False):
            directories += 1
            if directories > 2000 or time.monotonic() > deadline:
                truncated = True
                break
            if len(dirs) > 2000:
                truncated = True
            dirs[:] = sorted(d for d in dirs[:2000] if _allowed([d]) and not _linked(Path(directory) / d)
                             and (Path(directory) / d).resolve().is_relative_to(root))
            if len(files) > 2000:
                truncated = True
            for filename in sorted(files[:2000]):
                scanned += 1
                if scanned > 2000 or total_bytes > 8 * 1024 * 1024 or time.monotonic() > deadline:
                    truncated = True
                    break
                relative = (Path(directory) / filename).relative_to(root).as_posix()
                try:
                    path = _path(root, relative)
                    text = _text(path)
                except (OSError, ValueError):
                    continue
                total_bytes += len(text.encode('utf8'))
                lines = _lines(text)
                if backend == 'ripgrep':
                    proc = subprocess.run(['rg', '--no-config', '--no-heading', '--color', 'never',
                                           '-n', '-F', '-m', str(max_results + 1), '-e', query, '--', str(path)],
                                          capture_output=True, timeout=max(.01, deadline - time.monotonic()))
                    if proc.returncode not in (0, 1):
                        raise ValueError('ripgrep search failed')
                    numbers = [int(line.split(b':', 1)[0]) for line in proc.stdout.splitlines()]
                else:
                    numbers = [i + 1 for i, line in enumerate(lines) if query in line]
                for number in numbers:
                    if len(matches) >= max_results:
                        truncated = True
                        break
                    snippet = '\n'.join(f'{i + 1}: {lines[i]}' for i in range(max(0, number - context_lines - 1), min(len(lines), number + context_lines)))
                    if size + len(snippet) > MAX_OUTPUT:
                        truncated = True
                        break
                    matches.append({'file_path': relative, 'line_number': number,
                                    'snippet': snippet, 'function': _function(text, number) if path.suffix == '.py' else None})
                    size += len(snippet)
                if truncated:
                    break
            if truncated:
                break
        return {'ok': True, 'matches': matches, 'truncated': truncated, 'backend': backend}
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        return _error(exc)


# Arguments each agent tool accepts (shared by the Planner and the single agent).
TOOL_ARGUMENTS = {
    'search_repo': {'query', 'max_results', 'context_lines'},
    'read_file': {'relative_path', 'start_line', 'end_line'},
    'list_directory': {'relative_path'},
    'find_definition': {'name', 'max_results'},
}
MAX_LISTING = 100
MAX_DEFINITION_FILES = 5000
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,99}')


def _tracked_files(root):
    proc = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), 'ls-files', '-z'],
                          capture_output=True, timeout=10)
    if proc.returncode:
        raise ValueError('Could not list tracked files')
    names = [n for n in proc.stdout.decode('utf-8', 'replace').split('\0') if n]
    return [n for n in names if _allowed(n.split('/'))]


def list_directory(repo_root, relative_path='.'):
    """Tracked entries directly under a directory: sub-directories with their file
    counts, then files. Shows the layout of the repository without reading code."""
    try:
        root = _root(repo_root)
        if not isinstance(relative_path, str) or '\x00' in relative_path:
            raise ValueError('Expected a relative directory path')
        prefix = relative_path.replace('\\', '/').strip('/')
        if prefix in ('', '.'):
            prefix = ''
        else:
            parts = prefix.split('/')
            win = PureWindowsPath(relative_path)
            if Path(relative_path).is_absolute() or win.drive or win.root or '..' in parts or ':' in relative_path:
                raise ValueError('Absolute paths and traversal are forbidden')
            if not _allowed(parts):
                raise ValueError('Excluded directory')
        dirs, files = {}, []
        for name in _tracked_files(root):
            if prefix:
                if not name.startswith(prefix + '/'):
                    continue
                rest = name[len(prefix) + 1:]
            else:
                rest = name
            head, sep, _ = rest.partition('/')
            if sep:
                dirs[head] = dirs.get(head, 0) + 1
            else:
                files.append(head)
        if not dirs and not files:
            raise ValueError('No tracked files under this directory')
        entries = ([{'name': d + '/', 'type': 'directory', 'tracked_files': n} for d, n in sorted(dirs.items())]
                   + [{'name': f, 'type': 'file'} for f in sorted(files)])
        return {'ok': True, 'directory': prefix or '.', 'entries': entries[:MAX_LISTING],
                'truncated': len(entries) > MAX_LISTING}
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        return _error(exc)


def _definitions(text, name):
    """(qualified name, kind, start, end, signature line) for every def/class called name."""
    out = []
    lines = text.split('\n')

    def visit(node, scope, in_class):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_class = isinstance(child, ast.ClassDef)
                if child.name == name:
                    kind = 'class' if is_class else ('method' if in_class else 'function')
                    signature = lines[child.lineno - 1].strip()[:200] if child.lineno <= len(lines) else ''
                    out.append(('.'.join([*scope, child.name]), kind, child.lineno, child.end_lineno, signature))
                visit(child, [*scope, child.name], is_class)
            else:
                visit(child, scope, in_class)
    visit(ast.parse(text), [], False)
    return out


def find_definition(repo_root, name, *, max_results=10):
    """Where a Python class, function or method called `name` is defined
    (tracked .py files, parsed with ast; nothing is imported or executed)."""
    try:
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            raise ValueError('name must be a single Python identifier, e.g. "Field" or "deserialize"')
        _integer(max_results, 1, 20, 'max_results')
        root = _root(repo_root)
        pattern = re.compile(r'^\s*(?:async\s+def|def|class)\s+' + re.escape(name) + r'\b', re.M)
        found, scanned, truncated = [], 0, False
        deadline = time.monotonic() + 15
        for relative in _tracked_files(root):
            if not relative.endswith('.py'):
                continue
            scanned += 1
            if scanned > MAX_DEFINITION_FILES or time.monotonic() > deadline:
                truncated = True
                break
            try:
                text = _text(_path(root, relative))
            except (OSError, ValueError):
                continue
            if not pattern.search(text):
                continue
            try:
                hits = _definitions(text, name)
            except (SyntaxError, RecursionError, ValueError):
                continue
            for qualified, kind, start, end, signature in hits:
                found.append({'file_path': relative, 'qualified_name': qualified, 'kind': kind,
                              'start_line': start, 'end_line': end, 'signature': signature})
        found.sort(key=lambda d: (d['file_path'].count('/') if 'test' not in d['file_path'] else 99, d['file_path'], d['start_line']))
        return {'ok': True, 'name': name, 'definitions': found[:max_results],
                'truncated': truncated or len(found) > max_results}
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        return _error(exc)


AGENT_TOOLS = {'search_repo': search_repo, 'read_file': read_file,
               'list_directory': list_directory, 'find_definition': find_definition}


def validate_repository(repo_root, base_commit):
    root = _root(repo_root)
    if not isinstance(base_commit, str) or not re.fullmatch(r'[0-9a-fA-F]{7,40}', base_commit):
        raise ValueError('base_commit must be a 7-40 digit commit SHA')
    def git(*args):
        result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args], capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ValueError('Git repository or commit is invalid')
        return result.stdout.strip()
    if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('Use repository root, not a subdirectory')
    commit = git('rev-parse', '--verify', base_commit + '^{commit}')
    if git('rev-parse', 'HEAD') != commit or git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Repository must be clean and HEAD must match base_commit; no checkout performed')
    return {'repo_root': str(root), 'base_commit': commit}


def is_tracked(repo_root, relative_path):
    """Used by Planner: ignore local files that are absent from the commit."""
    root = _root(repo_root)
    try:
        path = _path(root, relative_path)
    except (OSError, ValueError):
        return False
    proc = subprocess.run(['git', '--literal-pathspecs', '-c', 'core.fsmonitor=false', '-C', str(root),
                           'ls-files', '--error-unmatch', '--', path.relative_to(root).as_posix()],
                          capture_output=True, timeout=10)
    return proc.returncode == 0
