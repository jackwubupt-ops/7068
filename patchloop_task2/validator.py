"""Strict, bounded parser for a deliberately small subset of text unified diffs.

Only modifications to existing, tracked regular files are supported in Task 2.
Complex edits (renames, deletions, additions, modes, binary/submodule) can be
added later with separate policies and tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re


class PatchValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PatchInfo:
    paths: tuple[str, ...]
    hunk_count: int
    byte_count: int


_HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?:.*)?$")
_INDEX = re.compile(r"^index [0-9a-fA-F]{4,64}\.\.[0-9a-fA-F]{4,64}(?: 100[0-7]{3})?$")


def _check_path(value: str) -> None:
    if (
        not value
        or len(value) > 240
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or "\r" in value
    ):
        raise PatchValidationError("unsafe_path", f"Non-portable or unsafe path: {value!r}")
    chunks = value.split("/")
    if any(c in {"", ".", "..", ".git", ".gitmodules", ".gitattributes"} for c in chunks):
        raise PatchValidationError("unsafe_path", f"Forbidden path segment: {value!r}")
    if PurePosixPath(value).is_absolute():
        raise PatchValidationError("unsafe_path", f"Absolute path: {value!r}")


def validate_patch(
    patch: str,
    tracked_regular_paths: set[str],
    *,
    max_bytes: int = 120_000,
    max_files: int = 5,
    max_hunks: int = 60,
) -> PatchInfo:
    if not isinstance(patch, str) or not patch:
        raise PatchValidationError("empty_patch", "Patch is empty")
    encoded = patch.encode("utf-8")
    if len(encoded) > max_bytes:
        raise PatchValidationError("patch_too_large", f"Patch exceeds {max_bytes} bytes")
    if "\x00" in patch or "\r" in patch:
        raise PatchValidationError("invalid_patch", "NUL/CR are not accepted in text patches")
    if not patch.endswith("\n"):
        raise PatchValidationError("invalid_patch", "Patch must end in newline")

    paths: list[str] = []
    active: str | None = None
    old_seen = new_seen = in_hunk = False
    hunks = 0
    for lineno, line in enumerate(patch.splitlines(), start=1):
        if len(line) > 2000:
            raise PatchValidationError("patch_too_large", f"Overlong line {lineno}")
        if line.startswith("diff --git "):
            if active is not None and not (old_seen and new_seen and in_hunk):
                raise PatchValidationError("invalid_patch", "Previous file has no complete hunk")
            match = _HEADER.fullmatch(line)
            if not match or match[1] != match[2]:
                raise PatchValidationError("unsupported_patch", "Only unquoted same-path modifications supported")
            active = match[1]
            _check_path(active)
            if active not in tracked_regular_paths:
                raise PatchValidationError("unsafe_path", f"Not a tracked regular file: {active}")
            if active in paths:
                raise PatchValidationError("invalid_patch", "File repeated in patch")
            paths.append(active)
            if len(paths) > max_files:
                raise PatchValidationError("patch_too_large", "Too many changed files")
            old_seen = new_seen = in_hunk = False
            continue

        if active is None:
            raise PatchValidationError("invalid_patch", f"Expected diff --git header at line {lineno}")

        if not old_seen:
            if line.startswith("index ") and _INDEX.fullmatch(line):
                continue
            if line == f"--- a/{active}":
                old_seen = True
                continue
            raise PatchValidationError("unsupported_patch", f"Unexpected extended header on line {lineno}")
        if not new_seen:
            if line == f"+++ b/{active}":
                new_seen = True
                continue
            raise PatchValidationError("invalid_patch", f"Expected +++ b/{active} at line {lineno}")
        if line.startswith("@@ "):
            if not _HUNK.fullmatch(line):
                raise PatchValidationError("invalid_patch", f"Invalid hunk header on line {lineno}")
            in_hunk = True
            hunks += 1
            if hunks > max_hunks:
                raise PatchValidationError("patch_too_large", "Too many hunks")
            continue
        if in_hunk and line.startswith((" ", "+", "-")):
            continue
        if in_hunk and line == r"\ No newline at end of file":
            continue
        raise PatchValidationError("invalid_patch", f"Unexpected patch content on line {lineno}")

    if not (old_seen and new_seen and in_hunk):
        raise PatchValidationError("invalid_patch", "Incomplete patch")
    return PatchInfo(tuple(paths), hunks, len(encoded))
