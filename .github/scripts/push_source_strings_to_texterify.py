#!/usr/bin/env python3
"""
Push hypha/locale/en/LC_MESSAGES/django.po to Texterify via its API (txty-cli has
no bulk push/import command, only `download` and `add`).

Overwrites the source language's content unconditionally. This is safe for the source
locale (English) as its msgstr is always blank, with no authored content. Please note
the same call would clobber authored work for any other language.

Import is additive only, but a key removed from the codebase is reported as an orphan
after every push, and can be removed from Texterify if the `TXTY_PRUNE_ORPHAN_KEYS` var
is set (see report_orphan_keys method).

Required environment variables:
    TXTY_AUTH_EMAIL, TXTY_AUTH_SECRET  - from the Texterify access token page
    TXTY_PROJECT_ID                    - the Texterify project id

Optional environment variables:
    TXTY_SOURCE_LANGUAGE_NAME - how the source language is named in the
        Texterify project's Languages settings (default: "en")
    TXTY_SOURCE_PO_FILE - path to the .po file to push
        (default: hypha/locale/en/LC_MESSAGES/django.po)
    TXTY_PRUNE_ORPHAN_KEYS - set to "true" to actually delete orphan keys
        found after the push, instead of just reporting them (default: unset)
"""

import os
import sys
import time

import requests
from babel.messages.pofile import read_po
from texterify_api import PROJECT_ID, api_url, make_session

SOURCE_LANGUAGE_NAME = os.environ.get("TXTY_SOURCE_LANGUAGE_NAME") or "en"
PO_FILE_PATH = os.environ.get(
    "TXTY_SOURCE_PO_FILE", "hypha/locale/en/LC_MESSAGES/django.po"
)

# ~5 minutes timeout per background job. Sized against translations-push.yml's job-level
# timeout-minutes, which budgets for both calls plus setup overhead. An increase here
# should be reflected in the config.
POLL_INTERVAL_SECONDS = 10
POLL_MAX_ATTEMPTS = 30


def create_import(session: requests.Session) -> str:
    """Upload PO_FILE_PATH to Texterify and return the new import's id."""
    with open(PO_FILE_PATH, "rb") as po_file:
        response = session.post(
            api_url(f"projects/{PROJECT_ID}/imports"),
            files={"files[]": (os.path.basename(PO_FILE_PATH), po_file, "text/x-po")},
        )
    response.raise_for_status()
    return response.json()["data"]["id"]


def get_import_file_id(session: requests.Session, import_id: str) -> str:
    """Return the id of the single file attached to an import.

    Args:
        session (requests.Session): authenticated Texterify API session.
        import_id (str): id of the import to look up.

    Raises:
        RuntimeError: if the import has anything other than exactly one
            file - this script only ever uploads one, so more than one
            indicates an unexpected response shape.

    Returns:
        str: id of the import's single attached file.
    """
    response = session.get(
        api_url(f"projects/{PROJECT_ID}/imports/{import_id}/import_files")
    )
    response.raise_for_status()
    files = response.json()["data"]
    if len(files) != 1:
        raise RuntimeError(
            f"Expected exactly one import file, found {len(files)}: {files}"
        )
    return files[0]["id"]


def get_source_language_id(session: requests.Session) -> str:
    """Return the Texterify id of the project's source language.

    Matches SOURCE_LANGUAGE_NAME against each language's "name" attribute.

    Args:
        session (requests.Session): authenticated Texterify API session.

    Raises:
        RuntimeError: if no language in the project has that name.

    Returns:
        str: id of the matching language.
    """
    response = session.get(api_url(f"projects/{PROJECT_ID}/languages"))
    response.raise_for_status()
    for language in response.json()["data"]:
        if language["attributes"]["name"] == SOURCE_LANGUAGE_NAME:
            return language["id"]
    raise RuntimeError(
        f'No language named "{SOURCE_LANGUAGE_NAME}" found in project {PROJECT_ID}. '
        "Set TXTY_SOURCE_LANGUAGE_NAME to match how it's named in Texterify."
    )


def get_po_file_format_id(session: requests.Session) -> str:
    """Return Texterify's id for the "po" file format.

    Args:
        session (requests.Session): authenticated Texterify API session.

    Raises:
        RuntimeError: if no such format is registered on this instance.

    Returns:
        str: id of the "po" file format.
    """
    response = session.get(api_url("file_formats"))
    response.raise_for_status()
    for file_format in response.json()["data"]:
        if file_format["attributes"]["format"] == "po":
            return file_format["id"]
    raise RuntimeError("No 'po' file format returned by /file_formats")


def extract_background_job_id(body: dict, action: str) -> str:
    """Return the background job id found in a verify/import response body.

    Args:
        body (dict): parsed JSON body of a verify or import response.
        action (str): "verify" or "import", used only for the error message.

    Raises:
        RuntimeError: if no id can be found there.

    Returns:
        str: id of the background job.
    """
    background_job = body.get("background_job") or {}
    data = background_job.get("data") or {}
    if "id" in data:
        return data["id"]
    raise RuntimeError(
        f"Could not find a background job id in the {action} response. "
        f"Full response body: {body!r}"
    )


def verify_import(
    session: requests.Session,
    import_id: str,
    import_file_id: str,
    language_id: str,
    file_format_id: str,
) -> str:
    """Assign an import's file to a language and format, then verify it.

    Args:
        session (requests.Session): authenticated Texterify API session.
        import_id (str): id of the import to verify.
        import_file_id (str): id of the file within that import.
        language_id (str): id of the language to assign the file to.
        file_format_id (str): id of the file format to assign the file to.

    Raises:
        RuntimeError: if Texterify reports an error synchronously, rather
            than via the background job itself.

    Returns:
        str: id of the background job performing the verification.
    """
    response = session.post(
        api_url(f"projects/{PROJECT_ID}/imports/{import_id}/verify"),
        json={
            "file_language_assignments": {import_file_id: language_id},
            "file_format_assignments": {import_file_id: file_format_id},
        },
    )
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise RuntimeError(f"Verify failed: {body}")
    return extract_background_job_id(body, "verify")


def log_review(session: requests.Session, import_id: str) -> None:
    """Print what verify() found would change, for visibility in CI logs.

    This is informational only - it does not block execute_import(). There
    is no dry-run/confirmation flag at the API level, so review is the only
    way to see the diff before it's applied.

    Args:
        session (requests.Session): authenticated Texterify API session.
        import_id (str): id of the import to review.
    """
    response = session.get(api_url(f"projects/{PROJECT_ID}/imports/{import_id}/review"))
    response.raise_for_status()
    new_translations = response.json().get("new_translations", {})
    changed_count = sum(len(keys) for keys in new_translations.values())
    print(f"Review: {changed_count} translation(s) will be added or overwritten.")
    for _, keys in new_translations.items():
        for key_name, diff in keys.items():
            action = "new" if diff["new_translation"] else "changed"
            print(
                f"  [{action}] {key_name}: {diff['old']['other']!r} -> {diff['new']['other']!r}"
            )


def execute_import(session: requests.Session, import_id: str) -> str:
    """Start executing a verified import and return its background job id.

    Args:
        session (requests.Session): authenticated Texterify API session.
        import_id (str): id of the import to execute.

    Raises:
        RuntimeError: if Texterify reports an error synchronously, rather
            than via the background job itself.

    Returns:
        str: id of the background job performing the import.
    """
    response = session.post(
        api_url(f"projects/{PROJECT_ID}/imports/{import_id}/import")
    )
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise RuntimeError(f"Import failed: {body}")
    return extract_background_job_id(body, "import")


def wait_for_background_job(
    session: requests.Session, background_job_id: str, job_type: str
) -> None:
    """Block until a background job completes.

    Polls every POLL_INTERVAL_SECONDS for up to POLL_MAX_ATTEMPTS attempts.

    Args:
        session (requests.Session): authenticated Texterify API session.
        background_job_id (str): id of the job to wait for.
        job_type (str): the job's type, e.g. "IMPORT_VERIFY" or
            "IMPORT_IMPORT" - used to filter the background_jobs listing.

    Raises:
        RuntimeError: if the job id isn't found in the job_type listing, or
            if it finishes with status "ERROR".
        TimeoutError: if it hasn't finished within the attempt budget.
    """
    for attempt in range(POLL_MAX_ATTEMPTS):
        response = session.get(
            api_url(f"projects/{PROJECT_ID}/background_jobs"),
            params={"job_types": job_type},
        )
        response.raise_for_status()
        jobs = {job["id"]: job["attributes"] for job in response.json()["data"]}
        job = jobs.get(background_job_id)
        if job is None:
            raise RuntimeError(
                f"Background job {background_job_id} not found in {job_type} listing"
            )
        if job["status"] == "COMPLETED":
            return
        if job["status"] == "ERROR":
            raise RuntimeError(f"Background job {background_job_id} failed: {job}")
        if attempt < POLL_MAX_ATTEMPTS - 1:
            time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"Background job {background_job_id} ({job_type}) did not complete within "
        f"{POLL_MAX_ATTEMPTS} attempts ({POLL_MAX_ATTEMPTS * POLL_INTERVAL_SECONDS}s)"
    )


def get_current_msgids() -> set:
    """Return the set of msgids in the source .po file we just pushed.

    Returns:
        set: every non-empty msgid in PO_FILE_PATH.
    """
    with open(PO_FILE_PATH, "rb") as po_file:
        catalog = read_po(po_file, abort_invalid=False)
    return {message.id for message in catalog if message.id}


def list_all_keys(session: requests.Session) -> dict:
    """Return every key currently in the Texterify project, as {name: id}.

    Works around a Texterify import quirk in which a key created from a msgid containing
    `\\"` comes back with a name containing a literal backslash before the quote, rather
    than the plain `"` character the msgid actually contains. Texterify's PO importer
    uses the raw, still-escaped substring between the file's quote delimiters as the key
    name, instead of resolving the gettext escape sequence first. Without normalising
    that here, any such key would permanently mismatch get_current_msgids() and be
    misreported (and, with pruning on, deleted) as an orphan on every future push.
    """
    keys = {}
    page = 0
    per_page = 100
    while True:
        response = session.get(
            api_url(f"projects/{PROJECT_ID}/keys"),
            params={"page": page, "per_page": per_page},
        )
        response.raise_for_status()
        body = response.json()
        batch = body["data"]
        if not batch:
            break
        keys.update(
            {key["attributes"]["name"].replace(r"\"", '"'): key["id"] for key in batch}
        )
        if len(keys) >= body.get("meta", {}).get("total", len(keys)):
            break
        page += 1
    return keys


def delete_keys(session: requests.Session, key_ids: list) -> None:
    """Delete the given Texterify keys, and their translations in every language."""
    response = session.delete(
        api_url(f"projects/{PROJECT_ID}/keys"),
        json={"keys": key_ids},
    )
    response.raise_for_status()


def report_orphan_keys(session: requests.Session) -> None:
    """Report (and optionally delete) Texterify keys no longer in our source.

    Deletion is opt-in via TXTY_PRUNE_ORPHAN_KEYS because it cascades across
    every language's translations for that key, not just the source one.

    Args:
        session (requests.Session): authenticated Texterify API session.
    """
    current_msgids = get_current_msgids()
    all_keys = list_all_keys(session)
    orphans = {
        name: key_id for name, key_id in all_keys.items() if name not in current_msgids
    }

    if not orphans:
        print("No orphan keys found.")
        return

    prune = os.environ.get("TXTY_PRUNE_ORPHAN_KEYS", "").lower() == "true"
    action = (
        "Deleting"
        if prune
        else "Found (not deleting - set TXTY_PRUNE_ORPHAN_KEYS=true to delete)"
    )
    print(f"{action} {len(orphans)} orphan key(s) no longer present in the source:")
    for name in sorted(orphans):
        print(f"::warning::orphan translation key no longer in source: {name!r}")

    if prune:
        delete_keys(session, list(orphans.values()))
        print(f"Deleted {len(orphans)} orphan key(s).")


def main() -> int:
    """Push the source strings to Texterify, then report or prune orphan keys."""
    session = make_session()

    print(f"Uploading {PO_FILE_PATH} to Texterify project {PROJECT_ID}...")
    import_id = create_import(session)
    import_file_id = get_import_file_id(session, import_id)

    language_id = get_source_language_id(session)
    file_format_id = get_po_file_format_id(session)

    print("Verifying import...")
    verify_job_id = verify_import(
        session, import_id, import_file_id, language_id, file_format_id
    )
    wait_for_background_job(session, verify_job_id, "IMPORT_VERIFY")
    log_review(session, import_id)

    print("Executing import (this overwrites the source language's translations)...")
    import_job_id = execute_import(session, import_id)
    wait_for_background_job(session, import_job_id, "IMPORT_IMPORT")

    report_orphan_keys(session)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
