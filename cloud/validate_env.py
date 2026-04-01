#!/usr/bin/env python3
"""Environment variable validator for AUTO-REELS runtime modes."""

from __future__ import annotations

import argparse
import os
import sys


def _is_set(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value)


def _check(mode: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []

    common_required = [
        "ENVIRONMENT",
    ]

    for key in common_required:
        if not _is_set(key):
            failures.append(f"{key} is missing")

    if mode == "real-run":
        real_required = [
            "FB_PAGE_ID",
            "FB_PAGE_ACCESS_TOKEN",
        ]
        for key in real_required:
            if not _is_set(key):
                failures.append(f"{key} is missing")

    if not _is_set("ANTHROPIC_API_KEY"):
        warnings.append("ANTHROPIC_API_KEY missing (free-mode fallback may be used)")

    return failures, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AUTO-REELS environment variables")
    parser.add_argument(
        "--mode",
        choices=["dry-run", "real-run"],
        default="dry-run",
        help="Validation mode",
    )
    args = parser.parse_args()

    failures, warnings = _check(args.mode)

    print(f"=== ENV VALIDATION ({args.mode}) ===")
    if failures:
        print("Result: FAIL")
        for item in failures:
            print(f"  - {item}")
    else:
        print("Result: OK")

    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"  - {item}")

    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
