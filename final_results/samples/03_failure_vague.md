# Sample 03_failure_vague: failure case: under-specified request

The maintainer only writes 'it is broken'. The agent must not guess.

**Expected:** needs_clarification with questions, and ZERO model calls.

## Session 1122-110458-ab28 (round 1) -> `needs_clarification`

- model backend: `deepseek`, agent: `pcr`, retrieval_k: 10
- tokens: None prompt / None completion; duration: None s; run status: `None`

Questions asked:

- The issue is very short. What exactly goes wrong, and what did you expect instead?

| t (s) | kind | step |
|---|---|---|
| 0.0 | info | Repository sqlfluff/sqlfluff at 14e1a23a31 |
| 0.6 | tool | retrieval -> 10 candidate files |
| 0.6 | stop | Stopped to ask for clarification before using the model |

