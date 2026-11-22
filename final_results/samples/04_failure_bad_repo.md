# Sample 04_failure_bad_repo: failure case: invalid repository

The maintainer points the agent at a path that is not a Git repository.

**Expected:** failed with a clear message that the path is not a Git repository; no model calls, nothing exported.

## Session 1122-110458-5ef9 (round 1) -> `failed`

- model backend: `deepseek`, agent: `pcr`, retrieval_k: 10
- tokens: None prompt / None completion; duration: None s; run status: `None`

| t (s) | kind | step |
|---|---|---|
| 0.0 | error | Run failed |

