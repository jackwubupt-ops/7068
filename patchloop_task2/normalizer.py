"""Deterministically repair unified-diff HUNK COUNTS, never code content.

A model may produce valid intended +/- source lines but incorrect old/new
line-count metadata in the @@ header. Git rejects those as "corrupt patch".
This operator-controlled postprocessing only recounts hunk line metadata;
Git apply --check and tracked-file allowlists remain authoritative.
"""
from __future__ import annotations
import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


def normalize_hunk_counts(patch: str) -> tuple[str, int]:
    if not isinstance(patch, str) or not patch or len(patch.encode("utf-8")) > 120_000:
        raise ValueError("Patch must be bounded text")
    if "\x00" in patch or "\r" in patch or not patch.endswith("\n"):
        raise ValueError("Patch contains forbidden characters or lacks final newline")

    output = patch.splitlines(keepends=True)
    corrections = 0
    active = None
    old_count = new_count = 0

    def finish():
        nonlocal corrections, active, old_count, new_count
        if active is not None:
            index, old_start, new_start, suffix = active
            header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}\n"
            if output[index] != header:
                output[index] = header
                corrections += 1
        active = None
        old_count = new_count = 0

    for index, text in enumerate(output):
        if text.startswith("diff --git "):
            finish()
            continue
        if text.startswith("@@ "):
            finish()
            match = _HUNK.fullmatch(text.rstrip("\n"))
            if not match:
                raise ValueError(f"Malformed unified diff hunk header at line {index + 1}")
            active = (index, match.group(1), match.group(2), match.group(3))
            continue
        if active is not None:
            prefix = text[:1]
            if prefix == " ":
                old_count += 1
                new_count += 1
            elif prefix == "-":
                old_count += 1
            elif prefix == "+":
                new_count += 1
            elif text.startswith("\\ No newline at end of file"):
                pass
            else:
                raise ValueError(f"Invalid unified diff body at line {index + 1}")
    finish()
    return "".join(output), corrections
