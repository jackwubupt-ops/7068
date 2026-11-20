"""Rank a repository's Python files for an issue, before any model call.

Used to hand both agents (P-C-R Planner and single agent) the same short list
of starting files, so 7B localization does not depend on guessing search
keywords. Inputs are ONLY the issue text and the repository at the base commit
(tracked files); no benchmark labels. Deterministic, pure Python, no new
dependencies.

score(file) = BM25(issue tokens, path + content tokens), normalized to [0, 1]
            + 2.0  if the issue names this file's path (a "x/y.py" mention or a
                   traceback line), matched as a path suffix
            + 1.0  if the issue names it as a dotted module (pkg.mod -> pkg/mod.py)
            + up to 1.0 for issue identifiers (CamelCase / snake_case / >= 4 chars)
                   that this file DEFINES as a def/class
then x 0.5 for test files (tests usually check the bug rather than contain it).
"""
from __future__ import annotations

from collections import Counter
import keyword
import math
from pathlib import Path
import re
import subprocess

MAX_FILE_BYTES = 400_000
TEST_FACTOR = 0.5
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_PATH_MENTION = re.compile(r"[\w./\\-]+\.py\b")
_DEF = re.compile(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)", re.M)
_DOTTED = re.compile(r"\b[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*){1,}\b")
_STOP = set(keyword.kwlist) | {
    "self", "none", "true", "false", "the", "and", "for", "with", "this", "that", "from",
    "when", "not", "are", "but", "have", "has", "was", "can", "should", "would", "could",
    "use", "using", "get", "set", "new", "file", "line", "lines", "error", "issue", "python",
    "return", "value", "values", "data", "test", "tests", "code", "example", "expected",
    "actual", "result", "results", "here", "there", "what", "which", "also", "like", "into",
    "will", "does", "only", "some", "more", "than", "then", "just", "one", "two", "see",
}


def tokens(text: str) -> list[str]:
    """Identifiers plus their snake_case / CamelCase parts, lower-cased."""
    out = []
    for ident in _IDENT.findall(text):
        low = ident.lower()
        if len(low) >= 2 and low not in _STOP:
            out.append(low)
        parts = [p.lower() for chunk in ident.split("_") for p in _CAMEL.findall(chunk)]
        if len(parts) > 1:
            out.extend(p for p in parts if len(p) >= 3 and p not in _STOP)
    return out


def tracked_python_files(repo_root: str | Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.fsmonitor=false", "ls-files", "-z", "--", "*.py"],
        capture_output=True, timeout=60, check=True,
    )
    return sorted(p for p in result.stdout.decode("utf-8", "replace").split("\0") if p)


def is_test_path(path: str) -> bool:
    parts = path.lower().split("/")
    name = parts[-1]
    return (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
            or any(p in {"test", "tests", "testing"} for p in parts[:-1]))


def _issue_hints(issue: str) -> tuple[set[str], set[str], set[str]]:
    paths = {m.replace("\\", "/").lstrip("./") for m in _PATH_MENTION.findall(issue)}
    modules = {m.replace(".", "/") for m in _DOTTED.findall(issue)
               if not m.lower().endswith((".py", ".txt", ".md", ".rst", ".cfg", ".toml", ".json"))}
    names = {i for i in _IDENT.findall(issue)
             if i.lower() not in _STOP and (len(i) >= 4 or "_" in i or any(c.isupper() for c in i[1:]))}
    return paths, modules, names


def _path_suffix_match(path: str, mention: str) -> bool:
    mention = mention.strip("/")
    return bool(mention) and (path == mention or path.endswith("/" + mention))


def _module_match(path: str, module: str) -> bool:
    for cand in (module + ".py", module + "/__init__.py"):
        if path == cand or path.endswith("/" + cand):
            return True
    return False


def rank_files(repo_root: str | Path, issue: str, k: int = 10) -> list[dict]:
    """Top-k tracked .py files: [{"file_path", "score", "why": [...]}], best first."""
    if not isinstance(issue, str) or not issue.strip():
        raise ValueError("Issue text is required")
    if type(k) is not int or not 1 <= k <= 50:
        raise ValueError("k must be in [1, 50]")
    root = Path(repo_root)
    files = tracked_python_files(root)
    query = Counter(tokens(issue))
    if not files:
        return []
    docs, defs = {}, {}
    for path in files:
        try:
            raw = (root / path).read_bytes()[:MAX_FILE_BYTES]
        except OSError:
            continue
        text = raw.decode("utf-8", "replace")
        defs[path] = set(_DEF.findall(text))
        docs[path] = Counter(tokens(path.replace("/", " ") + " ") * 2 + tokens(text))
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs.values()) / max(n, 1)
    df = Counter(t for d in docs.values() for t in d)
    bm25 = {}
    for path, doc in docs.items():
        length = sum(doc.values())
        score = 0.0
        for term in query:
            tf = doc.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / max(avg, 1)))
        bm25[path] = score
    top = max(bm25.values(), default=0.0) or 1.0
    paths, modules, names = _issue_hints(issue)
    ranked = []
    for path in docs:
        why = []
        score = bm25[path] / top
        if any(_path_suffix_match(path, m) for m in paths):
            score += 2.0
            why.append("path named in issue")
        if any(_module_match(path, m) for m in modules):
            score += 1.0
            why.append("module named in issue")
        defined = sorted(names & defs[path])
        if defined:
            score += min(len(defined), 3) / 3
            why.append("defines " + ", ".join(defined[:3]))
        if is_test_path(path):
            score *= TEST_FACTOR
            why.append("test file")
        if bm25[path] > 0:
            why.append("keyword match")
        ranked.append({"file_path": path, "score": round(score, 4), "why": why})
    ranked.sort(key=lambda item: (-item["score"], item["file_path"]))
    return [item for item in ranked[:k] if item["score"] > 0]


def candidate_message_fields(candidates: list[dict]) -> dict:
    """The fields added to the agents' first user message (same for both agents)."""
    return {
        "candidate_files": [{"file_path": c["file_path"], "why": c["why"]} for c in candidates],
        "candidate_files_note": ("Ranked by keyword retrieval over the repository at the base "
                                 "commit; unverified. Read the most relevant ones first, and "
                                 "search further if none of them fits the issue."),
    }
