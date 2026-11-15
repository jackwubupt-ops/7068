# Code cleanup review — 2026-11-15

## Removed or simplified

| Finding | Action | Reason |
| --- | --- | --- |
| Unused `os`/`openai` imports | Removed | No runtime purpose |
| `utils/log_utils.py` has no callers and writes malformed JSON | Removed | Dead implementation, not a functioning logging system |
| Manual global stdout capture in Flask | Replaced with returned report | Less state and no cross-request output capture |
| Model score errors silently become four zeros | Removed fallback | Hides an actual failure and triggers an unjustified improvement call |
| Parent output directory created twice | Kept creation in `save_code` only | One responsibility |
| File saving uses separate dirname/open handling | Replaced with `Path` | Handles UTF-8 and bare filenames directly |
| Recursion regex matches the function definition | Replaced with AST call inspection | Fixes the observed false positive; remains a heuristic |
| Empty/stale comments and commented CSS | Removed | No behavior or explanatory value |
| API key checked both in config and SDK | Kept SDK validation only | No duplicate credential validation |
| File size checked before and after bounded read | Kept bounded read and its limit check | Same memory cap with one check |

## Deliberately retained

- Path, symlink/junction and tracked-file checks implement the Task 1 contract.
- Read/search/output/action limits prevent unbounded file and model context use.
- Planner JSON and evidence validation protect the Coder handoff from malformed model output.
- Search fallback lets the demo run where ripgrep is not installed.
- Legacy entry points, visualization scripts and experiment data remain part of the project.
- The localization web route and CLI present operational errors. The original generation route still propagates API/JSON errors as failed requests rather than fabricating scores.

No new Agent framework, compatibility layer or generic abstraction was added.
The original `language='zh'` option is retained for Python callers, while the
web default requests English. User-supplied Issue text and source code are not
translated or altered by the interface.

## Remaining limitations

- Recursion metrics are heuristic; nested scopes and aliasing are not a full semantic analysis.
- LLM scoring still requires the requested JSON structure; invalid responses surface as errors.
- Repository inspection assumes a static local working tree, as described in `task1.md`.
- Real model quality and SWE-bench outcomes require separate evaluation.

This review supersedes the old stdout/metric/logging limitation notes in the
Task 1 baseline document. See CHANGELOG.md for the interface change.
