#!/usr/bin/env python3
"""
Guard against a pulled translation introducing markup that isn't present in
the source string.

Django's `{% blocktranslate %}` only escapes interpolated variables, not the
literal text of the translated string - so a msgstr can contain arbitrary
HTML that renders unescaped. A msgid with no markup at all can still have
markup added to its msgstr, so this checks every entry, not just ones whose
source already contains a tag.

Runs standalone (no Django settings needed) so it's cheap to call as a CI
step against exactly the .po files a pull-translations job just wrote,
before they're committed to a PR.

Usage:
    uv run python .github/scripts/check_translation_markup.py [PO_FILE ...]

With no arguments, checks every locale/*/LC_MESSAGES/*.po file.
"""

import re
import sys
from pathlib import Path

from babel.messages.pofile import read_po

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GLOB = "hypha/locale/*/LC_MESSAGES/*.po"

HTML_TAG_RE = re.compile(r"<[^>]*>")


def normalise(tag: str) -> str:
    """Collapse incidental whitespace differences so they don't trigger false positives."""
    return re.sub(r"\s+", " ", tag).strip()


def extract_tags(strings) -> set:
    """Return the set of normalised HTML-tag-like substrings found in `strings`.

    Args:
        strings (str | tuple[str, ...]): a single string, or a tuple of
            strings (plural forms).

    Returns:
        set: every normalised HTML-tag-like substring found.
    """
    if isinstance(strings, str):
        strings = (strings,)

    tags = set()
    for value in strings:
        if not value:
            continue
        tags.update(normalise(tag) for tag in HTML_TAG_RE.findall(value))
    return tags


def check_file(path: Path) -> list:
    """Check a single .po file for translations that add markup not in the source.

    Args:
        path (Path): the .po file to check.

    Returns:
        list: a human-readable violation message per problem message found.
    """
    violations = []
    with path.open("rb") as po_file:
        catalog = read_po(po_file, abort_invalid=False)

    for message in catalog:
        if not message.id:
            # Skip the catalog header entry.
            continue

        source_tags = extract_tags(message.id)
        target_tags = extract_tags(message.string)
        new_tags = target_tags - source_tags

        if new_tags:
            location = f"{path}:{message.lineno}" if message.lineno else str(path)
            msgid_preview = message.id if isinstance(message.id, str) else message.id[0]
            violations.append(
                f"{location}: translation adds markup not in the source string "
                f"{sorted(new_tags)!r} (msgid: {msgid_preview!r})"
            )

    return violations


def main(argv: list) -> int:
    """Check the given .po files, or every locale/*/LC_MESSAGES/*.po file by default."""
    if argv:
        paths = [Path(arg) for arg in argv]
    else:
        paths = sorted(REPO_ROOT.glob(DEFAULT_GLOB))

    if not paths:
        print("No .po files found to check.")
        return 0

    violations = []
    for path in paths:
        violations.extend(check_file(path))

    print(f"Checked {len(paths)} .po file(s).")

    if violations:
        for violation in violations:
            print(f"::error::{violation}")
        print(
            f"\n{len(violations)} translation(s) introduce markup not present "
            "in the source string. Review before merging."
        )
        return 1

    print("No unexpected markup found in translations.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
