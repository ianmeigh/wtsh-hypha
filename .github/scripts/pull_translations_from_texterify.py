#!/usr/bin/env python3
"""
Download the latest translations from Texterify and extract them into locale/
(replaces txty-cli's `download` command, which does nothing more than one GET
plus unzipping the result).

Required environment variables:
    TXTY_AUTH_EMAIL, TXTY_AUTH_SECRET  - from the Texterify access token page
    TXTY_PROJECT_ID                    - the Texterify project id
    TXTY_EXPORT_CONFIG_ID              - which export config to download

Optional environment variables:
    TXTY_EXPORT_DIRECTORY - where to extract the downloaded files
        (default: hypha/locale)
"""

import io
import os
import sys
import zipfile

from texterify_api import PROJECT_ID, api_url, make_session

EXPORT_CONFIG_ID = os.environ["TXTY_EXPORT_CONFIG_ID"]
EXPORT_DIRECTORY = os.environ.get("TXTY_EXPORT_DIRECTORY", "hypha/locale")


def download_export(session) -> bytes:
    """Download the project's export .zip from Texterify and return its raw bytes."""
    response = session.get(api_url(f"projects/{PROJECT_ID}/exports/{EXPORT_CONFIG_ID}"))
    response.raise_for_status()
    return response.content


def extract(zip_bytes: bytes) -> list:
    """Extract every real file in the archive into EXPORT_DIRECTORY.

    Not archive.extractall(): Texterify's export zip includes at least one
    structural entry (a blank root, "." / "./" marker, or similar - the
    exact filename varies) whose path has no real components once zipfile
    normalises it. zipfile raises ValueError("Empty filename.") on these
    instead of skipping them, and there's more than one filename shape that
    triggers it (confirmed live: a plain "" entry was fixed, then a second,
    differently-named entry hit the same error) - so rather than guess at
    every variant a zip writer might produce, catch the specific failure
    per member and skip just that entry.

    Args:
        zip_bytes (bytes): the raw export archive, as downloaded.

    Returns:
        list: path of every real file extracted, relative to EXPORT_DIRECTORY.
    """
    extracted = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        for member in archive.infolist():
            try:
                archive.extract(member, EXPORT_DIRECTORY)
            except ValueError as exc:
                print(f"  skipping non-file zip entry {member.filename!r}: {exc}")
                continue
            if not member.is_dir():
                extracted.append(member.filename)
    return extracted


def main() -> int:
    """Download and extract the latest translations from Texterify."""
    session = make_session()

    print(f"Downloading export {EXPORT_CONFIG_ID} for project {PROJECT_ID}...")
    zip_bytes = download_export(session)

    print(f"Extracting to {EXPORT_DIRECTORY}...")
    extracted = extract(zip_bytes)
    for name in extracted:
        print(f"  {name}")

    print(f"Done - extracted {len(extracted)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
