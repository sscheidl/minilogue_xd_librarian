"""Increment the displayed app version before packaging a build."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


VERSION_PATTERN = re.compile(r'(APP_VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(")')


def bump_version_text(text: str) -> tuple[str, str, str]:
    match = VERSION_PATTERN.search(text)
    if not match:
        raise ValueError("APP_VERSION assignment not found")
    major, minor, patch = (int(match.group(2)), int(match.group(3)), int(match.group(4)))
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{patch + 1}"
    return VERSION_PATTERN.sub(rf"\g<1>{new_version}\g<5>", text, count=1), old_version, new_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Increment app/version.py patch version.")
    parser.add_argument("--dry-run", action="store_true", help="Print the next version without writing it.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    version_path = repo_root / "app" / "version.py"
    text = version_path.read_text(encoding="utf-8")
    updated, old_version, new_version = bump_version_text(text)
    if not args.dry_run:
        version_path.write_text(updated, encoding="utf-8")
    action = "would bump" if args.dry_run else "bumped"
    print(f"Build version {action}: {old_version} -> {new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
