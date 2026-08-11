"""Fail when a GitHub alpha release tag does not match package metadata."""

from __future__ import annotations

import re
import sys

from agent_os import __version__


def release_tag(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", version)
    if match is None:
        raise ValueError(f"release automation currently supports alpha versions only: {version}")
    return f"v{match.group(1)}-alpha.{match.group(2)}"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_release.py TAG")
    expected = release_tag(__version__)
    actual = sys.argv[1]
    if actual != expected:
        raise SystemExit(f"release tag {actual!r} does not match package version {expected!r}")
    print(f"release tag matches package version: {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
